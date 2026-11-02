#!/usr/bin/env python3
"""The exact live portfolio rules (PR #3), tested day by day against the old baseline.

    python portfolio_rules.py --years 10 --oos-frac 0.35 --cost-pct 0.30

Questions, answered with the same data, costs and a DAILY engine (stops need daily prices):
  1. Do the live rules (28th-of-month trigger, keep-while-top-30 buffer, NIFTYBEES 200-DMA filter) match the
     old monthly baseline from portfolio.py?  2. Does the top-30 buffer help?  3. Does a fixed-% trailing stop
  help?  4. What does the market filter protect against, and what does it cost?  Is half exposure in a weak market better?

Pre-registered (nothing is tuned after seeing results):
  universe  Nifty 500 list; point-in-time top-200 by 126-day traded value; close above own 200-day average
  rank      12-1 return (252 sessions back to 21 back), highest first;  20 slots, equal weight of current equity
  filter    BULL = NIFTYBEES adjusted close above its own 200-day average on the signal day (as in PR #3)
  target    PR #3's build_target_holdings: incumbents stay if still eligible and rank <= 30, then fill from ranks <= 20
  execute   signal after the close, trade at the NEXT session's open, 0.30% round trip on traded value, cash earns 0%
  stops     trailing stop from the highest close since entry; checked on closes, sold at the next open, slot stays
            in cash until the next rebalance
Variants:
  V1_baseline      month-end signal, no buffer, filter on  (what portfolio.py tested)
  V3_live_nobuf    28th-of-month signal, no buffer, filter on  (isolates the timing change)
  V2_live          28th-of-month signal, buffer 30, filter on  (the live rules)
  V4a_stop20       V2 + 20% trailing stop         V4b_stop30   V2 + 30% trailing stop
  V5_nofilter      V2 without the market filter    V6_half      V2 but half exposure (not cash) when the filter says BEAR
Decision rules:
  stop helps    if max drawdown improves by >= 5 points (full AND out-of-sample) and CAGR falls by <= 2 points (IS AND OOS)
  buffer helps  if turnover falls >= 20% and CAGR does not fall by more than 1 point
  live rules ~ baseline if CAGR is within 2 points (IS and OOS) and max drawdown no more than 3 points worse
Biases that flatter results: today's constituents (survivorship), flat costs, no taxes, cash at 0% (understates cash),
trades on different names can overlap. First split: first (1 - oos_frac) of the calendar is in-sample.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

import backtest as B
import leaders as LD
import pattern_lab as PL

SIZE, RETAIN, LIQUID_TOP = 20, 30, 200
START = 253


# ------------------------------------------------------------------- data ---
def prepare(frames: dict, bench_df: pd.DataFrame, liquid_top: int = LIQUID_TOP) -> dict:
    idx = bench_df.index
    cols = list(frames)
    O = pd.concat({t: frames[t].Open for t in cols}, axis=1).reindex(idx)
    C = pd.concat({t: frames[t].Close for t in cols}, axis=1).reindex(idx)
    V = pd.concat({t: frames[t].Volume for t in cols}, axis=1).reindex(idx)
    sma200 = C.rolling(200, min_periods=200).mean()
    tv = (C * V).rolling(126, min_periods=100).mean()
    liquid = tv.rank(axis=1, ascending=False) <= liquid_top
    mom = C.shift(21) / C.shift(252) - 1
    valid = C.notna() & sma200.notna() & mom.notna()
    elig = valid & liquid & (C > sma200)
    rank = mom.where(elig).rank(axis=1, ascending=False, method="first")
    bc = bench_df["Close"]
    bsma = bc.rolling(200, min_periods=200).mean()
    return {"idx": idx, "cols": cols, "O": O.ffill(limit=5).to_numpy(float), "C": C.ffill(limit=5).to_numpy(float),
            "rank": rank.to_numpy(float), "univ": (valid & liquid).to_numpy(bool),
            "bull": (bc > bsma).to_numpy(bool), "bull_known": bsma.notna().to_numpy(bool),
            "bench_close": bc.to_numpy(float)}


def month_end_signals(idx) -> set:
    s = pd.Series(np.arange(len(idx)), index=idx)
    return set(s.groupby([idx.year, idx.month]).last().tolist())


def rule28_signals(idx) -> set:
    """PR #3's trigger: the first scan on or after the 28th of a month (a month with no trading day >= 28 gets none)."""
    s = pd.Series(np.arange(len(idx)), index=idx)
    late = s[idx.day >= 28]
    return set(late.groupby([late.index.year, late.index.month]).first().tolist())


