#!/usr/bin/env python3
"""Do fixed entry setups add anything INSIDE the momentum leaders?  (the open question in the plan)

    python leader_setups.py --years 10 --oos-frac 0.35 --cost-pct 0.30

Pre-registered (nothing here is tuned; the setups, exits and rule are research.py's, unchanged):
  leader    point-in-time: top-200 by 126-day traded value, close above its 200-day average, and in the
            top LEAD_N=20 by 12-1 return among those, on the signal date (the same list leaders.py shows)
  setups    breakout55 (close above the prior 55-day high, volume >= 20-day average, uptrend) and
            pullback20 (uptrend, dipped under the 20-day EMA in the last 3 days, closed back above it on an up day)
  entry     next session's open; exit = initial stop 2 x ATR14, trail 3 x ATR14 from the highest close,
            60-session time stop, 0.30% round-trip cost
  controls  ctrl_leader: the same exits applied on EVERY leader day (entering whenever flat);
            ctrl_other: same on liquid uptrend stocks that are NOT leaders, to show whether leader context matters
  split     first (1 - oos_frac) of the calendar in-sample, the rest out-of-sample
  adopt     research.verdict(): OOS trades >= 100, IS and OOS avg R > 0, OOS beats the matched control,
            OOS 95% interval (months resampled) excludes 0.  Four setup variants are tried.
A setup that fails stays a description ("this fired"), not a recommendation.
Biases that flatter results: today's Nifty 500 list (survivorship), daily bars, flat cost, trades may overlap across stocks.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

import analyzer as A
import backtest as B
import leaders as LD
import pattern_lab as PL
import research as R

LEAD_N = 20
LIQUID_TOP = 200


def leader_mask(frames: dict, liquid_top=LIQUID_TOP, lead_n=LEAD_N):
    """(dates x tickers) bool: is the stock a point-in-time leader on that date? Uses data through each date only."""
    idx = pd.DatetimeIndex(sorted(set().union(*[f.index for f in frames.values()])))
    cols = list(frames)
    C = pd.concat({t: frames[t].Close for t in cols}, axis=1).reindex(idx)
    V = pd.concat({t: frames[t].Volume for t in cols}, axis=1).reindex(idx)
    sma200 = C.rolling(200, min_periods=200).mean()
    tv = (C * V).rolling(126, min_periods=100).mean()
    liquid = tv.rank(axis=1, ascending=False) <= liquid_top
    mom = C.shift(21) / C.shift(252) - 1
    elig = liquid & (C > sma200) & mom.notna()
    rank = mom.where(elig).rank(axis=1, ascending=False)
    return (rank <= lead_n), liquid


def run_setups(frames, bench_close, oos_frac=0.35, cost_pct=0.30, lead_n=LEAD_N, liquid_top=LIQUID_TOP):
    mkt_up = bench_close > bench_close.rolling(200).mean()
    lead, liquid = leader_mask(frames, liquid_top, lead_n)
    rows = []
    for t, df in frames.items():
        d = R.prep(df, mkt_up)
        d["rs"] = np.nan
        sg = R.signals(d)
        L = lead[t].reindex(d.index).fillna(False).astype(bool)
        other = (d.uptrend & liquid[t].reindex(d.index).fillna(False).astype(bool) & ~L).astype(bool)
        variants = {"ctrl_leader": L, "breakout55@leader": sg["breakout55"] & L, "pullback20@leader": sg["pullback20"] & L,
                    "ctrl_other": other, "breakout55@other": sg["breakout55"] & other, "pullback20@other": sg["pullback20"] & other}
        for name, sig in variants.items():
            rows += R.run_trades(d, sig, name, t, cost_pct)
    tr = pd.DataFrame(rows)
    if tr.empty:
        return tr, "No trades generated."
    lo_d, hi_d = tr.signal_date.min(), tr.signal_date.max()
    split = lo_d + (hi_d - lo_d) * (1 - oos_frac)
    tr["period"] = np.where(tr.signal_date <= split, "IS", "OOS")
    S = {(n, p): R.stats(tr[(tr.variant == n) & (tr.period == p)]) for n in tr.variant.unique() for p in ("IS", "OOS")}
    head = (f"{'variant':<22}{'per':<5}{'n':>6}{'win%':>7}{'avg R':>8}{'95% (month boot)':>16}{'PF':>6}{'bars':>6}{'ret/tr':>9}{'vs ctrl':>8}")
    out = [f"Leader setups: {tr.ticker.nunique()} stocks, trades {lo_d.date()} to {hi_d.date()}, split {split.date()}, "
           f"leaders = top {lead_n} of liquid top {liquid_top} above 200-DMA by 12-1, cost {cost_pct}%",
           f"Exit: stop {R.ATR_STOP}xATR, trail {R.ATR_TRAIL}xATR from highest close, time stop {R.MAX_HOLD}d. R net of cost, 1R = 2xATR.", "", head]
    ctrl_of = {"leader": "ctrl_leader", "other": "ctrl_other"}
    verdicts = []
    for grp in ("leader", "other"):
        out.append(f"-- {grp} stocks --")
        for n in (f"ctrl_{grp}", f"breakout55@{grp}", f"pullback20@{grp}"):
            for p in ("IS", "OOS"):
                c = S.get((ctrl_of[grp], p))
                s = S.get((n, p))
                out.append(R._fmt(n, p, s, c if (c and s and not n.startswith("ctrl")) else None))
            if not n.startswith("ctrl"):
                verdicts.append((n, R.verdict(S.get((n, "IS")), S.get((n, "OOS")), S.get((ctrl_of[grp], "OOS")))))
    tr["year"] = tr.signal_date.dt.year
    out += ["", "-- avg R by signal year (n) --"]
    for n in sorted(tr.variant.unique()):
        parts = [f"{y}:{g.R.mean():+.2f}({len(g)})" for y, g in tr[tr.variant == n].groupby("year")]
        out.append(f"{n:<22}" + " ".join(parts))
    out += ["", "-- verdicts (rule fixed in advance) --"] + [f"{n:<22}{v}" for n, v in verdicts]
    return tr, "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--oos-frac", type=float, default=0.35)
    ap.add_argument("--cost-pct", type=float, default=0.30)
    ap.add_argument("--cache", default="data_cache/frames_10y.pkl")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--outdir", default="results")
    a = ap.parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)
    bench = B.load_history("^NSEI", a.years)
    if bench is None:
        sys.exit("could not fetch ^NSEI")
    frames = PL.load_frames(LD.load_universe(), a.years, a.cache, a.refresh)
    tr, text = run_setups(frames, bench["Close"], a.oos_frac, a.cost_pct)
    tr.to_csv(os.path.join(a.outdir, "leader_setups_trades.csv"), index=False)
    open(os.path.join(a.outdir, "leader_setups_report.md"), "w").write("```\n" + text + "\n```\n")
    print(text)


if __name__ == "__main__":
    main()
