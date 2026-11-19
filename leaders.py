#!/usr/bin/env python3
"""Daily momentum leaders over a WIDE, LIQUID universe -- the part of this project with evidence.

Rule (the same one tested in portfolio.py, 'liquid500' universe, 2017-2026):
  universe  Nifty 500 list (universe/nifty500.txt, versioned)
  liquid    the top LIQUID_TOP names by trailing 126-day average traded value, as of the latest close
  trend     close above its own 200-day average
  rank      12-1 return (252 sessions back to 21 back) relative to NIFTYBEES -- highest first

What the backtest said (see results/portfolio_report_liquid500.md): holding the top 20 of this list
monthly beat holding the same universe equal-weight by roughly 12 points a year over 9 years, but with
a deeper drawdown (about -34% vs -13% for the Nifty 50 in the held-out period), and survivorship bias
(failed companies are missing) means the true edge is smaller. It is a ranking, not an entry signal.
Each leader also gets the existing structure read (trend, support/resistance ladders with touches).
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

import analyzer as A
import research as R

UNIVERSE_FILE = "universe/nifty500.txt"
LIQUID_TOP = 200
BOARD_SIZE = 20
RANKED_SNAPSHOT_SIZE = 40
LIVE_RETAIN_RANK = 30
LIVE_REBALANCE_DAY = 28
TV_WINDOW = 126
EVIDENCE = ("Backtest 2017-2026, monthly top-20 by 12-1 relative strength among the point-in-time top-200 liquid "
            "Nifty 500 names above their 200-day average: ~28%/yr vs ~15% for holding the same universe equal-weight "
            "and ~10.5% for the Nifty 50, max drawdown about -34%. Survivorship bias remains (failed companies are "
            "missing), the held-out period is 3 years, and nothing here is validated live. See results/portfolio_report_liquid500.md.")


# Track record of the two entry setups INSIDE the leaders, filled from results/leader_setups_report.md.
# Until that test has been read, they are shown as unvalidated.
SETUP_RECORD = ("Tested 2017-26 inside the leaders: breakout55 and pullback20 did not beat entering on any leader day "
                "(last 3 yrs avg R -0.06 / -0.04 vs -0.02, all within noise). Both are unvalidated; the plan is a risk calculator.")


def entry_plan(df: pd.DataFrame, benchmark_df: pd.DataFrame) -> dict:
    """What would be a buy today, and what the risk would be. Uses research.py's rules unchanged:
    entry next open; initial stop 2 x ATR14 below the fill; exit if price falls to the highest close minus
    3 x ATR14 (ATR fixed at the signal); 60-session time stop. Sizing is per Rs 1,000 of risk so it scales to any account."""
    bc = pd.to_numeric(benchmark_df["Close"], errors="coerce")
    d = R.prep(df, bc > bc.rolling(200).mean())
    d["rs"] = np.nan
    sg = R.signals(d)
    last = d.iloc[-1]
    close, atr = float(last.Close), float(last.atr)
    risk = R.ATR_STOP * atr
    fired = [n for n in ("breakout55", "pullback20") if bool(sg[n].iloc[-1])]
    return {
        "fired": fired,
        "ref_close": round(close, 2), "atr14": round(atr, 2),
        "stop_if_filled_at_ref": round(close - risk, 2),
        "risk_per_share": round(risk, 2), "risk_pct": round(100 * risk / close, 1),
        "shares_per_1000_risk": int(1000 // round(risk, 2)) if round(risk, 2) > 0 else None,   # from the number shown
        "triggers": {"breakout55_close_above": round(float(d.High.rolling(55).max().iloc[-1]), 2),
                     "pullback20_ema20": round(float(last.ema20), 2)},
        "exit_rule": f"stop {R.ATR_STOP}xATR under the fill; then exit at highest close - {R.ATR_TRAIL}xATR; 60-session time stop",
    }


def sanitize_json(obj):
    """NaN / Infinity / numpy scalars -> strict JSON (RFC 8259). Python's json writes NaN as a bare word that
    browsers' JSON.parse and ChatGPT's tools reject, which broke the published screen file."""
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(x) for x in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return v if math.isfinite(v) else None
    return obj


def load_universe(path: str = UNIVERSE_FILE) -> list:
    with open(path) as fh:
        return list(dict.fromkeys(s.strip() for s in fh if s.strip() and not s.startswith("#")))


def leader_metrics(df: pd.DataFrame, benchmark_df: pd.DataFrame) -> dict:
    """Relative strength (analyzer's stale/coverage-gated version) plus liquidity and trend for one stock."""
    m = A.relative_strength_metrics(df, benchmark_df)
    close = pd.to_numeric(df["Close"], errors="coerce")
    vol = pd.to_numeric(df["Volume"], errors="coerce")
    sma200 = close.rolling(200, min_periods=200).mean().iloc[-1]
    tv = (close * vol).rolling(TV_WINDOW, min_periods=100).mean().iloc[-1]
    hi252 = pd.to_numeric(df["High"], errors="coerce").rolling(252, min_periods=200).max().iloc[-1]
    last = float(close.iloc[-1])
    m.update({
        "last_close": round(last, 2),
        "sma200": round(float(sma200), 2) if np.isfinite(sma200) else None,
        "above_sma200": bool(np.isfinite(sma200) and last > sma200),
        "traded_value_126d": float(tv) if np.isfinite(tv) else None,
        "pct_below_52w_high": round(100 * (1 - last / float(hi252)), 1) if np.isfinite(hi252) and hi252 > 0 else None,
    })
    return m


def select_leaders(rows: list, liquid_top: int = LIQUID_TOP, board: int = BOARD_SIZE):
    """rows: [{'ticker', **leader_metrics}] -> (leaders, counts). Pure function, no I/O."""
    ok = [r for r in rows if r.get("relative_strength_status") == "ok"
          and r.get("relative_strength_12_1_pct") is not None and r.get("traded_value_126d")]
    ok.sort(key=lambda r: -r["traded_value_126d"])
    for i, r in enumerate(ok, 1):
        r["liquidity_rank"] = i
    liquid = [r for r in ok if r["liquidity_rank"] <= liquid_top]
    trend = [r for r in liquid if r["above_sma200"]]
    trend.sort(key=lambda r: (-r["relative_strength_12_1_pct"], r["ticker"]))
    for i, r in enumerate(trend, 1):
        r["leader_rank"] = i
    counts = {"universe": len(rows), "rankable": len(ok), "liquid": len(liquid), "above_200dma": len(trend)}
    return trend[:board], counts


# ------------------------------------------------------------------ paper-trading log ---
SNAPSHOT_DIR = "docs/history"
MIN_COVERAGE_PCT = 90.0


def snapshot_record(payload: dict) -> dict:
    """What gets saved each day: top-20 leaders, top-40 eligible ranked stocks (for the live top-30 hold buffer),
    and the liquid universe (for the equal-weight baseline)."""
    ranked_src = payload.get("eligible_ranked")
    if ranked_src is None:
        ranked_src = payload.get("leaders", [])
    ranked = [
        {
            "ticker": r["ticker"],
            "rank": r.get("leader_rank", r.get("rank")),
            "rs12_1": r.get("relative_strength_12_1_pct", r.get("rs12_1")),
            "close": r.get("last_close", r.get("close")),
        }
        for r in ranked_src[:RANKED_SNAPSHOT_SIZE]
        if r.get("ticker")
    ]
    return {
        "as_of": payload["as_of"], "benchmark": payload["benchmark"], "counts": payload["counts"],
        "leaders": [{"ticker": r["ticker"], "rank": r["leader_rank"], "rs12_1": r["relative_strength_12_1_pct"],
                     "close": r["last_close"], "fired": (r.get("plan") or {}).get("fired", [])} for r in payload["leaders"]],
        "ranked": ranked,
        "liquid": payload.get("liquid_universe", []),
    }


def save_snapshot(payload: dict, history_dir: str = SNAPSHOT_DIR):
    """Write docs/history/leaders_<date>.json unless the scan was partial or thin. Returns (path or None, reason)."""
    c = payload.get("counts", {})
    if c.get("partial_scan_time_limit"):
        return None, "scan hit its time limit"
    if c.get("load_coverage_pct", 0) < MIN_COVERAGE_PCT:
        return None, f"coverage {c.get('load_coverage_pct')}% < {MIN_COVERAGE_PCT}%"
    if not payload.get("leaders"):
        return None, "no leaders"
    os.makedirs(history_dir, exist_ok=True)
    path = os.path.join(history_dir, f"leaders_{payload['as_of']}.json")
    with open(path, "w") as fh:
        json.dump(sanitize_json(snapshot_record(payload)), fh, indent=1, allow_nan=False)
    return path, "saved"


def load_snapshots(history_dir: str = SNAPSHOT_DIR) -> list:
    out = []
    if os.path.isdir(history_dir):
        for fn in sorted(os.listdir(history_dir)):
            if fn.startswith("leaders_") and fn.endswith(".json"):
                try:
                    with open(os.path.join(history_dir, fn)) as fh:
                        out.append(json.load(fh))
                except Exception as e:
                    print(f"[history] could not read {fn}: {e}", file=sys.stderr)
    return sorted(out, key=lambda s: s["as_of"])


def _px(frames, t, kind, date):
    df = frames.get(t)
    if df is None or date not in df.index:
        return float("nan")
    v = df[kind].at[date]
    return float(v) if np.isfinite(v) else float("nan")


def _basket_return(tickers, frames, entry_date, exit_date, exit_kind, denominator=None):
    """Return a fixed-weight basket return; never reweight surviving names when data is missing.

    denominator defaults to the number of selected names. For the strategy basket pass
    n_hold so fewer than n_hold names leave the unused allocation in zero-return cash.
    """
    names = list(dict.fromkeys(tickers))
    if not names:
        return None, 0, []
    returns, missing = {}, []
    for ticker in names:
        entry = _px(frames, ticker, "Open", entry_date)
        exit_value = _px(frames, ticker, exit_kind, exit_date)
        if not (np.isfinite(entry) and np.isfinite(exit_value) and entry > 0):
            missing.append(ticker)
        else:
            returns[ticker] = exit_value / entry - 1.0
    if missing:
        return None, len(returns), missing
    weight_denominator = len(names) if denominator is None else int(denominator)
    if weight_denominator <= 0:
        return None, len(returns), []
    return sum(returns.values()) / weight_denominator, len(returns), []


def _benchmark_return(benchmark_df, entry_date, exit_date, exit_kind):
    try:
        entry = float(benchmark_df["Open"].at[entry_date])
        exit_value = float(benchmark_df[exit_kind].at[exit_date])
    except (KeyError, TypeError, ValueError):
        return None
    if not (np.isfinite(entry) and np.isfinite(exit_value) and entry > 0):
        return None
    return exit_value / entry - 1.0


def _benchmark_regime_lookup(benchmark_df: pd.DataFrame, calendar: pd.DatetimeIndex):
    """Return a lookup function mapping a session Timestamp -> 'BULL', 'BEAR', or 'UNKNOWN'
    from benchmark Close vs its 200-session simple moving average."""
    close = pd.to_numeric(benchmark_df["Close"], errors="coerce").reindex(calendar)
    sma200 = close.rolling(200, min_periods=200).mean()

    def regime_at(day: pd.Timestamp) -> str:
        if day not in calendar:
            return "UNKNOWN"
        c = close.at[day]
        m = sma200.at[day]
        if not (np.isfinite(c) and np.isfinite(m) and m > 0):
            return "UNKNOWN"
        return "BULL" if float(c) > float(m) else "BEAR"

    return regime_at


def _month_end_snapshots(snaps, calendar):
    """Use a completed month's final session, confirmed by the next month's data."""
    observed_months = sorted({session.strftime("%Y-%m") for session in calendar})
    # The latest observed month may still be in progress. Exclude it: the exchange
    # calendar cannot confirm its final session until a following-month session exists.
    completed_months = set(observed_months[:-1])
    month_ends = {}
    for session in calendar:
        month = session.strftime("%Y-%m")
        if month in completed_months:
            month_ends[month] = session

    by_date = {str(s.get("as_of")): s for s in snaps if s.get("as_of")}
    eligible = []
    for month, session in sorted(month_ends.items()):
        snap = by_date.get(session.date().isoformat())
        if snap is not None:
            eligible.append(snap)

    first_month = min((str(s.get("as_of"))[:7] for s in snaps if s.get("as_of")), default=None)
    missing_month_ends = []
    if first_month:
        for month, session in sorted(month_ends.items()):
            if month < first_month:
                continue
            if session.date().isoformat() not in by_date:
                missing_month_ends.append({
                    "month": month,
                    "expected_signal_date": session.date().isoformat(),
                })
    return eligible, missing_month_ends


def _live_rebalance_snapshots(snaps, calendar, min_day: int = LIVE_REBALANCE_DAY):
    """Select the Variant B (live) rebalance snapshot for each month.

    Rule:
      - First snapshot on or after day `min_day` (28th) in that month.
      - If a completed month has no calendar session on or after `min_day` (e.g., February
        when the 28th falls on a weekend), use that month's last snapshot.
      - An in-progress month with no session on or after `min_day` yet is not triggered early.
    """
    observed_months = sorted({session.strftime("%Y-%m") for session in calendar})
    completed_months = set(observed_months[:-1])
    sessions_by_month = {}
    for session in calendar:
        sessions_by_month.setdefault(session.strftime("%Y-%m"), []).append(session)

    snaps_by_month = {}
    for snap in snaps:
        raw = snap.get("as_of")
        if not raw:
            continue
        try:
            day = pd.Timestamp(raw)
        except (TypeError, ValueError):
            continue
        if day not in calendar:
            continue
        month = day.strftime("%Y-%m")
        snaps_by_month.setdefault(month, {})[day] = snap

    first_month = min(snaps_by_month, default=None)
    if first_month is None:
        return [], []

    eligible = []
    missing = []
    for month in observed_months:
        if month < first_month:
            continue
        month_sessions = sessions_by_month[month]
        ge_sessions = [d for d in month_sessions if d.day >= min_day]
        month_snaps = snaps_by_month.get(month, {})
        if ge_sessions:
            ge_snaps = [month_snaps[d] for d in sorted(month_snaps) if d.day >= min_day]
            if ge_snaps:
                eligible.append(ge_snaps[0])
            elif month in completed_months:
                missing.append({
                    "month": month,
                    "expected_signal_date": ge_sessions[0].date().isoformat(),
                })
        elif month in completed_months:
            last_session = month_sessions[-1]
            if month_snaps:
                eligible.append(month_snaps[max(month_snaps)])
            else:
                missing.append({
                    "month": month,
                    "expected_signal_date": last_session.date().isoformat(),
                })
    return eligible, missing


def _snapshot_ranked(snap: dict) -> list[dict]:
    """Return deduplicated ranked eligible entries from a snapshot.

    New-format snapshots include `ranked` (up to top 40); legacy snapshots only have
    `leaders` (top 20), so earlier months naturally behave as no-buffer.
    """
    source = snap.get("ranked") if snap.get("ranked") is not None else snap.get("leaders", [])
    seen, out = set(), []
    for pos, item in enumerate(source, 1):
        ticker = item.get("ticker")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        raw_rank = item.get("rank", item.get("leader_rank", pos))
        out.append({"ticker": ticker, "rank": int(raw_rank) if raw_rank is not None else pos})
    out.sort(key=lambda x: (x["rank"], x["ticker"]))
    return out


def _select_variant_holdings(snap: dict, incumbents: list[str], regime: str,
                             n_hold: int = BOARD_SIZE, use_buffer: bool = False,
                             retain_rank: int = LIVE_RETAIN_RANK) -> list[str]:
    """Select target holdings for a paper-log variant.

    - BEAR regime -> cash ([]).
    - Without buffer (or with no incumbents): top `n_hold` eligible stocks (rank <= n_hold).
    - With buffer (Variant B): keep incumbents still eligible and ranked <= `retain_rank` (30),
      then fill remaining slots up to `n_hold` (20) ONLY from stocks ranked <= `n_hold`.
    """
    if regime == "BEAR" or n_hold <= 0:
        return []
    ranked = _snapshot_ranked(snap)
    if not use_buffer or not incumbents:
        return [item["ticker"] for item in ranked if item["rank"] <= n_hold][:n_hold]
    rank_by_ticker = {item["ticker"]: item["rank"] for item in ranked}
    kept = [t for t in incumbents if t in rank_by_ticker and rank_by_ticker[t] <= retain_rank]
    kept.sort(key=lambda t: (rank_by_ticker[t], t))
    selected = kept[:n_hold]
    selected_set = set(selected)
    for item in ranked:
        if len(selected) >= n_hold:
            break
        if item["rank"] <= n_hold and item["ticker"] not in selected_set:
            selected.append(item["ticker"])
            selected_set.add(item["ticker"])
    return selected


def _score_variant(signals: list, missing_signals: list, frames: dict, benchmark_df: pd.DataFrame,
                   calendar: pd.DatetimeIndex, regime_at, outside_window: list, *,
                   cost_pct: float = 0.30, n_hold: int = BOARD_SIZE,
                   use_buffer: bool = False, use_regime: bool = True,
                   retain_rank: int = LIVE_RETAIN_RANK) -> tuple[list[dict], dict]:
    """Simulate one paper-log variant over a sequence of rebalance signal snapshots."""
    monthly = []
    previous_weights = None
    previous_entry = None
    incumbents = []
    for i, snap in enumerate(signals):
        signal_date = pd.Timestamp(snap["as_of"])
        month = signal_date.strftime("%Y-%m")
        regime = regime_at(signal_date) if use_regime else "UNFILTERED"
        entry_pos = calendar.searchsorted(signal_date, side="right")
        if entry_pos >= len(calendar):
            monthly.append({
                "month": month,
                "signal_date": snap["as_of"],
                "regime": regime,
                "status": "pending",
                "data_status": "waiting_for_next_session",
            })
            continue
        entry_date = calendar[entry_pos]

        liquid = list(dict.fromkeys(
            item["ticker"] for item in snap.get("liquid", []) if item.get("ticker")
        ))
        regime_unknown = use_regime and regime == "UNKNOWN"
        if regime_unknown:
            selected = []
        else:
            selected = _select_variant_holdings(
                snap, incumbents, regime if use_regime else "BULL",
                n_hold=n_hold, use_buffer=use_buffer, retain_rank=retain_rank,
            )
        current_weights = {
            ticker: 1.0 / float(n_hold) for ticker in selected
        } if n_hold > 0 else {}

        next_entry = None
        period_gap = False
        closed = False
        if i + 1 < len(signals):
            next_signal = pd.Timestamp(signals[i + 1]["as_of"])
            next_pos = calendar.searchsorted(next_signal, side="right")
            if next_pos < len(calendar):
                next_entry = calendar[next_pos]
                closed = True
                period_gap = (
                    next_signal.to_period("M") - signal_date.to_period("M")
                ).n != 1
        if closed:
            exit_date, exit_kind = next_entry, "Open"
        else:
            exit_date, exit_kind = calendar[-1], "Close"

        turnover = None
        missing_turnover = []
        if not period_gap and not regime_unknown and n_hold > 0:
            if previous_weights is None or not previous_weights:
                # First entry or re-entry from 100% cash: traded weight equals new invested weight.
                turnover = sum(current_weights.values())
            else:
                individual_returns = {}
                for ticker in previous_weights:
                    start_price = _px(frames, ticker, "Open", previous_entry)
                    end_price = _px(frames, ticker, "Open", entry_date)
                    if not (np.isfinite(start_price) and np.isfinite(end_price) and start_price > 0):
                        missing_turnover.append(ticker)
                    else:
                        individual_returns[ticker] = end_price / start_price - 1.0
                if not missing_turnover:
                    prior_return = sum(
                        previous_weights[t] * individual_returns[t]
                        for t in previous_weights
                    )
                    if 1.0 + prior_return > 0:
                        drifted_weights = {
                            ticker: weight * (1.0 + individual_returns[ticker]) / (1.0 + prior_return)
                            for ticker, weight in previous_weights.items()
                        }
                        all_names = set(drifted_weights) | set(current_weights)
                        turnover = sum(
                            abs(current_weights.get(t, 0.0) - drifted_weights.get(t, 0.0))
                            for t in all_names
                        )

        if period_gap:
            gross = universe_gross = benchmark_return = net = None
            priced = universe_priced = 0
            missing_selected = list(selected)
            universe_missing = list(liquid)
            data_status = "missing_month_end_snapshot"
        elif regime_unknown:
            gross = net = None
            priced = 0
            missing_selected = []
            universe_gross, universe_priced, universe_missing = _basket_return(
                liquid, frames, entry_date, exit_date, exit_kind, denominator=len(liquid),
            )
            benchmark_return = _benchmark_return(benchmark_df, entry_date, exit_date, exit_kind)
            data_status = "regime_unavailable"
        else:
            if use_regime and regime == "BEAR":
                gross, priced, missing_selected = 0.0, 0, []
            else:
                gross, priced, missing_selected = _basket_return(
                    selected, frames, entry_date, exit_date, exit_kind, denominator=n_hold,
                )
            universe_gross, universe_priced, universe_missing = _basket_return(
                liquid, frames, entry_date, exit_date, exit_kind, denominator=len(liquid),
            )
            benchmark_return = _benchmark_return(benchmark_df, entry_date, exit_date, exit_kind)
            net = (
                gross - turnover * cost_pct / 200.0
                if gross is not None and turnover is not None else None
            )
            data_complete = (
                gross is not None and universe_gross is not None
                and benchmark_return is not None and turnover is not None
                and not missing_selected and not universe_missing and not missing_turnover
            )
            data_status = "complete" if data_complete else "missing_price_or_turnover_data"

        row_status = ("closed" if closed else "open") if data_status == "complete" else (
            "incomplete_data" if closed else "open_incomplete"
        )
        monthly.append({
            "month": month,
            "signal_date": snap["as_of"],
            "entry_date": entry_date.date().isoformat(),
            "exit_date": exit_date.date().isoformat(),
            "regime": regime,
            "in_cash": bool(use_regime and regime == "BEAR"),
            "status": row_status,
            "data_status": data_status,
            "holdings": len(selected),
            "holding_tickers": list(selected),
            "priced": priced,
            "expected_holdings": len(selected),
            "missing_tickers": missing_selected[:20],
            "liquid_universe_size": len(liquid),
            "liquid_priced": universe_priced,
            "liquid_missing_count": len(universe_missing),
            "missing_turnover_tickers": missing_turnover[:20],
            "turnover_l1": turnover,
            "gross": gross,
            "net": net,
            "same_universe_equal_weight": universe_gross,
            "nifty50": benchmark_return,
            "excess_vs_universe": net - universe_gross if net is not None and universe_gross is not None else None,
            "excess_vs_nifty": net - benchmark_return if net is not None and benchmark_return is not None else None,
        })

        if regime_unknown:
            previous_weights = None
            previous_entry = None
            incumbents = []
        else:
            previous_weights = current_weights
            previous_entry = entry_date
            incumbents = list(selected)

    closed_rows = [row for row in monthly if row.get("status") in ("closed", "incomplete_data")]
    incomplete_closed = [row for row in closed_rows if row.get("data_status") != "complete"]
    complete_closed = [row for row in closed_rows if row.get("data_status") == "complete"]
    audit_incomplete = bool(missing_signals or outside_window)
    cumulative = {
        "status": "complete" if closed_rows and not incomplete_closed and not audit_incomplete else "incomplete",
        "months": len(complete_closed),
        "net": None,
        "same_universe_equal_weight": None,
        "nifty50": None,
    }
    if closed_rows and not incomplete_closed and not audit_incomplete:
        for key in ("net", "same_universe_equal_weight", "nifty50"):
            values = [row[key] for row in closed_rows]
            if all(value is not None and np.isfinite(value) for value in values):
                cumulative[key] = float(np.prod([1.0 + value for value in values]) - 1.0)
            else:
                cumulative["status"] = "incomplete"
    return monthly, cumulative


def _build_comparison_rows(raw_monthly: list, simple_monthly: list, live_monthly: list) -> list[dict]:
    """Align raw top-20, Variant A (simple), Variant B (live), and benchmarks by month."""
    by_month = {}
    for bucket, rows in (("raw", raw_monthly), ("simple", simple_monthly), ("live", live_monthly)):
        for row in rows:
            month = row.get("month") or str(row.get("signal_date", ""))[:7]
            if not month:
                continue
            by_month.setdefault(month, {})[bucket] = row
    comparison = []
    for month in sorted(by_month):
        entry = by_month[month]
        r_row, s_row, l_row = entry.get("raw"), entry.get("simple"), entry.get("live")
        ref = r_row or s_row or l_row or {}
        comparison.append({
            "month": month,
            "regime": (s_row or l_row or {}).get("regime"),
            "simple_signal_date": s_row.get("signal_date") if s_row else None,
            "live_signal_date": l_row.get("signal_date") if l_row else None,
            "raw_signal_date": r_row.get("signal_date") if r_row else None,
            "simple_status": s_row.get("status") if s_row else None,
            "live_status": l_row.get("status") if l_row else None,
            "raw_status": r_row.get("status") if r_row else None,
            "simple_net": s_row.get("net") if s_row else None,
            "live_net": l_row.get("net") if l_row else None,
            "raw_top20_net": r_row.get("top20_net") if r_row else None,
            "same_universe_equal_weight": ref.get("same_universe_equal_weight"),
            "nifty50": ref.get("nifty50"),
        })
    return comparison


def build_scorecard(snaps: list, frames: dict, benchmark_df: pd.DataFrame,
                    cost_pct: float = 0.30, n_hold: int = BOARD_SIZE,
                    retain_rank: int = LIVE_RETAIN_RANK) -> dict:
    """Score confirmed leader snapshots with fixed weights and drift-aware turnover.

    Reports side by side:
      - raw_top20 (existing `monthly` / `cumulative`): month-end top-20, no buffer, no regime filter
      - simple (Variant A): month-end top-20, no buffer, BEAR (NIFTYBEES <= 200-DMA) -> cash
      - live (Variant B): first snapshot >= 28th (or month's last snapshot in months like February),
        top-30 incumbent hold buffer filled from top-20, BEAR -> cash
      - Nifty 50 (benchmark ETF) and same-universe equal weight

    Missing signals or missing prices make the affected interval incomplete rather than
    silently reweighting survivors or stitching across gaps.
    """
    if benchmark_df is None or benchmark_df.empty or not {"Open", "Close"}.issubset(benchmark_df.columns):
        return {
            "status": "unavailable", "snapshots": len(snaps), "monthly": [],
            "variants": {}, "comparison": [],
            "daily_forward": {}, "summary": "Paper log unavailable: benchmark history is missing.",
        }
    calendar = pd.DatetimeIndex(benchmark_df.index).sort_values()
    if len(calendar) < 2:
        return {
            "status": "unavailable", "snapshots": len(snaps), "monthly": [],
            "variants": {}, "comparison": [],
            "daily_forward": {}, "summary": "Paper log unavailable: benchmark history is too short.",
        }
    if not snaps:
        return {
            "status": "collecting", "snapshots": 0, "monthly": [],
            "variants": {}, "comparison": [],
            "daily_forward": {}, "missing_month_ends": [],
            "summary": "Paper log: no snapshots yet.",
        }

    signals, missing_month_ends = _month_end_snapshots(snaps, calendar)
    live_signals, missing_live_signals = _live_rebalance_snapshots(snaps, calendar)
    outside_window = []
    for snap in snaps:
        try:
            if pd.Timestamp(snap["as_of"]) < calendar[0]:
                outside_window.append(str(snap["as_of"]))
        except (KeyError, TypeError, ValueError):
            outside_window.append(str(snap.get("as_of", "unknown")))

    regime_at = _benchmark_regime_lookup(benchmark_df, calendar)

    # Existing raw top-20 (unbuffered, no regime filter) preserved at top-level monthly/cumulative
    raw_rows, raw_cum = _score_variant(
        signals, missing_month_ends, frames, benchmark_df, calendar, regime_at, outside_window,
        cost_pct=cost_pct, n_hold=n_hold, use_buffer=False, use_regime=False, retain_rank=retain_rank,
    )
    monthly = []
    for row in raw_rows:
        mapped = dict(row)
        if "gross" in mapped:
            mapped["top20_gross"] = mapped.pop("gross")
        if "net" in mapped:
            mapped["top20_net"] = mapped.pop("net")
        monthly.append(mapped)

    cumulative = {
        "status": raw_cum["status"],
        "months": raw_cum["months"],
        "top20_net": raw_cum["net"],
        "same_universe_equal_weight": raw_cum["same_universe_equal_weight"],
        "nifty50": raw_cum["nifty50"],
    }

    # Variant A (simple): month-end, no buffer, BEAR -> cash
    simple_monthly, simple_cumulative = _score_variant(
        signals, missing_month_ends, frames, benchmark_df, calendar, regime_at, outside_window,
        cost_pct=cost_pct, n_hold=n_hold, use_buffer=False, use_regime=True, retain_rank=retain_rank,
    )

    # Variant B (live): first snapshot >= 28th (Feb last snapshot), top-30 buffer, BEAR -> cash
    live_monthly, live_cumulative = _score_variant(
        live_signals, missing_live_signals, frames, benchmark_df, calendar, regime_at, outside_window,
        cost_pct=cost_pct, n_hold=n_hold, use_buffer=True, use_regime=True, retain_rank=retain_rank,
    )

    comparison = _build_comparison_rows(monthly, simple_monthly, live_monthly)
    variants = {
        "simple": {
            "label": "Simple (month-end, no buffer, BEAR=cash)",
            "signals": len(signals),
            "missing_signals": missing_month_ends,
            "monthly": simple_monthly,
            "cumulative": simple_cumulative,
        },
        "live": {
            "label": "Live (>=28th / Feb last, top-30 buffer, BEAR=cash)",
            "signals": len(live_signals),
            "missing_signals": missing_live_signals,
            "monthly": live_monthly,
            "cumulative": live_cumulative,
        },
        "raw_top20": {
            "label": "Raw top-20 (month-end, no buffer, no regime filter)",
            "signals": len(signals),
            "missing_signals": missing_month_ends,
            "monthly": monthly,
            "cumulative": cumulative,
        },
    }

    # Overlapping 5/21/63-session diagnostics, explicitly count missing-price samples.
    forward = {}
    for horizon in (5, 21, 63):
        excess, fired_excess, quiet_excess = [], [], []
        expected, incomplete = 0, 0
        for snap in snaps:
            try:
                signal_date = pd.Timestamp(snap["as_of"])
            except (KeyError, TypeError, ValueError):
                incomplete += 1
                continue
            if signal_date < calendar[0] or signal_date >= calendar[-1]:
                continue
            position = calendar.searchsorted(signal_date, side="right")
            if position + horizon - 1 >= len(calendar):
                continue
            expected += 1
            entry, exit_date = calendar[position], calendar[position + horizon - 1]
            basket, _, missing = _basket_return(
                [item["ticker"] for item in snap.get("leaders", []) if item.get("ticker")],
                frames, entry, exit_date, "Close", denominator=n_hold,
            )
            benchmark_return = _benchmark_return(benchmark_df, entry, exit_date, "Close")
            if basket is None or benchmark_return is None:
                incomplete += 1
                continue
            excess.append(basket - benchmark_return)
            for item in snap.get("leaders", []):
                ticker = item.get("ticker")
                if not ticker:
                    continue
                single, _, _ = _basket_return(
                    [ticker], frames, entry, exit_date, "Close", denominator=1,
                )
                if single is not None:
                    (fired_excess if item.get("fired") else quiet_excess).append(
                        single - benchmark_return
                    )
        forward[f"{horizon}d"] = {
            "expected_snapshots": expected,
            "snapshots": len(excess),
            "incomplete_snapshots": incomplete,
            "mean_excess_vs_nifty": float(np.mean(excess)) if excess else None,
            "share_positive": float(np.mean([value > 0 for value in excess])) if excess else None,
            "setup_fired_n": len(fired_excess),
            "setup_fired_mean_excess": float(np.mean(fired_excess)) if fired_excess else None,
            "no_setup_n": len(quiet_excess),
            "no_setup_mean_excess": float(np.mean(quiet_excess)) if quiet_excess else None,
        }

    closed_rows = [row for row in monthly if row.get("status") in ("closed", "incomplete_data")]
    incomplete_closed = [row for row in closed_rows if row.get("data_status") != "complete"]
    complete_closed = [row for row in closed_rows if row.get("data_status") == "complete"]
    first = min((str(snap.get("as_of")) for snap in snaps if snap.get("as_of")), default="unknown")
    if cumulative["status"] == "complete":
        extra = ""
        if simple_cumulative["status"] == "complete" and live_cumulative["status"] == "complete":
            extra = (
                f" | simple {simple_cumulative['net'] * 100:+.1f}% vs "
                f"live {live_cumulative['net'] * 100:+.1f}%"
            )
        summary = (
            f"Paper log since {first}: {len(closed_rows)} completed month(s): "
            f"top-20 {cumulative['top20_net'] * 100:+.1f}%{extra} vs Nifty "
            f"{cumulative['nifty50'] * 100:+.1f}% vs same-universe equal-weight "
            f"{cumulative['same_universe_equal_weight'] * 100:+.1f}% (after costs; far too early to judge)."
        )
    elif closed_rows:
        summary = (
            f"Paper log since {first}: {len(complete_closed)} complete and "
            f"{len(incomplete_closed)} incomplete closed interval(s); "
            f"{len(missing_month_ends)} missing month-end snapshot(s), "
            f"{len(outside_window)} snapshot(s) outside available price history. "
            "Cumulative returns withheld to avoid biased results."
        )
    else:
        summary = (
            f"Paper log: {len(signals)} confirmed month-end snapshot(s) since {first}; "
            "the first completed interval is not available yet."
        )

    return {
        "schema_version": 3,
        "status": cumulative["status"] if closed_rows else "tracking",
        "snapshots": len(snaps),
        "month_end_snapshots": len(signals),
        "first_snapshot": first,
        "missing_month_ends": missing_month_ends,
        "snapshots_outside_price_window": outside_window,
        "monthly": monthly,
        "cumulative": cumulative,
        "variants": variants,
        "comparison": comparison,
        "daily_forward": forward,
        "summary": summary,
    }


def log_and_score(payload: dict, frames: dict, benchmark_df, history_dir=SNAPSHOT_DIR, scorecard_path="docs/scorecard.json") -> dict:
    """Save today's snapshot (if the scan was healthy), then rebuild the scorecard from all snapshots."""
    path, reason = save_snapshot(payload, history_dir)
    sc = build_scorecard(load_snapshots(history_dir), frames, benchmark_df)
    sc = sanitize_json(sc)
    sc["snapshot_status"] = reason if path is None else f"saved {os.path.basename(path)}"
    os.makedirs(os.path.dirname(scorecard_path) or ".", exist_ok=True)
    with open(scorecard_path, "w") as fh:
        json.dump(sc, fh, indent=1, allow_nan=False)
    return sc


def run_leaders(universe=None, benchmark_df=None, liquid_top=LIQUID_TOP, board=BOARD_SIZE, sleep=None,
                max_seconds=2700, history_dir=None, max_session=None, require_session=None):
    universe = universe or load_universe()
    if benchmark_df is None:
        benchmark_df = A.fetch_ticker(A.RS_BENCHMARK)
    if benchmark_df is None or benchmark_df.empty:
        raise RuntimeError(f"no benchmark data for {A.RS_BENCHMARK}")
    sleep = A.YF_SLEEP_SECONDS if sleep is None else sleep
    frames, failed = {}, []
    started, partial = time.time(), False
    for t in universe:
        if time.time() - started > max_seconds:        # a slow Yahoo day must not hold the whole daily run hostage
            partial = True
            failed.append(t)
            continue
        try:
            df = A.fetch_ticker(t)
            if df is None or df.empty or len(df) < 260:
                failed.append(t)
            else:
                frames[t] = df
        except Exception as e:                                   # one bad symbol must not sink the run
            failed.append(t)
            print(f"[error] {t}: {e}", file=sys.stderr)
        time.sleep(sleep)
    # Rank every stock on ONE common session (the latest the benchmark and >= 90% of loaded stocks share). Comparing each
    # stock with the benchmark's own last bar rejected the entire universe whenever the ETF's newest bar arrived first.
    session, alignment = A.common_session(frames, benchmark_df, max_session=max_session)
    if session is not None:
        benchmark_df = A.truncate_to_session(benchmark_df, session)
        frames = {t: A.truncate_to_session(df, session) for t, df in frames.items()}
    rows = []
    for t, df in frames.items():
        try:
            rows.append({"ticker": t, **leader_metrics(df, benchmark_df)})
        except Exception as e:
            failed.append(t)
            print(f"[error] {t}: {e}", file=sys.stderr)
    frames = {t: df for t, df in frames.items() if t in {r["ticker"] for r in rows}}
    ranked_pool, counts = select_leaders(rows, liquid_top, max(board, RANKED_SNAPSHOT_SIZE))
    leaders = ranked_pool[:board]
    eligible_ranked = [
        {
            "ticker": r["ticker"],
            "leader_rank": r["leader_rank"],
            "relative_strength_12_1_pct": r["relative_strength_12_1_pct"],
            "last_close": r["last_close"],
        }
        for r in ranked_pool[:RANKED_SNAPSHOT_SIZE]
    ]
    for r in leaders:                                            # structure read for the leaders only
        s = None
        try:
            res = A.score_ticker(frames[r["ticker"]], r["ticker"], benchmark_df)
            s = A.asdict(res) if res else None
        except Exception as e:
            print(f"[structure] {r['ticker']}: {e}", file=sys.stderr)
        r["structure"] = None if s is None else {k: s.get(k) for k in (
            "trend", "support_level", "support_touches", "support_ladder", "resistance_ladder",
            "volume_ratio", "rsi", "above_sma50")}
        r["traded_value_cr"] = round(r["traded_value_126d"] / 1e7, 1)
        try:
            r["plan"] = entry_plan(frames[r["ticker"]], benchmark_df)
            res = [x["level"] for x in ((r["structure"] or {}).get("resistance_ladder") or []) if x["level"] > r["plan"]["ref_close"]]
            r["plan"]["rr_to_next_resistance"] = (round((min(res) - r["plan"]["ref_close"]) / r["plan"]["risk_per_share"], 1)
                                                  if res and r["plan"]["risk_per_share"] else None)
        except Exception as e:
            r["plan"] = None
            print(f"[plan] {r['ticker']}: {e}", file=sys.stderr)
    liquid_universe = [{"ticker": r["ticker"], "close": r["last_close"]} for r in rows if r.get("liquidity_rank") and r["liquidity_rank"] <= liquid_top]
    counts["failed_to_load"] = len(failed)
    counts["partial_scan_time_limit"] = partial
    counts["load_coverage_pct"] = round(100 * (len(universe) - len(failed)) / len(universe), 1)
    out = {
        "as_of": benchmark_df.index[-1].date().isoformat(), "benchmark": A.RS_BENCHMARK,
        "liquid_universe": liquid_universe, "eligible_ranked": eligible_ranked,
        "definition": (f"Top {liquid_top} by 126-day traded value of the Nifty 500 list, close above 200-day average, "
                       "ranked by 12-1 return relative to the benchmark (latest 21 sessions skipped)."),
        "evidence": EVIDENCE, "setup_record": SETUP_RECORD, "counts": counts, "failed_tickers": failed[:60], "leaders": leaders,
        # Why a list is short or empty: status of every stock, and how the common session was chosen.
        "diagnostics": {"rs_status_counts": dict(Counter(r.get("relative_strength_status") for r in rows)),
                        "missing_traded_value": sum(1 for r in rows if not r.get("traded_value_126d")),
                        "session_alignment": alignment},
    }
    if require_session is not None and out["as_of"] != require_session.isoformat():
        # Today's session is not available yet: save NOTHING (no snapshot, no scorecard) and let the caller retry later.
        out["not_ready"] = True
        out["expected_session"] = require_session.isoformat()
        out["snapshot_status"] = f"not saved: data as of {out['as_of']}, expected {require_session.isoformat()}"
        return out
    if history_dir:                                   # the paper-trading log must never be able to break the scan
        try:
            sc = log_and_score(out, frames, benchmark_df, history_dir,
                               os.path.join(os.path.dirname(os.path.normpath(history_dir)), "scorecard.json"))
            out["scorecard_text"], out["snapshot_status"] = sc["summary"], sc["snapshot_status"]
        except Exception as e:
            out["scorecard_text"], out["snapshot_status"] = "Paper log unavailable today.", f"error: {e}"
            print(f"[history] {e}", file=sys.stderr)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="results/leaders_preview.json")
    ap.add_argument("--limit", type=int, help="only the first N symbols (for quick checks)")
    a = ap.parse_args(argv)
    uni = load_universe()
    if a.limit:
        uni = uni[:a.limit]
    t0 = datetime.now()
    out = run_leaders(uni)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"as of {out['as_of']}  counts {out['counts']}  ({(datetime.now() - t0).seconds}s)")
    for r in out["leaders"]:
        print(f"#{r['leader_rank']:>2} {r['ticker']:<14} RS12-1 {r['relative_strength_12_1_pct']:>+7.1f}pp  "
              f"6m {r.get('relative_strength_6m_pct') or 0:>+6.1f}  1m {r.get('relative_strength_1m_pct') or 0:>+6.1f}  "
              f"{r['pct_below_52w_high']}% below 52w high  value {r['traded_value_cr']} cr")


if __name__ == "__main__":
    main()
