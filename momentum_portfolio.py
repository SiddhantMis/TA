#!/usr/bin/env python3
"""Monthly momentum portfolio manager with daily monitoring and a confirmed-fill ledger.

Target membership is a recommendation. Actual holdings change only through a
recorded execution fill. Daily monitoring never submits or assumes an order.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

SCHEMA_VERSION = 2
PORTFOLIO_SIZE = 20
LIQUID_TOP = 200
HYSTERESIS_RANK = 30
MIN_SCAN_COVERAGE_PCT = 95.0
DEFAULT_STATE_PATH = ".local/momentum_portfolio_state.json"
DEFAULT_GEMINI_PATH = ".local/gemini_gem_brief.md"
DEFAULT_CHATGPT_PATH = ".local/chatgpt_task_brief.md"


def number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def new_state(capital=1_000_000.0):
    capital = number(capital)
    if capital is None or capital <= 0:
        raise ValueError("capital must be a positive finite amount")
    return {
        "schema_version": SCHEMA_VERSION,
        "initial_capital_inr": capital,
        "cash_balance_inr": capital,
        "realized_pnl_inr": 0.0,
        "actual_holdings": {},
        "execution_history": [],
        "target_holdings": [],
        "target_as_of": None,
        "last_rebalanced_month": None,
        "run_history": [],
    }


def normalize_state(state, capital=1_000_000.0):
    """Never import legacy recommended holdings as actual executed positions."""
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        result = new_state(capital)
        if isinstance(state, dict) and state:
            result["migration_note"] = (
                "Legacy holdings were not imported because the previous schema "
                "did not distinguish recommendations from confirmed executions."
            )
        return result
    result = new_state(state.get("initial_capital_inr", capital))
    result.update(deepcopy(state))
    defaults = {
        "actual_holdings": {},
        "execution_history": [],
        "target_holdings": [],
        "run_history": [],
    }
    for key, default in defaults.items():
        if not isinstance(result.get(key), type(default)):
            result[key] = default
    if number(result.get("cash_balance_inr")) is None:
        result["cash_balance_inr"] = result["initial_capital_inr"]
    result["schema_version"] = SCHEMA_VERSION
    return result


def load_state(path, capital=1_000_000.0):
    if not os.path.exists(path):
        return new_state(capital)
    with open(path, "r", encoding="utf-8") as handle:
        return normalize_state(json.load(handle), capital)


def atomic_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write("\n")
    os.replace(temp, target)


def record_execution_fill(state, ticker, side, quantity, price, executed_at=None,
                          execution_id=None, costs_inr=0.0):
    """Apply a confirmed BUY/SELL fill; duplicate IDs are idempotent."""
    state = normalize_state(state)
    ticker = str(ticker or "").strip().upper()
    side = str(side or "").strip().upper()
    if not ticker or side not in {"BUY", "SELL"}:
        raise ValueError("ticker is required and side must be BUY or SELL")
    if isinstance(quantity, bool) or int(quantity) != quantity or int(quantity) <= 0:
        raise ValueError("quantity must be a positive integer")
    quantity = int(quantity)
    price, costs = number(price), number(costs_inr)
    if price is None or price <= 0:
        raise ValueError("price must be positive and finite")
    if costs is None or costs < 0:
        raise ValueError("costs must be finite and non-negative")
    execution_id = str(execution_id or uuid.uuid4())
    if any(x.get("execution_id") == execution_id for x in state["execution_history"]):
        return state, False

    executed_at = str(executed_at or date.today().isoformat())
    cash, holdings = float(state["cash_balance_inr"]), state["actual_holdings"]
    position = holdings.get(ticker)
    if side == "BUY":
        total_cost = quantity * price + costs
        if total_cost > cash + 1e-8:
            raise ValueError(f"insufficient cash: required ₹{total_cost:.2f}, available ₹{cash:.2f}")
        old_qty = int(position["quantity"]) if position else 0
        old_avg = float(position["average_cost"]) if position else 0.0
        new_qty = old_qty + quantity
        average_cost = (old_qty * old_avg + total_cost) / new_qty
        high = number(position.get("high_water_mark")) if position else None
        holdings[ticker] = {
            "ticker": ticker, "quantity": new_qty,
            "average_cost": round(average_cost, 4),
            "opened_on": position.get("opened_on", executed_at) if position else executed_at,
            "high_water_mark": round(max(high or price, price), 4),
            "last_execution_id": execution_id,
        }
        cash -= total_cost
        realized = 0.0
    else:
        if not position:
            raise ValueError(f"cannot sell {ticker}: no actual holding exists")
        old_qty = int(position["quantity"])
        if quantity > old_qty:
            raise ValueError(f"cannot sell {quantity}; only {old_qty} shares of {ticker} are held")
        average_cost = float(position["average_cost"])
        cash += quantity * price - costs
        realized = (price - average_cost) * quantity - costs
        remaining = old_qty - quantity
        if remaining:
            position["quantity"] = remaining
            position["last_execution_id"] = execution_id
        else:
            del holdings[ticker]

    state["cash_balance_inr"] = round(cash, 2)
    state["realized_pnl_inr"] = round(float(state.get("realized_pnl_inr", 0)) + realized, 2)
    state["execution_history"].append({
        "execution_id": execution_id, "executed_at": executed_at, "ticker": ticker,
        "side": side, "quantity": quantity, "price": price, "costs_inr": costs,
        "realized_pnl_inr": round(realized, 2),
    })
    return state, True


def relative_context(stock_closes, benchmark_closes, lookback=63):
    """3M relative return and RS-line/EMA50 from same-session close arrays."""
    stock = [number(x) for x in stock_closes]
    bench = [number(x) for x in benchmark_closes]
    out = {"relative_strength_3m_pct": None, "rs_line_above_ema50": None}
    if len(stock) != len(bench) or len(stock) <= lookback:
        return out
    recent = stock[-(lookback + 1):] + bench[-(lookback + 1):]
    if any(x is None or x <= 0 for x in recent):
        return out
    rs = (stock[-1] / stock[-(lookback + 1)] - 1) - (bench[-1] / bench[-(lookback + 1)] - 1)
    out["relative_strength_3m_pct"] = round(rs * 100, 2)
    ratios = [s / b for s, b in zip(stock, bench) if s and b and s > 0 and b > 0]
    if len(ratios) >= 50:
        alpha, ema = 2 / 51, ratios[0]
        for value in ratios[1:]:
            ema = alpha * value + (1 - alpha) * ema
        out["rs_line_above_ema50"] = bool(ratios[-1] > ema)
    return out


def market_regime_from_closes(closes, window=200):
    values = [number(x) for x in closes]
    values = [x for x in values if x is not None and x > 0]
    if len(values) < window:
        return {"regime": "UNKNOWN", "benchmark_close": None, "sma200": None,
                "above_sma200": None, "reason": f"Need {window} valid benchmark closes; found {len(values)}"}
    close, sma = values[-1], sum(values[-window:]) / window
    above = close > sma
    return {
        "regime": "BULL" if above else "BEAR",
        "benchmark_close": round(close, 2), "sma200": round(sma, 2),
        "above_sma200": above,
        "reason": "Benchmark above 200-DMA" if above else "Benchmark at or below 200-DMA",
    }


def is_rebalance_due(as_of, state, force=False):
    if force or not state.get("last_rebalanced_month"):
        return True
    try:
        d = date.fromisoformat(as_of[:10])
    except ValueError:
        return False
    return d.day >= 28 and state.get("last_rebalanced_month") != d.strftime("%Y-%m")


def build_target_holdings(ranked_rows, rows_by_ticker, actual_holdings, market_regime,
                          portfolio_size=PORTFOLIO_SIZE, hysteresis_rank=HYSTERESIS_RANK):
    """Build a monthly target. Missing incumbent data is retained pending review."""
    if market_regime != "BULL":
        return []
    retained = []
    for ticker in actual_holdings:
        row = rows_by_ticker.get(ticker)
        if row is None or row.get("relative_strength_status") != "ok":
            retained.append(ticker)
            continue
        rank = row.get("leader_rank")
        if row.get("above_sma200") is True and rank is not None and int(rank) <= hysteresis_rank:
            retained.append(ticker)
    target = list(dict.fromkeys(retained))[:portfolio_size]
    for row in ranked_rows:
        ticker, rank = row.get("ticker"), row.get("leader_rank")
        if not ticker or ticker in target or rank is None or int(rank) > portfolio_size:
            continue
        target.append(ticker)
        if len(target) == portfolio_size:
            break
    return target[:portfolio_size]


def monitor_actual_holdings(actual_holdings, rows_by_ticker,
                            portfolio_size=PORTFOLIO_SIZE, hysteresis_rank=HYSTERESIS_RANK):
    """Daily descriptive monitoring. No status changes actual membership."""
    updated, report = deepcopy(actual_holdings), []
    for ticker, position in updated.items():
        row = rows_by_ticker.get(ticker)
        close = number(row.get("last_close")) if row else None
        if close is not None and close > 0:
            high = number(position.get("high_water_mark")) or close
            position["high_water_mark"] = round(max(high, close), 4)
            position["last_mark"] = round(close, 4)
        if row is None or row.get("relative_strength_status") != "ok":
            status, rank = "DATA_UNAVAILABLE", None
            reasons = ["Valid price or relative-strength data unavailable; no sell action inferred."]
        else:
            rank, reasons = row.get("leader_rank"), []
            if row.get("above_sma200") is not True:
                status = "EXIT_REVIEW"
                reasons.append("Close is not above the 200-DMA eligibility filter.")
            elif rank is None:
                status = "EXIT_REVIEW"
                reasons.append("Stock no longer qualifies for the ranked liquid universe.")
            elif int(rank) > hysteresis_rank:
                status = "EXIT_REVIEW"
                reasons.append(f"Rank {rank} is outside the Top-{hysteresis_rank} retention buffer.")
            elif int(rank) > portfolio_size:
                status = "WATCH"
                reasons.append(f"Rank {rank} is outside the target Top-{portfolio_size}, but inside the retention buffer.")
            elif row.get("above_sma50") is False:
                status = "WATCH"
                reasons.append("Close is below the 50-DMA; monitor, but do not automatically exit.")
            else:
                status = "HEALTHY"
                reasons.append("Eligible and within the target momentum rank range.")
        high = number(position.get("high_water_mark"))
        drawdown = (close / high - 1) * 100 if close and high else None
        report.append({
            "ticker": ticker, "quantity": int(position["quantity"]),
            "average_cost": number(position.get("average_cost")), "last_close": close,
            "leader_rank": rank,
            "relative_strength_12_1_pct": number(row.get("relative_strength_12_1_pct")) if row else None,
            "relative_strength_3m_pct": number(row.get("relative_strength_3m_pct")) if row else None,
            "above_sma50": row.get("above_sma50") if row else None,
            "above_sma200": row.get("above_sma200") if row else None,
            "high_water_mark": high,
            "drawdown_from_high_pct": round(drawdown, 2) if drawdown is not None else None,
            "status": status, "reasons": reasons,
        })
    return updated, report


def proposed_changes(actual, target, rows_by_ticker, slot_capital, monitor):
    actual_set, target_set = set(actual), set(target)
    by_monitor = {x["ticker"]: x for x in monitor}
    changes = []
    for ticker in sorted(actual_set - target_set):
        row = rows_by_ticker.get(ticker) or {}
        changes.append({
            "side": "SELL", "ticker": ticker, "actual_quantity": int(actual[ticker]["quantity"]),
            "reference_close": number(row.get("last_close")),
            "reason": "; ".join(by_monitor.get(ticker, {}).get("reasons", [])) or "Not in monthly target.",
            "execution_status": "PROPOSED_NOT_EXECUTED",
        })
    for ticker in sorted(target_set - actual_set):
        row = rows_by_ticker.get(ticker) or {}
        close = number(row.get("last_close"))
        changes.append({
            "side": "BUY", "ticker": ticker,
            "suggested_quantity": int(slot_capital // close) if close and close > 0 else None,
            "reference_close": close, "leader_rank": row.get("leader_rank"),
            "relative_strength_12_1_pct": number(row.get("relative_strength_12_1_pct")),
            "reason": "New member of the monthly target portfolio.",
            "execution_status": "PROPOSED_NOT_EXECUTED",
        })
    return changes


def apply_scan_result(state, as_of, market_regime, rows_by_ticker, ranked_rows,
                      data_quality, portfolio_size=PORTFOLIO_SIZE,
                      hysteresis_rank=HYSTERESIS_RANK, force_rebalance=False):
    state = normalize_state(state)
    actual, monitor = monitor_actual_holdings(
        state["actual_holdings"], rows_by_ticker, portfolio_size, hysteresis_rank
    )
    state["actual_holdings"] = actual
    due = is_rebalance_due(as_of, state, force_rebalance)
    coverage = number(data_quality.get("coverage_pct"))
    coverage_ok = coverage is not None and coverage >= MIN_SCAN_COVERAGE_PCT
    regime = market_regime.get("regime", "UNKNOWN")
    if regime in {"BEAR", "UNKNOWN"}:
        for item in monitor:
            if item["status"] != "DATA_UNAVAILABLE":
                if regime == "BEAR":
                    item["status"] = "MARKET_WARNING"
                    item["reasons"].append(
                        "Benchmark is below its 200-DMA; target model is defensive, but no automatic sale is made."
                    )
                else:
                    item["status"] = "MARKET_DATA_UNAVAILABLE"
                    item["reasons"].append(
                        "Benchmark regime cannot be confirmed; review market exposure manually."
                    )
    rebalance_status, blocked = "NOT_DUE", False
    if due:
        if regime == "UNKNOWN":
            rebalance_status, blocked = "BLOCKED_UNKNOWN_MARKET_REGIME", True
        elif not coverage_ok:
            rebalance_status, blocked = "BLOCKED_INCOMPLETE_UNIVERSE_SCAN", True
        else:
            state["target_holdings"] = build_target_holdings(
                ranked_rows, rows_by_ticker, actual, regime, portfolio_size, hysteresis_rank
            )
            state["target_as_of"] = as_of
            state["last_rebalanced_month"] = as_of[:7]
            rebalance_status = "REBALANCED"

    target = list(state.get("target_holdings") or [])
    equity = float(state.get("cash_balance_inr") or 0.0)
    actual_value, marked = 0.0, 0
    for ticker, position in actual.items():
        close = number((rows_by_ticker.get(ticker) or {}).get("last_close"))
        if close is not None:
            value = int(position["quantity"]) * close
            equity += value
            actual_value += value
            marked += 1
    slot_capital = equity / portfolio_size if portfolio_size else 0.0
    changes = [] if blocked else proposed_changes(actual, target, rows_by_ticker, slot_capital, monitor)

    target_details = []
    for ticker in target:
        row = rows_by_ticker.get(ticker) or {}
        target_details.append({
            "ticker": ticker, "leader_rank": row.get("leader_rank"),
            "last_close": number(row.get("last_close")),
            "relative_strength_12_1_pct": number(row.get("relative_strength_12_1_pct")),
            "relative_strength_6m_pct": number(row.get("relative_strength_6m_pct")),
            "relative_strength_3m_pct": number(row.get("relative_strength_3m_pct")),
            "data_status": row.get("relative_strength_status", "unavailable"),
        })
    cash_slots = max(0, portfolio_size - len(target))
    state.update({
        "as_of": as_of, "benchmark": market_regime.get("benchmark", "NIFTYBEES.NS"),
        "market_regime": market_regime, "data_quality": data_quality,
        "portfolio_rules": {
            "portfolio_size": portfolio_size, "liquid_universe_top": LIQUID_TOP,
            "monthly_rebalance": True, "holding_buffer_rank": hysteresis_rank,
            "stock_eligibility": "Close > 200-DMA with valid benchmark-aligned 12-1 relative-strength data",
            "market_filter": "NIFTYBEES close > 200-DMA; otherwise target portfolio is cash",
            "daily_monitoring": "Descriptive only; no automatic orders or membership changes",
        },
        "rebalance_status": rebalance_status, "actual_holdings": actual,
        "actual_holding_monitor": monitor, "target_holdings": target,
        "target_portfolio": target_details, "proposed_changes": changes,
        "summary": {
            "actual_positions": len(actual), "target_positions": len(target),
            "target_cash_slots": cash_slots,
            "target_cash_pct": round(100 * cash_slots / portfolio_size, 1) if portfolio_size else 0,
            "proposed_buys": sum(x["side"] == "BUY" for x in changes),
            "proposed_sells": sum(x["side"] == "SELL" for x in changes),
            "cash_balance_inr": round(float(state.get("cash_balance_inr") or 0), 2),
            "actual_market_value_inr": round(actual_value, 2),
            "marked_actual_positions": marked,
            "estimated_account_equity_inr": round(equity, 2),
            "realized_pnl_inr": round(float(state.get("realized_pnl_inr") or 0), 2),
        },
    })
    state.setdefault("run_history", []).append({
        "as_of": as_of, "rebalance_status": rebalance_status,
        "actual_positions": len(actual), "target_positions": len(target),
        "proposed_buys": state["summary"]["proposed_buys"],
        "proposed_sells": state["summary"]["proposed_sells"], "market_regime": regime,
    })
    state["run_history"] = state["run_history"][-365:]
    return state


def generate_gemini_brief(state):
    s, market = state.get("summary") or {}, state.get("market_regime") or {}
    actual = state.get("actual_holding_monitor") or []
    target, changes = state.get("target_portfolio") or [], state.get("proposed_changes") or []
    quality = state.get("data_quality") or {}
    lines = [
        f"# Gemini fundamental and catalyst review — {state.get('as_of', 'unknown date')}",
        "", "Review an Indian cash-equity momentum portfolio. Proposed trades are not executed.",
        "", "## Market and data context",
        f"- Benchmark: {state.get('benchmark', 'NIFTYBEES.NS')}",
        f"- Regime: {market.get('regime', 'UNKNOWN')}",
        f"- Benchmark close / 200-DMA: {market.get('benchmark_close')} / {market.get('sma200')}",
        f"- Universe coverage: {quality.get('loaded', 0)}/{quality.get('requested', 0)} ({quality.get('coverage_pct')}%)",
        f"- Rebalance status: {state.get('rebalance_status')}",
        "", "## Actual executed holdings",
    ]
    if not actual:
        lines.append("- No executed holdings are recorded in the ledger.")
    else:
        lines.extend(["| Ticker | Qty | Avg cost | Close | Rank | Monitor |", "|---|---:|---:|---:|---:|---|"])
        for x in actual:
            lines.append(f"| {x['ticker']} | {x['quantity']} | {x.get('average_cost')} | {x.get('last_close')} | {x.get('leader_rank')} | {x['status']} |")
    lines.extend(["", "## Monthly target portfolio (recommendation only)"])
    if not target:
        lines.append("- No equity target is selected; target is cash or a rebalance is pending.")
    else:
        lines.extend(["| Ticker | Rank | 12-1 RS | 6M RS | 3M RS | Close |", "|---|---:|---:|---:|---:|---:|"])
        for x in target:
            lines.append(f"| {x['ticker']} | {x.get('leader_rank')} | {x.get('relative_strength_12_1_pct')} | {x.get('relative_strength_6m_pct')} | {x.get('relative_strength_3m_pct')} | {x.get('last_close')} |")
    lines.extend(["", "## Proposed transactions — not executed"])
    if not changes:
        lines.append("- No differences between actual and target membership, or no changes are proposed.")
    else:
        for x in changes:
            qty = x.get("actual_quantity", x.get("suggested_quantity"))
            lines.append(f"- {x['side']} {x['ticker']}: quantity {qty}; reference close {x.get('reference_close')}; reason: {x.get('reason')}. Status: PROPOSED_NOT_EXECUTED.")
    lines.extend([
        "", "## Research requested",
        "Check results, revenue/EPS trends, debt, cash flow, guidance, order-book visibility where relevant, promoter pledges, "
        "auditor changes, institutional ownership and sector concentration. Cite dated primary sources. Distinguish facts "
        "from interpretation. Do not change portfolio membership.",
        "", "## Account context",
        f"- Cash balance: ₹{s.get('cash_balance_inr', 0):,.2f}",
        f"- Actual marked value: ₹{s.get('actual_market_value_inr', 0):,.2f}",
        f"- Estimated equity: ₹{s.get('estimated_account_equity_inr', 0):,.2f}",
    ])
    return "\n".join(lines) + "\n"


def generate_chatgpt_brief(state):
    market = state.get("market_regime") or {}
    actual, changes = state.get("actual_holding_monitor") or [], state.get("proposed_changes") or []
    quality = state.get("data_quality") or {}
    tickers = sorted({x["ticker"] for x in changes} | {x["ticker"] for x in actual})
    lines = [
        f"# ChatGPT news and portfolio-risk audit — {state.get('as_of', 'unknown date')}",
        "", "Search current sources for Indian listed-company announcements and reputable financial news. "
        "Use exact publication dates, source URLs and retrieval timestamps. Proposed trades are not executed.",
        "", "## Market context",
        f"- Regime: {market.get('regime', 'UNKNOWN')}",
        f"- Benchmark close / 200-DMA: {market.get('benchmark_close')} / {market.get('sma200')}",
        f"- Universe coverage: {quality.get('coverage_pct')}%",
        f"- Rebalance status: {state.get('rebalance_status')}",
        "", "## Priority tickers",
    ]
    lines.extend([f"- {t}" for t in tickers] if tickers else ["- No actual holdings or proposed transactions are recorded."])
    lines.extend([
        "", "## Audit checklist",
        "1. Last 72 hours: NSE/BSE announcements, material news, order wins/losses, management changes and guidance.",
        "2. Upcoming results and board meetings: exact dates; flag results within three trading sessions as ENTRY_WAIT, not an automatic sell.",
        "3. Regulatory matters: SEBI, exchanges, regulators, auditor resignations, credit-rating actions and material litigation.",
        "4. Promoter and institutional activity: pledge changes, insider trades, block/bulk deals, OFS/QIP and ownership changes.",
        "5. Portfolio risk: sector/theme concentration, correlated exposures, gaps, liquidity and unusual volatility.",
        "6. Explicitly state when a source or event calendar cannot be verified; no search result is not proof of no event.",
        "", "## Actual holdings (executed)",
    ])
    if not actual:
        lines.append("- None recorded.")
    else:
        for x in actual:
            lines.append(f"- {x['ticker']}: {x['quantity']} shares; {x['status']}; rank {x.get('leader_rank')}; close {x.get('last_close')}; reasons: {'; '.join(x['reasons'])}")
    lines.extend(["", "## Proposed changes (not executed)"])
    if not changes:
        lines.append("- None.")
    else:
        for x in changes:
            lines.append(f"- {x['side']} {x['ticker']}: {x.get('reason')} Reference close: {x.get('reference_close')}.")
    lines.extend(["", "Return one section per ticker with primary-source citations, event dates, severity and unresolved questions. Keep factual news separate from interpretation."])
    return "\n".join(lines) + "\n"


def _relative_context_for_frame(df, benchmark_df):
    import pandas as pd
    stock = pd.to_numeric(df["Close"], errors="coerce")
    bench = pd.to_numeric(benchmark_df["Close"], errors="coerce")
    aligned = pd.concat([stock.rename("stock"), bench.rename("benchmark")], axis=1).sort_index()
    aligned = aligned.loc[aligned["benchmark"].notna()]
    tail = aligned.iloc[-64:]
    if len(tail) < 64 or tail["stock"].isna().any():
        return {"relative_strength_3m_pct": None, "rs_line_above_ema50": None}
    return relative_context(aligned["stock"].tolist(), aligned["benchmark"].tolist(), 63)


def scan_market(universe_path=None, liquid_top=LIQUID_TOP):
    import analyzer as A
    import leaders as LD
    import pandas as pd

    benchmark_df = A.fetch_ticker(A.RS_BENCHMARK)
    if benchmark_df is None or benchmark_df.empty:
        raise RuntimeError(f"Could not fetch benchmark {A.RS_BENCHMARK}")
    benchmark_close = pd.to_numeric(benchmark_df["Close"], errors="coerce").dropna()
    if benchmark_close.empty:
        raise RuntimeError("Benchmark data contains no valid closes")
    universe = LD.load_universe(universe_path or LD.UNIVERSE_FILE)
    if not universe:
        raise RuntimeError("Universe file is empty or unavailable")

    rows, failed = [], []
    sleep_seconds = max(0.0, float(getattr(A, "YF_SLEEP_SECONDS", 0.15)))
    for ticker in universe:
        try:
            frame = A.fetch_ticker(ticker)
            if frame is None or frame.empty or len(frame) < 260:
                failed.append(ticker)
            else:
                metrics = LD.leader_metrics(frame, benchmark_df)
                metrics.update(_relative_context_for_frame(frame, benchmark_df))
                close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
                sma50 = close.rolling(50, min_periods=50).mean().iloc[-1]
                metrics.update({
                    "ticker": ticker, "last_close": round(float(close.iloc[-1]), 2),
                    "above_sma50": bool(close.iloc[-1] > sma50) if pd.notna(sma50) else None,
                    "data_as_of": close.index[-1].date().isoformat(),
                })
                rows.append(metrics)
        except Exception as exc:
            print(f"[scan] {ticker}: {exc}", file=sys.stderr)
            failed.append(ticker)
        if sleep_seconds:
            time.sleep(sleep_seconds)

    ranked, counts = LD.select_leaders(rows, liquid_top=liquid_top, board=max(1, len(rows)))
    by_ticker = {x["ticker"]: x for x in rows}
    as_of = benchmark_close.index[-1].date().isoformat()
    regime = market_regime_from_closes(benchmark_close.tolist())
    regime.update({"benchmark": A.RS_BENCHMARK, "as_of": as_of})
    requested, loaded = len(universe), len(universe) - len(failed)
    quality = {
        "requested": requested, "loaded": loaded, "failed": len(failed),
        "coverage_pct": round(100 * loaded / requested, 1) if requested else 0.0,
        "rankable": counts.get("rankable", 0), "liquid": counts.get("liquid", 0),
        "above_200dma": counts.get("above_200dma", 0),
        "failed_tickers": failed[:100], "partial_scan": bool(failed),
    }
    return as_of, regime, by_ticker, ranked, quality


def run_portfolio(state, as_of, market_regime, rows_by_ticker, ranked_rows,
                  data_quality, portfolio_size=PORTFOLIO_SIZE,
                  hysteresis_rank=HYSTERESIS_RANK, force_rebalance=False):
    return apply_scan_result(
        state, as_of, market_regime, rows_by_ticker, ranked_rows, data_quality,
        portfolio_size, hysteresis_rank, force_rebalance,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", help="Nifty 500 symbol file; defaults to leaders.UNIVERSE_FILE")
    parser.add_argument("--state-file", default=DEFAULT_STATE_PATH)
    parser.add_argument("--gemini-out", default=DEFAULT_GEMINI_PATH)
    parser.add_argument("--chatgpt-out", default=DEFAULT_CHATGPT_PATH)
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    parser.add_argument("--portfolio-size", type=int, default=PORTFOLIO_SIZE)
    parser.add_argument("--hysteresis-rank", type=int, default=HYSTERESIS_RANK)
    parser.add_argument("--liquid-top", type=int, default=LIQUID_TOP)
    parser.add_argument("--force-rebalance", action="store_true")
    parser.add_argument("--record-fill", nargs=4, metavar=("TICKER", "BUY|SELL", "QTY", "PRICE"),
                        help="record a confirmed execution; this does not run a market scan")
    parser.add_argument("--execution-date", help="ISO date for --record-fill")
    parser.add_argument("--execution-id", help="unique broker/order/fill ID for idempotency")
    parser.add_argument("--fill-costs", type=float, default=0.0, help="total fees/taxes for this fill in INR")
    args = parser.parse_args(argv)
    state = load_state(args.state_file, args.capital)

    if args.record_fill:
        ticker, side, quantity, price = args.record_fill
        state, applied = record_execution_fill(
            state, ticker, side, int(quantity), float(price),
            args.execution_date, args.execution_id, args.fill_costs,
        )
        atomic_json(args.state_file, state)
        print("Execution recorded." if applied else "Duplicate execution ignored (idempotent).")
        print(f"Actual positions: {len(state['actual_holdings'])}; cash: ₹{state['cash_balance_inr']:,.2f}")
        return

    as_of, regime, rows, ranked, quality = scan_market(args.universe, args.liquid_top)
    state = run_portfolio(
        state, as_of, regime, rows, ranked, quality,
        args.portfolio_size, args.hysteresis_rank, args.force_rebalance,
    )
    atomic_json(args.state_file, state)
    Path(args.gemini_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.gemini_out).write_text(generate_gemini_brief(state), encoding="utf-8")
    Path(args.chatgpt_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.chatgpt_out).write_text(generate_chatgpt_brief(state), encoding="utf-8")
    s = state["summary"]
    print(
        f"As of {as_of} | regime={regime['regime']} | coverage={quality['coverage_pct']}% "
        f"| actual={s['actual_positions']} | target={s['target_positions']} "
        f"| proposed buys={s['proposed_buys']} | proposed sells={s['proposed_sells']} "
        f"| rebalance={state['rebalance_status']}"
    )
    print(f"Saved state: {args.state_file}")
    print(f"Saved Gemini brief: {args.gemini_out}")
    print(f"Saved ChatGPT brief: {args.chatgpt_out}")


if __name__ == "__main__":
    main()
