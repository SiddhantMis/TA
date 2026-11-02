#!/usr/bin/env python3
"""Validate NSE-sourced NIFTYBEES history against the index and Yahoo diagnostics."""
from datetime import datetime
from zoneinfo import ZoneInfo
import os

import pandas as pd

import backtest as B
from nse_benchmark import (
    apply_niftybees_split_adjustments, load_niftybees_raw_history,
    load_nifty50_index_history, reconcile_niftybees_sources,
)
from nifty500_pit import MEMBERSHIP_COVERAGE_THROUGH
from tejhq_data import get_dataset_revision, load_niftybees_raw_frame
from portfolio_rules import cross_check_benchmark, validate_benchmark

YEARS = 10
END = MEMBERSHIP_COVERAGE_THROUGH.date()
START = (pd.Timestamp(END) - pd.DateOffset(years=YEARS)).date()

# NSE NextApi is the independent benchmark check. TejHQ raw bhavcopy fields are
# the primary NIFTYBEES series so the stock universe and ETF use one data source.
nse_raw = load_niftybees_raw_history(
    START, END, cache_path="data_cache/niftybees_nse_raw.csv"
)
tej_raw, _ = load_niftybees_raw_frame(
    START.isoformat(), END.isoformat(),
    cache_dir="data_cache/tejhq_parquet", revision=get_dataset_revision(),
)
reconciliation = reconcile_niftybees_sources(nse_raw, tej_raw)
tej = apply_niftybees_split_adjustments(tej_raw)
quality = validate_benchmark(tej, "TejHQ raw NIFTYBEES, split-adjusted")
nifty = load_nifty50_index_history(
    START, END, cache_path="data_cache/nifty50_index.csv"
)
index_quality = validate_benchmark(nifty, "official NSE NIFTY 50 price index")
corr = cross_check_benchmark(tej, nifty)

out = [
    f"Primary benchmark source: {tej.attrs.get('source')}",
    f"Requested range: {START} through {END}",
    f"TejHQ bars: {quality['bars']}; max absolute daily return: {quality['max_abs_daily_return_pct']:.2f}%",
    f"NSE API reconciliation: {reconciliation}",
    f"Official NSE NIFTY 50 sessions: {index_quality['bars']}; source={nifty.attrs.get('source')}",
    f"Daily-return correlation of split-adjusted NIFTYBEES vs official NIFTY 50: {corr:.4f}",
    "Corporate action: 10:1 face-value split effective 2019-12-19; pre-ex-date OHLC x0.1, volume x10.",
    f"Adjustment record: {tej.attrs.get('corporate_actions')}",
]

split_start = pd.Timestamp("2019-12-18")
split_end = pd.Timestamp("2019-12-23")
window_raw = tej_raw.loc[split_start:split_end, ["Open", "High", "Low", "Close", "Volume"]]
window_adj = tej.loc[split_start:split_end, ["Open", "High", "Low", "Close", "Volume"]]
out.append("== TejHQ raw NSE bhavcopy prices around the split")
out.extend(
    f"  {day.date()} close={row.Close:.2f} volume={row.Volume:.0f}"
    for day, row in window_raw.iterrows()
)
out.append("== TejHQ prices on current face-value basis")
out.extend(
    f"  {day.date()} close={row.Close:.3f} volume={row.Volume:.0f}"
    for day, row in window_adj.iterrows()
)

# Yahoo is an independent vendor diagnostic only. It is not consumed by the strategy.
try:
    yahoo = B.load_history("NIFTYBEES.NS", YEARS, repair=False)
    if yahoo is not None:
        yahoo_ret = yahoo["Close"].pct_change()
        bad = yahoo_ret[yahoo_ret.abs() > 0.25]
        out.append(f"== Yahoo adjusted-price diagnostic: {len(yahoo)} bars; >25% daily moves: {len(bad)}")
        out.extend(f"  {day.date()} {value * 100:+.1f}%" for day, value in bad.items())
        if split_start in yahoo.index:
            y = yahoo.loc[split_start:split_end, "Close"]
            out.append("== Yahoo split window (diagnostic only)")
            out.extend(f"  {day.date()} close={value:.3f}" for day, value in y.items())
except Exception as exc:
    out.append(f"Yahoo diagnostic unavailable (not used by strategy): {exc}")

os.makedirs("results", exist_ok=True)
report = "\n".join(out)
with open("results/bench_check.md", "w", encoding="utf-8") as handle:
    handle.write(report + "\n")
print(report)
