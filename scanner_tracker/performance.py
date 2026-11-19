"""Source-qualified performance summaries; no missing outcomes become zero returns."""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import math
from statistics import mean, median

from .ledger import money


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None
    return result if result.is_finite() and result >= 0 else None


def _average(values):
    present = [number for value in values if (number := _number(value)) is not None]
    return mean(present) if present else None


def _return_stats(values):
    wins, losses = [x for x in values if x > 0], [x for x in values if x < 0]
    avg_win, avg_loss = _average(wins), _average(losses)
    return {
        "closed": len(values), "n_closed": len(values),
        "mean_net_R": mean(values) if values else None,
        "median_net_R": median(values) if values else None,
        "win_rate_pct": 100 * len(wins) / len(values) if values else None,
        "avg_win_R": avg_win, "avg_loss_R": avg_loss,
        "avg_win_loss_ratio": avg_win / abs(avg_loss) if avg_win is not None and avg_loss else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "profit_factor_status": "defined" if losses else ("no_losses" if values else "no_trades"),
        "breakeven": sum(x == 0 for x in values),
    }


def _ta_group(candidates):
    complete, incomplete = [], []
    for candidate in candidates:
        trade = candidate.get("model_trade") or {}
        unavailable = candidate.get("status") == "data_unavailable" or candidate.get("current", {}).get("data_status", "complete") != "complete"
        closed = candidate.get("status") == "closed" and trade.get("status") == "closed"
        if unavailable or (closed and _number(trade.get("net_R")) is None):
            incomplete.append(candidate)
        elif closed:
            complete.append(candidate)
    trades = [candidate["model_trade"] for candidate in complete]
    values = [float(trade["net_R"]) for trade in trades]
    stress, stress_missing = [], 0
    for trade in trades:
        risk = _number(trade.get("initial_risk"))
        cost = _number(trade.get("total_cost_per_share"))
        gross = _number(trade.get("gross_R"))
        if risk is not None and risk > 0 and cost is not None and cost >= 0:
            stress.append(float(trade["net_R"]) - cost / risk)
        elif gross is not None and gross >= float(trade["net_R"]):
            stress.append(2 * float(trade["net_R"]) - gross)
        else:
            stress_missing += 1
    wait = []
    for candidate in complete:
        explicit = _number(candidate["model_trade"].get("wait_sessions"))
        confirmation = _number(candidate.get("current", {}).get("confirmation_sessions"))
        if explicit is not None:
            wait.append(explicit)
        elif confirmation is not None:
            wait.append(confirmation + 1)
    hold = [_number(trade.get("bars_after_entry")) for trade in trades]
    result = {
        **_return_stats(values), "candidates": len(candidates),
        "statuses": dict(Counter(candidate.get("status", "unknown") for candidate in candidates)),
        "strategy_versions": sorted({str(candidate.get("strategy_version", "unknown")) for candidate in candidates}),
        "incomplete": len(incomplete), "model_open": sum(candidate.get("status") == "model_open" for candidate in candidates),
        "ambiguities": sum(len((candidate.get("model_trade") or {}).get("ambiguities") or []) for candidate in candidates),
        "mean_mfe_R": _average(trade.get("mfe_R") for trade in trades),
        "mean_mae_R": _average(trade.get("mae_R") for trade in trades),
        "mean_mfe_pct": _average(trade.get("mfe_pct") for trade in trades),
        "mean_mae_pct": _average(trade.get("mae_pct") for trade in trades),
        "mean_wait_sessions": _average(wait),
        "mean_hold_sessions": _average(x + 1 for x in hold if x is not None),
        "mean_bars_after_entry": _average(hold),
        "excursion_bases": dict(Counter(str(trade.get("excursion_basis", "unspecified")) for trade in trades)),
        "double_cost_stress": {**_return_stats(stress), "missing_cost_records": stress_missing,
                               "status": "incomplete" if stress_missing else "complete",
                               "basis": "Same observed fills with transaction costs doubled; no rule retuning."},
    }
    return result


def summarize_ta(candidates):
    """Summarize independent unit-risk observations, never a funded TA equity curve."""
    ids = [candidate["id"] for candidate in candidates if candidate.get("id")]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate candidate IDs would double-count TA outcomes")
    families = sorted({"reversal", "breakout55", "pullback20"} | {str(x.get("family", "unknown")) for x in candidates})
    return {
        "families": {family: _ta_group([candidate for candidate in candidates if candidate.get("family") == family]) for family in families},
        "overall": _ta_group(candidates), "basis": "independent_unit_risk_not_funded_portfolio",
        "timing_basis": "Wait = observed confirmation sessions plus next-session entry; hold includes entry session. No calendar-day approximation.",
        "limitations": ["Setup observations can overlap and are not independent portfolio trades.",
                        "Excursions use the TA engine's guaranteed extremes and disclosed daily-bar bounds.",
                        "Small or mixed-version cohorts do not establish a profitable strategy."],
    }


