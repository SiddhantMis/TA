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
    """What gets saved each day: the top-20 plus the liquid universe (for the equal-weight baseline)."""
    return {
        "as_of": payload["as_of"], "benchmark": payload["benchmark"], "counts": payload["counts"],
        "leaders": [{"ticker": r["ticker"], "rank": r["leader_rank"], "rs12_1": r["relative_strength_12_1_pct"],
                     "close": r["last_close"], "fired": (r.get("plan") or {}).get("fired", [])} for r in payload["leaders"]],
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
        return (0.0 if not names else None), len(returns), []
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


def _month_end_snapshots(snaps, calendar):
    """Use only the actual final benchmark session of each month; never substitute an earlier scan."""
    month_ends = {}
    for session in calendar:
        month_ends[session.strftime("%Y-%m")] = session
    by_date = {str(s.get("as_of")): s for s in snaps if s.get("as_of")}
    eligible = []
    for signal_date, snap in sorted(by_date.items()):
        try:
            day = pd.Timestamp(signal_date)
        except (TypeError, ValueError):
            continue
        if day not in calendar:
            continue
        expected = month_ends.get(day.strftime("%Y-%m"))
        if expected is not None and day == expected:
            eligible.append(snap)

    first_month = min((str(s.get("as_of"))[:7] for s in snaps if s.get("as_of")), default=None)
    missing_month_ends = []
    if first_month:
        for month, session in sorted(month_ends.items()):
            if month < first_month or session > calendar[-1]:
                continue
            if session.date().isoformat() not in by_date:
                missing_month_ends.append({
                    "month": month,
                    "expected_signal_date": session.date().isoformat(),
                })
    return eligible, missing_month_ends


def build_scorecard(snaps: list, frames: dict, benchmark_df: pd.DataFrame,
                    cost_pct: float = 0.30, n_hold: int = BOARD_SIZE) -> dict:
    """Score month-end leader snapshots with fixed weights and portfolio-style turnover.

    Signal is the final benchmark session of a month; entry is the next session open.
    Missing month-end snapshots are reported, not silently replaced by an earlier scan.
    Missing security prices make the affected basket incomplete instead of reweighting
    the remaining securities. Turnover uses the previous book's drifted weights.
    """
    if benchmark_df is None or benchmark_df.empty or not {"Open", "Close"}.issubset(benchmark_df.columns):
        return {
            "status": "unavailable", "snapshots": len(snaps), "monthly": [],
            "daily_forward": {}, "summary": "Paper log unavailable: benchmark history is missing.",
        }
    calendar = pd.DatetimeIndex(benchmark_df.index).sort_values()
    if len(calendar) < 2:
        return {
            "status": "unavailable", "snapshots": len(snaps), "monthly": [],
            "daily_forward": {}, "summary": "Paper log unavailable: benchmark history is too short.",
        }
    if not snaps:
        return {
            "status": "collecting", "snapshots": 0, "monthly": [],
            "daily_forward": {}, "missing_month_ends": [],
            "summary": "Paper log: no snapshots yet.",
        }

    signals, missing_month_ends = _month_end_snapshots(snaps, calendar)
    outside_window = [
        str(s.get("as_of")) for s in snaps
        if s.get("as_of") and pd.Timestamp(s["as_of"]) < calendar[0]
    ]
    non_month_end = [
        str(s.get("as_of")) for s in snaps
        if s.get("as_of") and pd.Timestamp(s["as_of"]) in calendar
        and all(s.get("as_of") != x.get("as_of") for x in signals)
        and pd.Timestamp(s["as_of"]).strftime("%Y-%m") in {
            pd.Timestamp(x["expected_signal_date"]).strftime("%Y-%m")
            for x in missing_month_ends
        }
    ]

    monthly = []
    previous_weights = {}
    previous_entry = None
    for i, snap in enumerate(signals):
        signal_date = pd.Timestamp(snap["as_of"])
        entry_pos = calendar.searchsorted(signal_date, side="right")
        if entry_pos >= len(calendar):
            monthly.append({
                "signal_date": snap["as_of"], "status": "pending",
                "data_status": "waiting_for_next_session",
            })
            continue
        entry_date = calendar[entry_pos]

        top = list(dict.fromkeys(x["ticker"] for x in snap.get("leaders", []) if x.get("ticker")))
        liquid = list(dict.fromkeys(x["ticker"] for x in snap.get("liquid", []) if x.get("ticker")))
        current_weights = {ticker: 1.0 / float(n_hold) for ticker in top} if n_hold > 0 else {}

        turnover = None
        missing_turnover = []
        if previous_entry is None:
            turnover = sum(current_weights.values())
        else:
            drift_returns, _, missing_turnover = _basket_return(
                list(previous_weights), frames, previous_entry, entry_date, "Open",
                denominator=max(1, len(previous_weights)),
            )
            # The equal-weight basket helper above is not used for drift: each old
            # position has its own prior weight, so fetch its individual return.
            individual, unavailable = {}, []
            for ticker in previous_weights:
                a = _px(frames, ticker, "Open", previous_entry)
                b = _px(frames, ticker, "Open", entry_date)
                if not (np.isfinite(a) and np.isfinite(b) and a > 0):
                    unavailable.append(ticker)
                else:
                    individual[ticker] = b / a - 1.0
            missing_turnover = unavailable
            if not unavailable:
                prior_return = sum(previous_weights[t] * individual[t] for t in previous_weights)
                if 1.0 + prior_return > 0:
                    drifted_weights = {
                        t: w * (1.0 + individual[t]) / (1.0 + prior_return)
                        for t, w in previous_weights.items()
                    }
                    all_names = set(drifted_weights) | set(current_weights)
                    turnover = sum(
                        abs(current_weights.get(t, 0.0) - drifted_weights.get(t, 0.0))
                        for t in all_names
                    )

        next_entry = None
        closed = False
        if i + 1 < len(signals):
            next_signal = pd.Timestamp(signals[i + 1]["as_of"])
            next_pos = calendar.searchsorted(next_signal, side="right")
            if next_pos < len(calendar):
                next_entry = calendar[next_pos]
                closed = True
        if closed:
            exit_date, exit_kind = next_entry, "Open"
        else:
            exit_date, exit_kind = calendar[-1], "Close"

        top_gross, top_priced, top_missing = _basket_return(
            top, frames, entry_date, exit_date, exit_kind, denominator=n_hold,
        )
        universe_gross, universe_priced, universe_missing = _basket_return(
            liquid, frames, entry_date, exit_date, exit_kind, denominator=len(liquid),
        )
        benchmark_return = _benchmark_return(benchmark_df, entry_date, exit_date, exit_kind)
        net = (
            top_gross - turnover * cost_pct / 200.0
            if top_gross is not None and turnover is not None else None
        )
        data_complete = (
            not top_missing and not universe_missing and benchmark_return is not None
        )
        if not data_complete:
            data_status = "missing_price_data"
        elif turnover is None:
            data_status = "turnover_unavailable"
        else:
            data_status = "complete"

        row_status = ("closed" if closed else "open") if data_status == "complete" else (
            "incomplete_data" if closed else "open_incomplete"
        )
        monthly.append({
            "signal_date": snap["as_of"],
            "entry_date": entry_date.date().isoformat(),
            "exit_date": exit_date.date().isoformat(),
            "status": row_status,
            "data_status": data_status,
            "holdings": len(top),
            "priced": top_priced,
            "expected_holdings": len(top),
            "missing_tickers": top_missing[:20],
            "liquid_universe_size": len(liquid),
            "liquid_priced": universe_priced,
            "liquid_missing_count": len(universe_missing),
            "missing_turnover_tickers": missing_turnover[:20],
            "turnover_l1": turnover,
            "top20_gross": top_gross,
            "top20_net": net,
            "same_universe_equal_weight": universe_gross,
            "nifty50": benchmark_return,
            "excess_vs_universe": net - universe_gross if net is not None and universe_gross is not None else None,
            "excess_vs_nifty": net - benchmark_return if net is not None and benchmark_return is not None else None,
        })

        # At the next signal, drift this book from its entry open to the next entry open.
        # The next loop calculates the drifted weights from these target weights.
        previous_weights = current_weights
        previous_entry = entry_date

    closed_rows = [m for m in monthly if m.get("status") == "closed"]
    complete_closed = [m for m in closed_rows if m.get("data_status") == "complete"]
    incomplete_closed = [m for m in closed_rows if m.get("data_status") != "complete"]
    cumulative = {
        "status": "complete" if closed_rows and not incomplete_closed else "incomplete",
        "months": len(complete_closed),
        "top20_net": None,
        "same_universe_equal_weight": None,
        "nifty50": None,
    }
    if closed_rows and not incomplete_closed:
        for key in ("top20_net", "same_universe_equal_weight", "nifty50"):
            values = [m[key] for m in closed_rows]
            if all(v is not None and np.isfinite(v) for v in values):
                cumulative[key] = float(np.prod([1.0 + v for v in values]) - 1.0)
            else:
                cumulative["status"] = "incomplete"

    # Overlapping 5/21/63-session diagnostics; each basket remains fixed-weight.
    forward = {}
    for horizon in (5, 21, 63):
        excess, fired_excess, quiet_excess = [], [], []
        expected, incomplete = 0, 0
        for snap in snaps:
            signal_date = pd.Timestamp(snap["as_of"])
            if signal_date < calendar[0] or signal_date >= calendar[-1]:
                continue
            pos = calendar.searchsorted(signal_date, side="right")
            if pos + horizon - 1 >= len(calendar):
                continue
            expected += 1
            entry, exit_date = calendar[pos], calendar[pos + horizon - 1]
            basket, _, missing = _basket_return(
                [x["ticker"] for x in snap.get("leaders", [])],
                frames, entry, exit_date, "Close", denominator=n_hold,
            )
            benchmark_return = _benchmark_return(benchmark_df, entry, exit_date, "Close")
            if basket is None or benchmark_return is None:
                incomplete += 1
            else:
                excess.append(basket - benchmark_return)
            for item in snap.get("leaders", []):
                ticker = item.get("ticker")
                if not ticker:
                    continue
                single, _, missing_single = _basket_return(
                    [ticker], frames, entry, exit_date, "Close", denominator=1,
                )
                if single is None:
                    continue
                (fired_excess if item.get("fired") else quiet_excess).append(single - benchmark_return)
        forward[f"{horizon}d"] = {
            "expected_snapshots": expected,
            "snapshots": len(excess),
            "incomplete_snapshots": incomplete,
            "mean_excess_vs_nifty": float(np.mean(excess)) if excess else None,
            "share_positive": float(np.mean([x > 0 for x in excess])) if excess else None,
            "setup_fired_n": len(fired_excess),
            "setup_fired_mean_excess": float(np.mean(fired_excess)) if fired_excess else None,
            "no_setup_n": len(quiet_excess),
            "no_setup_mean_excess": float(np.mean(quiet_excess)) if quiet_excess else None,
        }

    first = min((str(s.get("as_of")) for s in snaps if s.get("as_of")), default="unknown")
    if closed_rows and not incomplete_closed and cumulative["status"] == "complete":
        summary = (
            f"Paper log since {first}: {len(closed_rows)} completed month(s): "
            f"top-20 {cumulative['top20_net'] * 100:+.1f}% vs Nifty "
            f"{cumulative['nifty50'] * 100:+.1f}% vs same-universe equal-weight "
            f"{cumulative['same_universe_equal_weight'] * 100:+.1f}% (after costs; far too early to judge)."
        )
    elif incomplete_closed:
        summary = (
            f"Paper log since {first}: {len(complete_closed)} complete and "
            f"{len(incomplete_closed)} incomplete closed interval(s). Cumulative returns withheld "
            "because incomplete price coverage would bias the result."
        )
    else:
        summary = (
            f"Paper log: {len(signals)} month-end snapshot(s) since {first}; "
            "the first completed interval is not available yet."
        )

    return {
        "schema_version": 2,
        "status": cumulative["status"] if closed_rows else "tracking",
        "snapshots": len(snaps),
        "month_end_snapshots": len(signals),
        "first_snapshot": first,
        "missing_month_ends": missing_month_ends,
        "snapshots_outside_price_window": outside_window,
        "monthly": monthly,
        "cumulative": cumulative,
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
                max_seconds=2700, history_dir=None):
    universe = universe or load_universe()
    if benchmark_df is None:
        benchmark_df = A.fetch_ticker(A.RS_BENCHMARK)
    if benchmark_df is None or benchmark_df.empty:
        raise RuntimeError(f"no benchmark data for {A.RS_BENCHMARK}")
    sleep = A.YF_SLEEP_SECONDS if sleep is None else sleep
    rows, frames, failed = [], {}, []
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
                rows.append({"ticker": t, **leader_metrics(df, benchmark_df)})
                frames[t] = df
        except Exception as e:                                   # one bad symbol must not sink the run
            failed.append(t)
            print(f"[error] {t}: {e}", file=sys.stderr)
        time.sleep(sleep)
    leaders, counts = select_leaders(rows, liquid_top, board)
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
        "as_of": benchmark_df.index[-1].date().isoformat(), "benchmark": A.RS_BENCHMARK, "liquid_universe": liquid_universe,
        "definition": (f"Top {liquid_top} by 126-day traded value of the Nifty 500 list, close above 200-day average, "
                       "ranked by 12-1 return relative to the benchmark (latest 21 sessions skipped)."),
        "evidence": EVIDENCE, "setup_record": SETUP_RECORD, "counts": counts, "failed_tickers": failed[:60], "leaders": leaders,
    }
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
