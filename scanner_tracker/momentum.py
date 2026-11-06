"""Daily, next-session-open momentum model and separate actual-account proposals.

Inputs are validated equity OHLCV frames supplied by the ingestion layer. This
module does no fetching, persistence or broker execution. Missing execution bars
block a frozen paper rebalance instead of moving its execution to a later open.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR
import math

import pandas as pd

import leaders
from .ledger import decimal, money, new_ledger, record_fill

RULE_VERSION = "momentum-12_1-liquid200-sma200-top20-buffer30-eod-v1"
SLOTS = 20
FEE_RATE = Decimal("0.0015")
MIN_COVERAGE = 95.0


def rebalance_month_due(as_of, last_month=None, force=False):
    """Return only a forward month; February's missed 28th is caught up once."""
    day = date.fromisoformat(as_of)
    if force or not last_month:
        return day.strftime("%Y-%m")
    candidate = (day if day.day >= 28 else day.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    return candidate if candidate > last_month else None


def _frame(frame, as_of):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("history unavailable")
    result = frame.copy()
    index = pd.DatetimeIndex(pd.to_datetime(result.index))
    if index.tz is not None:
        index = index.tz_localize(None)
    result.index = index.normalize()
    if result.index.has_duplicates or result.index.isna().any():
        raise ValueError("duplicate or invalid session dates")
    result = result.sort_index().loc[lambda x: x.index <= pd.Timestamp(as_of)]
    if result.empty:
        raise ValueError("no history at or before requested session")
    for column in result.columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def _price(frames, symbol, session, column):
    frame = frames.get(symbol)
    if frame is None or column not in frame or pd.Timestamp(session) not in frame.index:
        return None
    value = frame.at[pd.Timestamp(session), column]
    try:
        return decimal(value, f"{symbol} {column}", positive=True)
    except ValueError:
        return None


def _equity(ledger, frames, session, column="Close"):
    total, missing = decimal(ledger["cash_balance_inr"]), []
    for symbol, position in ledger["holdings"].items():
        price = _price(frames, symbol, session, column)
        if price is None:
            missing.append(symbol)
        else:
            total += position["quantity"] * price
    return (None if missing else total), missing


def _target(ranks, by_symbol, incumbents, regime):
    if regime != "BULL":
        return []
    target = []
    for symbol in sorted(incumbents):
        row = by_symbol.get(symbol)
        if row is not None and row.get("in_universe") is False:
            continue
        if row is None or row.get("relative_strength_status") != "ok":
            target.append(symbol)
        elif row.get("above_sma200") and row.get("leader_rank") is not None and row["leader_rank"] <= 30:
            target.append(symbol)
    if len(target) > SLOTS:
        raise ValueError("more than 20 retained incumbents require manual reconciliation")
    for row in ranks[:SLOTS]:
        if len(target) == SLOTS:
            break
        if row["symbol"] not in target:
            target.append(row["symbol"])
    return target


def _quantities(equity, symbols, prices):
    slot = equity / SLOTS
    return {symbol: int((slot / prices[symbol]).to_integral_value(rounding=ROUND_FLOOR)) for symbol in symbols}


def _cost(quantity, price):
    gross = Decimal(money(quantity * price))
    return gross + Decimal(money(gross * FEE_RATE))


def _analytic_frame(frame):
    result = frame.copy()
    if "Adj Close" in result:
        factor = result["Adj Close"] / result["Close"].where(result["Close"] > 0)
        for column in ("Open", "High", "Low", "Close"):
            if column in result:
                result[column] = result[column] * factor
    return result


def _fill_target(ledger, symbols, frames, session, fill_prefix):
    """Value all holdings at this open, sell first, then proportionately fund buys."""
    all_symbols = sorted(set(symbols) | set(ledger["holdings"]))
    prices = {s: _price(frames, s, session, "Open") for s in all_symbols}
    missing = [s for s, value in prices.items() if value is None]
    if missing:
        return deepcopy(ledger), None, missing
    equity, missing = _equity(ledger, frames, session, "Open")
    desired = _quantities(equity, symbols, prices)
    result = deepcopy(ledger)
    for symbol in all_symbols:
        quantity = result["holdings"].get(symbol, {}).get("quantity", 0) - desired.get(symbol, 0)
        if quantity > 0:
            gross = Decimal(money(quantity * prices[symbol]))
            result = record_fill(result, {
                "execution_id": f"{fill_prefix}:{symbol}:SELL", "mode": "MOMENTUM",
                "executed_at": session, "symbol": symbol, "side": "SELL", "quantity": quantity,
                "price_inr": str(prices[symbol]), "fees_inr": money(gross * FEE_RATE),
            })
    buys = {s: max(0, desired.get(s, 0) - result["holdings"].get(s, {}).get("quantity", 0)) for s in symbols}
    total_cost = sum((_cost(q, prices[s]) for s, q in buys.items() if q), Decimal(0))
    cash = decimal(result["cash_balance_inr"])
    if total_cost > cash:
        factor = cash / total_cost
        buys = {s: int((q * factor).to_integral_value(rounding=ROUND_FLOOR)) for s, q in buys.items()}
    for symbol in sorted(buys):
        quantity = buys[symbol]
        while quantity and _cost(quantity, prices[symbol]) > decimal(result["cash_balance_inr"]):
            quantity -= 1
        if quantity:
            gross = Decimal(money(quantity * prices[symbol]))
            result = record_fill(result, {
                "execution_id": f"{fill_prefix}:{symbol}:BUY", "mode": "MOMENTUM",
                "executed_at": session, "symbol": symbol, "side": "BUY", "quantity": quantity,
                "price_inr": str(prices[symbol]), "fees_inr": money(gross * FEE_RATE),
            })
    return result, desired, []


def _new_model(capital, rule_version=RULE_VERSION):
    if capital is not None:
        decimal(capital, "model_capital", positive=True)
    return {
        "schema_version": 1, "rule_version": rule_version,
        "capital_configured": capital is not None,
        "ledger": new_ledger("MOMENTUM", capital or 0, kind="model"),
        "target_holdings": [], "target_weights": {}, "target_as_of": None,
        "last_rebalanced_month": None, "pending_rebalance": None,
        "history": [], "rebalance_history": [], "actual_target": None,
    }


def _actual_target(ledger, symbols, frames, signal_date):
    target = {"holdings": symbols, "quantities": {}, "as_of": signal_date,
              "weights": {s: 1 / SLOTS for s in symbols}, "cash_weight": 1 - len(symbols) / SLOTS}
    equity, missing = _equity(ledger, frames, signal_date)
    prices = {s: _price(frames, s, signal_date, "Close") for s in symbols}
    missing = sorted(set(missing + [s for s, price in prices.items() if price is None]))
    if missing:
        target.update(status="BLOCKED_MISSING_MARKS", missing_symbols=missing)
    else:
        target.update(status="READY", quantities=_quantities(equity, symbols, prices), equity_inr=money(equity), missing_symbols=[])
    return target


def _proposals(ledger, target, frames, as_of):
    if ledger is None or target is None or target.get("status") != "READY":
        return [], []
    _, missing = _equity(ledger, frames, as_of)
    symbols = sorted(set(ledger["holdings"]) | set(target["quantities"]))
    missing = sorted(set(missing + [s for s in symbols if _price(frames, s, as_of, "Close") is None]))
    if missing:
        return [], missing
    proposals = []
    for symbol in symbols:
        actual_quantity = ledger["holdings"].get(symbol, {}).get("quantity", 0)
        target_quantity = target["quantities"].get(symbol, 0)
        difference = target_quantity - actual_quantity
        if difference:
            price = _price(frames, symbol, as_of, "Close")
            proposals.append({
                "symbol": symbol, "ticker": symbol, "side": "BUY" if difference > 0 else "SELL",
                "quantity": abs(difference), "actual_quantity": actual_quantity, "target_quantity": target_quantity,
                "reference_price_inr": money(price), "reference_close": float(price),
                "target_as_of": target["as_of"], "execution_status": "PROPOSED_NOT_EXECUTED",
            })
    return sorted(proposals, key=lambda p: (p["side"] != "SELL", p["symbol"])), []


def reconcile_actual_proposals(ledger, target, frames, as_of):
    """Read-only quantity differences against a frozen target, with fee reserves.

    Hypothetical sells fund buys only under the explicit sell-first assumption.
    Membership and target quantities are never recalculated on this read path.
    """
    as_of = date.fromisoformat(as_of).isoformat()
    result = {"as_of": as_of, "status": "NOT_CONFIGURED", "proposals": [], "missing_symbols": [],
              "unfunded": [], "requested_buys": 0, "fundable_buys": 0,
              "requested_buy_quantity": 0, "fundable_buy_quantity": 0,
              "estimated_fees_inr": "0.00", "estimated_cash_after_inr": None,
              "cash_after_proposed_sells_inr": None,
              "funding_assumption": "Proposed sells execute first at displayed EOD closes; fees are estimated at 0.15% per side. Cash is not reserved and orders are not executed."}
    if ledger is None or target is None:
        return result
    if ledger.get("mode") != "MOMENTUM" or ledger.get("kind") != "actual":
        raise ValueError("proposal reconciliation requires the MOMENTUM actual ledger")
    if target.get("status") != "READY":
        result.update(status=target.get("status", "BLOCKED_TARGET"), missing_symbols=target.get("missing_symbols", []))
        return result
    normalized, diagnostics = {}, {}
    for symbol, frame in frames.items():
        try:
            normalized[symbol] = _frame(frame, as_of)
        except (TypeError, ValueError) as exc:
            diagnostics[symbol] = str(exc)
    requested, missing = _proposals(ledger, target, normalized, as_of)
    if missing:
        result.update(status="BLOCKED_MISSING_MARKS", missing_symbols=missing, diagnostics=diagnostics)
        return result
    cash = decimal(ledger["cash_balance_inr"])
    sell_proposals, buys, sell_fees = [], [], Decimal(0)
    for proposal in requested:
        row = dict(proposal, requested_quantity=proposal["quantity"])
        price = _price(normalized, row["symbol"], as_of, "Close")
        if row["side"] == "SELL":
            gross = Decimal(money(row["quantity"] * price))
            fees = Decimal(money(gross * FEE_RATE))
            cash += gross - fees
            sell_fees += fees
            row.update(estimated_fees_inr=money(fees), fundable_quantity=row["quantity"], funding_status="SELL_FIRST")
            sell_proposals.append(row)
        else:
            buys.append((row, price))
    available = cash
    requested_cost = sum((_cost(row["quantity"], price) for row, price in buys), Decimal(0))
    factor = min(Decimal(1), cash / requested_cost) if requested_cost else Decimal(1)
    funded, unfunded, buy_fees = [], [], Decimal(0)
    for row, price in buys:
        requested_quantity = row["requested_quantity"]
        quantity = int((requested_quantity * factor).to_integral_value(rounding=ROUND_FLOOR))
        while quantity and _cost(quantity, price) > cash:
            quantity -= 1
        gross = Decimal(money(quantity * price))
        fees = Decimal(money(gross * FEE_RATE))
        if quantity:
            cash -= gross + fees
            buy_fees += fees
            funded.append(dict(row, quantity=quantity, fundable_quantity=quantity, estimated_fees_inr=money(fees),
                               funding_status="FULLY_FUNDED" if quantity == requested_quantity else "PROPORTIONALLY_SCALED"))
        if quantity < requested_quantity:
            unfunded.append({"symbol": row["symbol"], "requested_quantity": requested_quantity,
                             "fundable_quantity": quantity, "unfunded_quantity": requested_quantity - quantity,
                             "reason": "Buy quantities were proportionately reduced and rounded down after reserving estimated sell/buy fees."})
    result.update(status="READY", proposals=sell_proposals + funded, unfunded=unfunded,
                  requested_buys=len(buys), fundable_buys=len(funded),
                  requested_buy_quantity=sum(row["requested_quantity"] for row, _ in buys),
                  fundable_buy_quantity=sum(row["quantity"] for row in funded),
                  estimated_fees_inr=money(sell_fees + buy_fees),
                  cash_after_proposed_sells_inr=money(available), estimated_cash_after_inr=money(cash),
                  funding_status="SCALED_TO_REFERENCE_CASH" if unfunded else "FULLY_FUNDED",
                  reason="Buy requests exceed reference cash after estimated fees; the frozen target is unchanged." if unfunded else "Quantity differences fit reference cash after estimated fees.")
    return result


def run_momentum(frames, benchmark_frame, as_of, previous_model=None, actual_ledger=None,
                 model_capital=None, force=False, universe_size=None, ranking_method="baseline",
                 universe_symbols=None):
    """Return JSON-safe ranks, a separate paper model and unexecuted actual proposals.

    ``model`` is the only value to pass back as ``previous_model``. ``ranks``
    contains all eligible ranked rows, with both ``symbol`` and legacy ``ticker``.
    Money fields in ledgers/targets/proposals are decimal strings. A forced
    rebalance is explicitly labelled and idempotent for the same signal session.
    """
    as_of = date.fromisoformat(as_of).isoformat()
    if ranking_method not in {"baseline", "volatility_adjusted", "fip"}:
        raise ValueError("unknown research ranking_method")
    if ranking_method != "baseline" and actual_ledger is not None:
        raise ValueError("research ranking methods cannot generate actual-account targets")
    rule_version = RULE_VERSION if ranking_method == "baseline" else f"{RULE_VERSION}:research:{ranking_method}"
    model = deepcopy(previous_model) if previous_model is not None else _new_model(model_capital, rule_version)
    if model.get("schema_version") != 1 or model.get("rule_version") != rule_version:
        raise ValueError("unsupported momentum model version")
    if model.get("last_processed_session") and as_of < model["last_processed_session"]:
        raise ValueError("cannot process a session older than the persisted momentum model")
    if previous_model is not None and not model.get("capital_configured") and model_capital is not None:
        decimal(model_capital, "model_capital", positive=True)
        if model["ledger"]["events"]:
            raise ValueError("cannot configure model capital after ledger activity")
        model["ledger"] = new_ledger("MOMENTUM", model_capital, kind="model")
        model["capital_configured"] = True
        model["last_rebalanced_month"] = None
    if actual_ledger is not None and (actual_ledger.get("mode") != "MOMENTUM" or actual_ledger.get("kind") != "actual"):
        raise ValueError("actual_ledger must be the MOMENTUM actual ledger")
    if isinstance(universe_symbols, (str, bytes)):
        raise ValueError("universe_symbols must be a sequence of symbols")
    scope = list(dict.fromkeys(frames if universe_symbols is None else universe_symbols))
    requested = len(scope) if universe_size is None else universe_size
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < len(scope) or requested < 0:
        raise ValueError("universe_size must be an integer no smaller than the supplied universe")
    output = {"as_of": as_of, "rule_version": rule_version, "ranking_method": ranking_method, "benchmark": "NIFTYBEES.NS",
              "ranks": [], "coverage": {"requested": requested, "valid": 0, "coverage_pct": 0.0},
              "regime": {"regime": "UNKNOWN"}, "model": model, "actual_target": model.get("actual_target"),
              "proposals": [], "warnings": [], "status": "BLOCKED_BENCHMARK"}
    try:
        benchmark = _frame(benchmark_frame, as_of)
        if "Close" not in benchmark or benchmark.index[-1] != pd.Timestamp(as_of):
            raise ValueError("benchmark lacks the exact requested session")
        benchmark_close = benchmark["Close"].replace([math.inf, -math.inf], math.nan)
        if len(benchmark) < 253 or benchmark_close.iloc[-253:].isna().any() or (benchmark_close.iloc[-253:] <= 0).any():
            raise ValueError("benchmark needs 253 complete, positive session closes")
    except (ValueError, TypeError) as exc:
        output["warnings"].append(str(exc))
        return output
    indicator_benchmark = _analytic_frame(benchmark)["Close"].replace([math.inf, -math.inf], math.nan)
    if indicator_benchmark.iloc[-253:].isna().any() or (indicator_benchmark.iloc[-253:] <= 0).any():
        output["warnings"].append("benchmark adjusted closes are incomplete")
        return output
    sma = float(indicator_benchmark.iloc[-200:].mean())
    regime = "BULL" if float(indicator_benchmark.iloc[-1]) > sma else "BEAR"
    output["regime"] = {"regime": regime, "benchmark_close": float(benchmark_close.iloc[-1]), "sma200": sma,
                        "benchmark_adjusted_close": float(indicator_benchmark.iloc[-1]),
                        "above_sma200": regime == "BULL", "as_of": as_of}
    normalized, rows, failures, by_symbol = {}, [], {}, {}
    for symbol, frame in frames.items():
        try:
            normalized[symbol] = _frame(frame, as_of)
            if symbol not in scope:
                by_symbol[symbol] = {"symbol": symbol, "in_universe": False}
                continue
            if not {"Close", "Volume", "High"}.issubset(normalized[symbol]):
                raise ValueError("history requires Close, High and Volume")
            metrics = leaders.leader_metrics(_analytic_frame(normalized[symbol]), _analytic_frame(benchmark))
            if metrics["relative_strength_status"] != "ok":
                raise ValueError(metrics["relative_strength_status"])
            raw = normalized[symbol]
            proxy = (raw["Close"] * raw["Volume"]).rolling(126, min_periods=100).mean().iloc[-1]
            metrics["traded_value_126d"] = float(proxy) if pd.notna(proxy) and math.isfinite(float(proxy)) else None
            metrics["liquidity_basis"] = "reported_close_times_volume_proxy"
            metrics["indicator_price_basis"] = "Adj Close" if "Adj Close" in raw else "Close supplied by caller"
            metrics["last_close"] = float(raw["Close"].iloc[-1])
            if metrics.get("traded_value_126d") is None or metrics["traded_value_126d"] <= 0:
                raise ValueError("liquidity data unavailable")
            row = {**metrics, "symbol": symbol, "ticker": symbol, "in_universe": True}
            rows.append(row)
            by_symbol[symbol] = row
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            if symbol in scope:
                failures[symbol] = str(exc)
    for symbol in scope:
        if symbol not in frames:
            failures[symbol] = "history unavailable"
    ranks, counts = leaders.select_leaders(rows, liquid_top=200, board=len(rows))
    if ranking_method != "baseline":
        from .research import compare_momentum_rankings
        comparison = compare_momentum_rankings({s: normalized[s] for s in scope if s in normalized}, benchmark, as_of)
        factor_rows = comparison["rankings"][ranking_method]
        eligible = {row["symbol"]: row for row in ranks}
        for row in rows:
            row.pop("leader_rank", None)
        ranks = []
        for factor in sorted(factor_rows, key=lambda item: item["rank"]):
            row = eligible.pop(factor["symbol"], None)
            if row is not None:
                row["leader_rank"] = len(ranks) + 1
                row["ranking_score"] = factor["score"]
                ranks.append(row)
    coverage = 100 * len(rows) / requested if requested else 0.0
    output.update(ranks=leaders.sanitize_json(ranks), coverage={
        "requested": requested, "valid": len(rows), "loaded": sum(s in normalized for s in scope),
        "coverage_pct": round(coverage, 3), "failed_symbols": failures, **counts,
    })
    scan_ok = coverage >= MIN_COVERAGE
    output["status"] = "READY" if scan_ok else "BLOCKED_INCOMPLETE_UNIVERSE"
    if not scan_ok:
        output["warnings"].append("Fewer than 95% of the intended universe have current valid ranking histories.")
    if regime == "BEAR":
        output["warnings"].append("BEAR market warning; target becomes cash only at a scheduled rebalance, never through a daily automatic exit.")

    pending = model.get("pending_rebalance")
    recovered_execution = None
    if pending and as_of > pending["signal_date"]:
        if pd.Timestamp(pending["signal_date"]) not in benchmark.index:
            pending.update(status="BLOCKED_EXECUTION_CALENDAR", missing_symbols=[])
            output["warnings"].append("Frozen signal session is outside benchmark history; exact next-session execution cannot be established.")
            following = []
        else:
            following = benchmark.index[benchmark.index > pd.Timestamp(pending["signal_date"])]
        if len(following):
            execution_date = following[0].date().isoformat()
            pre_execution_equity, _ = _equity(model["ledger"], normalized, execution_date, "Open")
            old_fill_ids = {fill["execution_id"] for fill in model["ledger"]["execution_history"]}
            ledger, desired, missing = _fill_target(model["ledger"], pending["target_holdings"], normalized,
                                                   execution_date, pending["rebalance_id"])
            if missing:
                pending.update(status="BLOCKED_MISSING_OPEN", execution_date=execution_date, missing_symbols=missing)
                output["warnings"].append("Frozen model rebalance awaits exact next-session opens: " + ", ".join(missing))
            else:
                model["ledger"] = ledger
                recovered_execution = execution_date
                traded_notional = sum((Decimal(fill["price_inr"]) * fill["quantity"]
                                       for fill in ledger["execution_history"] if fill["execution_id"] not in old_fill_ids), Decimal(0))
                model["rebalance_history"].append({**pending, "execution_date": execution_date,
                    "status": "EXECUTED", "desired_quantities": desired,
                    "pre_execution_equity_inr": format(pre_execution_equity, "f"),
                    "traded_notional_inr": format(traded_notional, "f"),
                    "weight_turnover": float(traded_notional / pre_execution_equity) if pre_execution_equity > 0 else None,
                    "turnover_basis": "sum(abs(quantity traded)*execution open)/pre-execution marked equity"})
                model["pending_rebalance"] = None

    effective_force = bool(force and model.get("last_force_session") != as_of)
    due = rebalance_month_due(as_of, model.get("last_rebalanced_month"), effective_force)
    if scan_ok and due and model.get("pending_rebalance") is None:
        model_target = _target(ranks, by_symbol, model["ledger"]["holdings"], regime)
        missing_model = [s for s in model["ledger"]["holdings"] if _price(normalized, s, as_of, "Close") is None]
        if missing_model:
            output["status"] = "BLOCKED_MISSING_MODEL_MARKS"
            output["warnings"].append("Model target blocked by unavailable held marks: " + ", ".join(missing_model))
        else:
            model.update(target_holdings=model_target, target_weights={s: 1 / SLOTS for s in model_target},
                         target_as_of=as_of, last_rebalanced_month=due)
            if model.get("capital_configured"):
                label = rule_version + (":FORCED" if effective_force else "")
                model["pending_rebalance"] = {"signal_date": as_of, "period": due, "target_holdings": model_target,
                    "weights": {s: 1 / SLOTS for s in model_target}, "status": "PENDING_NEXT_SESSION_OPEN",
                    "rule_version": label, "forced": effective_force,
                    "rebalance_id": f"{rule_version}:{as_of}:{due}:{'forced' if effective_force else 'scheduled'}"}
            if effective_force:
                model["last_force_session"] = as_of
    # Actual-account target formation has its own initial/period state; a newly
    # configured account must not wait for the model's next monthly rebalance.
    if actual_ledger is not None and scan_ok:
        prior_target = model.get("actual_target") or {}
        actual_due = rebalance_month_due(as_of, prior_target.get("period"), effective_force)
        if actual_due:
            symbols = _target(ranks, by_symbol, actual_ledger["holdings"], regime)
            model["actual_target"] = {**_actual_target(actual_ledger, symbols, normalized, as_of),
                                      "period": actual_due, "forced": effective_force}
            if effective_force:
                model["last_force_session"] = as_of
    if not model.get("capital_configured"):
        output["warnings"].append("Model capital is not configured; no nominal account balance or model fills were invented.")
    target = model.get("actual_target")
    if target and actual_ledger is not None and target.get("status") == "BLOCKED_MISSING_MARKS" and scan_ok:
        target = {**target, **_actual_target(actual_ledger, target["holdings"], normalized, target["as_of"])}
        model["actual_target"] = target
    funding = reconcile_actual_proposals(actual_ledger, target, normalized, as_of) if scan_ok else {
        "proposals": [], "missing_symbols": [], "status": "BLOCKED_INCOMPLETE_UNIVERSE"}
    proposals, missing_actual = funding["proposals"], funding["missing_symbols"]
    if missing_actual:
        output["warnings"].append("Actual proposals blocked by unavailable marks: " + ", ".join(missing_actual))
    if target and target.get("status") != "READY":
        output["warnings"].append("Actual target sizing is blocked; no trade quantities are proposed.")
    if funding.get("unfunded"):
        output["warnings"].append(funding["reason"])
    output.update(actual_target=target, proposals=proposals, proposal_status=funding["status"], proposal_funding=funding)
    if model.get("capital_configured"):
        if recovered_execution and recovered_execution < as_of:
            for historical_mark in model["history"]:
                if historical_mark["as_of"] >= recovered_execution:
                    equity, missing = _equity(model["ledger"], normalized, historical_mark["as_of"])
                    historical_mark.update(equity_inr=money(equity) if equity is not None else None,
                        cash_inr=model["ledger"]["cash_balance_inr"],
                        status="INCOMPLETE_MISSING_MARKS" if missing else "COMPLETE",
                        missing_symbols=missing, revision_reason="Recovered exact next-session execution open")
            previous_mark = None
            for historical_mark in model["history"]:
                historical_mark["daily_return"] = (
                    float(Decimal(historical_mark["equity_inr"]) / Decimal(previous_mark["equity_inr"]) - 1)
                    if previous_mark and previous_mark.get("equity_inr") is not None and historical_mark.get("equity_inr") is not None
                    else None
                )
                previous_mark = historical_mark
        equity, missing = _equity(model["ledger"], normalized, as_of)
        blocked_execution = model.get("pending_rebalance") or {}
        execution_incomplete = blocked_execution.get("status") in {"BLOCKED_MISSING_OPEN", "BLOCKED_EXECUTION_CALENDAR"}
        if execution_incomplete:
            equity = None
        history = model["history"]
        previous = next((row for row in reversed(history) if row["as_of"] < as_of), None)
        daily_return = None
        if equity is not None and previous and previous.get("equity_inr") is not None:
            daily_return = float(equity / Decimal(previous["equity_inr"]) - 1)
        mark = {"as_of": as_of, "equity_inr": money(equity) if equity is not None else None,
                "cash_inr": model["ledger"]["cash_balance_inr"], "daily_return": daily_return,
                "status": "INCOMPLETE_PENDING_EXECUTION" if execution_incomplete else ("INCOMPLETE_MISSING_MARKS" if missing else "COMPLETE"),
                "missing_symbols": missing, "benchmark_close": float(benchmark_close.iloc[-1]),
                "benchmark_adjusted_close": float(indicator_benchmark.iloc[-1]) if "Adj Close" in benchmark else None,
                "previous_benchmark_session": benchmark.index[-2].date().isoformat()}
        history[:] = [row for row in history if row["as_of"] != as_of] + [mark]
    model["last_processed_session"] = as_of
    return output
