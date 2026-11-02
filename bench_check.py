#!/usr/bin/env python3
"""Data-quality check of the benchmark series that drives the market filter: NIFTYBEES.NS vs ^NSEI."""
import os
import numpy as np
import pandas as pd
import backtest as B

nb = B.load_history("NIFTYBEES.NS", 10)
ix = B.load_history("^NSEI", 10)
out = []
for name, df in (("NIFTYBEES.NS", nb), ("^NSEI", ix)):
    c = df["Close"]
    r = c.pct_change()
    out.append(f"== {name}: {len(df)} bars {df.index[0].date()} to {df.index[-1].date()}, last close {c.iloc[-1]:.2f}, 200-DMA {c.rolling(200).mean().iloc[-1]:.2f}")
    out.append(f"   NaN closes {int(c.isna().sum())}, zero/negative closes {int((c <= 0).sum())}, daily-return std {r.std() * 100:.2f}%")
    big = r[r.abs() > 0.08]
    out.append(f"   days with |return| > 8%: {len(big)}")
    for d, v in big.items():
        i = c.index.get_loc(d)
        out.append(f"     {d.date()}  return {v * 100:+.1f}%   close {c.iloc[i - 1]:.4f} -> {c.iloc[i]:.4f}   (open {df['Open'].iloc[i]:.4f})")
j = pd.concat([nb["Close"].pct_change().rename("nb"), ix["Close"].pct_change().rename("ix")], axis=1).dropna()
out.append(f"== daily-return correlation NIFTYBEES vs ^NSEI: {j.corr().iloc[0, 1]:.3f}")
gap = (j.nb - j.ix).abs()
out.append(f"   days where they differ by > 3 points: {int((gap > 0.03).sum())}")
for d in gap[gap > 0.03].index[:12]:
    out.append(f"     {d.date()}  NIFTYBEES {j.nb[d] * 100:+.1f}%  ^NSEI {j.ix[d] * 100:+.1f}%")
reg = {}
for name, df in (("NIFTYBEES", nb), ("NSEI", ix)):
    c = df["Close"]; reg[name] = (c > c.rolling(200, min_periods=200).mean()).where(c.rolling(200, min_periods=200).mean().notna())
r2 = pd.concat(reg, axis=1).dropna()
out.append(f"== market filter agreement (BULL = close above 200-DMA): {len(r2)} days, share BEAR: NIFTYBEES {100 * (~r2.NIFTYBEES.astype(bool)).mean():.0f}%  ^NSEI {100 * (~r2.NSEI.astype(bool)).mean():.0f}%, disagree on {int((r2.NIFTYBEES != r2.NSEI).sum())} days")
dis = r2[r2.NIFTYBEES != r2.NSEI]
if len(dis):
    out.append(f"   first/last disagreement: {dis.index[0].date()} / {dis.index[-1].date()}")
os.makedirs("results", exist_ok=True)
open("results/bench_check.md", "w").write("```\n" + "\n".join(out) + "\n```\n")
print("\n".join(out))
