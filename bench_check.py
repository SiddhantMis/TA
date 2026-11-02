#!/usr/bin/env python3
"""Compare raw vs Yahoo-repaired NIFTYBEES data and validate the NIFTY 50 regime proxy.

The Yahoo repair path uses SciPy for some unit-mixup checks; requirements.txt installs it.
"""
import os

import numpy as np
import pandas as pd

import backtest as B

raw = B.load_history("NIFTYBEES.NS", 10, repair=False)
fixed = B.load_history("NIFTYBEES.NS", 10, repair=True)
nifty = B.load_history("^NSEI", 10)
if raw is None or fixed is None or nifty is None:
    raise SystemExit("Benchmark diagnostic could not download all required series.")


def summarize(name, frame):
    close = pd.to_numeric(frame["Close"], errors="coerce")
    returns = close.pct_change()
    out = [
        f"== {name}: {len(frame)} bars {frame.index[0].date()} to {frame.index[-1].date()}",
        f"   last close {close.iloc[-1]:.4f}; 200-DMA {close.rolling(200, min_periods=200).mean().iloc[-1]:.4f}",
        f"   NaN closes {int(close.isna().sum())}; non-positive closes {int((close <= 0).sum())}",
        f"   daily-return std {returns.std() * 100:.3f}%; max abs move {returns.abs().max() * 100:.2f}%",
    ]
    big = returns[returns.abs() > 0.08]
    out.append(f"   days with |return| > 8%: {len(big)}")
    for day, value in big.items():
        pos = close.index.get_loc(day)
        out.append(f"     {day.date()} {value * 100:+.1f}%: {close.iloc[pos - 1]:.4f} -> {close.iloc[pos]:.4f}")
    return out, returns


out = [
    "NIFTYBEES had a 10:1 face-value split effective 2019-12-19 (NSE circular NSE/CML/42873).",
    "The raw Yahoo series is shown only as a diagnostic; strategy results use repair=True.",
]
raw_lines, raw_ret = summarize("NIFTYBEES raw Yahoo adjusted history", raw)
fixed_lines, fixed_ret = summarize("NIFTYBEES Yahoo repair=True adjusted history", fixed)
nifty_lines, nifty_ret = summarize("^NSEI price-index history", nifty)
out += raw_lines + fixed_lines + nifty_lines

# Show the split window explicitly: the data-quality fix must remove the false one-session jump.
split = pd.Timestamp("2019-12-19")
if split in fixed.index:
    around = fixed.loc[split - pd.Timedelta(days=4):split + pd.Timedelta(days=4), "Close"]
    out.append("== repaired NIFTYBEES split window (2019-12-19)")
    out.extend(f"   {d.date()} close {v:.4f}" for d, v in around.items())

bad = fixed_ret[fixed_ret.abs() > 0.25]
out.append(f"== repaired benchmark hard gate: {len(bad)} daily returns exceed 25%")
if not bad.empty:
    out.extend(f"   FAIL {d.date()} {v * 100:+.1f}%" for d, v in bad.items())

j = pd.concat([fixed["Close"].rename("NIFTYBEES"), nifty["Close"].rename("^NSEI")], axis=1).dropna()
out.append(f"== repaired ETF vs ^NSEI daily-return correlation: {j.pct_change().dropna().corr().iloc[0, 1]:.3f}")
etf_sma = j["NIFTYBEES"].rolling(200, min_periods=200).mean()
idx_sma = j["^NSEI"].rolling(200, min_periods=200).mean()
reg = pd.DataFrame({
    "ETF_BULL": j["NIFTYBEES"] > etf_sma,
    "INDEX_BULL": j["^NSEI"] > idx_sma,
}).dropna()
dis = reg[reg["ETF_BULL"] != reg["INDEX_BULL"]]
out.append(f"== 200-DMA regime comparison: {len(reg)} common sessions; disagreement {len(dis)} ({len(dis) / max(1, len(reg)) * 100:.1f}%)")
if len(dis):
    out.append(f"   first/last disagreement: {dis.index[0].date()} / {dis.index[-1].date()}")

os.makedirs("results", exist_ok=True)
report = "\n".join(out)
open("results/bench_check.md", "w").write("\x60\x60\x60\n" + report + "\n\x60\x60\x60\n")
print(report)
if not bad.empty:
    raise SystemExit("Yahoo repair did not remove all >25% NIFTYBEES daily jumps; do not trust ETF-filter backtest yet.")
