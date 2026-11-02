#!/usr/bin/env python3
"""The exact live portfolio rules (PR #3), tested day by day against the old baseline.

Stock OHLC uses pinned TejHQ adjusted NSE history. NIFTYBEES raw bhavcopy OHLC is split-adjusted and reconciled to NSE historical trades; a pinned NSE holiday calendar plus observed NIFTY 50 dates supplies the session calendar.

    python portfolio_rules.py --years 10 --oos-frac 0.35 --cost-pct 0.30

Questions, answered with the same data, costs and a DAILY engine (stops need daily prices):
  1. Do the live rules (28th-of-month trigger, keep-while-top-30 buffer, NIFTYBEES 200-DMA filter) match the
     old monthly baseline from portfolio.py?  2. Does the top-30 buffer help?  3. Does a fixed-% trailing stop
  help?  4. What does the market filter protect against, and what does it cost?  Is half exposure in a weak market better?

Pre-registered (nothing is tuned after seeing results):
  universe  historical Nifty 500 membership; top-200 by 126-day traded value among members on each signal date
  rank      12-1 return (252 sessions back to 21 back), highest first;  20 slots, equal weight of current equity
  filter    BULL = NIFTYBEES split-adjusted traded close above its 200-day average
  diagnostic compare: official NSE NIFTY 50 200-DMA regime as a separate variant; it does not replace the live ETF rule
  target    PR #3's build_target_holdings: incumbents stay if still eligible and rank <= 30, then fill from ranks <= 20
  execute   signal after the close, trade at the NEXT session's open, 0.30% round trip on traded value, cash earns 0%
  stops     trailing stop from the highest close since entry; checked on closes, sold at the next open, slot stays
            in cash until the next rebalance
Variants:
  V1_baseline      month-end signal, no buffer, NSE-sourced ETF filter
  V3_live_nobuf    NSE-sourced ETF filter, no buffer, corrected 28th trigger (isolates timing)
  V2_live          corrected 28th trigger, buffer 30, NSE-sourced ETF filter (the live rules)
  V4a_stop20       V2 + 20% trailing stop         V4b_stop30   V2 + 30% trailing stop
  V5_nofilter      V2 without the market filter    V6_half      V2 but half exposure when ETF filter says BEAR
  V7_nifty50       same live rules, but ^NSEI 200-DMA regime (diagnostic alternative only)
Decision rules:
  stop helps    if max drawdown improves by >= 5 points (full AND out-of-sample) and CAGR falls by <= 2 points (IS AND OOS)
  buffer helps  if turnover falls >= 20% and CAGR does not fall by more than 1 point
  live rules ~ baseline if CAGR is within 2 points (IS and OOS) and max drawdown no more than 3 points worse
Biases that remain: incomplete/misaligned source membership history, unavailable delisted price histories, flat costs,
no taxes, and cash at 0%. Membership is point-in-time filtered, but this is not a fully survivorship-free reconstruction.
First split: first (1 - oos_frac) of the calendar is in-sample.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from nse_benchmark import (
    apply_niftybees_split_adjustments, build_nse_session_calendar,
    load_niftybees_raw_history, load_nifty50_index_history,
    merge_niftybees_sources,
)
from tejhq_data import load_niftybees_raw_frame
import pattern_lab as PL
from nifty500_pit import (
    DEFAULT_MEMBERSHIP_FILE, EXPECTED_INDEX_SIZE, MEMBERSHIP_COVERAGE_THROUGH,
    build_membership_mask, expected_member_counts, load_membership_calendar,
    normalise_symbol, validate_membership_calendar,
)

SIZE, RETAIN, LIQUID_TOP = 20, 30, 200
START = 253


# ------------------------------------------------------------------- data ---
def prepare(frames: dict, bench_df: pd.DataFrame, liquid_top: int = LIQUID_TOP,
            index_df: pd.DataFrame | None = None,
            membership_df: pd.DataFrame | None = None,
            membership_path: str = DEFAULT_MEMBERSHIP_FILE) -> dict:
    idx = bench_df.index
    if len(idx) and pd.Timestamp(idx.max()).tz_localize(None) > MEMBERSHIP_COVERAGE_THROUGH:
        raise ValueError(
            f"Backtest ends after PIT membership coverage ({MEMBERSHIP_COVERAGE_THROUGH.date()}); "
            "refusing to extrapolate constituent membership."
        )
    cols = list(frames)
    if membership_df is None:
        membership_df = load_membership_calendar(membership_path)
    calendar = validate_membership_calendar(membership_df)
    pit_mask = build_membership_mask(idx, cols, calendar)

    O = pd.concat({t: frames[t].Open for t in cols}, axis=1).reindex(idx)
    C = pd.concat({t: frames[t].Close for t in cols}, axis=1).reindex(idx)
    V = pd.concat({t: frames[t].Volume for t in cols}, axis=1).reindex(idx)
    turnover_flags = ["Turnover" in frames[t].columns for t in cols]
    if any(turnover_flags) and not all(turnover_flags):
        raise ValueError("mixed price frames: either every symbol must have raw Turnover or none")
    if all(turnover_flags):
        TV = pd.concat({t: frames[t].Turnover for t in cols}, axis=1).reindex(idx)
        tv = TV.rolling(126, min_periods=100).mean()
    else:
        # Legacy-only fallback for the existing Yahoo data path. Research runs
        # using TejHQ must use exchange-reported raw turnover.
        tv = (C * V).rolling(126, min_periods=100).mean()
    sma200 = C.rolling(200, min_periods=200).mean()
    # Both the liquidity ranking and the strategy eligibility are restricted
    # to the Nifty 500 members on that exact signal date.
    liquid = tv.where(pit_mask).rank(axis=1, ascending=False) <= liquid_top
    mom = C.shift(21) / C.shift(252) - 1
    valid = C.notna() & sma200.notna() & mom.notna() & pit_mask
    elig = valid & liquid & (C > sma200)
    rank = mom.where(elig).rank(axis=1, ascending=False, method="first")

    expected = expected_member_counts(idx, calendar)
    available = (pit_mask & C.notna()).sum(axis=1).to_numpy(dtype=int)
    coverage_pct = np.divide(
        available * 100.0, expected,
        out=np.full(len(expected), np.nan, dtype=float),
        where=expected > 0,
    )

    bc_raw = pd.to_numeric(bench_df["Close"], errors="coerce").reindex(idx)
    bc_observed = bc_raw.dropna()
    if bc_observed.empty:
        raise ValueError("NIFTYBEES has no observed closes on the NSE session calendar")
    # The 200-DMA is calculated on actual ETF observations, not repeated stale closes.
    bsma_observed = bc_observed.rolling(200, min_periods=200).mean()
    bull_observed = (bc_observed > bsma_observed).where(bsma_observed.notna())
    bull = bull_observed.reindex(idx).ffill()
    bull_known = bull.notna()
    bc = bc_observed.reindex(idx).ffill()
    if index_df is not None:
        ic = pd.to_numeric(index_df["Close"], errors="coerce").reindex(idx)
        if ic.isna().any():
            raise ValueError("Official NIFTY 50 index has missing closes on its session calendar")
    else:
        ic = bc.copy()
    isma = ic.rolling(200, min_periods=200).mean()
    # Never forward-fill opens: a missing exchange bar is not an executable price.
    # Close is carried only for mark-to-market of an existing holding; all signals,
    # eligibility and cross-sectional returns use the unfilled source observations.
    C_mark = C.ffill()
    return {"idx": idx, "cols": cols, "O": O.to_numpy(float), "C": C_mark.to_numpy(float),
            "C_raw": C.to_numpy(float),
            "rank": rank.to_numpy(float), "univ": (valid & liquid).to_numpy(bool),
            "pit_mask": pit_mask.to_numpy(bool), "pit_expected_count": expected,
            "pit_available_count": available, "pit_coverage_pct": coverage_pct,
            "membership_calendar": calendar,
            "bull": bull.fillna(False).to_numpy(bool), "bull_known": bull_known.to_numpy(bool),
            "bull_index": (ic > isma).fillna(False).to_numpy(bool), "bull_index_known": isma.notna().to_numpy(bool),
            "bench_close": bc.to_numpy(float), "bench_close_observed": bc_raw.to_numpy(float),
            "bench_stale": (~bc_raw.notna() & bc.notna()).to_numpy(bool),
            "index_close": ic.to_numpy(float),
            "index_is_distinct": index_df is not None}


def cross_check_benchmark(etf: pd.DataFrame, index: pd.DataFrame, min_corr: float = 0.95) -> float:
    """The ETF and the index it tracks must move together day to day; if not, one of the series is still wrong."""
    common = pd.concat([etf["Close"], index["Close"]], axis=1, keys=["etf", "idx"]).dropna()
    j = common.pct_change(fill_method=None).dropna()
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
    returns = close.pct_change(fill_method=None)
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
    """Daily engine: no synthetic opens, actual closes for signals, stale closes for valuation only."""
    idx, O, C = P["idx"], P["O"], P["C"]
    C_raw = P.get("C_raw", C)
    n, side = len(idx), cost_pct / 200.0
    cash, sh, hwm, pending = 1.0, {}, {}, set()
    last_close_seen = {}
    eq = np.full(n, np.nan)
    turns, stops, cash_days = [], 0, 0
    stale_holding_days, max_stale_sessions = 0, 0
    for t in range(start, n):
        o, c, actual_c = O[t], C[t], C_raw[t]
        prior_mark = C[t - 1] if t > 0 else c
        valid_open = np.isfinite(o) & (o > 0)
        mark_o = np.where(valid_open, o, prior_mark)
        mark_o = np.where(np.isfinite(mark_o), mark_o, c)
        reb = (t - 1) in signals and (t - 1) >= start - 1
        if reb or pending:
            traded = 0.0
            stopped_today = set()
            still_pending = set()
            for j in list(pending):
                if j in sh and valid_open[j]:
                    v = sh.pop(j) * o[j]
                    cash += v
                    traded += v
                    hwm.pop(j, None)
                    last_close_seen.pop(j, None)
                    stopped_today.add(j)
                elif j in sh:
                    still_pending.add(j)
            pending = still_pending
            equity_before = cash + sum(q * mark_o[j] for j, q in sh.items()
                                       if np.isfinite(mark_o[j]))
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
                target = [j for j in target if j not in stopped_today]
                for j in list(sh):
                    if j not in target and valid_open[j]:
                        v = sh.pop(j) * o[j]
                        cash += v
                        traded += v
                        hwm.pop(j, None)
                        last_close_seen.pop(j, None)
                        pending.discard(j)
                eq_now = cash + sum(q * mark_o[j] for j, q in sh.items()
                                    if np.isfinite(mark_o[j]))
                per_slot = exposure / size * eq_now if size > 0 else 0.0
                for j in target:
                    if not valid_open[j]:
                        continue
                    want, cur = per_slot, sh.get(j, 0.0) * o[j]
                    delta = want - cur
                    if delta > 1e-12:
                        # Reserve transaction costs before committing cash so
                        # a fully invested target does not create negative cash.
                        spendable = max(cash - traded * side, 0.0) / (1.0 + side)
                        delta = min(delta, spendable)
                        if delta <= 1e-12:
                            continue
                        cash -= delta
                        sh[j] = sh.get(j, 0.0) + delta / o[j]
                        traded += delta
                        hwm.setdefault(j, o[j])
                        last_close_seen.setdefault(j, t)
                    elif delta < -1e-12:
                        cash += -delta
                        sh[j] = sh[j] + delta / o[j]
                        traded += -delta
                turns.append(traded / equity_before if equity_before > 0 else 0.0)
            cash -= traded * side

        total = cash + sum(q * c[j] for j, q in sh.items())
        eq[t] = total
        if not sh:
            cash_days += 1
        for j in list(sh):
            if np.isfinite(actual_c[j]) and actual_c[j] > 0:
                last_close_seen[j] = t
                if trail:
                    hwm[j] = max(hwm.get(j, actual_c[j]), actual_c[j])
                    if actual_c[j] <= hwm[j] * (1 - trail) and j not in pending:
                        pending.add(j)
                        stops += 1
            else:
                last_seen = last_close_seen.setdefault(j, t)
                stale = t - last_seen
                if stale > 0:
                    stale_holding_days += 1
                    max_stale_sessions = max(max_stale_sessions, stale)
    return {
        "equity": eq, "turnover": turns, "stops": stops, "cash_days": cash_days,
        "stale_holding_days": stale_holding_days,
        "max_stale_sessions": max_stale_sessions,
    }


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


def build_missing_history_audit(calendar, frames, loader_diagnostics, start, end):
    """Audit absent price histories, distinguishing in-window members from older constituents."""
    cal = validate_membership_calendar(calendar)
    loaded = {normalise_symbol(t) for t in frames}
    diagnostics = {
        normalise_symbol(t): value for t, value in (loader_diagnostics or {}).items()
    }
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    missing = sorted(
        symbol for symbol in set(cal["symbol"])
        if symbol not in loaded or diagnostics.get(symbol, {}).get("status") in {
            "no_history", "insufficient_history", "error"
        }
    )
    rows = []
    for symbol in missing:
        group = cal.loc[cal["symbol"].eq(symbol)]
        overlaps = group["valid_from"].le(end_ts) & (
            group["valid_to"].isna() | group["valid_to"].gt(start_ts)
        )
        diag = diagnostics.get(symbol, {})
        last_end = "OPEN" if group["valid_to"].isna().any() else group["valid_to"].max().date().isoformat()
        rows.append({
            "symbol": symbol,
            "overlaps_test_window": bool(overlaps.any()),
            "membership_first": group["valid_from"].min().date().isoformat(),
            "membership_last": last_end,
            "membership_intervals": int(len(group)),
            "membership_sources": ",".join(sorted(group["source"].dropna().astype(str).unique())),
            "load_status": diag.get("status", "not_attempted"),
            "history_bars": diag.get("bars", 0),
            "load_detail": str(diag.get("detail", ""))[:400],
        })
    return pd.DataFrame(rows, columns=[
        "symbol", "overlaps_test_window", "membership_first", "membership_last",
        "membership_intervals", "membership_sources", "load_status",
        "history_bars", "load_detail",
    ])


def build_daily_coverage_audit(prepared, frames, start_pos=START):
    """Return one row per tested session, including all-series and PIT-member bar counts."""
    idx = pd.DatetimeIndex(prepared["idx"])
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    all_series_bars = np.zeros(len(idx), dtype=np.int32)
    for frame in frames.values():
        frame_idx = pd.DatetimeIndex(frame.index)
        if frame_idx.tz is not None:
            frame_idx = frame_idx.tz_localize(None)
        positions = idx.get_indexer(frame_idx.unique())
        positions = positions[positions >= 0]
        if len(positions):
            all_series_bars += np.bincount(positions, minlength=len(idx)).astype(np.int32)
    daily = pd.DataFrame({
        "date": idx.strftime("%Y-%m-%d"),
        "expected_active_members": prepared["pit_expected_count"],
        "active_member_bars": prepared["pit_available_count"],
        "active_member_coverage_pct": prepared["pit_coverage_pct"],
        "all_loaded_symbol_bars": all_series_bars,
        "loaded_price_series": int(len(frames)),
    })
    return daily.iloc[start_pos:].reset_index(drop=True)


def normalise_session_index(values) -> pd.DatetimeIndex:
    """Normalize exchange-session timestamps to unique, timezone-naive trading dates."""
    idx = pd.DatetimeIndex(pd.to_datetime(values))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    idx = idx.normalize()
    if idx.has_duplicates:
        duplicates = idx[idx.duplicated()].strftime("%Y-%m-%d").tolist()
        raise RuntimeError(f"Duplicate sessions after date normalization: {duplicates[:8]}")
    return idx.sort_values()


def build_session_calendar_audit(
    nse_sessions, benchmark_sessions, index_sessions, frames: dict
) -> pd.DataFrame:
    """Compare stock, ETF benchmark and NIFTY 50 index dates without dropping gaps."""
    nse = normalise_session_index(nse_sessions)
    benchmark = normalise_session_index(benchmark_sessions)
    index = normalise_session_index(index_sessions)
    stock_counts: dict[pd.Timestamp, int] = {}
    for ticker, frame in frames.items():
        dates = normalise_session_index(frame.index)
        for day in dates:
            stock_counts[day] = stock_counts.get(day, 0) + 1
    stock_dates = pd.DatetimeIndex(sorted(stock_counts))
    all_dates = nse.union(benchmark).union(index).union(stock_dates).sort_values()
    nse_set, benchmark_set, index_set = set(nse), set(benchmark), set(index)
    stock_set = set(stock_dates)
    return pd.DataFrame({
        "date": all_dates.strftime("%Y-%m-%d"),
        "nse_nifty50_session": [day in nse_set for day in all_dates],
        "adjusted_benchmark_bar": [day in benchmark_set for day in all_dates],
        "nifty50_index_bar": [day in index_set for day in all_dates],
        "stock_symbol_bars": [int(stock_counts.get(day, 0)) for day in all_dates],
        "zero_stock_bar_session": [
            day in nse_set and stock_counts.get(day, 0) == 0 for day in all_dates
        ],
        "missing_benchmark_bar": [
            day in nse_set and day not in benchmark_set for day in all_dates
        ],
        "missing_index_bar": [
            day in nse_set and day not in index_set for day in all_dates
        ],
        "extra_benchmark_session": [
            day in benchmark_set and day not in nse_set for day in all_dates
        ],
        "extra_index_session": [
            day in index_set and day not in nse_set for day in all_dates
        ],
        "extra_stock_session": [
            day in stock_set and day not in nse_set for day in all_dates
        ],
    })


def build_comparison_sessions(nse_sessions, session_audit: pd.DataFrame):
    """Exclude all-stock-data gaps from every series while preserving the full audit."""
    sessions = normalise_session_index(nse_sessions)
    required = {"date", "zero_stock_bar_session"}
    missing = required - set(session_audit.columns)
    if missing:
        raise ValueError(f"session audit is missing columns: {sorted(missing)}")
    zero_stock_dates = normalise_session_index(
        session_audit.loc[session_audit["zero_stock_bar_session"].astype(bool), "date"]
    )
    excluded = sessions.intersection(zero_stock_dates)
    return sessions.difference(excluded), excluded


def run_rules(frames: dict, bench_df: pd.DataFrame, oos_frac=0.35, cost_pct=0.30,
              index_df: pd.DataFrame | None = None,
              membership_df: pd.DataFrame | None = None,
              membership_path: str = DEFAULT_MEMBERSHIP_FILE,
              loader_diagnostics: dict | None = None,
              audit_outputs: dict | None = None,
              source_metadata: dict | None = None):
    source_metadata = source_metadata or {}
    loader_diagnostics = loader_diagnostics or {}
    audit_outputs = audit_outputs or {}
    observed_benchmark = bench_df.loc[bench_df["Close"].notna(), ["Close"]]
    quality = validate_benchmark(observed_benchmark, "adjusted NIFTYBEES")
    index_quality = (
        validate_benchmark(index_df, "NIFTY 50 price index")
        if index_df is not None else None
    )
    P = prepare(frames, bench_df, index_df=index_df,
                membership_df=membership_df, membership_path=membership_path)
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
    C = P["C"]; C_raw = P["C_raw"]; univ = P["univ"]
    dr = np.full(n, np.nan)
    for t in range(START + 1, n):
        m = univ[t - 1] & np.isfinite(C_raw[t]) & np.isfinite(C_raw[t - 1]) & (C_raw[t - 1] > 0)
        if m.any():
            dr[t] = np.mean(C_raw[t][m] / C_raw[t - 1][m] - 1)
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
    calendar = P["membership_calendar"]
    source_counts = calendar["source"].value_counts().to_dict()
    calendar_symbols = set(calendar["symbol"])
    loaded_symbols = {normalise_symbol(t) for t in frames}
    diagnostics_by_symbol = {
        normalise_symbol(t): value for t, value in (loader_diagnostics or {}).items()
    }
    missing_symbols = sorted(
        symbol for symbol in calendar_symbols
        if symbol not in loaded_symbols or diagnostics_by_symbol.get(symbol, {}).get("status") in {
            "no_history", "insufficient_history", "error"
        }
    )
    test_window_symbols = set(calendar.loc[
        calendar["valid_from"].le(idx[-1]) &
        (calendar["valid_to"].isna() | calendar["valid_to"].gt(idx[START])),
        "symbol",
    ])
    price_history_audit = build_missing_history_audit(
        calendar, frames, loader_diagnostics or {}, idx[START], idx[-1]
    )
    daily_coverage_audit = build_daily_coverage_audit(P, frames)
    missing_test_window = price_history_audit.loc[
        price_history_audit["overlaps_test_window"]
    ]
    missing_outside_window = price_history_audit.loc[
        ~price_history_audit["overlaps_test_window"]
    ]
    if audit_outputs is not None:
        audit_outputs["pit_price_history_audit"] = price_history_audit
        audit_outputs["pit_daily_coverage_audit"] = daily_coverage_audit
    coverage = P["pit_coverage_pct"][START:]
    coverage = coverage[np.isfinite(coverage)]
    active_counts = P["pit_expected_count"][START:]
    if len(coverage):
        coverage_stats = (float(np.min(coverage)), float(np.percentile(coverage, 10)),
                          float(np.median(coverage)), float(np.mean(coverage < 90) * 100))
    else:
        coverage_stats = (float("nan"),) * 4
    zero_rows = daily_coverage_audit.loc[
        daily_coverage_audit["active_member_coverage_pct"].eq(0)
    ]
    zero_stock_rows = daily_coverage_audit.loc[
        daily_coverage_audit["all_loaded_symbol_bars"].eq(0)
    ]
    worst_rows = daily_coverage_audit.dropna(
        subset=["active_member_coverage_pct"]
    ).nsmallest(8, "active_member_coverage_pct")
    worst_detail = "; ".join(
        f"{r.date}: {int(r.active_member_bars)}/{int(r.expected_active_members)} "
        f"({r.active_member_coverage_pct:.1f}%), all-symbol bars={int(r.all_loaded_symbol_bars)}"
        for r in worst_rows.itertuples(index=False)
    )
    load_status_counts = missing_test_window["load_status"].value_counts().to_dict()
    missing_active_sample = [
        f"{r.symbol}:{r.load_status}({int(r.history_bars)} bars)"
        for r in missing_test_window.head(20).itertuples(index=False)
    ]
    source_line = (
        f"Stock source: {source_metadata.get('source')} | dataset revision "
        f"{source_metadata.get('dataset_revision')} | series {source_metadata.get('series_scope')}"
        if source_metadata else "Stock source: unspecified"
    )
    adjustment_scope = source_metadata.get("adjustment_scope", "not recorded") if source_metadata else "not recorded"
    stale_days = sum(v.get("stale_holding_days", 0) for v in runs.values())
    max_stale = max((v.get("max_stale_sessions", 0) for v in runs.values()), default=0)
    benchmark_stale = P["bench_stale"]
    computed_benchmark_stale_max = 0
    current_stale = 0
    for stale in benchmark_stale:
        current_stale = current_stale + 1 if stale else 0
        computed_benchmark_stale_max = max(computed_benchmark_stale_max, current_stale)
    benchmark_stale_days = int(source_metadata.get(
        "benchmark_missing_official_sessions", benchmark_stale.sum()
    ))
    benchmark_stale_max = int(source_metadata.get(
        "benchmark_max_consecutive_missing_sessions", computed_benchmark_stale_max
    ))
    quality_issues = []
    if len(missing_test_window):
        quality_issues.append(f"{len(missing_test_window)} active-window symbols lack a full 253-bar history")
    if len(zero_rows):
        quality_issues.append(f"{len(zero_rows)} official sessions have zero active-member bars")
    if len(zero_stock_rows):
        quality_issues.append(f"{len(zero_stock_rows)} official sessions have zero bars across the loaded stock universe")
    if benchmark_stale_days:
        quality_issues.append(
            f"{benchmark_stale_days} official sessions have no NIFTYBEES bar "
            f"(maximum consecutive gap {benchmark_stale_max}); only the prior regime state is carried"
        )
    if max_stale > 5:
        quality_issues.append(f"a held position had up to {max_stale} consecutive sessions without an actual close")
    if source_metadata and any(term in adjustment_scope.lower() for term in ("merger", "demerger", "rights", "buyback")):
        quality_issues.append("the provider does not scale mergers/demergers/rights/buybacks")
    quality_status = (
        "NOT DECISION-GRADE — " + "; ".join(quality_issues)
        if quality_issues else "DIAGNOSTIC ONLY — source-level corporate-action coverage must be reviewed"
    )
    out = [source_line, f"Adjustment scope: {adjustment_scope}",
           f"Data quality status: {quality_status}",
           f"Portfolio rules: {len(frames)} loaded price histories for PIT Nifty 500, daily engine {d0} to {d1}, IS/OOS split {ds}, cost {cost_pct}% round trip, cash 0%",
           f"PIT calendar: {len(calendar)} intervals / {len(calendar_symbols)} symbols; source coverage through {MEMBERSHIP_COVERAGE_THROUGH.date()}; source categories {source_counts}",
           f"PIT active-member count during test: {int(np.min(active_counts))}–{int(np.max(active_counts))} (nominal index size {EXPECTED_INDEX_SIZE}; source documents historical count drift and a 499-name 2026 snapshot)",
           f"Price-history coverage across full calendar: {len(calendar_symbols) - len(missing_symbols)}/{len(calendar_symbols)} symbols loaded; {len(missing_symbols)} missing/unusable",
           f"Missing histories overlapping test window: {len(missing_test_window)}/{len(test_window_symbols)} active-window symbols; {len(missing_outside_window)} additional missing symbols have no overlap with this backtest window",
           f"Active-window missing load outcomes: {load_status_counts}; first 20: {missing_active_sample}",
           f"Daily active-member bars covered: min {coverage_stats[0]:.1f}%, p10 {coverage_stats[1]:.1f}%, median {coverage_stats[2]:.1f}%; {coverage_stats[3]:.1f}% of sessions below 90% coverage",
           f"Zero active-member-coverage sessions: {len(zero_rows)}; dates: {zero_rows['date'].tolist()[:20]}",
           f"Zero-stock-bar sessions: {len(zero_stock_rows)}; dates: {zero_stock_rows['date'].tolist()[:20]}",
           f"Worst coverage sessions (date: active bars/expected, coverage, all loaded-symbol bars): {worst_detail}",
           "Missing opens are never forward-filled; close carry-forward is used only to value existing holdings, while eligibility, returns and stops use observed closes.",
           f"Stale-close diagnostics: {stale_days} held-position stale-close days across variants; maximum consecutive stale sessions={max_stale}.",
           f"Benchmark: {source_metadata.get('benchmark_source', 'NIFTYBEES split-adjusted close')} | {quality['bars']} observed bars; max abs daily move {quality['max_abs_daily_return_pct']:.2f}%; stale official sessions={benchmark_stale_days} (max consecutive {benchmark_stale_max})",
           *([f"Session calendar / regime diagnostic: {source_metadata.get('session_calendar_source', 'official NSE NIFTY 50 index history')} | {index_quality['bars']} bars; max abs daily move {index_quality['max_abs_daily_return_pct']:.2f}%"] if index_quality else []),
           "NIFTY50_price_index is an official NSE PRICE index (not a total-return index).",
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
    out += ["", f"-- what the NSE-sourced NIFTYBEES filter sees: {len(bear_days)} BEAR days ({len(bear_days) / max(1, len(bear_days) + len(bull_days)) * 100:.0f}% of known-regime days), {len(bull_days)} BULL days --",
            f"annualised adjusted ETF return on ETF-BEAR days: {ann(etf_ret, bear_days) * 100:+.1f}%; same-universe equal-weight: {ann(dr, bear_days) * 100:+.1f}%",
            f"annualised adjusted ETF return on ETF-BULL days: {ann(etf_ret, bull_days) * 100:+.1f}%; same-universe equal-weight: {ann(dr, bull_days) * 100:+.1f}%"]
    if P["index_is_distinct"]:
        ibear = [t for t in range(START + 1, n) if P["bull_index_known"][t - 1] and not P["bull_index"][t - 1]]
        ibull = [t for t in range(START + 1, n) if P["bull_index_known"][t - 1] and P["bull_index"][t - 1]]
        common = [t for t in range(START + 1, n) if P["bull_known"][t - 1] and P["bull_index_known"][t - 1]]
        disagree = sum(P["bull"][t - 1] != P["bull_index"][t - 1] for t in common)
        out += [f"^NSEI filter: {len(ibear)} BEAR / {len(ibull)} BULL days; disagrees with NSE-sourced ETF regime on {disagree}/{len(common)} common days",
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
    ap.add_argument("--cache", default="data_cache/tejhq_frames_10y_v2.pkl")
    ap.add_argument("--data-source", choices=("tejhq", "yahoo"), default="tejhq",
                    help="price history source; research default is one consistent TejHQ adjusted NSE dataset")
    ap.add_argument("--membership-file", default=DEFAULT_MEMBERSHIP_FILE)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--outdir", default="results")
    a = ap.parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)
    membership = load_membership_calendar(a.membership_file)
    if a.data_source != "tejhq":
        sys.exit("The PIT data-quality comparison requires TejHQ adjusted NSE prices; Yahoo mode is not a consistent source.")
    end_date = MEMBERSHIP_COVERAGE_THROUGH.date()
    start_date = (pd.Timestamp(end_date) - pd.DateOffset(years=a.years)).date()
    tickers = [f"{symbol}.NS" for symbol in sorted(membership["symbol"].unique())]

    nse_benchmark_raw = load_niftybees_raw_history(
        start_date, end_date, cache_path="data_cache/niftybees_nse_raw.csv", refresh=a.refresh,
    )
    index = load_nifty50_index_history(
        start_date, end_date, cache_path="data_cache/nifty50_index.csv", refresh=a.refresh,
    )
    if index.empty:
        sys.exit("could not fetch official NSE NIFTY 50 index history")

    frames, loader_diagnostics = PL.load_frames(
        tickers, a.years, a.cache, a.refresh, min_bars=253,
        return_diagnostics=True, source=a.data_source, membership_df=membership,
        start_date=start_date, end_date=end_date,
    )
    source_metadata = loader_diagnostics.pop("_source", {})
    symbol_audit = loader_diagnostics.pop("_symbol_audit", [])
    if not frames:
        sys.exit(f"no stock histories loaded from {a.data_source}")

    tej_benchmark_raw, _ = load_niftybees_raw_frame(
        start_date.isoformat(), end_date.isoformat(),
        cache_dir="data_cache/tejhq_parquet", refresh=a.refresh,
        revision=source_metadata.get("dataset_revision"),
    )
    index_sessions = normalise_session_index(index.index)
    official_sessions = build_nse_session_calendar(
        start_date, end_date, index_sessions=index_sessions,
    )
    official_sessions = official_sessions[
        (official_sessions >= index_sessions.min())
        & (official_sessions <= index_sessions.max())
    ]
    calendar_start, calendar_end = official_sessions.min(), official_sessions.max()
    nse_benchmark_raw.index = normalise_session_index(nse_benchmark_raw.index)
    tej_benchmark_raw.index = normalise_session_index(tej_benchmark_raw.index)
    nse_benchmark_raw = nse_benchmark_raw.loc[
        (nse_benchmark_raw.index >= calendar_start)
        & (nse_benchmark_raw.index <= calendar_end)
    ].copy()
    tej_benchmark_raw = tej_benchmark_raw.loc[
        (tej_benchmark_raw.index >= calendar_start)
        & (tej_benchmark_raw.index <= calendar_end)
    ].copy()
    benchmark_raw, benchmark_reconciliation = merge_niftybees_sources(
        nse_benchmark_raw, tej_benchmark_raw,
        allowed_extra_sessions=official_sessions,
    )
    official_bench = apply_niftybees_split_adjustments(benchmark_raw)
    validate_benchmark(official_bench, "NSE/TejHQ raw NIFTYBEES, split-adjusted")

    # Preserve the full official calendar for audit. Exclude a date from every
    # strategy and benchmark series only when the stock provider has zero bars
    # for the entire loaded universe on that exchange session.
    bench = official_bench[["Open", "Close"]].copy()
    benchmark_sessions = normalise_session_index(bench.index)
    session_audit = build_session_calendar_audit(
        official_sessions, benchmark_sessions, index_sessions, frames
    )
    comparison_sessions, excluded_zero_stock_sessions = build_comparison_sessions(
        official_sessions, session_audit
    )
    comparison_date_set = set(comparison_sessions.strftime("%Y-%m-%d"))
    session_audit["comparison_included"] = session_audit["date"].isin(comparison_date_set)
    session_audit["comparison_exclusion_reason"] = np.where(
        session_audit["zero_stock_bar_session"],
        "no stock bars for any loaded symbol",
        "",
    )
    session_audit.to_csv(os.path.join(a.outdir, "pit_session_calendar_audit.csv"), index=False)
    missing_benchmark = comparison_sessions.difference(benchmark_sessions)
    extra_benchmark = benchmark_sessions.difference(official_sessions)
    missing_index = comparison_sessions.difference(index_sessions)
    extra_index = index_sessions.difference(official_sessions)
    index_coverage = (
        len(index_sessions.intersection(comparison_sessions)) / len(comparison_sessions)
        if len(comparison_sessions) else 0.0
    )
    extra_stock = session_audit.loc[session_audit["extra_stock_session"], "date"].tolist()
    missing_benchmark_mask = pd.Series(
        comparison_sessions.isin(missing_benchmark), index=comparison_sessions
    )
    max_benchmark_gap = 0
    current_gap = 0
    for missing in missing_benchmark_mask.to_numpy(bool):
        current_gap = current_gap + 1 if missing else 0
        max_benchmark_gap = max(max_benchmark_gap, current_gap)
    if (
        not missing_benchmark.empty or not extra_benchmark.empty
        or not missing_index.empty or not extra_index.empty or bool(extra_stock)
        or index_coverage < 1.0
    ):
        sys.exit(
            "NSE session alignment failed: "
            f"missing benchmark={len(missing_benchmark)} (max consecutive {max_benchmark_gap}), "
            f"extra benchmark={len(extra_benchmark)}, missing NIFTY50 index={len(missing_index)} "
            f"({index_coverage:.3%} comparison-session coverage), extra NIFTY50 index={len(extra_index)}, "
            f"off-calendar stock dates={len(extra_stock)}, "
            f"zero-stock sessions excluded={len(excluded_zero_stock_sessions)}; "
            f"first missing index dates={missing_index.strftime('%Y-%m-%d').tolist()[:10]}, "
            f"first missing benchmark dates={missing_benchmark.strftime('%Y-%m-%d').tolist()[:10]}, "
            f"first stock dates={extra_stock[:10]}"
        )
    bench.index = normalise_session_index(bench.index)
    bench = bench.reindex(comparison_sessions)
    index.index = normalise_session_index(index.index)
    index = index.reindex(comparison_sessions)
    corr = cross_check_benchmark(bench, index)
    source_metadata.update({
        "benchmark_source": "NSE NextApi raw NIFTYBEES OHLC, supplemented only by TejHQ raw NSE bhavcopy bars on validated NSE-calendar sessions absent from NextApi; common dates reconciled",
        "benchmark_adjustment_scope": "10:1 face-value split only; no dividend adjustment applied to the ETF",
        **{f"benchmark_{key}": value for key, value in benchmark_reconciliation.items()},
        "session_calendar_source": "pandas_market_calendars==5.6.0 NSE holiday calendar + observed NIFTY 50 index sessions + NSE Circular MSD/60677 (2024-03-02)",
        "session_calendar_start": calendar_start.date().isoformat(),
        "session_calendar_end": calendar_end.date().isoformat(),
        "session_calendar_bars": int(len(official_sessions)),
        "comparison_session_bars": int(len(comparison_sessions)),
        "comparison_excluded_zero_stock_session_count": int(len(excluded_zero_stock_sessions)),
        "comparison_excluded_zero_stock_session_dates": excluded_zero_stock_sessions.strftime("%Y-%m-%d").tolist(),
        "index_missing_official_sessions": int(len(missing_index)),
        "index_missing_official_dates": missing_index.strftime('%Y-%m-%d').tolist()[:20],
        "index_missing_excluded_sessions": int(session_audit.loc[~session_audit["comparison_included"], "missing_index_bar"].sum()),
        "index_session_coverage_pct": float(index_coverage * 100),
        "benchmark_missing_official_sessions": int(len(missing_benchmark)),
        "benchmark_missing_excluded_sessions": int(session_audit.loc[~session_audit["comparison_included"], "missing_benchmark_bar"].sum()),
        "benchmark_max_consecutive_missing_sessions": int(max_benchmark_gap),
        "zero_stock_bar_sessions": int(session_audit["zero_stock_bar_session"].sum()),
        "off_calendar_stock_dates": int(len(extra_stock)),
    })
    audit_outputs = {}
    _, text = run_rules(
        frames, bench, a.oos_frac, a.cost_pct, index_df=index,
        membership_df=membership, loader_diagnostics=loader_diagnostics,
        audit_outputs=audit_outputs, source_metadata=source_metadata,
    )
    daily_audit = audit_outputs.get("pit_daily_coverage_audit", pd.DataFrame()).copy()
    if not daily_audit.empty:
        session_audit = session_audit.merge(daily_audit, on="date", how="left")
        aligned = session_audit.dropna(subset=["all_loaded_symbol_bars"])
        if (
            aligned["stock_symbol_bars"].astype(int)
            != aligned["all_loaded_symbol_bars"].astype(int)
        ).any():
            sys.exit("Session audit stock-bar counts do not reconcile with the daily coverage audit")
        excluded_mask = ~session_audit["comparison_included"]
        session_audit.loc[excluded_mask, "all_loaded_symbol_bars"] = 0
        session_audit.loc[excluded_mask, "active_member_bars"] = 0
        tested_start = pd.Timestamp(comparison_sessions[START]).strftime("%Y-%m-%d")
        session_audit["tested_session"] = session_audit["date"].ge(tested_start)
        session_audit["zero_active_member_bar_session"] = (
            session_audit["tested_session"]
            & session_audit["nse_nifty50_session"]
            & session_audit["active_member_bars"].fillna(0).eq(0)
        )
    audit_outputs["pit_session_calendar_audit"] = session_audit
    for audit_name, audit_frame in audit_outputs.items():
        audit_frame.to_csv(os.path.join(a.outdir, f"{audit_name}.csv"), index=False)
    if symbol_audit:
        pd.DataFrame(symbol_audit).to_csv(
            os.path.join(a.outdir, "tejhq_symbol_continuity_audit.csv"), index=False
        )
    if source_metadata:
        with open(os.path.join(a.outdir, "tejhq_source_metadata.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(f"- {key}: {value}" for key, value in source_metadata.items()) + "\n")

    source_note = (
        f"Stock universe: TejHQ adjusted NSE OHLC (dataset revision {source_metadata.get('dataset_revision', 'unknown')}), "
        "back-adjusted for splits, bonuses and dividends; raw exchange volume/turnover retained; "
        "mergers/demergers/rights/buybacks are not scaled. "
        "Benchmark: NSE NextApi raw NIFTYBEES OHLC, supplemented only with TejHQ raw NSE bhavcopy bars on validated NSE-calendar sessions absent from NextApi, split-adjusted for the 10:1 face-value split "
        "effective 2019-12-19 and cross-checked against TejHQ raw bars on common dates; the ETF is not dividend-adjusted. "
        "Session calendar: pandas_market_calendars==5.6.0 NSE holiday schedule, observed official NIFTY 50 index sessions, and the documented NSE special session on 2024-03-02 (Circular MSD/60677). "
        f"The full calendar has {len(official_sessions)} sessions; all strategy and benchmark series use the same {len(comparison_sessions)} comparison sessions. "
        f"Excluded {len(excluded_zero_stock_sessions)} official sessions with zero stock bars across the loaded universe: {', '.join(excluded_zero_stock_sessions.strftime('%Y-%m-%d')) or 'none'}. "
        "The complete calendar and exclusion flags remain in pit_session_calendar_audit.csv. "
        "The comparison fails closed on any missing NIFTYBEES or NIFTY 50 bar on an included session; no benchmark prices are synthesized. "
        "Missing stock opens, eligibility and returns are never forward-filled; close carry-forward is used only to mark existing holdings to market.\n"
    )
    text = source_note + f"Daily-return correlation split-adjusted NIFTYBEES vs official NSE NIFTY 50: {corr:.3f}\n" + text
    with open(os.path.join(a.outdir, "portfolio_rules_report.md"), "w", encoding="utf-8") as fh:
        fh.write("```\n" + text + "\n```\n")
    print(text)


if __name__ == "__main__":
    main()
