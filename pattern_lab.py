#!/usr/bin/env python3
"""Pattern lab: does each chart pattern actually pay, in Indian stocks, after controlling for context?

    python pattern_lab.py --years 10 --liquid-top 200 --oos-frac 0.35

For every pattern event (geo_patterns.detect_all) it measures what happened next, then asks whether
that beats simply being a stock in the same situation.

Pre-registered before any result was seen (nothing here is tuned):
  universe  today's Nifty 500 list; an event counts only if the stock is in the point-in-time top
            `liquid-top` by trailing 126-day traded value on the breakout day (no look-ahead on size)
  outcome   market-adjusted return over the next 20 sessions, measured from the NEXT open
            (stock return minus the average return of all liquid stocks over the same dates),
            minus the average of all liquid stock-days in the SAME trend state (uptrend /
            downtrend / mixed by 50- and 200-day averages). That removes market moves AND the plain
            momentum/trend effect, so only what the pattern itself adds is left.
            5- and 10-day versions are shown for information only. Bearish patterns are scored
            with the sign flipped (a bearish pattern "works" if the stock under-performs).
  trade     enter next open; stop and measured-move target from the pattern; stop wins ties; gaps
            exit at the open; 40-session time stop; cost 0.30% round trip
  dedupe    one event per (stock, pattern, direction) per 20 sessions
  split     first (1 - oos_frac) of the calendar = in-sample, the rest = out-of-sample
  VALIDATED only if: >=150 events, >=50 OOS events, IS mean > 0, OOS mean > 0, the OOS 99% interval
            (months resampled) is above 0, and OOS average R > 0. 12 detectors are tested, so the
            99% level is used to keep the chance of one lucky pass near 10%.
A pattern that is not VALIDATED is context, not a signal.

Biases that flatter results: today's constituents (survivorship), daily bars, flat costs.
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys

import numpy as np
import pandas as pd

import geo_patterns as G
import portfolio as P

HORIZONS = (5, 10, 20)
COOLDOWN = 20
MAX_HOLD = 40


# ------------------------------------------------------------------ outcomes --
def sim_event(O, H, L, C, t, d, stop, target, max_hold=MAX_HOLD, cost_pct=0.30):
    """R multiple of trading one event; NaN when no trade or unresolved at the end of the data."""
    n = len(C)
    if t + 1 >= n:
        return np.nan
    entry = O[t + 1]
    risk = d * (entry - stop)
    if not np.isfinite(entry) or risk <= 0 or d * (target - entry) <= 0:
        return np.nan                                   # gapped past the stop or target: no trade
    last = t + 1 + max_hold
    px = None
    for k in range(t + 1, min(last, n - 1) + 1):
        if k > t + 1:
            if d * (O[k] - stop) <= 0 or d * (O[k] - target) >= 0:
                px = O[k]
                break
        stop_hit = L[k] <= stop if d == 1 else H[k] >= stop
        tgt_hit = H[k] >= target if d == 1 else L[k] <= target
        if stop_hit:
            px = stop
            break
        if tgt_hit:
            px = target
            break
    if px is None:
        if last > n - 1:
            return np.nan
        px = C[last]
    return (d * (px - entry) - entry * cost_pct / 100.0) / risk


def month_ci(vals, dates, level=99.0, reps=2000, seed=5):
    v = np.asarray(vals, float)
    ok = np.isfinite(v)
    v, m = v[ok], pd.Series(pd.to_datetime(np.asarray(dates)[ok])).dt.to_period("M").astype(str).to_numpy()
    if len(v) < 20 or len(set(m)) < 8:
        return (np.nan, np.nan)
    keys, inv = np.unique(m, return_inverse=True)
    s = np.bincount(inv, weights=v)
    c = np.bincount(inv).astype(float)
    idx = np.random.default_rng(seed).integers(0, len(keys), size=(reps, len(keys)))
    means = s[idx].sum(1) / c[idx].sum(1)
    q = (100 - level) / 2
    return (float(np.percentile(means, q)), float(np.percentile(means, 100 - q)))


# --------------------------------------------------------------------- panels --
def build_panels(frames: dict, liquid_top):
    idx = sorted(set().union(*[f.index for f in frames.values()]))
    idx = pd.DatetimeIndex(idx)
    cols = list(frames)
    O = pd.concat({t: frames[t].Open for t in cols}, axis=1).reindex(idx)
    C = pd.concat({t: frames[t].Close for t in cols}, axis=1).reindex(idx)
    V = pd.concat({t: frames[t].Volume for t in cols}, axis=1).reindex(idx)
    sma50, sma200 = C.rolling(50).mean(), C.rolling(200).mean()
    up = (C > sma200) & (sma50 > sma200)
    dn = (C < sma200) & (sma50 < sma200)
    state = pd.DataFrame(np.where(up, 1, np.where(dn, -1, 0)), index=idx, columns=cols)
    state = state.where(sma200.notna())
    if liquid_top:
        tv = (C * V).rolling(126, min_periods=100).mean()
        liquid = tv.rank(axis=1, ascending=False) <= liquid_top
    else:
        liquid = C.notna()
    ar, base = {}, {}
    for h in HORIZONS:
        fwd = C.shift(-h) / O.shift(-1) - 1
        mkt = fwd.where(liquid).mean(axis=1)
        arh = fwd.sub(mkt, axis=0)
        ar[h] = arh
        base[h] = {s: float(np.nanmean(arh.where(liquid & (state == s)).to_numpy())) for s in (-1, 0, 1)}
    return idx, cols, liquid, state, ar, base


# --------------------------------------------------------------------- events --
def collect_events(frames: dict, panels, cost_pct=0.30) -> pd.DataFrame:
    idx, cols, liquid, state, ar, base = panels
    liq, st = liquid.to_numpy(), state.to_numpy()
    arr = {h: ar[h].to_numpy() for h in HORIZONS}
    rows = []
    for j, t_name in enumerate(cols):
        f = frames[t_name]
        O, H, L, C = (f[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
        pos = idx.get_indexer(f.index)                       # master row of each of this stock's bars
        last_kept = {}
        for e in G.detect_all(O, H, L, C):
            r = pos[e["t"]]
            if r < 0 or not liq[r, j] or not np.isfinite(st[r, j]):
                continue
            k = (e["name"], e["dir"])
            if k in last_kept and e["t"] - last_kept[k] < COOLDOWN:
                continue
            last_kept[k] = e["t"]
            s = int(st[r, j])
            row = {"ticker": t_name, "date": f.index[e["t"]], "name": e["name"], "dir": e["dir"], "state": s,
                   "R": sim_event(O, H, L, C, e["t"], e["dir"], e["stop"], e["target"], MAX_HOLD, cost_pct)}
            for h in HORIZONS:
                v = arr[h][r, j]
                row[f"ex{h}"] = e["dir"] * (v - base[h][s]) if np.isfinite(v) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------- report --
def _stats(d):
    if d is None or d.empty:
        return None
    ci = month_ci(d.ex20, d.date)
    r = d.R.dropna()
    return {"n": len(d), "ex5": d.ex5.mean(), "ex10": d.ex10.mean(), "ex20": d.ex20.mean(),
            "win": float((d.ex20.dropna() > 0).mean()) if d.ex20.notna().any() else np.nan,
            "lo": ci[0], "hi": ci[1], "avgR": float(r.mean()) if len(r) else np.nan,
            "rwin": float((r > 0).mean()) if len(r) else np.nan, "nr": len(r)}


def verdict(is_s, oos_s, n_total):
    why = []
    if n_total < 150:
        why.append(f"only {n_total} events")
    if oos_s is None or oos_s["n"] < 50:
        why.append("fewer than 50 OOS events")
        return "FAIL: " + "; ".join(why)
    if is_s is None or not is_s["ex20"] > 0:
        why.append("IS mean <= 0")
    if not oos_s["ex20"] > 0:
        why.append("OOS mean <= 0")
    if not (np.isfinite(oos_s["lo"]) and oos_s["lo"] > 0):
        why.append("OOS 99% interval includes 0")
    if not (np.isfinite(oos_s["avgR"]) and oos_s["avgR"] > 0):
        why.append("OOS avg R <= 0")
    return "VALIDATED" if not why else "FAIL: " + "; ".join(why)


def _fmt(label, per, s, years):
    if s is None:
        return f"{label:<30}{per:<5}{0:>6}"
    ci = f"[{s['lo'] * 100:+.1f},{s['hi'] * 100:+.1f}]" if np.isfinite(s["lo"]) else "[n/a]"
    return (f"{label:<30}{per:<5}{s['n']:>6}{s['n'] / years:>6.1f}{s['ex5'] * 100:>+7.2f}{s['ex10'] * 100:>+7.2f}"
            f"{s['ex20'] * 100:>+7.2f}{s['win'] * 100:>6.0f}%{ci:>16}{s['avgR']:>+7.2f}{s['rwin'] * 100:>6.0f}%")


def run_lab(frames: dict, oos_frac=0.35, cost_pct=0.30, liquid_top=200):
    panels = build_panels(frames, liquid_top)
    ev = collect_events(frames, panels, cost_pct)
    base = panels[5]
    head_base = ("Baseline (market-adjusted mean 20d return, all liquid stock-days by trend state): "
                 f"uptrend {base[20][1] * 100:+.2f}%  mixed {base[20][0] * 100:+.2f}%  downtrend {base[20][-1] * 100:+.2f}%")
    if ev.empty:
        return ev, head_base + "\nNo pattern events."
    d0, d1 = ev.date.min(), ev.date.max()
    split = d0 + (d1 - d0) * (1 - oos_frac)
    ev["period"] = np.where(ev.date <= split, "IS", "OOS")
    years_is, years_oos = max((split - d0).days / 365.25, 0.5), max((d1 - split).days / 365.25, 0.5)
    out = [f"Pattern lab: {len(ev)} events in {ev.ticker.nunique()} stocks, {d0.date()} to {d1.date()}, "
           f"IS/OOS split {split.date()}, liquid top {liquid_top} (point-in-time), cost {cost_pct}%",
           head_base,
           "ex = direction-adjusted return beyond market AND same-trend-state baseline, in %. "
           "R = trade outcome with the pattern's own stop/target.", "",
           f"{'pattern':<30}{'per':<5}{'n':>6}{'/yr':>6}{'ex5':>7}{'ex10':>7}{'ex20':>7}{'win%':>7}"
           f"{'99% CI of ex20':>16}{'avgR':>7}{'Rwin':>7}"]
    verdicts = []
    for (name, d), g in ev.groupby(["name", "dir"]):
        label = f"{name} ({'bull' if d == 1 else 'bear'})"
        s_is, s_oos = _stats(g[g.period == "IS"]), _stats(g[g.period == "OOS"])
        out.append(_fmt(label, "IS", s_is, years_is))
        out.append(_fmt(label, "OOS", s_oos, years_oos))
        verdicts.append((label, verdict(s_is, s_oos, len(g)), len(g)))
    out += ["", "-- verdicts (rule fixed in advance; 12 detectors tested) --"]
    out += [f"{lab:<34}{v}" for lab, v, _ in verdicts]
    ev["year"] = ev.date.dt.year
    out += ["", "-- mean ex20 by year (n), %: only for patterns with >=150 events --"]
    for (name, d), g in ev.groupby(["name", "dir"]):
        if len(g) >= 150:
            parts = [f"{y}:{x.ex20.mean() * 100:+.1f}({len(x)})" for y, x in g.groupby("year")]
            out.append(f"{name + ('_bull' if d == 1 else '_bear'):<30}" + " ".join(parts))
    return ev, "\n".join(out)


# ----------------------------------------------------------------------- main --
def load_frames(tickers, years, cache, refresh):
    if cache and os.path.exists(cache) and not refresh:
        with open(cache, "rb") as fh:
            store = pickle.load(fh)
        print(f"[cache] {len(store)} frames from {cache}", file=sys.stderr)
    else:
        store = {}
    P._load(tickers, years, store, "lab")
    if cache:
        os.makedirs(os.path.dirname(cache) or ".", exist_ok=True)
        with open(cache, "wb") as fh:
            pickle.dump(store, fh)
    return {t: store[t] for t in tickers if t in store}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--oos-frac", type=float, default=0.35)
    ap.add_argument("--cost-pct", type=float, default=0.30)
    ap.add_argument("--liquid-top", type=int, default=200)
    ap.add_argument("--tickers")
    ap.add_argument("--cache", default="data_cache/frames_10y.pkl")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--outdir", default="results")
    a = ap.parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)
    tickers = a.tickers.split(",") if a.tickers else P.fetch_constituents("nifty500", 400)
    if not tickers:
        sys.exit("could not fetch the Nifty 500 list")
    frames = load_frames(tickers, a.years, a.cache, a.refresh)
    ev, text = run_lab(frames, a.oos_frac, a.cost_pct, a.liquid_top)
    ev.to_csv(os.path.join(a.outdir, "pattern_events.csv"), index=False)
    open(os.path.join(a.outdir, "pattern_lab_report.md"), "w").write("```\n" + text + "\n```\n")
    print(text)


if __name__ == "__main__":
    main()
