#!/usr/bin/env python3
"""Walk-forward backtest of the screener's flags, with one simulated trade per flag.

    python backtest.py                              # whole WATCHLIST, 5 years
    python backtest.py --years 5 --max-hold 15 --cost-pct 0.25
    python backtest.py --tickers RELIANCE.NS,TCS.NS

For every past session it hands analyzer.score_ticker only the bars that existed
that day (no lookahead), and for every flag it plays the trade plan forward:
a buy-stop at `entry` (given `--trigger-days` sessions to trigger), a hard stop,
a target, and a time stop after `--max-hold` sessions. Same-bar ambiguity (stop
and target both inside one candle) always resolves to the STOP. Gaps through the
stop exit at the open, not at the stop price.

Reported in R (1R = the distance from fill to stop), net of `--cost-pct`
round-trip costs. Read the tables for: does the R:R gate help, which patterns
earn their keep, and does weak market breadth predict failures.

Known biases (they flatter the result, so discount accordingly): the watchlist
is today's list of names you chose to follow (survivorship); daily bars cannot
show intraday order; costs are one flat percentage. Fewer than ~30 trades in a
row of a table is noise -- the tables say so.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

import analyzer as A

WINDOW = 520            # bars given to score_ticker per session (it needs > ~482)
WARMUP = WINDOW - 1     # first session with enough history


def load_history(ticker: str, years: int):
    import yfinance as yf  # imported here so tests/imports work without it
    data = yf.download(ticker, period=f"{years}y", interval="1d", auto_adjust=True, progress=False)
    if data.empty:
        return None
    data = A._drop_unsettled_today(data)
    if data.empty:
        return None
    data = A._flatten_columns(data, ticker)
    return data.rename(columns=str.title)


def simulate(O, H, L, C, i, entry, stop, target, trigger_days=3, max_hold=15, cost_pct=0.25):
    """Play one plan forward from signal bar i. Returns dict(outcome, exit_idx, R, bars).

    outcome: target / stop / time / open (data ran out) for filled trades;
    no_trigger / invalidated / gapped_past_target for orders never filled.
    R is NaN unless the trade filled and closed.
    """
    n = len(C)
    tgt = np.inf if target is None else target
    fill = fj = None
    last_trigger_bar = min(i + trigger_days, n - 1)
    for j in range(i + 1, last_trigger_bar + 1):
        if H[j] >= entry:
            fill, fj = max(entry, O[j]), j
            break
        if L[j] <= stop:                      # setup broke before it ever triggered
            return {"outcome": "invalidated", "exit_idx": j, "R": np.nan, "bars": 0}
    if fill is None:
        return {"outcome": "no_trigger", "exit_idx": last_trigger_bar, "R": np.nan, "bars": 0}
    if fill >= tgt:                           # opened already past the target
        return {"outcome": "gapped_past_target", "exit_idx": fj, "R": np.nan, "bars": 0}

    risk = fill - stop
    time_exit_bar = fj + max_hold
    exit_px = why = None
    exit_idx = fj
    for k in range(fj, min(time_exit_bar, n - 1) + 1):
        if k > fj and O[k] <= stop:
            exit_px, why = O[k], "stop"        # gapped through the stop: fill at the open
        elif k > fj and O[k] >= tgt:
            exit_px, why = O[k], "target"
        elif L[k] <= stop:                     # includes the ambiguous stop-and-target bar
            exit_px, why = stop, "stop"
        elif H[k] >= tgt:
            exit_px, why = tgt, "target"
        if exit_px is not None:
            exit_idx = k
            break
    if exit_px is None:
        if time_exit_bar <= n - 1:
            exit_px, why, exit_idx = C[time_exit_bar], "time", time_exit_bar
        else:
            return {"outcome": "open", "exit_idx": n - 1, "R": np.nan, "bars": n - 1 - fj}
    gross = (exit_px - fill) / risk
    cost = fill * cost_pct / 100.0 / risk
    return {"outcome": why, "exit_idx": exit_idx, "R": gross - cost, "bars": exit_idx - fj}


def _has_pattern(df, i):
    curr, prev, prev2 = df.iloc[i], df.iloc[i - 1], df.iloc[i - 2]
    return bool(A.classify_three_candle(prev2, prev, curr)
                or A.classify_two_candle(prev, curr) or A.classify_single(curr))


def breadth_series(frames: dict) -> pd.Series:
    """Share of the watchlist closing above its own 50-day average, per date."""
    cols = []
    for t, df in frames.items():
        sma = df["Close"].rolling(A.SMA_MED).mean()
        cols.append((df["Close"] > sma).where(sma.notna()).astype(float).rename(t))
    return pd.concat(cols, axis=1).mean(axis=1)


def run_backtest(frames: dict, max_hold=15, trigger_days=3, cost_pct=0.25, progress=False) -> pd.DataFrame:
    breadth = breadth_series(frames)
    rows = []
    for t, df in frames.items():
        O, H, L, C = (df[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
        next_ok = WARMUP
        for i in range(WARMUP, len(df) - 1):
            if i < next_ok or not _has_pattern(df, i):
                continue
            r = A.score_ticker(df.iloc[i - WINDOW + 1: i + 1], t)
            if r is None or not r.flag:
                continue
            sim = simulate(O, H, L, C, i, r.entry, r.stop, r.target, trigger_days, max_hold, cost_pct)
            rows.append({
                "ticker": t, "date": df.index[i].date(), "pattern": r.pattern, "trend": r.trend,
                "confidence": r.confidence, "plan_rr": r.rr, "risk_pct": r.risk_pct,
                "trade_ok": bool(r.trade_ok), "breadth": float(breadth.get(df.index[i], np.nan)),
                **sim,
            })
            next_ok = sim["exit_idx"] + 1       # one live idea per ticker at a time
        if progress:
            print(f"  {t}: {sum(1 for x in rows if x['ticker'] == t)} flags", file=sys.stderr)
    return pd.DataFrame(rows)


def _row(label, d):
    res = d.dropna(subset=["R"])
    if res.empty:
        return f"{label:<30}{len(d):>8}{0:>8}{'-':>8}{'-':>9}{'-':>9}"
    note = "   <30 trades: noise" if len(res) < 30 else ""
    return (f"{label:<30}{len(d):>8}{len(res):>8}{(res.R > 0).mean() * 100:>7.0f}%"
            f"{res.R.mean():>9.2f}{res.R.sum():>9.1f}{note}")


def report(t: pd.DataFrame, args) -> str:
    head = f"{'group':<30}{'signals':>8}{'trades':>8}{'win%':>8}{'avg R':>9}{'sum R':>9}"
    out = [f"Backtest: {t.ticker.nunique()} tickers, {args.years}y, max hold {args.max_hold}d, "
           f"trigger window {args.trigger_days}d, costs {args.cost_pct}% round trip",
           "R = net of costs; 1R = fill-to-stop distance. Stop wins any same-bar tie.", ""]
    if t.empty:
        return "\n".join(out + ["No flags in the period."])

    out += ["1) Does the R:R gate help?", head,
            _row("old flag (pattern only)", t),
            _row("passes R:R gate  (new flag)", t[t.trade_ok]),
            _row("fails R:R gate  (watch only)", t[~t.trade_ok]), ""]

    out += ["2) By pattern (all old flags)", head]
    for p, d in t.groupby("pattern"):
        out.append(_row(str(p), d))
    out.append("")

    out += ["3) By watchlist breadth at signal (old flags)", head]
    for lab, lo, hi in (("breadth < 25%", 0, .25), ("breadth 25-50%", .25, .5), ("breadth >= 50%", .5, 1.01)):
        out.append(_row(lab, t[(t.breadth >= lo) & (t.breadth < hi)]))
    out.append("")

    out += ["4) By planned R:R (old flags with a target)", head]
    rr = t.dropna(subset=["plan_rr"])
    for lab, lo, hi in (("R:R < 1", 0, 1), ("1 - 1.5", 1, 1.5), ("1.5 - 2", 1.5, 2),
                        ("2 - 3", 2, 3), (">= 3", 3, 1e9)):
        out.append(_row(f"planned {lab}", rr[(rr.plan_rr >= lo) & (rr.plan_rr < hi)]))
    out.append("")

    oc = t.outcome.value_counts().to_dict()
    out.append("Outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(oc.items())))
    out.append("Bias: today's watchlist only (survivorship), daily bars only. Treat positives as an upper bound.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--tickers", help="comma-separated; default = analyzer.WATCHLIST")
    ap.add_argument("--max-hold", type=int, default=15, help="time stop, sessions after fill")
    ap.add_argument("--trigger-days", type=int, default=3, help="sessions the buy-stop stays live")
    ap.add_argument("--cost-pct", type=float, default=0.25, help="round-trip costs as %% of price")
    ap.add_argument("--out", default="backtest_trades.csv")
    ap.add_argument("--report", default="backtest_report.md")
    a = ap.parse_args(argv)

    tickers = a.tickers.split(",") if a.tickers else A.WATCHLIST
    frames = {}
    for t in tickers:
        try:
            df = load_history(t, a.years)
            if df is not None and len(df) > WINDOW + 20:
                frames[t] = df
            else:
                print(f"[skip] {t}: not enough history", file=sys.stderr)
        except Exception as e:
            print(f"[error] {t}: {e}", file=sys.stderr)
        time.sleep(A.YF_SLEEP_SECONDS)
    if not frames:
        sys.exit("no data fetched")

    trades = run_backtest(frames, a.max_hold, a.trigger_days, a.cost_pct, progress=True)
    trades.to_csv(a.out, index=False)
    text = report(trades, a)
    open(a.report, "w").write("```\n" + text + "\n```\n")
    print(text)


if __name__ == "__main__":
    main()