# ------------------------------------------------------------------ rules ---
def select_target(rank_row, incumbents, buffer: bool, size=SIZE, retain=RETAIN) -> list:
    """PR #3's build_target_holdings: incumbents stay while eligible and ranked <= retain; fill only from ranks <= size."""
    target = []
    if buffer:
        target = [j for j in incumbents if np.isfinite(rank_row[j]) and rank_row[j] <= retain][:size]
    for j in np.argsort(np.where(np.isfinite(rank_row), rank_row, np.inf), kind="stable"):
        if not np.isfinite(rank_row[j]) or rank_row[j] > size:
            break
        if j not in target:
            target.append(int(j))
        if len(target) >= size:
            break
    return [int(j) for j in target]


def simulate(P, signals: set, buffer=True, regime="cash", trail=None, cost_pct=0.30, size=SIZE, retain=RETAIN, start=START):
    """Daily engine. regime: 'cash' (BEAR -> no stocks), 'half' (BEAR -> half exposure), 'off' (ignore the filter)."""
    idx, O, C = P["idx"], P["O"], P["C"]
    n, side = len(idx), cost_pct / 200.0
    cash, sh, hwm, pending = 1.0, {}, {}, set()
    eq = np.full(n, np.nan)
    turns, stops, cash_days = [], 0, 0
    for t in range(start, n):
        o, c = O[t], C[t]
        reb = (t - 1) in signals and (t - 1) >= start - 1
        if reb or pending:
            traded = 0.0
            for j in list(pending):                                   # stop-outs flagged at yesterday's close
                if j in sh:
                    v = sh.pop(j) * o[j]; cash += v; traded += v; hwm.pop(j, None)
            pending.clear()
            equity_before = cash + sum(q * o[j] for j, q in sh.items())
            if reb:
                s = t - 1
                bull = bool(P["bull"][s]) and bool(P["bull_known"][s])
                exposure = 1.0 if (regime == "off" or bull) else (0.5 if regime == "half" else 0.0)
                target = select_target(P["rank"][s], list(sh), buffer, size, retain) if exposure > 0 else []
                for j in list(sh):
                    if j not in target:
                        v = sh.pop(j) * o[j]; cash += v; traded += v; hwm.pop(j, None)
                eq_now = cash + sum(q * o[j] for j, q in sh.items())
                for j in target:
                    want, cur = exposure / size * eq_now, sh.get(j, 0.0) * o[j]
                    d = want - cur
                    if d > 1e-12:
                        cash -= d; sh[j] = sh.get(j, 0.0) + d / o[j]; traded += d; hwm.setdefault(j, o[j])
                    elif d < -1e-12:
                        cash += -d; sh[j] = sh[j] + d / o[j]; traded += -d
                turns.append(traded / equity_before if equity_before > 0 else 0.0)
            cash -= traded * side                                        # costs on everything traded at this open
        total = cash + sum(q * c[j] for j, q in sh.items())
        eq[t] = total
        if not sh:
            cash_days += 1
        if trail:
            for j in sh:
                hwm[j] = max(hwm.get(j, c[j]), c[j])
                if c[j] <= hwm[j] * (1 - trail):
                    pending.add(j); stops += 1
    return {"equity": eq, "turnover": turns, "stops": stops, "cash_days": cash_days}


# ---------------------------------------------------------------- metrics ---
def metrics(eq, start_pos, end_pos):
    seg = eq[start_pos:end_pos + 1]
    seg = seg[np.isfinite(seg)]
    if len(seg) < 120:
        return None
    r = seg[1:] / seg[:-1] - 1
    yrs = len(r) / 252.0
    vol = r.std(ddof=1) * np.sqrt(252)
    return {"cagr": float((seg[-1] / seg[0]) ** (1 / yrs) - 1), "vol": float(vol),
            "sharpe": float(r.mean() * 252 / vol) if vol > 0 else np.nan,
            "maxdd": float((seg / np.maximum.accumulate(seg) - 1).min())}