def account_performance(valuations, ledger):
    """Cash-flow-aware observed EOD intervals using beginning-in/end-out timing.

    Missing valuations break the entire cumulative chain. The caller must include
    explicit incomplete rows for missing expected sessions; absent rows alone do
    not identify exchange holidays or missing observations.
    """
    mode = ledger.get("mode")
    rows = [dict(row) for row in valuations if row.get("mode", mode) == mode]
    for row in rows:
        row["as_of"] = date.fromisoformat(str(row["as_of"])[:10]).isoformat()
    rows.sort(key=lambda row: row["as_of"])
    if len({row["as_of"] for row in rows}) != len(rows):
        raise ValueError("duplicate valuation dates require explicit revision selection")
    events = [event for event in ledger.get("events", []) if event.get("event_type") == "CASH"]
    opening = str(ledger.get("opening_as_of") or "")[:10]
    history, intervals = [], []
    chain, cumulative_ok, peak, drawdown = Decimal(1), True, Decimal(1), Decimal(0)
    previous = None
    for row in rows:
        value = _amount(row.get("equity_inr"))
        complete = row.get("complete", row.get("status") == "COMPLETE") is True and value is not None
        if opening and row["as_of"] < opening:
            complete = False
        record = {"as_of": row["as_of"], "equity_inr": money(value) if value is not None and complete else None,
                  "complete": complete, "period_return": None, "cumulative_twr": None,
                  "status": "BASELINE" if previous is None and complete else ("COMPLETE" if complete else "INCOMPLETE")}
        if previous is None:
            cumulative_ok = complete
            if complete:
                record["cumulative_twr"] = 0.0
        else:
            relevant = [event for event in events if previous["as_of"] < event["executed_at"][:10] <= row["as_of"]]
            deposits = sum((Decimal(event["amount_inr"]) for event in relevant if event["cash_type"] == "DEPOSIT"), Decimal(0))
            withdrawals = sum((Decimal(event["amount_inr"]) for event in relevant if event["cash_type"] == "WITHDRAWAL"), Decimal(0))
            income = sum((Decimal(event["amount_inr"]) for event in relevant if event["cash_type"] == "DIVIDEND"), Decimal(0))
            denominator = Decimal(previous["equity_inr"]) + deposits if previous["equity_inr"] is not None else None
            valid = complete and previous["complete"] and denominator is not None and denominator > 0
            interval = {"start": previous["as_of"], "end": row["as_of"], "deposits_inr": money(deposits),
                        "withdrawals_inr": money(withdrawals), "dividends_inr": money(income),
                        "return": None, "status": "COMPLETE" if valid else "INCOMPLETE"}
            if valid:
                factor = (value + withdrawals) / denominator
                interval["return"] = record["period_return"] = float(factor - 1)
                if cumulative_ok:
                    chain *= factor
                    peak = max(peak, chain)
                    drawdown = min(drawdown, chain / peak - 1)
                    record["cumulative_twr"] = float(chain - 1)
            else:
                cumulative_ok = False
            intervals.append(interval)
        history.append(record)
        previous = record
    valid_intervals = sum(item["status"] == "COMPLETE" for item in intervals)
    status = "complete" if intervals and cumulative_ok else ("collecting" if len(rows) < 2 else "incomplete")
    return {
        "mode": mode, "status": status, "history": history, "intervals": intervals,
        "n_intervals": len(intervals), "valid_intervals": valid_intervals,
        "missing_intervals": len(intervals) - valid_intervals,
        "cumulative_twr": float(chain - 1) if status == "complete" else None,
        "max_drawdown": float(drawdown) if status == "complete" else None,
        "basis": "Observed EOD time-weighted account returns; deposits/withdrawals and allocation transfers are external flows; dividends are income.",
        "timing_convention": "Inflows at interval start, outflows at interval end: (ending equity + withdrawals)/(starting equity + deposits)-1.",
        "opening_date_known": bool(opening),
        "limitations": ["Explicit incomplete sessions are required to detect missing observations.",
                        "Multi-session intervals apply the disclosed flow-timing approximation; daily valuations are preferred.",
                        "Unknown cost basis affects realized P&L, not marked-equity TWR when all positions and cash are reconciled."],
    }


