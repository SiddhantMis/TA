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
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

import analyzer as A

UNIVERSE_FILE = "universe/nifty500.txt"
LIQUID_TOP = 200
BOARD_SIZE = 20
TV_WINDOW = 126
EVIDENCE = ("Backtest 2017-2026, monthly top-20 by 12-1 relative strength among the point-in-time top-200 liquid "
            "Nifty 500 names above their 200-day average: ~28%/yr vs ~15% for holding the same universe equal-weight "
            "and ~10.5% for the Nifty 50, max drawdown about -34%. Survivorship bias remains (failed companies are "
            "missing), the held-out period is 3 years, and nothing here is validated live. See results/portfolio_report_liquid500.md.")


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


def run_leaders(universe=None, benchmark_df=None, liquid_top=LIQUID_TOP, board=BOARD_SIZE, sleep=None,
                max_seconds=2700):
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
    counts["failed_to_load"] = len(failed)
    counts["partial_scan_time_limit"] = partial
    counts["load_coverage_pct"] = round(100 * (len(universe) - len(failed)) / len(universe), 1)
    return {
        "as_of": benchmark_df.index[-1].date().isoformat(), "benchmark": A.RS_BENCHMARK,
        "definition": (f"Top {liquid_top} by 126-day traded value of the Nifty 500 list, close above 200-day average, "
                       "ranked by 12-1 return relative to the benchmark (latest 21 sessions skipped)."),
        "evidence": EVIDENCE, "counts": counts, "failed_tickers": failed[:60], "leaders": leaders,
    }


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
