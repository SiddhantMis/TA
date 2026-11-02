#!/usr/bin/env python3
"""The exact live portfolio rules (PR #3), tested day by day against the old baseline.

Benchmark inputs are corporate-action repaired and sanity-gated before metrics are calculated.

    python portfolio_rules.py --years 10 --oos-frac 0.35 --cost-pct 0.30

Questions, answered with the same data, costs and a DAILY engine (stops need daily prices):
  1. Do the live rules (28th-of-month trigger, keep-while-top-30 buffer, NIFTYBEES 200-DMA filter) match the
     old monthly baseline from portfolio.py?  2. Does the top-30 buffer help?  3. Does a fixed-% trailing stop
  help?  4. What does the market filter protect against, and what does it cost?  Is half exposure in a weak market better?

Pre-registered (nothing is tuned after seeing results):
  universe  Nifty 500 list; point-in-time top-200 by 126-day traded value; close above own 200-day average
  rank      12-1 return (252 sessions back to 21 back), highest first;  20 slots, equal weight of current equity
  filter    BULL = split/dividend-repaired NIFTYBEES adjusted close above its 200-day average (as in PR #3)
  diagnostic compare: ^NSEI 200-DMA regime as a separate variant; it does not replace the live ETF rule
  target    PR #3's build_target_holdings: incumbents stay if still eligible and rank <= 30, then fill from ranks <= 20
  execute   signal after the close, trade at the NEXT session's open, 0.30% round trip on traded value, cash earns 0%
  stops     trailing stop from the highest close since entry; checked on closes, sold at the next open, slot stays
            in cash until the next rebalance
Variants:
  V1_baseline      month-end signal, no buffer, repaired ETF filter
  V3_live_nobuf    repaired ETF filter, no buffer, corrected 28th trigger (isolates timing)
  V2_live          corrected 28th trigger, buffer 30, repaired ETF filter (the live rules)
  V4a_stop20       V2 + 20% trailing stop         V4b_stop30   V2 + 30% trailing stop
  V5_nofilter      V2 without the market filter    V6_half      V2 but half exposure when ETF filter says BEAR
  V7_nifty50       same live rules, but ^NSEI 200-DMA regime (diagnostic alternative only)
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
def prepare(frames: dict, bench_df: pd.DataFrame, liquid_top: int = LIQUID_TOP,
            index_df: pd.DataFrame | None = None) -> dict:
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
    bc = pd.to_numeric(bench_df["Close"], errors="coerce").reindex(idx)
    bsma = bc.rolling(200, min_periods=200).mean()
    if index_df is not None:
        ic = pd.to_numeric(index_df["Close"], errors="coerce").reindex(idx)
    else:
        ic = bc.copy()
    isma = ic.rolling(200, min_periods=200).mean()
    return {"idx": idx, "cols": cols, "O": O.ffill(limit=5).to_numpy(float), "C": C.ffill(limit=5).to_numpy(float),
            "rank": rank.to_numpy(float), "univ": (valid & liquid).to_numpy(bool),
            "bull": (bc > bsma).fillna(False).to_numpy(bool), "bull_known": bsma.notna().to_numpy(bool),
            "bull_index": (ic > isma).fillna(False).to_numpy(bool), "bull_index_known": isma.notna().to_numpy(bool),
            "bench_close": bc.to_numpy(float), "index_close": ic.to_numpy(float),
            "index_is_distinct": index_df is not None}


def cross_check_benchmark(etf: pd.DataFrame, index: pd.DataFrame, min_corr: float = 0.95) -> float:
    """The ETF and the index it tracks must move together day to day; if not, one of the series is still wrong."""
    j = pd.concat([etf["Close"].pct_change(), index["Close"].pct_change()], axis=1, keys=["etf", "idx"]).dropna()
    corr = float(j.corr().iloc[0, 1]) if len(j) > 100 else float("nan")
    if not corr >= min_corr:
        raise RuntimeError(f"benchmark cross-check failed: daily-return correlation with ^NSEI is {corr:.3f} (< {min_corr}); "
                           "refusing to calculate strategy metrics")
    return corr


def validate_benchmark(df: pd.DataFrame, label="NIFTYBEES", max_abs_daily_return=0.25):
    """Fail closed on benchmark price jumps large enough to indicate an unhandled split/data error."""
    if df is None or df.empty or "Close" not in df:
        raise RuntimeError(f"{label} benchmark history is missing or empty")
    close = pd.to_numeric(df["Close"], errors="coerce")
    if close.isna().any() or (close <= 0).any():
        raise RuntimeError(f"{label} benchmark contains missing/non-positive closes")
    returns = close.pct_change()
    bad = returns[returns.abs() > max_abs_daily_return]
    if not bad.empty:
        samples = ", ".join(f"{d.date()} {v * 100:+.1f}%" for d, v in bad.head(8).items())
        raise RuntimeError(
            f"{label} benchmark quality gate failed: {len(bad)} daily returns exceed "
            f"{max_abs_daily_return * 100:.0f}% ({samples}). Refusing to calculate strategy metrics."
        )
    return {"bars": int(len(close)), "max_abs_daily_return_pct": float(returns.abs().max() * 100)}


def month_end_signals(idx) -> set:
    s = pd.Series(np.arange(len(idx)), index=idx)
    return set(s.groupby([idx.year, idx.month]).last().tolist())


def rule28_signals(idx) -> set:
    """First available exchange session on/after each month's calendar 28th.

    If the 28th is a weekend/holiday and the month has no session at or after it,
    the signal moves to the first session in the next month. This matches the live
    manager's first-scan catch-up. The final observed month is skipped when its
    28th has not yet arrived, avoiding a partial-month lookahead.
    """
    idx = pd.DatetimeIndex(idx)
    if len(idx) == 0:
        return set()
    signals = set()
    months = sorted(set(zip(idx.year, idx.month)))
    for year, month in months:
        trigger = pd.Timestamp(int(year), int(month), 28)
        if idx[-1] < trigger:
            continue
        pos = int(idx.searchsorted(trigger, side="left"))
        if pos < len(idx):
            signals.add(pos)
    return signals


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


def simulate(P, signals: set, buffer=True, regime="cash", trail=None, cost_pct=0.30,
             size=SIZE, retain=RETAIN, start=START, regime_source="etf"):
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
                if regime_source == "index":
                    bull = bool(P["bull_index"][s]) and bool(P["bull_index_known"][s])
                elif regime_source == "etf":
                    bull = bool(P["bull"][s]) and bool(P["bull_known"][s])
                else:
                    raise ValueError(f"Unknown regime_source: {regime_source}")
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


def run_rules(frames: dict, bench_df: pd.DataFrame, oos_frac=0.35, cost_pct=0.30,
              index_df: pd.DataFrame | None = None):
    quality = validate_benchmark(bench_df, "Repaired NIFTYBEES")
    index_quality = (
        validate_benchmark(index_df, "NIFTY 50 price index")
        if index_df is not None else None
    )
    P = prepare(frames, bench_df, index_df=index_df)
    idx = P["idx"]
    me, r28 = month_end_signals(idx), rule28_signals(idx)
    cfg = {"V1_baseline": dict(signals=me, buffer=False),
           "V3_live_nobuf": dict(signals=r28, buffer=False),
           "V2_live": dict(signals=r28, buffer=True),
           "V4a_stop20": dict(signals=r28, buffer=True, trail=0.20),
           "V4b_stop30": dict(signals=r28, buffer=True, trail=0.30),
           "V5_nofilter": dict(signals=r28, buffer=True, regime="off"),
           "V6_half": dict(signals=r28, buffer=True, regime="half"),
           "V7_nifty50_filter": dict(signals=r28, buffer=True, regime_source="index")}
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
    series = {**{k: v["equity"] for k, v in runs.items()},
              "NIFTYBEES_adjusted_buyhold": bench_eq, "EW_universe_daily": ew_eq}
    if P["index_is_distinct"]:
        ic = P["index_close"]
        index_eq = np.full(n, np.nan); index_eq[START:] = ic[START:] / ic[START]
        series["NIFTY50_price_index"] = index_eq
    spans = {"FULL": (START, n - 1), "IS": (START, split), "OOS": (split, n - 1)}
    M = {(k, p): metrics(e, a, b) for k, e in series.items() for p, (a, b) in spans.items()}
    d0, d1, ds = idx[START].date(), idx[-1].date(), idx[split].date()
    out = [f"Portfolio rules: {len(frames)} stocks, daily engine {d0} to {d1}, IS/OOS split {ds}, cost {cost_pct}% round trip, cash 0%",
           f"Benchmark: NIFTYBEES auto-adjusted with yfinance repair=True; {quality['bars']} bars; max abs daily move {quality['max_abs_daily_return_pct']:.2f}%",
           *([f"Regime diagnostic: ^NSEI price index quality gate passed; {index_quality['bars']} bars; max abs daily move {index_quality['max_abs_daily_return_pct']:.2f}%"] if index_quality else []),
           "NIFTY50_price_index is a PRICE index (not a total-return index).",
           "CAGR / vol / Sharpe(rf=0) / max drawdown (daily)"]
    for per in ("FULL", "IS", "OOS"):
        out += ["", f"-- {per} --", f"{'':<28}{'CAGR':>8}{'vol':>8}{'Sharpe':>8}{'maxDD':>9}"]
        for k in series:
            m = M[(k, per)]
            out.append(f"{k:<28}" + ("n/a" if m is None else f"{m['cagr'] * 100:>7.1f}%{m['vol'] * 100:>7.1f}%{m['sharpe']:>8.2f}{m['maxdd'] * 100:>8.1f}%"))
    out += ["", "-- activity --", f"{'':<28}{'rebalances':>11}{'avg turnover':>14}{'stop-outs':>10}{'days in cash':>14}"]
    for k, v in runs.items():
        out.append(f"{k:<28}{len(v['turnover']):>11}{(np.mean(v['turnover']) if v['turnover'] else 0):>14.2f}{v['stops']:>10}{v['cash_days'] / max(1, n - START) * 100:>13.0f}%")
    bear_days = [t for t in range(START + 1, n) if P["bull_known"][t - 1] and not P["bull"][t - 1]]
    bull_days = [t for t in range(START + 1, n) if P["bull_known"][t - 1] and P["bull"][t - 1]]
    ann = lambda arr, days: float(np.prod([1 + arr[t] for t in days if np.isfinite(arr[t])]) ** (252 / max(1, sum(np.isfinite(arr[t]) for t in days))) - 1)
    etf_ret = np.full(n, np.nan); etf_ret[1:] = bc[1:] / bc[:-1] - 1
    index_close = P["index_close"]
    index_ret = np.full(n, np.nan); index_ret[1:] = index_close[1:] / index_close[:-1] - 1
    out += ["", f"-- what the repaired NIFTYBEES filter sees: {len(bear_days)} BEAR days ({len(bear_days) / max(1, len(bear_days) + len(bull_days)) * 100:.0f}% of known-regime days), {len(bull_days)} BULL days --",
            f"annualised adjusted ETF return on ETF-BEAR days: {ann(etf_ret, bear_days) * 100:+.1f}%; same-universe equal-weight: {ann(dr, bear_days) * 100:+.1f}%",
            f"annualised adjusted ETF return on ETF-BULL days: {ann(etf_ret, bull_days) * 100:+.1f}%; same-universe equal-weight: {ann(dr, bull_days) * 100:+.1f}%"]
    if P["index_is_distinct"]:
        ibear = [t for t in range(START + 1, n) if P["bull_index_known"][t - 1] and not P["bull_index"][t - 1]]
        ibull = [t for t in range(START + 1, n) if P["bull_index_known"][t - 1] and P["bull_index"][t - 1]]
        common = [t for t in range(START + 1, n) if P["bull_known"][t - 1] and P["bull_index_known"][t - 1]]
        disagree = sum(P["bull"][t - 1] != P["bull_index"][t - 1] for t in common)
        out += [f"^NSEI filter: {len(ibear)} BEAR / {len(ibull)} BULL days; disagrees with repaired ETF regime on {disagree}/{len(common)} common days",
                f"annualised ^NSEI price-index return on ^NSEI-BEAR days: {ann(index_ret, ibear) * 100:+.1f}%; same-universe equal-weight: {ann(dr, ibear) * 100:+.1f}%"]
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
        out.append(f"{label:<52}" + ("~ SAME as baseline" if ok else "DIFFERENT: " + "; ".join(why)))
    line("V2_live", "V1_baseline", "live rules vs old baseline")
    line("V3_live_nobuf", "V1_baseline", "28th trigger vs month-end (timing only)")
    t2 = np.mean(runs["V2_live"]["turnover"]) if runs["V2_live"]["turnover"] else 0
    t3 = np.mean(runs["V3_live_nobuf"]["turnover"]) if runs["V3_live_nobuf"]["turnover"] else 0
    d_cagr = (M[("V2_live", "FULL")]["cagr"] - M[("V3_live_nobuf", "FULL")]["cagr"]) if M[("V2_live", "FULL")] and M[("V3_live_nobuf", "FULL")] else float("nan")
    out.append(f"{'buffer 30 vs none':<52}turnover {t2:.2f} vs {t3:.2f} ({(1 - t2 / t3) * 100 if t3 else 0:+.0f}% lower); CAGR {d_cagr * 100:+.1f} pts -> "
               + ("BUFFER HELPS" if t3 and t2 <= 0.8 * t3 and d_cagr >= -0.01 else "NOT SHOWN TO HELP"))
    for k in ("V4a_stop20", "V4b_stop30"):
        out.append(f"{k + ' vs V2_live':<52}" + compare_stop({p: M[("V2_live", p)] for p in ("FULL", "IS", "OOS")}, {p: M[(k, p)] for p in ("FULL", "IS", "OOS")}))
    for k in ("V5_nofilter", "V6_half", "V7_nifty50_filter"):
        a, b = M[(k, "FULL")], M[("V2_live", "FULL")]
        if a and b:
            oos_a, oos_b = M[(k, "OOS")], M[("V2_live", "OOS")]
            out.append(f"{k + ' vs V2_live':<52}FULL CAGR {(a['cagr'] - b['cagr']) * 100:+.1f} pts; FULL maxDD {(a['maxdd'] - b['maxdd']) * 100:+.1f} pts; "
                       f"OOS CAGR {(oos_a['cagr'] - oos_b['cagr']) * 100:+.1f} pts; OOS maxDD {(oos_a['maxdd'] - oos_b['maxdd']) * 100:+.1f} pts")
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
    bench = B.load_history("NIFTYBEES.NS", a.years, repair=True)
    if bench is None:
        sys.exit("could not fetch NIFTYBEES.NS")
    validate_benchmark(bench, "Repaired NIFTYBEES")
    index = B.load_history("^NSEI", a.years)
    if index is None:
        sys.exit("could not fetch ^NSEI")
    frames = PL.load_frames(LD.load_universe(), a.years, a.cache, a.refresh)
    corr = cross_check_benchmark(bench, index)
    _, text = run_rules(frames, bench, a.oos_frac, a.cost_pct, index_df=index)
    fixes = bench.attrs.get("scale_repairs") or []
    text = (f"Benchmark data repairs: {[(f['from'], f['to'], 'x%g' % f['factor']) for f in fixes] or 'none'}; "
            f"daily-return correlation NIFTYBEES vs ^NSEI after repair {corr:.3f}\n") + text
    open(os.path.join(a.outdir, "portfolio_rules_report.md"), "w").write("```\n" + text + "\n```\n")
    print(text)


if __name__ == "__main__":
    main()
