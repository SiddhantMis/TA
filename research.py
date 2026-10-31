#!/usr/bin/env python3
"""Pre-registered research on long-only daily setups for NSE cash delivery.

    python research.py --years 10 --oos-frac 0.35 --cost-pct 0.30

Why this exists: backtest.py showed the candlestick-reversal flags have no edge. This
tests a small FIXED set of trend/momentum setups, with exits built for them, against
matched controls, with a held-out final period.

Rules fixed BEFORE looking at any result (there is no tuning loop):
  setups  breakout55, pullback20, rs_breakout -- each with and without a market filter
          (Nifty above its 200-day average)
  entry   next session's open after the signal close (an EOD alert plans tomorrow's open)
  exit    initial stop = fill - 2*ATR14; trail = highest close since entry - 3*ATR14;
          a gap through the stop exits at the open; 60-session time stop
  control the same exits applied to EVERY eligible day of the matching trend state
          (ctrl_uptrend for breakout55/pullback20, ctrl_above50 for rs_breakout)
  split   first (1 - oos_frac) of the calendar = in-sample, the rest = out-of-sample
  adopt   only if: OOS trades >= 100, IS avg R > 0, OOS avg R > 0, OOS avg R beats the
          matched control, and the OOS 95% interval (months resampled) excludes 0.
Six variants are tried, so one interval excluding zero by luck is possible: look for
agreement between IS and OOS and across years, not a single number.

Biases that flatter results: today's watchlist only (survivorship), daily bars, one flat
cost, no portfolio limits (trades on different tickers can overlap).
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

import analyzer as A
import backtest as B

BENCH = "^NSEI"
ATR_STOP = 2.0
ATR_TRAIL = 3.0
MAX_HOLD = 60
MIN_BARS = 252
SETUPS = ("breakout55", "pullback20", "rs_breakout")
CONTROL_FOR = {"breakout55": "ctrl_uptrend", "pullback20": "ctrl_uptrend", "rs_breakout": "ctrl_above50"}


def prep(df: pd.DataFrame, mkt_up: pd.Series) -> pd.DataFrame:
    d = df[["Open", "High", "Low", "Close", "Volume"]].astype(float).copy()
    c, h, l = d.Close, d.High, d.Low
    d["sma50"] = c.rolling(50).mean()
    d["sma200"] = c.rolling(200).mean()
    d["ema20"] = c.ewm(span=20, adjust=False).mean()
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.rolling(14).mean()
    d["hh55"] = h.rolling(55).max().shift(1)      # prior highs only: today is excluded
    d["hh20"] = h.rolling(20).max().shift(1)
    d["ret126"] = c.pct_change(126)
    d["vol_ratio"] = d.Volume / d.Volume.rolling(20).mean()
    d["uptrend"] = (c > d.sma200) & (d.sma50 > d.sma200)
    d["mkt_up"] = mkt_up.reindex(d.index).ffill().fillna(False).astype(bool)
    return d


def build_universe(frames: dict, bench: pd.Series) -> dict:
    mkt_up = bench > bench.rolling(200).mean()
    prepped = {t: prep(df, mkt_up) for t, df in frames.items()}
    ret = pd.concat({t: d.ret126 for t, d in prepped.items()}, axis=1)
    rank = ret.rank(axis=1, pct=True)             # same-date cross-section only
    for t, d in prepped.items():
        d["rs"] = rank[t].reindex(d.index)
    return prepped


def signals(d: pd.DataFrame) -> dict:
    c, o, l = d.Close, d.Open, d.Low
    base = {
        "breakout55": (c > d.hh55) & d.uptrend & (d.vol_ratio >= 1.0),
        "pullback20": d.uptrend & (l.rolling(3).min() < d.ema20) & (c > d.ema20) & (c > o),
        "rs_breakout": (d.rs >= 0.75) & (c > d.hh20) & (c > d.sma50),
        "ctrl_uptrend": d.uptrend,
        "ctrl_above50": c > d.sma50,
    }
    out = {}
    for k, v in base.items():
        v = v.fillna(False).astype(bool)
        out[k] = v
        out[k + "+mkt"] = v & d.mkt_up
    return out


def run_trades(d, sig, name, ticker, cost_pct=0.30, start=MIN_BARS, max_hold=MAX_HOLD):
    O, H, L, C, ATR = (d[c].to_numpy(float) for c in ("Open", "High", "Low", "Close", "atr"))
    s = sig.to_numpy(bool)
    n, rows, i = len(d), [], start
    while i < n - 1:
        if not s[i] or not np.isfinite(ATR[i]) or ATR[i] <= 0:
            i += 1
            continue
        k0 = i + 1
        fill = O[k0]
        risk = ATR_STOP * ATR[i]
        stop0 = fill - risk
        if stop0 <= 0:
            i += 1
            continue
        stop, hi_close = stop0, fill
        exit_px = why = None
        exit_idx = k0
        last = min(k0 + max_hold, n - 1)
        for k in range(k0, last + 1):
            if k > k0:                             # trail uses closes through the PREVIOUS bar
                hi_close = max(hi_close, C[k - 1])
                stop = max(stop, hi_close - ATR_TRAIL * ATR[i])
                if O[k] <= stop:
                    exit_px, why = O[k], "stop"
            if exit_px is None and L[k] <= stop:
                exit_px, why = stop, "stop"
            if exit_px is not None:
                exit_idx = k
                break
        if exit_px is None:
            if k0 + max_hold <= n - 1:
                exit_px, why, exit_idx = C[last], "time", last
            else:
                break                              # still open at the end of the data
        cost = fill * cost_pct / 100.0
        rows.append({"ticker": ticker, "variant": name, "signal_date": d.index[i],
                     "exit_date": d.index[exit_idx], "R": (exit_px - fill - cost) / risk,
                     "ret": (exit_px - fill - cost) / fill, "bars": exit_idx - k0, "why": why})
        i = exit_idx + 1
    return rows


def month_boot(df, reps=1000, seed=7):
    m = df.signal_date.dt.to_period("M").astype(str).to_numpy()
    if len(set(m)) < 8:
        return (np.nan, np.nan)
    keys = sorted(set(m))
    s = np.array([df.R.to_numpy()[m == k].sum() for k in keys])
    c = np.array([(m == k).sum() for k in keys], float)
    idx = np.random.default_rng(seed).integers(0, len(keys), size=(reps, len(keys)))
    means = s[idx].sum(1) / c[idx].sum(1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def stats(df):
    if df is None or df.empty:
        return None
    R = df.R.to_numpy()
    wins, losses = R[R > 0].sum(), -R[R <= 0].sum()
    lo, hi = month_boot(df)
    return {"n": len(df), "win": float((R > 0).mean()), "avg": float(R.mean()),
            "pf": float(wins / losses) if losses > 0 else float("inf"),
            "lo": lo, "hi": hi, "bars": float(df.bars.mean()), "ret": float(df.ret.mean())}


def verdict(is_s, oos_s, ctrl_oos):
    why = []
    if oos_s is None or oos_s["n"] < 100:
        why.append(f"OOS trades {0 if oos_s is None else oos_s['n']} < 100")
    if is_s is None or is_s["avg"] <= 0:
        why.append("IS avg R <= 0")
    if oos_s is not None:
        if oos_s["avg"] <= 0:
            why.append("OOS avg R <= 0")
        if ctrl_oos is not None and oos_s["avg"] <= ctrl_oos["avg"]:
            why.append("does not beat matched control OOS")
        if not (oos_s["lo"] > 0):
            why.append("OOS interval includes 0")
    return "PASS" if not why else "FAIL: " + "; ".join(why)


def _fmt(label, period, s, ctrl=None):
    if s is None:
        return f"{label:<22}{period:<5}{0:>6}"
    ci = f"[{s['lo']:+.2f},{s['hi']:+.2f}]" if np.isfinite(s["lo"]) else "[n/a]"
    ex = f"{s['avg'] - ctrl['avg']:+.2f}" if ctrl else ""
    return (f"{label:<22}{period:<5}{s['n']:>6}{s['win'] * 100:>6.0f}%{s['avg']:>+8.2f}{ci:>16}"
            f"{s['pf']:>6.2f}{s['bars']:>6.0f}{s['ret'] * 100:>+8.2f}%{ex:>8}")


def run_research(frames, bench, oos_frac=0.35, cost_pct=0.30):
    prepped = build_universe(frames, bench)
    rows = []
    for t, d in prepped.items():
        for name, sig in signals(d).items():
            rows += run_trades(d, sig, name, t, cost_pct)
    tr = pd.DataFrame(rows)
    if tr.empty:
        return tr, "No trades generated."
    lo_d, hi_d = tr.signal_date.min(), tr.signal_date.max()
    split = lo_d + (hi_d - lo_d) * (1 - oos_frac)
    tr["period"] = np.where(tr.signal_date <= split, "IS", "OOS")

    head = (f"{'variant':<22}{'per':<5}{'n':>6}{'win%':>7}{'avg R':>8}{'95% (month boot)':>16}"
            f"{'PF':>6}{'bars':>6}{'ret/tr':>9}{'vs ctrl':>8}")
    out = [f"Research: {len(frames)} tickers, trades {lo_d.date()} to {hi_d.date()}, "
           f"IS/OOS split {split.date()}, cost {cost_pct}% round trip",
           f"Exit: stop {ATR_STOP}xATR, trail {ATR_TRAIL}xATR from highest close, time stop {MAX_HOLD}d. "
           "R = net of cost; 1R = 2xATR.", "", head]
    verdicts = []
    names = [f"{k}{m}" for k in SETUPS for m in ("", "+mkt")]
    ctrls = [f"{c}{m}" for c in sorted(set(CONTROL_FOR.values())) for m in ("", "+mkt")]
    S = {}
    for nm in ctrls + names:
        for per in ("IS", "OOS"):
            S[(nm, per)] = stats(tr[(tr.variant == nm) & (tr.period == per)])
    out.append("-- controls: same exits on every eligible day --")
    for nm in ctrls:
        for per in ("IS", "OOS"):
            out.append(_fmt(nm, per, S[(nm, per)]))
    out.append("-- setups --")
    for nm in names:
        key = nm.split("+")[0]
        cname = CONTROL_FOR[key] + ("+mkt" if nm.endswith("+mkt") else "")
        for per in ("IS", "OOS"):
            out.append(_fmt(nm, per, S[(nm, per)], S[(cname, per)] if S[(cname, per)] and S[(nm, per)] else None))
        verdicts.append((nm, verdict(S[(nm, "IS")], S[(nm, "OOS")], S[(cname, "OOS")])))
    out += ["", "-- avg R by signal year (n) --"]
    tr["year"] = tr.signal_date.dt.year
    for nm in names:
        parts = [f"{y}: {g.R.mean():+.2f} ({len(g)})" for y, g in tr[tr.variant == nm].groupby("year")]
        out.append(f"{nm:<22}" + "  ".join(parts))
    out += ["", "-- verdicts (rule fixed in advance) --"] + [f"{nm:<22}{v}" for nm, v in verdicts]
    out += ["", "Exit reasons (setups): " + ", ".join(
        f"{k} {v}" for k, v in tr[tr.variant.isin(names)].why.value_counts().items())]
    return tr, "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=10, help="yfinance supports 5 or 10")
    ap.add_argument("--oos-frac", type=float, default=0.35)
    ap.add_argument("--cost-pct", type=float, default=0.30)
    ap.add_argument("--tickers")
    ap.add_argument("--outdir", default="results")
    a = ap.parse_args(argv)
    import os
    os.makedirs(a.outdir, exist_ok=True)
    bench_df = B.load_history(BENCH, a.years)
    if bench_df is None:
        sys.exit("could not fetch " + BENCH)
    frames = {}
    for t in (a.tickers.split(",") if a.tickers else A.WATCHLIST):
        try:
            df = B.load_history(t, a.years)
            if df is not None and len(df) > MIN_BARS + 150:
                frames[t] = df
            else:
                print(f"[skip] {t}: not enough history", file=sys.stderr)
        except Exception as e:
            print(f"[error] {t}: {e}", file=sys.stderr)
        time.sleep(A.YF_SLEEP_SECONDS)
    if not frames:
        sys.exit("no data fetched")
    tr, text = run_research(frames, bench_df["Close"], a.oos_frac, a.cost_pct)
    tr.to_csv(os.path.join(a.outdir, "research_trades.csv"), index=False)
    open(os.path.join(a.outdir, "research_report.md"), "w").write("```\n" + text + "\n```\n")
    print(text)


if __name__ == "__main__":
    main()
