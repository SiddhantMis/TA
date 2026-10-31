#!/usr/bin/env python3
"""Pre-registered portfolio test: monthly cross-sectional momentum vs buy-and-hold.

    python portfolio.py --years 10 --n-hold 20 --cost-pct 0.30 --oos-frac 0.35

The question that decides whether any of this is a tool: does a rules-based stock
portfolio beat (a) just holding the Nifty 50 and (b) holding the SAME stocks equal-weight?
(b) isolates what the strategy adds from survivorship in today's constituent list.

Rules fixed BEFORE looking at results (no tuning loop):
  universe   (1) the 48-name watchlist, (2) current Nifty 200 constituents (fetched from NSE)
             (3) liquid500: today's Nifty 500 list, but at each rebalance only the top 200 by trailing
             126-day average traded value are eligible (point-in-time; added after the static Nifty 200
             run showed its universe flattered the results; the adoption rule below is UNCHANGED)
  rebalance  first trading day of each month, executed at that day's OPEN, signals use data
             through the previous close
  select     eligible = close above its 200-day average; rank by momentum; hold the top
             N_HOLD (20) equal-weight; fewer eligible names => the rest sits in cash at 0%
  variants   mom12_1 (252-day return skipping the last 21 days), mom6 (126-day return),
             each with and without a market filter (all cash when Nifty 50 < its 200-day avg)
  costs      cost_pct round trip on traded value (half per side) on each rebalance
  benchmarks Nifty BeES ETF (open-to-open, dividends via adjusted prices) and monthly
             rebalanced equal-weight of every eligible name in the universe (no costs charged)
  split      first (1 - oos_frac) of months = in-sample, rest = out-of-sample
  candidate  only if, in BOTH IS and OOS, CAGR beats both benchmarks; OOS max drawdown is
             no more than 5 points worse than Nifty 50; and the full-period excess return vs
             the equal-weight universe has a 95% interval (6-month blocks) above 0.
Four variants x two universes are tried: treat a lone pass with suspicion.

Biases that flatter the strategy: the universe is TODAY's list (stocks that later entered the
index are picked up early), monthly bars hide intra-month drawdowns, cash earns 0%, tax is
only roughly modelled and in the strategy's favour. A FAIL here is informative; a PASS is
only a reason to test further.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

import analyzer as A
import backtest as B

N_HOLD = 20
VARIANTS = ("mom12_1", "mom12_1+mkt", "mom6", "mom6+mkt")
INDEX_URL_TEMPLATES = (
    "https://nsearchives.nseindia.com/content/indices/ind_{name}list.csv",
    "https://archives.nseindia.com/content/indices/ind_{name}list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_{name}list.csv",
)
STCG, LTCG = 0.20, 0.125     # rough: strategy gains taxed short-term, index gains long-term


# ----------------------------------------------------------------- universe ---
def parse_constituents(text: str) -> list:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return []
    key = next((k for k in rows[0] if k and k.strip().lower() == "symbol"), None)
    if key is None:
        return []
    return [r[key].strip() + ".NS" for r in rows if (r.get(key) or "").strip()]


def constituent_urls(name: str) -> list:
    return [t.format(name=name) for t in INDEX_URL_TEMPLATES]


def fetch_constituents(name: str, min_symbols: int):
    for url in constituent_urls(name):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                "Accept": "text/csv,*/*"})
            txt = urllib.request.urlopen(req, timeout=30).read().decode("utf-8-sig")
            syms = parse_constituents(txt)
            if len(syms) >= min_symbols:
                print(f"[universe] {len(syms)} symbols from {url}", file=sys.stderr)
                return syms
            print(f"[universe] {url}: only {len(syms)} symbols", file=sys.stderr)
        except Exception as e:
            print(f"[universe] {url}: {e}", file=sys.stderr)
    return None


# ------------------------------------------------------------------- engine ---
def indicators(C: pd.DataFrame, V: pd.DataFrame = None, liquid_top: int = None) -> dict:
    ind = {"sma200": C.rolling(200, min_periods=200).mean(),
           "mom12_1": C.shift(21) / C.shift(252) - 1,
           "mom6": C / C.shift(126) - 1}
    ind["valid"] = C.notna() & ind["sma200"].notna() & ind["mom12_1"].notna() & ind["mom6"].notna()
    if V is not None and liquid_top:
        # Point-in-time universe: only the top `liquid_top` names by trailing 126-day average
        # traded value, ranked using data through each row only. A stock becomes eligible when it
        # was actually liquid, not because it is large today.
        tv = (C * V).rolling(126, min_periods=100).mean()
        ind["liquid"] = tv.rank(axis=1, ascending=False) <= liquid_top
        ind["valid"] = ind["valid"] & ind["liquid"]
    return ind


def select(C, ind, s, variant, mkt_ok, n_hold=N_HOLD):
    """Names to hold, decided from data through row s only."""
    if variant.endswith("+mkt") and not mkt_ok:
        return []
    key = "mom12_1" if variant.startswith("mom12_1") else "mom6"
    ok = ind["valid"].iloc[s] & (C.iloc[s] > ind["sma200"].iloc[s])
    return ind[key].iloc[s][ok].nlargest(n_hold).index.tolist()


def first_days_of_month(idx):
    pos = pd.Series(np.arange(len(idx)), index=idx)
    return pos.groupby([idx.year, idx.month]).first().tolist()


def simulate(O, C, ind, mkt_close, mkt_sma, bench_O, variants=VARIANTS, n_hold=N_HOLD, cost_pct=0.30):
    ex = [p for p in first_days_of_month(C.index) if p >= 253]
    rows, info, prev = [], [], {v: pd.Series(dtype=float) for v in variants}
    for a, b in zip(ex[:-1], ex[1:]):
        s = a - 1
        r = (O.iloc[b] / O.iloc[a] - 1).where(O.iloc[a].notna() & O.iloc[b].notna())
        row = {"date": C.index[a],
               "nifty50": float(np.nan_to_num(bench_O.iloc[b] / bench_O.iloc[a] - 1)),
               "ew_universe": float(np.nan_to_num(r[ind["valid"].iloc[s]].mean()))}
        mkt_ok = bool(mkt_close.iloc[s] > mkt_sma.iloc[s])
        for v in variants:
            names = select(C, ind, s, v, mkt_ok, n_hold)
            w = pd.Series(1.0 / n_hold, index=names, dtype=float)
            allx = w.index.union(prev[v].index)
            turn = float((w.reindex(allx).fillna(0) - prev[v].reindex(allx).fillna(0)).abs().sum())
            rr = r.reindex(names).fillna(0.0)
            pr = float((w * rr).sum())
            row[v] = pr - turn * cost_pct / 200.0
            prev[v] = (w * (1 + rr) / (1 + pr)) if len(names) else pd.Series(dtype=float)
            info.append({"date": C.index[a], "variant": v, "held": len(names), "turnover": turn})
        rows.append(row)
    return pd.DataFrame(rows).set_index("date"), pd.DataFrame(info)


# ------------------------------------------------------------------ metrics ---
def metrics(r: pd.Series):
    if r is None or len(r) < 6:
        return None
    eq = np.concatenate([[1.0], (1 + r).cumprod().to_numpy()])
    yrs = len(r) / 12
    cagr = eq[-1] ** (1 / yrs) - 1
    vol = r.std(ddof=1) * np.sqrt(12)
    gain = eq[-1] - 1
    return {"cagr": float(cagr), "vol": float(vol), "sharpe": float(r.mean() * 12 / vol) if vol > 0 else np.nan,
            "maxdd": float((eq / np.maximum.accumulate(eq) - 1).min()), "months": len(r), "gain": float(gain)}


def after_tax_cagr(m, rate):
    if m is None:
        return np.nan
    at = 1 + m["gain"] - rate * max(m["gain"], 0)
    return at ** (12 / m["months"]) - 1 if at > 0 else -1.0


def block_boot_mean(x, block=6, reps=2000, seed=11):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2 * block:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(reps, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(reps, -1)[:, :n]
    m = x[idx].mean(1) * 12
    return (float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)))


def verdict(v, M, ci):
    why = []
    for per in ("IS", "OOS"):
        m = M.get((v, per))
        if m is None:
            why.append(f"{per} too short")
            continue
        for b in ("nifty50", "ew_universe"):
            if M.get((b, per)) is not None and m["cagr"] <= M[(b, per)]["cagr"]:
                why.append(f"{per} CAGR <= {b}")
    n50 = M.get(("nifty50", "OOS"))
    mo = M.get((v, "OOS"))
    if mo and n50 and mo["maxdd"] < n50["maxdd"] - 0.05:
        why.append("OOS drawdown > 5 pts worse than Nifty 50")
    if not (np.isfinite(ci[0]) and ci[0] > 0):
        why.append("full-period excess vs equal-weight universe interval includes 0")
    return "CANDIDATE" if not why else "FAIL: " + "; ".join(why)


def _row(label, m, at=None):
    if m is None:
        return f"{label:<22}{'n/a':>8}"
    s = f"{label:<22}{m['cagr'] * 100:>7.1f}%{m['vol'] * 100:>7.1f}%{m['sharpe']:>8.2f}{m['maxdd'] * 100:>8.1f}%"
    return s + (f"{at * 100:>9.1f}%" if at is not None and np.isfinite(at) else "")


def run_portfolio(frames, mkt_close, bench_open, label, oos_frac=0.35, cost_pct=0.30, n_hold=N_HOLD, liquid_top=None):
    idx = mkt_close.index
    O = pd.concat({t: f.Open for t, f in frames.items()}, axis=1).reindex(idx)
    C = pd.concat({t: f.Close for t, f in frames.items()}, axis=1).reindex(idx)
    V = pd.concat({t: f.Volume for t, f in frames.items()}, axis=1).reindex(idx) if liquid_top else None
    ind = indicators(C, V, liquid_top)
    rets, info = simulate(O, C, ind, mkt_close, mkt_close.rolling(200).mean(),
                          bench_open.reindex(idx), VARIANTS, n_hold, cost_pct)
    if rets.empty:
        return rets, f"[{label}] not enough history."
    d0, d1 = rets.index[0], rets.index[-1]
    split = d0 + (d1 - d0) * (1 - oos_frac)
    cols = list(VARIANTS) + ["nifty50", "ew_universe"]
    masks = {"FULL": rets.index == rets.index, "IS": rets.index <= split, "OOS": rets.index > split}
    M = {(c, p): metrics(rets.loc[m, c]) for c in cols for p, m in masks.items()}
    ci = {v: block_boot_mean((rets[v] - rets["ew_universe"]).to_numpy()) for v in VARIANTS}
    ci_oos = {v: block_boot_mean((rets[v] - rets["ew_universe"]).to_numpy()[masks["OOS"]], block=4) for v in VARIANTS}

    out = [f"=== {label}: {len(frames)} stocks, months {d0.date()} to {d1.date()} ({len(rets)}), "
           f"IS/OOS split {split.date()}, hold {n_hold}, cost {cost_pct}% round trip ===",
           "CAGR / vol / Sharpe(rf=0) / max drawdown (month-end) ; last column = rough after-tax CAGR (FULL only)"]
    elig = ind["valid"].sum(axis=1).shift(1).reindex(rets.index).mean()
    out.append(f"eligible names per rebalance (avg): {elig:.0f}"
               + (f" -- point-in-time top {liquid_top} by trailing 126-day traded value" if liquid_top else ""))
    for per in ("FULL", "IS", "OOS"):
        out += ["", f"-- {per} ({int(masks[per].sum())} months) --",
                f"{'':<22}{'CAGR':>8}{'vol':>8}{'Sharpe':>8}{'maxDD':>9}" + ("   after-tax" if per == "FULL" else "")]
        for c in cols:
            rate = LTCG if c == "nifty50" else STCG
            out.append(_row(c, M[(c, per)], after_tax_cagr(M[(c, per)], rate) if per == "FULL" and c != "ew_universe" else None))
    iv = info.groupby("variant").agg(held=("held", "mean"), turnover=("turnover", "mean"))
    out += ["", "-- avg names held / avg one-way turnover per rebalance (sum of |weight change|) --"]
    out += [f"{v:<22}{iv.loc[v, 'held']:>6.1f}{iv.loc[v, 'turnover']:>8.2f}" for v in VARIANTS]
    out += ["", "-- excess return vs equal-weight universe, annualised, 95% interval (6-mo blocks) --"]
    for v in VARIANTS:
        ex = (rets[v] - rets["ew_universe"]).mean() * 12
        out.append(f"{v:<22}full {ex * 100:+6.1f}% [{ci[v][0] * 100:+.1f}, {ci[v][1] * 100:+.1f}]   "
                   f"OOS-only interval [{ci_oos[v][0] * 100:+.1f}, {ci_oos[v][1] * 100:+.1f}]")
    out += ["", "-- calendar-year returns --", f"{'year':<6}" + "".join(f"{c:>14}" for c in cols)]
    yr = (1 + rets[cols]).groupby(rets.index.year).prod() - 1
    for y, row in yr.iterrows():
        out.append(f"{y:<6}" + "".join(f"{row[c] * 100:>13.1f}%" for c in cols))
    out += ["", "-- verdicts (rule fixed in advance) --"] + [f"{v:<14}{verdict(v, M, ci[v])}" for v in VARIANTS]
    return rets, "\n".join(out)


# --------------------------------------------------------------------- main ---
def _load(tickers, years, store, tag):
    for t in tickers:
        if t in store:
            continue
        try:
            df = B.load_history(t, years)
            if df is not None and len(df) > 400:
                store[t] = df
            else:
                print(f"[skip] {t}: not enough history", file=sys.stderr)
        except Exception as e:
            print(f"[error] {t}: {e}", file=sys.stderr)
        time.sleep(A.YF_SLEEP_SECONDS)
    print(f"[data] {tag}: {sum(1 for t in tickers if t in store)}/{len(tickers)} loaded", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--oos-frac", type=float, default=0.35)
    ap.add_argument("--cost-pct", type=float, default=0.30)
    ap.add_argument("--n-hold", type=int, default=N_HOLD)
    ap.add_argument("--universes", default="watchlist,nifty200",
                    help="comma list of: watchlist, nifty200 (static list), liquid500 (Nifty 500 list, point-in-time top 200 by traded value)")
    ap.add_argument("--outdir", default="results")
    a = ap.parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)

    nifty = B.load_history("^NSEI", a.years)
    if nifty is None:
        sys.exit("could not fetch ^NSEI")
    etf = B.load_history("NIFTYBEES.NS", a.years)
    note = ""
    if etf is None or len(etf) < 1000:
        etf, note = nifty, "NOTE: NIFTYBEES.NS unavailable; Nifty 50 benchmark is the PRICE index (no dividends, ~1%+/yr low)."
    mkt_close, bench_open = nifty["Close"], etf["Open"]

    sel = [u.strip() for u in a.universes.split(",") if u.strip()]
    store, texts = {}, [note] if note else []
    for u in sel:
        liquid_top = None
        if u == "watchlist":
            label, tick = "watchlist (48)", list(A.WATCHLIST)
        elif u in ("nifty200", "liquid500"):
            name, need = ("nifty200", 150) if u == "nifty200" else ("nifty500", 400)
            syms = fetch_constituents(name, need)
            if not syms:
                texts.append(f"NOTE: {name} list could not be fetched from NSE; '{u}' skipped.")
                continue
            open(os.path.join(a.outdir, f"{name}_symbols.txt"), "w").write("\n".join(syms))
            label, tick = ("Nifty 200 (today's list, static)", syms) if u == "nifty200" else \
                ("Nifty 500 list, point-in-time top 200 by traded value", syms)
            liquid_top = 200 if u == "liquid500" else None
        else:
            sys.exit(f"unknown universe: {u}")
        _load(tick, a.years, store, u)
        frames = {t: store[t] for t in tick if t in store}
        if len(frames) < 0.9 * len(tick):
            texts.append(f"WARNING [{u}]: only {len(frames)} of {len(tick)} symbols had usable data.")
        rets, text = run_portfolio(frames, mkt_close, bench_open, label, a.oos_frac, a.cost_pct, a.n_hold, liquid_top)
        rets.to_csv(os.path.join(a.outdir, f"portfolio_monthly_{u}.csv"))
        texts.append(text)
    text = "\n\n".join(texts)
    fname = "portfolio_report.md" if a.universes == "watchlist,nifty200" else f"portfolio_report_{'+'.join(sel)}.md"
    open(os.path.join(a.outdir, fname), "w").write("```\n" + text + "\n```\n")
    print(text)


if __name__ == "__main__":
    main()
