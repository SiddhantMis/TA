#!/usr/bin/env python3
"""All-eligible PIT cross-sectional factor rank-IC on pinned TejHQ data."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

import pattern_lab as PL
from corporate_action_audit import UNSUPPORTED, action_quarantine_masks
from nifty500_pit import MEMBERSHIP_COVERAGE_THROUGH, build_membership_mask, load_membership_calendar
from tejhq_data import get_dataset_revision

PIN = "0303d8c95b4519765a9d5556fd9c2d430f8f81d8"
CACHE = "data_cache/tejhq_frames_10y_v2.pkl"
SAMPLE_DIR = Path("results/pit_samples/n40_gap21_seed20261103_rev0303d8c/liquidity_first")
SAMPLES = SAMPLE_DIR / "selected_stocks_and_outcomes.csv"
AUDIT = Path("results/corporate_action_audit.csv")
FACTORS = {
    "momentum_12_1": "12–1 momentum",
    "distance_above_200dma": "Distance above 200-DMA",
    "distance_from_52w_high": "Distance from 52-week high",
    "liquidity_126d": "126-day traded value",
}
HORIZONS = ("1M", "3M", "6M")


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    return ranks


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    rx, ry = average_ranks(x), average_ranks(y)
    if np.std(rx) == 0 or np.std(ry) == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def main() -> None:
    if get_dataset_revision() != PIN:
        raise RuntimeError("All-eligible IC must use the pinned TejHQ revision")
    membership = load_membership_calendar()
    end = pd.Timestamp(MEMBERSHIP_COVERAGE_THROUGH).normalize()
    start = end - pd.DateOffset(years=10)
    tickers = [f"{s}.NS" for s in sorted(membership["symbol"].unique())]
    frames, _ = PL.load_frames(
        tickers, 10, CACHE, False, min_bars=253, return_diagnostics=True,
        source="tejhq", membership_df=membership,
        start_date=start, end_date=end,
    )
    if not frames:
        raise RuntimeError("Pinned TejHQ frame cache returned no stock histories")

    action_audit = pd.read_csv(AUDIT, dtype={"symbol": str})
    action_audit["symbol"] = action_audit["symbol"].str.upper().str.strip()
    action_audit["type"] = action_audit["type"].str.lower().str.strip()
    action_audit["ex_date"] = pd.to_datetime(action_audit["ex_date"], errors="coerce").dt.normalize()
    for ticker, frame in frames.items():
        symbol = ticker.removesuffix(".NS")
        dates = action_audit.loc[
            action_audit["symbol"].eq(symbol) & action_audit["type"].isin(UNSUPPORTED),
            "ex_date",
        ].dropna().drop_duplicates().sort_values()
        frame.attrs["unsupported_action_dates"] = dates.dt.strftime("%Y-%m-%d").tolist()

    idx = pd.DatetimeIndex(sorted(set().union(*[set(pd.DatetimeIndex(f.index).normalize()) for f in frames.values()])))
    cols = sorted(frames)
    close = pd.concat({t: frames[t]["Close"].set_axis(pd.DatetimeIndex(frames[t].index).normalize()) for t in cols}, axis=1).reindex(idx)
    open_ = pd.concat({t: frames[t]["Open"].set_axis(pd.DatetimeIndex(frames[t].index).normalize()) for t in cols}, axis=1).reindex(idx)
    turnover = pd.concat({t: frames[t]["Turnover"].set_axis(pd.DatetimeIndex(frames[t].index).normalize()) for t in cols}, axis=1).reindex(idx)
    pit = build_membership_mask(idx, cols, membership)
    sma200 = close.rolling(200, min_periods=200).mean()
    high52 = close.rolling(252, min_periods=200).max()
    momentum = close.shift(21) / close.shift(252) - 1.0
    distance200 = close / sma200 - 1.0
    distance52 = close / high52 - 1.0
    liquidity = turnover.rolling(126, min_periods=100).mean()
    observed253 = close.notna().rolling(253, min_periods=253).sum().eq(253)
    liquid_top200 = liquidity.where(pit).rank(axis=1, ascending=False, method="first").le(200)
    action_ok, _ = action_quarantine_masks(idx, frames)
    eligible = (
        close.notna() & observed253 & sma200.notna() & momentum.notna()
        & pit & liquid_top200 & (close > sma200) & action_ok
    )
    factor_matrices = {
        "momentum_12_1": momentum,
        "distance_above_200dma": distance200,
        "distance_from_52w_high": distance52,
        "liquidity_126d": liquidity,
    }
    event_dates = {
        t: pd.DatetimeIndex(pd.to_datetime(frames[t].attrs.get("unsupported_action_dates", []))).normalize()
        for t in cols
    }

    sample_rows = pd.read_csv(SAMPLES, dtype={"sample_id": str})
    sample_dates = sample_rows[["sample_id", "signal_date"]].drop_duplicates().sort_values("signal_date")
    rows_out = []
    for sample in sample_dates.itertuples(index=False):
        signal = pd.Timestamp(sample.signal_date).normalize()
        if signal not in idx:
            raise RuntimeError(f"Sample signal date {signal.date()} is absent from the pinned price calendar")
        pos = idx.get_loc(signal)
        eligible_names = eligible.iloc[pos]
        eligible_tickers = eligible_names.index[eligible_names].tolist()
        sample_selected = sample_rows.loc[sample_rows["sample_id"].eq(sample.sample_id)]
        for horizon in HORIZONS:
            exit_dates = pd.to_datetime(sample_selected[f"{horizon}_exit_date"], errors="coerce").dropna().unique()
            if len(exit_dates) != 1:
                raise RuntimeError(f"{sample.sample_id}/{horizon}: expected one common sample exit date")
            exit_date = pd.Timestamp(exit_dates[0]).normalize()
            entry_dates = pd.to_datetime(sample_selected["entry_date"], errors="coerce").dropna().unique()
            if len(entry_dates) != 1:
                raise RuntimeError(f"{sample.sample_id}: expected one common next-session entry date")
            entry_date = pd.Timestamp(entry_dates[0]).normalize()
            if entry_date not in idx or exit_date not in idx:
                raise RuntimeError(f"{sample.sample_id}/{horizon}: entry/exit date missing from price calendar")
            returns: dict[str, float] = {}
            for ticker in eligible_tickers:
                if event_dates[ticker].size and ((event_dates[ticker] > signal) & (event_dates[ticker] <= exit_date)).any():
                    continue
                buy = open_.at[entry_date, ticker]
                sell = close.at[exit_date, ticker]
                if pd.notna(buy) and pd.notna(sell) and buy > 0 and sell > 0:
                    returns[ticker] = float(sell / buy - 1.0)
            for factor, matrix in factor_matrices.items():
                pairs = [
                    (float(matrix.at[signal, ticker]), returns[ticker])
                    for ticker in eligible_tickers
                    if ticker in returns and pd.notna(matrix.at[signal, ticker])
                ]
                x = np.array([p[0] for p in pairs], dtype=float)
                y = np.array([p[1] for p in pairs], dtype=float)
                rows_out.append({
                    "sample_id": sample.sample_id,
                    "signal_date": signal.date().isoformat(),
                    "horizon": horizon,
                    "factor": factor,
                    "eligible_n": len(eligible_tickers),
                    "return_valid_n": len(pairs),
                    "spearman_rank_ic": spearman(x, y),
                })

    detail = pd.DataFrame(rows_out)
    detail_path = SAMPLE_DIR / "all_eligible_factor_rank_ic.csv"
    detail.to_csv(detail_path, index=False, float_format="%.8f")
    summary = detail.groupby(["horizon", "factor"], sort=False).agg(
        sample_dates=("sample_id", "nunique"),
        mean_eligible_n=("eligible_n", "mean"),
        mean_return_valid_n=("return_valid_n", "mean"),
        mean_ic=("spearman_rank_ic", "mean"),
        median_ic=("spearman_rank_ic", "median"),
    ).reset_index()
    summary_path = SAMPLE_DIR / "all_eligible_factor_rank_ic_summary.csv"
    summary.to_csv(summary_path, index=False, float_format="%.8f")
    lines = [
        "# All-eligible cross-sectional factor rank-IC",
        "",
        f"TejHQ dataset revision: `{PIN}`",
        "Eligibility on each signal date: point-in-time NIFTY 500 membership, at least 253 observed sessions, "
        "top 200 by 126-session average raw traded value, adjusted close above its 200-DMA, and corporate-action "
        "quarantine eligibility. Factors are measured on the signal close. Forward returns use next-session adjusted "
        "open to the sample's fixed horizon exit close; a stock is omitted for a horizon if an unsupported corporate "
        "action occurs between signal and exit. This avoids outcome contamination without changing the signal-date universe.",
        "",
        "| Horizon | Factor | Sample dates | Mean eligible N | Mean valid-return N | Mean Spearman IC | Median Spearman IC |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in summary.itertuples(index=False):
        lines.append(
            f"| {r.horizon} | {FACTORS[r.factor]} | {r.sample_dates} | {r.mean_eligible_n:.1f} | "
            f"{r.mean_return_valid_n:.1f} | {r.mean_ic:+.4f} | {r.median_ic:+.4f} |"
        )
    lines.extend([
        "",
        "IC is computed cross-sectionally across all eligible stocks on each sample date, not only the selected top-20. "
        "The 40 signal dates are overlapping observations and are descriptive, not independent statistical trials.",
        "",
        "Per-date results: `all_eligible_factor_rank_ic.csv`; summary: `all_eligible_factor_rank_ic_summary.csv`.",
    ])
    (SAMPLE_DIR / "all_eligible_factor_rank_ic.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
