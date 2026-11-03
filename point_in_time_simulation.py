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

from nifty500_pit import load_membership_calendar, normalise_symbol
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


def score_snapshot(as_of, symbols, frames, benchmark, actions):
    """Return the ranked top-20 and diagnostics using data known on as_of only."""
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

    rows, excluded = [], []
    for symbol in symbols:
        ticker = f"{symbol}.NS"
        frame = frames.get(ticker)
        if frame is None or frame.empty:
            excluded.append({"symbol": symbol, "reason": "no_price_history"})
            continue
        event_date = action_dates.get(symbol)
        if event_date is not None:
            frame = frame.loc[pd.DatetimeIndex(frame.index).tz_localize(None) >= event_date]
        close = _series(frame, "Close", sessions)
        volume = _series(frame, "Volume", sessions)
        open_ = _series(frame, "Open", sessions)
        high = _series(frame, "High", sessions)
        if close.isna().any() or volume.isna().any() or (close <= 0).any():
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
        traded_value = close * volume
        avg_traded_value = float(traded_value.iloc[-126:].mean())
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

    # Existing model: rank by 126-session average traded value, retain the liquid
    # top 200, then rank those above their 200-DMA by 12-1 relative strength.
    rows.sort(key=lambda row: (-row["avg_traded_value_126d"], row["ticker"]))
    liquid = rows[:LIQUID_TOP]
    liquid.sort(key=lambda row: (-row["momentum_12_1_pct"], row["ticker"]))
    for rank, row in enumerate(liquid, 1):
        row["leader_rank"] = rank
        row["liquidity_rank"] = 1 + next(
            i for i, candidate in enumerate(rows) if candidate["ticker"] == row["ticker"]
        )
    selected = liquid[:PORTFOLIO_SIZE]
    return {
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


def simulate_sample(snapshot, calendar, frames, tri, sample_id):
    signal_date = snapshot["signal_date"]
    pos = calendar.get_loc(signal_date)
    entry_pos = pos + 1
    entry_date = calendar[entry_pos]
    picks = snapshot["ranked"]
    stock_rows, returns = [], []
    for pick in picks:
        ticker = pick["ticker"]
        entry = _price_at(frames, ticker, "Open", entry_date)
        row = {
            "sample_id": sample_id, "signal_date": signal_date.date().isoformat(),
            "entry_date": entry_date.date().isoformat(), **pick,
            "entry_open": entry,
        }
        for label, offset in HORIZONS.items():
            exit_pos = entry_pos + offset - 1
            exit_date = calendar[exit_pos]
            exit_close = _price_at(frames, ticker, "Close", exit_date)
            row[f"{label}_exit_date"] = exit_date.date().isoformat()
            row[f"{label}_exit_close"] = exit_close
            row[f"{label}_gross_return_pct"] = (
                (exit_close / entry - 1) * 100 if entry and exit_close else None
            )
            if entry and exit_close:
                net_factor = (exit_close / entry) * (1 - ROUND_TRIP_COST / 2) / (1 + ROUND_TRIP_COST / 2)
                row[f"{label}_net_return_pct"] = (net_factor - 1) * 100
            else:
                row[f"{label}_net_return_pct"] = None
        stock_rows.append(row)

    for label, offset in HORIZONS.items():
        exit_date = calendar[entry_pos + offset - 1]
        try:
            benchmark_return = (
                float(tri.at[exit_date, "Close"]) / float(tri.at[signal_date, "Close"]) - 1
            ) * 100
        except (KeyError, TypeError, ValueError):
            benchmark_return = None
        vals = [row[f"{label}_net_return_pct"] for row in stock_rows]
        complete = len(vals) == PORTFOLIO_SIZE and all(value is not None for value in vals)
        raw_basket = float(np.mean(vals)) if complete else None
        investable = raw_basket if snapshot["market_regime"] == "BULL" else 0.0
        returns.append({
            "sample_id": sample_id,
            "signal_date": signal_date.date().isoformat(),
            "market_regime": snapshot["market_regime"],
            "entry_date": entry_date.date().isoformat(),
            "horizon": label,
            "exit_date": exit_date.date().isoformat(),
            "selected_stocks": len(stock_rows),
            "complete_stock_prices": complete,
            "raw_top20_equal_weight_net_return_pct": raw_basket,
            "market_filter_portfolio_net_return_pct": investable if complete else None,
            "nifty500_tri_return_pct": benchmark_return,
            "market_filter_outperformed_tri": (
                investable > benchmark_return if complete and benchmark_return is not None else None
            ),
            "missing_tickers": ",".join(
                row["ticker"] for row in stock_rows if row[f"{label}_net_return_pct"] is None
            ),
        })
    return stock_rows, returns


def markdown_table(frame):
    """Render a small dependency-free Markdown table."""
    if frame.empty:
        return "_No rows._"
    columns = list(frame.columns)
    rows = frame.fillna("").astype(str).values.tolist()
    def clean(value):
        return str(value).replace("|", "\\|").replace("\\n", " ")
    header = "| " + " | ".join(clean(x) for x in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(clean(x) for x in row) + " |" for row in rows]
    return "\\n".join([header, divider, *body])


def run_simulation(seed=DEFAULT_SEED, sample_count=5, outdir="point-in-time-simulation"):
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
        membership_df=membership, min_bars=1, revision=revision,
    )
    actions = load_unsupported_actions(
        DATA_START, DATA_END, "data_cache/tejhq_actions", revision
    )
    # TRI is the official performance benchmark; NIFTYBEES is the established
    # relative-strength and market-regime series used by the strategy.
    tri = load_nifty500_tri_history(POST_COVID_START, DATA_END)
    tri.index = pd.DatetimeIndex(tri.index).tz_localize(None)
    bees = frames.get("NIFTYBEES.NS")
    if bees is None or bees.empty:
        raise RuntimeError("TejHQ NIFTYBEES adjusted history unavailable")
    bees = bees.copy()
    bees.index = pd.DatetimeIndex(bees.index).tz_localize(None)
    calendar = pd.DatetimeIndex(tri.index.intersection(bees.index)).sort_values()
    calendar = calendar[(calendar >= pd.Timestamp(POST_COVID_START))]
    # Six-month follow-up must be observable for every sampled point.
    eligible_positions = np.arange(253, len(calendar) - 126)
    if len(eligible_positions) < sample_count:
        raise RuntimeError("Not enough post-COVID sessions with full 6-month forward coverage")
    rng = np.random.default_rng(seed)
    selected_positions = np.sort(rng.choice(eligible_positions, size=sample_count, replace=False))
    samples, stock_results, return_results = [], [], []
    for number, position in enumerate(selected_positions, 1):
        as_of = calendar[position]
        members = active_symbols(membership, as_of)
        snapshot = score_snapshot(as_of, members, frames, bees, actions)
        snapshot["signal_date"] = as_of
        sample_id = f"S{number}"
        samples.append({
            "sample_id": sample_id, "signal_date": as_of.date().isoformat(),
            "market_regime": snapshot["market_regime"],
            "active_pit_members": len(members), "eligible_after_data_and_trend": snapshot["eligible_count"],
            "liquid_top200_count": snapshot["ranked_count"],
            "selected_top20_count": len(snapshot["ranked"]),
            "unsupported_action_events_known": int(actions["ex_date"].le(as_of).sum()) if not actions.empty else 0,
        })
        stock_rows, return_rows = simulate_sample(snapshot, calendar, frames, tri, sample_id)
        stock_results.extend(stock_rows)
        return_results.extend(return_rows)
        print(f"{sample_id}: {as_of.date()} regime={snapshot['market_regime']} "
              f"members={len(members)} candidates={len(snapshot['ranked'])}")

    pd.DataFrame(samples).to_csv(out / "sample_dates.csv", index=False)
    pd.DataFrame(stock_results).to_csv(out / "selected_stocks_and_outcomes.csv", index=False)
    pd.DataFrame(return_results).to_csv(out / "portfolio_returns.csv", index=False)
    report = [
        "# Five-date point-in-time momentum simulation", "",
        f"- Random seed: {seed}",
        f"- Sampling window: {POST_COVID_START} through dates with a full 126-session follow-up",
        "- Universe: actual NIFTY 500 members on each signal date",
        "- Ranking: top 200 by 126-session average traded value, then top 20 by 12–1 relative strength among stocks above their 200-DMA",
        "- Momentum benchmark / market regime: TejHQ adjusted NIFTYBEES history; performance benchmark: official NIFTY 500 TRI",
        "- Entry: next exchange session open; exits: 21, 63 and 126 exchange sessions after entry",
        f"- Costs: {ROUND_TRIP_COST * 100:.2f}% round-trip, applied symmetrically to entry and exit",
        "- Unsupported corporate actions: only events with ex-dates on or before each signal date reset that symbol's lookback; future events do not affect earlier samples",
        "- Missing selected-stock exit/entry prices: basket return marked incomplete; no survivor reweighting",
        "- Market filter: raw top-20 basket shown for diagnosis; investable portfolio is 100% cash when NIFTYBEES is at/below its 200-DMA",
        "- Benchmark comparison uses NIFTY 500 TRI close on signal date through each exit close; stock entries occur next-session open, so the benchmark window includes the signal-close-to-entry-open overnight interval",
        "",
        "## Sample dates", "",
        markdown_table(pd.DataFrame(samples)), "",
        "## Returns", "",
        markdown_table(pd.DataFrame(return_results)), "",
        "## Interpretation notes", "",
        "Five observations are diagnostic case studies, not statistically sufficient evidence of strategy edge. Inspect the full stock-level file, including missing-price flags, before drawing conclusions.",
        "The price provider does not fully adjust mergers, demergers, rights issues or buybacks. The simulation applies a point-in-time 253-session reset after the latest such event known at each signal date.",
    ]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (out / "run_metadata.json").write_text(json.dumps({
        "seed": seed, "sample_count": sample_count, "dataset_revision": revision,
        "data_start": DATA_START, "data_end": DATA_END,
        "sample_window_start": POST_COVID_START,
        "benchmark": "official NIFTY 500 TRI",
        "selection_benchmark": "TejHQ adjusted NIFTYBEES",
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Reports written to {out.resolve()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--outdir", default="point-in-time-simulation")
    args = parser.parse_args()
    run_simulation(args.seed, args.samples, args.outdir)


if __name__ == "__main__":
    main()
