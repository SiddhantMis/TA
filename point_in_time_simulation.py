#!/usr/bin/env python3
"""Reproducible point-in-time momentum simulations at five random post-COVID dates.

Each sample freezes PIT NIFTY 500 membership, stock/benchmark prices and
unsupported corporate-action knowledge at the signal date. The basket is ranked
using the repository's 12-1 relative-strength, 200-DMA and 126-session liquidity
rules. Entries use the next session's open; exits use 1/3/6-month session closes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from nifty500_pit import load_membership_calendar
from tejhq_data import get_dataset_revision, load_adjusted_frames
from niftyindices_tri import load_nifty500_tri_history

UNSUPPORTED_ACTIONS = {"merger", "demerger", "rights", "buyback", "other"}
POST_COVID_START = "2020-03-23"
DATA_START = "2019-01-01"
DATA_END = "2026-10-13"
DEFAULT_SEED = 20261103
PORTFOLIO_SIZE = 20
LIQUID_TOP = 200
ROUND_TRIP_COST = 0.003
HORIZONS = {"1M": 21, "3M": 63, "6M": 126}


def load_unsupported_actions(start_date, end_date, cache_dir, revision):
    """Load event history once; callers apply only events known at each sample date."""
    from huggingface_hub import hf_hub_download

    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    parts = []
    for year in range(start.year, end.year + 1):
        filename = f"actions/nse_{year}.parquet"
        path = hf_hub_download(
            repo_id="tejhq/indian-markets", repo_type="dataset",
            filename=filename, cache_dir=str(root), revision=revision,
        )
        frame = pd.read_parquet(path)
        required = {"symbol", "ex_date", "type"}
        if not required.issubset(frame.columns):
            raise RuntimeError(f"{filename} lacks required columns: {sorted(required - set(frame.columns))}")
        frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
        frame["type"] = frame["type"].astype(str).str.strip().str.lower()
        frame["ex_date"] = pd.to_datetime(frame["ex_date"], errors="coerce").dt.normalize()
        frame = frame.loc[
            frame["ex_date"].between(start, end)
            & frame["type"].isin(UNSUPPORTED_ACTIONS)
        ].copy()
        if not frame.empty:
            parts.append(frame[["symbol", "ex_date", "type"]])
    if not parts:
        return pd.DataFrame(columns=["symbol", "ex_date", "type"])
    return pd.concat(parts, ignore_index=True).drop_duplicates().sort_values(["symbol", "ex_date"])


def active_symbols(calendar, as_of):
    date = pd.Timestamp(as_of)
    active = calendar.loc[
        (calendar["valid_from"] <= date)
        & (calendar["valid_to"].isna() | (calendar["valid_to"] > date)),
        "symbol",
    ]
    return sorted(set(active.astype(str).str.upper()))


def _series(frame, column, sessions):
    if frame is None or column not in frame:
        return pd.Series(index=sessions, dtype=float)
    values = pd.to_numeric(frame[column], errors="coerce")
    values.index = pd.DatetimeIndex(values.index).tz_localize(None)
    return values.reindex(sessions)


def score_snapshot(as_of, symbols, frames, benchmark, actions, selection_order="liquidity_first", liquid_top=LIQUID_TOP):
    """Return the ranked top-20 and diagnostics using data known on as_of only.

    selection_order="liquidity_first" mirrors portfolio_rules.prepare and the live rules: the liquid top-200 is
    chosen from ALL point-in-time members by 126-session traded value, THEN the data-validity, 200-DMA and
    momentum filters apply. "trend_first" is what the original five-date run did (filter by trend, then take the
    200 most liquid survivors, which admits less-liquid stocks in a broad bull market); it is kept only so the
    effect of the difference can be measured.
    """
    if selection_order not in ("liquidity_first", "trend_first"):
        raise ValueError(f"unknown selection_order {selection_order!r}")
    sessions = benchmark.index[benchmark.index <= pd.Timestamp(as_of)]
    if len(sessions) < 253:
        raise RuntimeError(f"{as_of}: fewer than 253 benchmark sessions in lookback")
    sessions = sessions[-253:]
    signal_date = sessions[-1]
    benchmark_close = _series(benchmark, "Close", sessions)
    if benchmark_close.isna().any() or (benchmark_close <= 0).any():
        raise RuntimeError(f"{as_of}: invalid NIFTYBEES close in ranking window")
    bench_start, bench_end = float(benchmark_close.iloc[0]), float(benchmark_close.iloc[-22])
    bench_sma200 = float(benchmark_close.iloc[-200:].mean())
    market_close = float(benchmark_close.iloc[-1])
    market_regime = "BULL" if market_close > bench_sma200 else "BEAR"

    action_dates = {}
    known_actions = actions.loc[actions["ex_date"] <= signal_date]
    if not known_actions.empty:
        action_dates = known_actions.groupby("symbol")["ex_date"].max().to_dict()

    rows, excluded, pool = [], [], {}
    for symbol in symbols:
        ticker = f"{symbol}.NS"
        frame = frames.get(ticker)
        if frame is None or frame.empty:
            excluded.append({"symbol": symbol, "reason": "no_price_history"})
            continue
        # Liquidity pool, as in portfolio_rules.prepare: mean raw traded value over the last 126 sessions with >= 100
        # observations, measured on the ORIGINAL history. A corporate-action reset changes eligibility, not liquidity.
        tv_window = _series(frame, "RawClose", sessions[-126:]) * _series(frame, "Volume", sessions[-126:])
        pool_tv = float(tv_window.mean()) if int(tv_window.notna().sum()) >= 100 else float("nan")
        if np.isfinite(pool_tv) and pool_tv > 0:
            pool[symbol] = pool_tv
        event_date = action_dates.get(symbol)
        if event_date is not None:
            frame = frame.loc[pd.DatetimeIndex(frame.index).tz_localize(None) >= event_date]
        close = _series(frame, "Close", sessions)
        volume = _series(frame, "Volume", sessions)
        raw_close = _series(frame, "RawClose", sessions)
        high = _series(frame, "High", sessions)
        if close.isna().any() or volume.isna().any() or raw_close.isna().any() or (close <= 0).any() or (raw_close <= 0).any():
            excluded.append({"symbol": symbol, "reason": "not_253_consecutive_observed_sessions"})
            continue
        if signal_date not in frame.index:
            excluded.append({"symbol": symbol, "reason": "no_exact_signal_date_bar"})
            continue
        # The unsupported event reset is point-in-time: future actions are ignored.
        stock_start, stock_end = float(close.iloc[0]), float(close.iloc[-22])
        momentum = (stock_end / stock_start - 1) - (bench_end / bench_start - 1)
        sma200 = float(close.iloc[-200:].mean())
        if not np.isfinite(sma200) or float(close.iloc[-1]) <= sma200:
            excluded.append({"symbol": symbol, "reason": "not_above_200dma"})
            continue
        # Raw exchange close x raw volume is the actual traded-value basis;
        # adjusted prices are reserved for momentum and trend calculations.
        avg_traded_value = pool_tv
        if not np.isfinite(avg_traded_value) or avg_traded_value <= 0:
            excluded.append({"symbol": symbol, "reason": "invalid_126d_traded_value"})
            continue
        high252 = float(high.max()) if high.notna().all() else np.nan
        rows.append({
            "ticker": ticker, "symbol": symbol,
            "close_on_signal": float(close.iloc[-1]),
            "sma200": sma200, "momentum_12_1_pct": momentum * 100,
            "stock_12_1_pct": (stock_end / stock_start - 1) * 100,
            "benchmark_12_1_pct": (bench_end / bench_start - 1) * 100,
            "avg_traded_value_126d": avg_traded_value,
            "pct_below_52w_high": (1 - float(close.iloc[-1]) / high252) * 100 if high252 > 0 else None,
            "unsupported_action_reset_date": event_date.date().isoformat() if event_date is not None else None,
        })

    pool_order = sorted(pool.items(), key=lambda kv: (-kv[1], kv[0]))
    liquidity_rank = {sym: i + 1 for i, (sym, _) in enumerate(pool_order)}
    if selection_order == "liquidity_first":
        liquid_set = {sym for sym, _ in pool_order[:liquid_top]}
        liquid = [row for row in rows if row["symbol"] in liquid_set]
    else:
        rows.sort(key=lambda row: (-row["avg_traded_value_126d"], row["ticker"]))
        liquid = rows[:liquid_top]
    liquid.sort(key=lambda row: (-row["momentum_12_1_pct"], row["ticker"]))
    for rank, row in enumerate(liquid, 1):
        row["leader_rank"] = rank
        row["liquidity_rank"] = liquidity_rank.get(row["symbol"])
    selected = liquid[:PORTFOLIO_SIZE]
    return {
        "selection_order": selection_order, "pool_size": len(pool), "liquid_pool_count": min(liquid_top, len(pool)),
        "signal_date": signal_date,
        "market_regime": market_regime,
        "benchmark_close": market_close,
        "benchmark_sma200": bench_sma200,
        "ranked": selected,
        "ranked_count": len(liquid),
        "eligible_count": len(rows),
        "excluded": excluded,
    }


def _price_at(frames, ticker, column, session):
    frame = frames.get(ticker)
    if frame is None or session not in frame.index or column not in frame:
        return None
    value = pd.to_numeric(pd.Series([frame.at[session, column]]), errors="coerce").iloc[0]
    return float(value) if pd.notna(value) and np.isfinite(value) and value > 0 else None


def _level(frame, session, column):
    """A strictly positive observed price/index level, or None (never filled)."""
    try:
        value = float(frame.at[session, column])
    except (KeyError, TypeError, ValueError):
        return None
    return value if np.isfinite(value) and value > 0 else None


def simulate_sample(snapshot, calendar, frames, tri, sample_id, actions, bees=None):
    signal_date = snapshot["signal_date"]
    pos = calendar.get_loc(signal_date)
    entry_pos = pos + 1
    entry_date = calendar[entry_pos]
    picks = snapshot["ranked"]
    stock_rows, returns = [], []
    for pick in picks:
        ticker = pick["ticker"]
        entry = _price_at(frames, ticker, "Open", entry_date)
        signal_close = _price_at(frames, ticker, "Close", signal_date)
        row = {
            "sample_id": sample_id, "signal_date": signal_date.date().isoformat(),
            "entry_date": entry_date.date().isoformat(), **pick,
            "entry_open_adjusted": entry,
            "signal_close_adjusted": signal_close,
        }
        for label, offset in HORIZONS.items():
            exit_pos = entry_pos + offset - 1
            exit_date = calendar[exit_pos]
            exit_close = _price_at(frames, ticker, "Close", exit_date)
            has_unsupported_event = False
            if not actions.empty:
                has_unsupported_event = bool((
                    actions["symbol"].eq(pick["symbol"])
                    & actions["ex_date"].gt(signal_date)
                    & actions["ex_date"].le(exit_date)
                ).any())
            row[f"{label}_exit_date"] = exit_date.date().isoformat()
            row[f"{label}_exit_close_adjusted"] = exit_close
            row[f"{label}_unsupported_action_during_hold"] = has_unsupported_event
            # Like-for-like with the TRI: adjusted close at the signal date -> exit close, same 0.30% round-trip cost.
            cc_factor = (exit_close / signal_close) * (1 - ROUND_TRIP_COST / 2) / (1 + ROUND_TRIP_COST / 2) if signal_close and exit_close else None
            row[f"{label}_close_to_close_net_return_pct"] = (cc_factor - 1) * 100 if cc_factor is not None and not has_unsupported_event else None
            if entry and exit_close and not has_unsupported_event:
                row[f"{label}_gross_return_pct"] = (exit_close / entry - 1) * 100
                net_factor = (exit_close / entry) * (1 - ROUND_TRIP_COST / 2) / (1 + ROUND_TRIP_COST / 2)
                row[f"{label}_net_return_pct"] = (net_factor - 1) * 100
                row[f"{label}_return_status"] = "ok"
            else:
                row[f"{label}_gross_return_pct"] = None
                row[f"{label}_net_return_pct"] = None
                row[f"{label}_return_status"] = (
                    "unsupported_corporate_action_during_hold" if has_unsupported_event
                    else "missing_entry_or_exit_price"
                )
        stock_rows.append(row)

    cost_factor = (1 - ROUND_TRIP_COST / 2) / (1 + ROUND_TRIP_COST / 2)
    for label, offset in HORIZONS.items():
        exit_date = calendar[entry_pos + offset - 1]
        tri_signal = _level(tri, signal_date, "Close")
        tri_exit = _level(tri, exit_date, "Close")
        # (1) the original comparison: TRI signal-date close -> exit close. It includes the overnight gap between the
        #     signal close and the next open that the stocks (bought at the open) never earn.
        benchmark_return = (tri_exit / tri_signal - 1) * 100 if tri_signal and tri_exit else None
        # (2) entry-aligned TRI: the TRI level at the entry OPEN is the signal close moved by NIFTYBEES' overnight change.
        aligned_return = bees_net_return = None
        b_close_signal = b_open_entry = None
        if bees is not None:
            b_close_signal, b_open_entry = _level(bees, signal_date, "Close"), _level(bees, entry_date, "Open")
        if bees is not None and tri_signal and tri_exit:
            b_close_exit = _level(bees, exit_date, "Close")
            if b_close_signal and b_open_entry:
                aligned_return = (tri_exit / (tri_signal * b_open_entry / b_close_signal) - 1) * 100
            # (3) like-for-like investable proxy: NIFTYBEES entry open -> exit close, same cost as the stocks.
            if b_open_entry and b_close_exit:
                bees_net_return = ((b_close_exit / b_open_entry) * cost_factor - 1) * 100
        vals = [row[f"{label}_net_return_pct"] for row in stock_rows]
        got = [v for v in vals if v is not None]
        complete = len(vals) > 0 and len(got) == len(vals)
        # Empty slots (fewer than 20 names qualified) stay in cash at 0%, exactly as portfolio_rules does; no reweighting.
        raw_basket = float(np.sum(got) / PORTFOLIO_SIZE) if complete else None
        available_mean = float(np.mean(got)) if got else None      # diagnostic ONLY: silently reweights over survivors
        if snapshot["market_regime"] == "BULL":
            filtered = raw_basket
        else:
            filtered = 0.0                                          # cash is certain, whether or not the stock basket is complete
        cc_vals = [row[f"{label}_close_to_close_net_return_pct"] for row in stock_rows]
        cc_complete = len(cc_vals) > 0 and all(v is not None for v in cc_vals)
        raw_cc = float(np.sum(cc_vals) / PORTFOLIO_SIZE) if cc_complete else None
        filtered_cc = raw_cc if snapshot["market_regime"] == "BULL" else 0.0
        # Flags compare against the TRI exactly as the original report did (signal close -> exit close). The open-entry
        # basket and that TRI differ by the overnight gap, so the like-for-like flags use the close-to-close basket.
        comparator = benchmark_return
        returns.append({
            "sample_id": sample_id,
            "signal_date": signal_date.date().isoformat(),
            "market_regime": snapshot["market_regime"],
            "entry_date": entry_date.date().isoformat(),
            "horizon": label,
            "exit_date": exit_date.date().isoformat(),
            "selected_stocks": len(stock_rows),
            "slots_filled": len(stock_rows),
            "complete_stock_prices": complete,
            "raw_top20_equal_weight_net_return_pct": raw_basket,
            "market_filter_portfolio_net_return_pct": filtered,
            "nifty500_tri_return_pct": benchmark_return,
            "niftybees_signal_close": b_close_signal,
            "niftybees_entry_open": b_open_entry,
            "niftybees_overnight_pct": (b_open_entry / b_close_signal - 1) * 100 if b_close_signal and b_open_entry else None,
            "nifty500_tri_entry_aligned_return_pct": aligned_return,
            "niftybees_entry_to_exit_net_return_pct": bees_net_return,
            "market_filter_outperformed_tri": (
                filtered > comparator if filtered is not None and comparator is not None else None
            ),
            "raw_outperformed_tri": (
                raw_basket > comparator if raw_basket is not None and comparator is not None else None
            ),
            "raw_top20_close_to_close_net_return_pct": raw_cc,
            "market_filter_close_to_close_net_return_pct": filtered_cc,
            "raw_cc_outperformed_tri": raw_cc > benchmark_return if raw_cc is not None and benchmark_return is not None else None,
            "market_filter_cc_outperformed_tri": (
                filtered_cc > benchmark_return if filtered_cc is not None and benchmark_return is not None else None),
            "overnight_execution_effect_pct": (raw_basket - raw_cc) if raw_basket is not None and raw_cc is not None else None,
            "available_stocks": len(got),
            "excluded_unsupported_action": sum(
                row[f"{label}_return_status"] == "unsupported_corporate_action_during_hold" for row in stock_rows),
            "excluded_missing_price": sum(
                row[f"{label}_return_status"] == "missing_entry_or_exit_price" for row in stock_rows),
            "raw_top20_available_mean_net_return_pct": available_mean,
            "missing_tickers": ",".join(
                row["ticker"] + ":" + row[f"{label}_return_status"]
                for row in stock_rows if row[f"{label}_net_return_pct"] is None
            ),
        })
    return stock_rows, returns

def markdown_table(frame):
    """Render a small dependency-free Markdown table."""
    if frame.empty:
        return "_No rows._"
    columns = list(frame.columns)
    rows = frame.astype("object").where(pd.notna(frame), "").astype(str).values.tolist()
    def clean(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    header = "| " + " | ".join(clean(x) for x in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(clean(x) for x in row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def max_feasible_samples(n_sessions, min_gap):
    """Most dates that can be spaced at least min_gap sessions apart inside n_sessions consecutive sessions."""
    return 0 if n_sessions <= 0 else int((n_sessions - 1) // min_gap + 1)


def choose_sample_positions(eligible_positions, sample_count=5, seed=DEFAULT_SEED, min_gap=127):
    """Randomly sample dates while keeping 6-month forward windows non-overlapping."""
    candidates = np.asarray(eligible_positions, dtype=int).copy()
    np.random.default_rng(seed).shuffle(candidates)
    selected = []
    for position in candidates:
        if all(abs(int(position) - prior) >= min_gap for prior in selected):
            selected.append(int(position))
        if len(selected) == sample_count:
            break
    if len(selected) != sample_count:
        raise ValueError(
            f"Could not choose {sample_count} dates with a minimum {min_gap}-session gap: "
            f"{len(candidates)} candidate sessions fit at most {max_feasible_samples(len(candidates), min_gap)} such dates. "
            "Use a smaller --min-gap (overlapping holding windows; summarise with the block bootstrap) or fewer samples."
        )
    return np.asarray(sorted(selected), dtype=int)


def run_simulation(seed=DEFAULT_SEED, sample_count=5, outdir="point-in-time-simulation", min_gap=127, selection_order="liquidity_first"):
    from tejhq_data import get_dataset_revision

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    membership = load_membership_calendar()
    symbols = sorted(set(membership["symbol"].astype(str).str.upper()))
    revision = get_dataset_revision()
    print(f"Loading {len(symbols)} PIT symbols from TejHQ revision {revision} ...")
    tickers = [f"{symbol}.NS" for symbol in symbols] + ["NIFTYBEES.NS"]
    frames, diagnostics = load_adjusted_frames(
        tickers, DATA_START, DATA_END, cache_dir="data_cache/tejhq_parquet",
        membership_df=membership, min_bars=1, revision=revision, include_raw=True,
    )
    actions = load_unsupported_actions(
        DATA_START, DATA_END, "data_cache/tejhq_actions", revision
    )
    # TRI is the official performance benchmark; NIFTYBEES is the established
    # relative-strength and market-regime series used by the strategy.
    tri = load_nifty500_tri_history(DATA_START, DATA_END)
    tri.index = pd.DatetimeIndex(tri.index).tz_localize(None)
    bees = frames.get("NIFTYBEES.NS")
    if bees is None or bees.empty:
        raise RuntimeError("TejHQ NIFTYBEES adjusted history unavailable")
    bees = bees.copy()
    bees.index = pd.DatetimeIndex(bees.index).tz_localize(None)
    calendar = pd.DatetimeIndex(tri.index.intersection(bees.index)).sort_values()
    bees = bees.loc[calendar].copy()
    # Preserve pre-COVID lookback history while restricting signal dates to post-COVID.
    post_covid_position = int(calendar.searchsorted(pd.Timestamp(POST_COVID_START)))
    # Six-month follow-up must be observable for every sampled point.
    eligible_positions = np.arange(post_covid_position, len(calendar) - 126)
    if len(eligible_positions) < sample_count:
        raise RuntimeError("Not enough post-COVID sessions with full 6-month forward coverage")
    selected_positions = choose_sample_positions(eligible_positions, sample_count, seed, min_gap)
    samples, stock_results, return_results = [], [], []
    for number, position in enumerate(selected_positions, 1):
        as_of = calendar[position]
        members = active_symbols(membership, as_of)
        snapshot = score_snapshot(as_of, members, frames, bees, actions, selection_order)
        snapshot["signal_date"] = as_of
        sample_id = f"S{number}"
        samples.append({
            "sample_id": sample_id, "signal_date": as_of.date().isoformat(),
            "market_regime": snapshot["market_regime"],
            "active_pit_members": len(members), "eligible_after_data_and_trend": snapshot["eligible_count"],
            "liquid_top200_count": snapshot["ranked_count"],
            "selection_order": selection_order, "pit_liquidity_pool": snapshot["pool_size"], "liquid_and_eligible": snapshot["ranked_count"],
            "selected_top20_count": len(snapshot["ranked"]),
            "unsupported_action_events_known": int((actions["ex_date"].le(as_of) & actions["symbol"].isin(members)).sum()) if not actions.empty else 0,
        })
        stock_rows, return_rows = simulate_sample(snapshot, calendar, frames, tri, sample_id, actions, bees)
        stock_results.extend(stock_rows)
        return_results.extend(return_rows)
        print(f"{sample_id}: {as_of.date()} regime={snapshot['market_regime']} "
              f"members={len(members)} candidates={len(snapshot['ranked'])}")

    pd.DataFrame(samples).to_csv(out / "sample_dates.csv", index=False)
    pd.DataFrame(stock_results).to_csv(out / "selected_stocks_and_outcomes.csv", index=False)
    pd.DataFrame(return_results).to_csv(out / "portfolio_returns.csv", index=False)
    from pit_summary import json_safe, summarize_returns
    summary_md, summary = summarize_returns(pd.DataFrame(return_results), pd.DataFrame(stock_results), min_gap, HORIZONS)
    (out / "summary.md").write_text(summary_md + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(json_safe(summary), indent=2, allow_nan=False), encoding="utf-8")
    report = [
        "# Five-date point-in-time momentum simulation", "",
        f"- Random seed: {seed}; minimum 127-session spacing between sampled dates to avoid overlapping 6-month holding windows",
        f"- Sampling window: {POST_COVID_START} through dates with a full 126-session follow-up",
        "- Universe: actual NIFTY 500 members on each signal date",
        f"- Selection order: {selection_order} ('liquidity_first' = engine/live order: top 200 by 126-session traded value among ALL point-in-time members, then 253-session validity, 200-DMA and 12-1 ranking; 'trend_first' = the original five-date run's order)",
        f"- Sampling: minimum {min_gap}-session spacing; holding windows {'do not overlap at the 6M horizon' if min_gap >= 127 else 'OVERLAP at the longer horizons, so samples are not independent (see summary.md)'}",
        "- Momentum benchmark / market regime: TejHQ adjusted NIFTYBEES history; performance benchmark: official NIFTY 500 TRI",
        "- Entry: next exchange session adjusted open; exits: adjusted close after 21, 63 and 126 exchange sessions",
        f"- Costs: {ROUND_TRIP_COST * 100:.2f}% round-trip, applied symmetrically to entry and exit",
        "- Unsupported corporate actions: only events with ex-dates on or before each signal date reset that symbol's lookback; future events do not affect ranking, but an unsupported event during a holding window invalidates that stock's return for the affected horizon",
        "- Missing selected-stock entry/exit prices or unsupported corporate actions during a holding window: basket return marked incomplete; no survivor reweighting",
        "- Market filter: raw top-20 basket shown for diagnosis; investable portfolio is 100% cash when NIFTYBEES is at/below its 200-DMA",
        "- Benchmarks and windows: the TRI is measured signal-date close to exit close. The LIKE-FOR-LIKE stock basket is therefore also measured signal close to exit close (raw_top20_close_to_close_*), after the same 0.30% cost. The as-traded basket (buy at the next open) differs from it by the overnight gap (overnight_execution_effect_pct). nifty500_tri_entry_aligned_* (TRI moved by NIFTYBEES' overnight change) is kept as a DIAGNOSTIC only: a single ETF opening print proved unreliable (e.g. +3.3% on 2021-09-09 while all 20 selected stocks gapped between -1.3% and +2.0%)",
        "- Baskets: empty slots (fewer than 20 qualifiers) are cash at 0%; a basket with any missing/invalid selected-stock return is marked incomplete and excluded from summaries (raw_top20_available_mean_* silently reweights and is diagnostic only)",
        "",
        "## Sample dates", "",
        markdown_table(pd.DataFrame(samples)), "",
        "## Selected stocks", "",
        markdown_table(pd.DataFrame(stock_results)[[
            "sample_id", "signal_date", "ticker", "leader_rank", "momentum_12_1_pct",
            "close_on_signal", "avg_traded_value_126d", "1M_net_return_pct", "3M_net_return_pct", "6M_net_return_pct",
            "1M_return_status", "3M_return_status", "6M_return_status",
        ]]), "",
        "## Returns", "",
        markdown_table(pd.DataFrame(return_results)), "",
        summary_md, "",
        "## Interpretation notes", "",
        "Five observations are diagnostic case studies, not statistically sufficient evidence of strategy edge. Inspect the full stock-level file, including missing-price flags, before drawing conclusions.",
        "The price provider does not fully adjust mergers, demergers, rights issues or buybacks. The simulation applies a point-in-time 253-session reset after the latest such event known at each signal date.",
    ]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (out / "run_metadata.json").write_text(json.dumps({
        "seed": seed, "sample_count": sample_count, "dataset_revision": revision,
        "data_start": DATA_START, "data_end": DATA_END,
        "sample_window_start": POST_COVID_START,
        "min_gap": min_gap, "selection_order": selection_order,
        "benchmark": "official NIFTY 500 TRI (entry-aligned via NIFTYBEES overnight change)",
        "selection_benchmark": "TejHQ adjusted NIFTYBEES",
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Reports written to {out.resolve()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--outdir", default="point-in-time-simulation")
    parser.add_argument("--min-gap", type=int, default=127, help="minimum sessions between sampled dates (127 = non-overlapping 6M windows)")
    parser.add_argument("--selection-order", choices=["liquidity_first", "trend_first"], default="liquidity_first")
    args = parser.parse_args()
    run_simulation(args.seed, args.samples, args.outdir, args.min_gap, args.selection_order)


if __name__ == "__main__":
    main()
