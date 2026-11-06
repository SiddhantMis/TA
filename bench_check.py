#!/usr/bin/env python3
"""Reconcile TejHQ NIFTYBEES raw bhavcopy history to NSE and validate the official index."""
from datetime import datetime
from zoneinfo import ZoneInfo
import os

import pandas as pd

import backtest as B
from nse_benchmark import (
    apply_niftybees_split_adjustments, build_nse_session_calendar,
    load_niftybees_raw_history, load_nifty50_index_history,
    merge_niftybees_sources,
)
from nifty500_pit import MEMBERSHIP_COVERAGE_THROUGH
from tejhq_data import get_dataset_revision, load_niftybees_raw_frame
from portfolio_rules import cross_check_benchmark, validate_benchmark

YEARS = 10
END = MEMBERSHIP_COVERAGE_THROUGH.date()
START = (pd.Timestamp(END) - pd.DateOffset(years=YEARS)).date()

# NSE NextApi is primary. TejHQ is a second ingestion of NSE bhavcopy data,
# not an independent market-data source. NSE-only dates are retained, never filled.
nse_raw = load_niftybees_raw_history(
    START, END, cache_path="data_cache/niftybees_nse_raw.csv"
)
tej_raw, _ = load_niftybees_raw_frame(
    START.isoformat(), END.isoformat(),
    cache_dir="data_cache/tejhq_parquet", revision=get_dataset_revision(),
)
nifty = load_nifty50_index_history(
    START, END, cache_path="data_cache/nifty50_index.csv"
)
index_sessions = pd.DatetimeIndex(pd.to_datetime(nifty.index))
if index_sessions.tz is not None:
    index_sessions = index_sessions.tz_localize(None)
index_sessions = index_sessions.normalize().sort_values()
official_sessions = build_nse_session_calendar(
    START, END, index_sessions=index_sessions,
)
official_sessions = official_sessions[
    (official_sessions >= index_sessions.min())
    & (official_sessions <= index_sessions.max())
]
calendar_start, calendar_end = official_sessions.min(), official_sessions.max()
index_coverage = len(index_sessions.intersection(official_sessions)) / len(official_sessions)
missing_index = official_sessions.difference(index_sessions)
if index_coverage < 0.99:
    raise RuntimeError(
        f"NSE NIFTY 50 index coverage is only {index_coverage:.3%}; "
        f"missing NSE-calendar sessions: {missing_index.strftime('%Y-%m-%d').tolist()[:20]}"
    )
nse_raw.index = pd.DatetimeIndex(pd.to_datetime(nse_raw.index)).normalize()
tej_raw.index = pd.DatetimeIndex(pd.to_datetime(tej_raw.index)).normalize()
nse_raw = nse_raw.loc[
    (nse_raw.index >= calendar_start) & (nse_raw.index <= calendar_end)
].copy()
tej_raw = tej_raw.loc[
    (tej_raw.index >= calendar_start) & (tej_raw.index <= calendar_end)
].copy()
benchmark_raw, reconciliation = merge_niftybees_sources(
    nse_raw, tej_raw, allowed_extra_sessions=official_sessions,
)
nse = apply_niftybees_split_adjustments(benchmark_raw)
nse_quality = validate_benchmark(nse, "NSE/TejHQ split-adjusted NIFTYBEES")
tej = apply_niftybees_split_adjustments(tej_raw)
tej_quality = validate_benchmark(tej, "TejHQ raw NIFTYBEES, split-adjusted")
quality = nse_quality
index_quality = validate_benchmark(nifty, "official NSE NIFTY 50 price index")
corr = cross_check_benchmark(nse, nifty)

out = [
    f"Primary benchmark source: {nse.attrs.get('source')}",
    f"Requested range: {START} through {END}",
    f"NSE bars: {quality['bars']}; max absolute daily return: {quality['max_abs_daily_return_pct']:.2f}%",
    f"TejHQ cross-check bars: {tej_quality['bars']}; max abs daily move: {tej_quality['max_abs_daily_return_pct']:.2f}%",
    f"NSE / TejHQ reconciliation: {reconciliation}",
    f"TejHQ-only bars accepted as supplements on validated NSE-calendar sessions: {reconciliation['tejhq_only_dates']}",
    f"NSE session calendar: pandas_market_calendars==5.6.0 plus observed NSE NIFTY 50 sessions ({len(official_sessions)} sessions)",
    f"NSE-calendar sessions missing NIFTY 50 index rows: {len(missing_index)}; index coverage={index_coverage:.3%}; dates={missing_index.strftime('%Y-%m-%d').tolist()[:20]}",
    f"Official NSE NIFTY 50 index rows: {index_quality['bars']}; source={nifty.attrs.get('source')}",
    f"Daily-return correlation of split-adjusted NIFTYBEES vs available NIFTY 50 index rows: {corr:.4f}",
    "Corporate action: 10:1 face-value split effective 2019-12-19; pre-ex-date OHLC x0.1, volume x10.",
    f"Adjustment record: {tej.attrs.get('corporate_actions')}",
]

split_start = pd.Timestamp("2019-12-18")
split_end = pd.Timestamp("2019-12-23")
window_raw = nse_raw.loc[split_start:split_end, ["Open", "High", "Low", "Close", "Volume"]]
window_adj = nse.loc[split_start:split_end, ["Open", "High", "Low", "Close", "Volume"]]
out.append("== NSE raw exchange prices around the split")
out.extend(
    f"  {day.date()} close={row.Close:.2f} volume={row.Volume:.0f}"
    for day, row in window_raw.iterrows()
)
out.append("== NSE prices on current face-value basis")
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