def compare_stop(base, stop):
    why = []
    for per in ("FULL", "OOS"):
        if stop[per] is None or base[per] is None or stop[per]["maxdd"] < base[per]["maxdd"] + 0.05:
            why.append(f"{per} max drawdown improves by < 5 points")
    for per in ("IS", "OOS"):
        if stop[per] is None or base[per] is None or stop[per]["cagr"] < base[per]["cagr"] - 0.02:
            why.append(f"{per} CAGR falls by more than 2 points")
    return "STOP HELPS" if not why else "NO: " + "; ".join(why)


def run_rules(frames: dict, bench_df: pd.DataFrame, oos_frac=0.35, cost_pct=0.30):
    P = prepare(frames, bench_df)
    idx = P["idx"]
    me, r28 = month_end_signals(idx), rule28_signals(idx)
    cfg = {"V1_baseline": dict(signals=me, buffer=False), "V3_live_nobuf": dict(signals=r28, buffer=False),
           "V2_live": dict(signals=r28, buffer=True), "V4a_stop20": dict(signals=r28, buffer=True, trail=0.20),
           "V4b_stop30": dict(signals=r28, buffer=True, trail=0.30),
           "V5_nofilter": dict(signals=r28, buffer=True, regime="off"), "V6_half": dict(signals=r28, buffer=True, regime="half")}
    runs = {k: simulate(P, cost_pct=cost_pct, **v) for k, v in cfg.items()}
    n = len(idx)
    split = START + int((n - 1 - START) * (1 - oos_frac))
    bc = P["bench_close"]
    bench_eq = np.full(n, np.nan); bench_eq[START:] = bc[START:] / bc[START]
    C = P["C"]; univ = P["univ"]
    dr = np.full(n, np.nan)
    for t in range(START + 1, n):
        m = univ[t - 1] & np.isfinite(C[t]) & np.isfinite(C[t - 1]) & (C[t - 1] > 0)
        if m.any():
            dr[t] = np.mean(C[t][m] / C[t - 1][m] - 1)
    ew_eq = np.full(n, np.nan); ew_eq[START] = 1.0
    for t in range(START + 1, n):
        ew_eq[t] = ew_eq[t - 1] * (1 + (dr[t] if np.isfinite(dr[t]) else 0.0))
    series = {**{k: v["equity"] for k, v in runs.items()}, "Nifty50_buyhold": bench_eq, "EW_universe_daily": ew_eq}
    spans = {"FULL": (START, n - 1), "IS": (START, split), "OOS": (split, n - 1)}
    M = {(k, p): metrics(e, a, b) for k, e in series.items() for p, (a, b) in spans.items()}
    d0, d1, ds = idx[START].date(), idx[-1].date(), idx[split].date()
    out = [f"Portfolio rules: {len(frames)} stocks, daily engine {d0} to {d1}, IS/OOS split {ds}, cost {cost_pct}% round trip, cash 0%",
           "CAGR / vol / Sharpe(rf=0) / max drawdown (daily)"]
    for per in ("FULL", "IS", "OOS"):
        out += ["", f"-- {per} --", f"{'':<18}{'CAGR':>8}{'vol':>8}{'Sharpe':>8}{'maxDD':>9}"]
        for k in series:
            m = M[(k, per)]
            out.append(f"{k:<18}" + ("n/a" if m is None else f"{m['cagr'] * 100:>7.1f}%{m['vol'] * 100:>7.1f}%{m['sharpe']:>8.2f}{m['maxdd'] * 100:>8.1f}%"))
    out += ["", "-- activity --", f"{'':<18}{'rebalances':>11}{'avg turnover':>14}{'stop-outs':>10}{'days in cash':>14}"]
    for k, v in runs.items():
        out.append(f"{k:<18}{len(v['turnover']):>11}{(np.mean(v['turnover']) if v['turnover'] else 0):>14.2f}{v['stops']:>10}{v['cash_days'] / max(1, n - START) * 100:>13.0f}%")
    bull = P["bull"] & P["bull_known"]
    bear_days = [t for t in range(START + 1, n) if P["bull_known"][t - 1] and not P["bull"][t - 1]]
    bull_days = [t for t in range(START + 1, n) if P["bull_known"][t - 1] and P["bull"][t - 1]]
    ann = lambda arr, days: float(np.prod([1 + arr[t] for t in days if np.isfinite(arr[t])]) ** (252 / max(1, len(days))) - 1)
    nb = np.full(n, np.nan); nb[1:] = bc[1:] / bc[:-1] - 1
    out += ["", f"-- what the market filter sees: {len(bear_days)} BEAR days ({len(bear_days) / max(1, len(bear_days) + len(bull_days)) * 100:.0f}% of the period), {len(bull_days)} BULL days --",
            f"annualised return on BEAR days:  Nifty50 {ann(nb, bear_days) * 100:+.1f}%   same-universe equal-weight {ann(dr, bear_days) * 100:+.1f}%",
            f"annualised return on BULL days:  Nifty50 {ann(nb, bull_days) * 100:+.1f}%   same-universe equal-weight {ann(dr, bull_days) * 100:+.1f}%"]
    out += ["", "-- comparisons (rules fixed in advance) --"]
    def line(a, b, label):
        ok = True; why = []
        for per in ("IS", "OOS"):
            x, y = M[(a, per)], M[(b, per)]
            if x is None or y is None or abs(x["cagr"] - y["cagr"]) > 0.02:
                ok = False; why.append(f"{per} CAGR differs by > 2 points")
        x, y = M[(a, "FULL")], M[(b, "FULL")]
        if x is None or y is None or x["maxdd"] < y["maxdd"] - 0.03:
            ok = False; why.append("max drawdown > 3 points worse")
        out.append(f"{label:<44}" + ("~ SAME as baseline" if ok else "DIFFERENT: " + "; ".join(why)))
    line("V2_live", "V1_baseline", "live rules vs old baseline")
    line("V3_live_nobuf", "V1_baseline", "28th trigger vs month-end (timing only)")
    t2 = np.mean(runs["V2_live"]["turnover"]) if runs["V2_live"]["turnover"] else 0
    t3 = np.mean(runs["V3_live_nobuf"]["turnover"]) if runs["V3_live_nobuf"]["turnover"] else 0
    d_cagr = (M[("V2_live", "FULL")]["cagr"] - M[("V3_live_nobuf", "FULL")]["cagr"]) if M[("V2_live", "FULL")] and M[("V3_live_nobuf", "FULL")] else float("nan")
    out.append(f"{'buffer 30 vs none':<44}turnover {t2:.2f} vs {t3:.2f} ({(1 - t2 / t3) * 100 if t3 else 0:+.0f}% lower); CAGR {d_cagr * 100:+.1f} pts -> "
               + ("BUFFER HELPS" if t3 and t2 <= 0.8 * t3 and d_cagr >= -0.01 else "NOT SHOWN TO HELP"))
    for k in ("V4a_stop20", "V4b_stop30"):
        out.append(f"{k + ' vs V2_live':<44}" + compare_stop({p: M[("V2_live", p)] for p in ("FULL", "IS", "OOS")}, {p: M[(k, p)] for p in ("FULL", "IS", "OOS")}))
    for k in ("V5_nofilter", "V6_half"):
        a, b = M[(k, "FULL")], M[("V2_live", "FULL")]
        if a and b:
            out.append(f"{k + ' vs V2_live':<44}CAGR {((a['cagr'] - b['cagr']) * 100):+.1f} pts, max drawdown {((a['maxdd'] - b['maxdd']) * 100):+.1f} pts (full period)")
    return series, "\n".join(out)


# ------------------------------------------------------------------- main ---
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
    bench = B.load_history("NIFTYBEES.NS", a.years)
    if bench is None:
        sys.exit("could not fetch NIFTYBEES.NS")
    frames = PL.load_frames(LD.load_universe(), a.years, a.cache, a.refresh)
    _, text = run_rules(frames, bench, a.oos_frac, a.cost_pct)
    open(os.path.join(a.outdir, "portfolio_rules_report.md"), "w").write("```\n" + text + "\n```\n")
    print(text)


if __name__ == "__main__":
    main()