def summarize_momentum(report):
    model = report.get("model") or {}
    ledger = model.get("ledger") or {}
    marks = sorted(model.get("history") or [], key=lambda row: row["as_of"])
    valuation_rows, gaps = [], []
    for index, row in enumerate(marks):
        gap = index > 0 and row.get("previous_benchmark_session") is not None and row["previous_benchmark_session"] != marks[index - 1]["as_of"]
        if gap:
            gaps.append({"after": marks[index - 1]["as_of"], "before": row["as_of"],
                         "expected_previous_session": row["previous_benchmark_session"]})
        valuation_rows.append(dict(row, mode="MOMENTUM", complete=row.get("status") == "COMPLETE" and not gap))
    result = account_performance(valuation_rows,
                                 {**ledger, "mode": "MOMENTUM"})
    fills = ledger.get("execution_history") or []
    buy = sum((Decimal(str(fill["price_inr"])) * int(fill["quantity"]) for fill in fills if fill["side"] == "BUY"), Decimal(0))
    sell = sum((Decimal(str(fill["price_inr"])) * int(fill["quantity"]) for fill in fills if fill["side"] == "SELL"), Decimal(0))
    fees = sum((Decimal(str(fill["fees_inr"])) for fill in fills), Decimal(0))
    last = marks[-1] if marks else {}
    equity, cash = _amount(last.get("equity_inr")), _amount(last.get("cash_inr"))
    rebalances, missing_turnover = [], 0
    for rebalance in model.get("rebalance_history") or []:
        if rebalance.get("status") != "EXECUTED":
            continue
        before = _amount(rebalance.get("pre_execution_equity_inr"))
        notional = _amount(rebalance.get("traded_notional_inr"))
        ratio = float(notional / before) if before is not None and before > 0 and notional is not None else None
        if ratio is None:
            missing_turnover += 1
        rebalances.append({"execution_date": rebalance.get("execution_date"),
                           "pre_execution_equity_inr": str(before) if before is not None else None,
                           "traded_notional_inr": str(notional) if notional is not None else None,
                           "weight_turnover": ratio})
    turnover_values = [row["weight_turnover"] for row in rebalances if row["weight_turnover"] is not None]
    raw_benchmark = [_amount(row.get("benchmark_close")) for row in marks]
    adjusted_benchmark = [_amount(row.get("benchmark_adjusted_close")) for row in marks]
    comparison_complete = result["status"] == "complete" and all(value is not None and value > 0 for value in raw_benchmark)
    adjusted_complete = comparison_complete and all(value is not None and value > 0 for value in adjusted_benchmark)
    benchmark_return = float(raw_benchmark[-1] / raw_benchmark[0] - 1) if comparison_complete else None
    adjusted_return = float(adjusted_benchmark[-1] / adjusted_benchmark[0] - 1) if adjusted_complete else None
    for index, row in enumerate(result["history"]):
        row["benchmark_close"] = float(raw_benchmark[index]) if raw_benchmark[index] is not None else None
        row["benchmark_cumulative_return"] = float(raw_benchmark[index] / raw_benchmark[0] - 1) if comparison_complete else None
        row["benchmark_adjusted_close"] = float(adjusted_benchmark[index]) if adjusted_benchmark[index] is not None else None
        row["benchmark_adjusted_cumulative_return"] = float(adjusted_benchmark[index] / adjusted_benchmark[0] - 1) if adjusted_complete else None
    result.update({
        "basis": "Separate funded momentum model, not actual-account performance.",
        "rule_version": report.get("rule_version", model.get("rule_version")),
        "capital_configured": bool(model.get("capital_configured")),
        "cumulative_return": result["cumulative_twr"], "fees_inr": money(fees),
        "turnover": {"traded_notional_inr": money(buy + sell), "buy_notional_inr": money(buy),
                     "sell_notional_inr": money(sell), "executed_rebalances": len(rebalances),
                     "weight_turnover": sum(turnover_values) if rebalances and not missing_turnover else None,
                     "mean_weight_turnover": mean(turnover_values) if turnover_values and not missing_turnover else None,
                     "per_rebalance": rebalances, "missing_rebalances": missing_turnover,
                     "status": "incomplete" if missing_turnover else ("complete" if rebalances else "collecting"),
                     "basis": "Per-rebalance L1 turnover = exact traded notional / pre-execution open-marked equity; aggregate is the sum, not annualized."},
        "benchmark": report.get("benchmark", "NIFTYBEES.NS"), "benchmark_return": benchmark_return,
        "excess_return": result["cumulative_twr"] - benchmark_return if benchmark_return is not None else None,
        "benchmark_adjusted_reference_return": adjusted_return,
        "benchmark_comparison": {"status": "complete" if comparison_complete else "incomplete",
            "start": marks[0]["as_of"] if marks else None, "end": last.get("as_of"),
            "basis": "Same first/last EOD model valuation dates; net model return versus raw ETF closing-price change without benchmark costs. Price proxy, not a total-return index.",
            "adjusted_reference_basis": "Provider-adjusted closing-price reference when every observation exists; not a validated TRI or guaranteed dividend-complete series."},
        "model_history_gaps": gaps,
        "cash_inr": money(cash) if cash is not None else None,
        "cash_pct": float(100 * cash / equity) if cash is not None and equity is not None and equity > 0 and last.get("status") == "COMPLETE" else None,
        "target_cash_pct": 100 * (1 - len(model.get("target_holdings") or []) / 20),
        "pending_rebalance": model.get("pending_rebalance"),
    })
    return result
