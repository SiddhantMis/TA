#!/usr/bin/env python3
"""Validate NSE-sourced NIFTYBEES history against the index and Yahoo diagnostics."""
from datetime import datetime
from zoneinfo import ZoneInfo
import os

import pandas as pd

import backtest as B
from nse_benchmark import apply_niftybees_split_adjustments, fetch_niftybees_history
from portfolio_rules import cross_check_benchmark, validate_benchmark

YEARS = 10
END = datetime.now(ZoneInfo("Asia/Kolkata")).date()
START = (pd.Timestamp(END) - pd.DateOffset(years=YEARS)).date()

# NSE traded OHLCV is the source of truth. Yahoo is diagnostic only.
nse_raw = fetch_niftybees_history(START, END)
nse = apply_niftybees_split_adjustments(nse_raw)
quality = validate_benchmark(nse, "NSE split-adjusted NIFTYBEES")

# The index is an independent cross-check, not a replacement for the ETF filter.
nifty = B.load_history("^NSEI", YEARS)
if nifty is None:
    raise SystemExit("Could not download ^NSEI for benchmark cross-check.")
corr = cross_check_benchmark(nse, nifty)

out = [
    f"Primary source: {nse.attrs.get('source')}",
    f"Requested range: {START} through {END}",
    f"NSE bars: {quality['bars']}; max absolute daily return: {quality['max_abs_daily_return_pct']:.2f}%",
    f"Daily-return correlation of split-adjusted NSE NIFTYBEES vs ^NSEI: {corr:.4f}",
    "Corporate action: 10:1 face-value split effective 2019-12-19; pre-ex-date OHLC x0.1, volume x10.",
    f"Adjustment record: {nse.attrs.get('corporate_actions')}",
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
