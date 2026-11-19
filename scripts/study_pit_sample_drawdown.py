#!/usr/bin/env python3
"""Reconstruct daily equal-weight basket paths and measure close-to-close drawdown.

Uses only the pinned TejHQ adjusted frames already cached by portfolio_rules.py.
A basket is included only when every selected holding has a valid horizon outcome;
incomplete corporate-action baskets are never reweighted.
"""
from __future__ import annotations

import csv
import json
import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

PIN = os.environ.get("TEJHQ_DATASET_REVISION", "").strip()
CACHE = Path("data_cache/tejhq_frames_10y_v2.pkl")
SAMPLE_DIR = Path("results/pit_samples/n40_gap21_seed20261103_rev0303d8c/liquidity_first")
INPUT = SAMPLE_DIR / "selected_stocks_and_outcomes.csv"


def load_frames():
    if not PIN or len(PIN) != 40:
        raise RuntimeError("TEJHQ_DATASET_REVISION must be pinned before drawdown reconstruction")
    if not CACHE.exists():
        raise FileNotFoundError(f"Expected cached TejHQ frames at {CACHE}")
    with CACHE.open("rb") as handle:
        frames = pickle.load(handle)
    if not isinstance(frames, dict):
        raise RuntimeError("TejHQ frame cache has an unexpected format")
    return frames


def main():
    frames = load_frames()
    samples: dict[str, list[dict[str, str]]] = {}
    with INPUT.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            samples.setdefault(row["sample_id"], []).append(row)

    output = []
    for horizon in ("1M", "3M", "6M"):
        for sample_id, rows in sorted(samples.items()):
            if not rows or any(row.get(f"{horizon}_return_status") != "ok" for row in rows):
                continue
            entry = pd.Timestamp(rows[0]["entry_date"]).normalize()
            exit_date = pd.Timestamp(rows[0][f"{horizon}_exit_date"]).normalize()
            series = {}
            entry_prices = {}
            missing = []
            for row in rows:
                ticker = row["ticker"]
                frame = frames.get(ticker)
                if frame is None or "Close" not in frame:
                    missing.append(ticker)
                    continue
                idx = pd.DatetimeIndex(pd.to_datetime(frame.index))
                if idx.tz is not None:
                    idx = idx.tz_localize(None)
                close = pd.Series(pd.to_numeric(frame["Close"], errors="coerce").to_numpy(), index=idx.normalize())
                close = close.loc[~close.index.duplicated(keep="last")].sort_index()
                close = close.loc[(close.index >= entry) & (close.index <= exit_date)]
                open_price = float(row["entry_open_adjusted"])
                if close.empty or entry not in close.index or exit_date not in close.index or not np.isfinite(open_price) or open_price <= 0:
                    missing.append(ticker)
                    continue
                series[ticker] = close
                entry_prices[ticker] = open_price
            if missing or len(series) != len(rows):
                raise RuntimeError(
                    f"{sample_id} {horizon}: cannot reconstruct all holdings from pinned cache; "
                    f"missing={sorted(set(missing))}"
                )

            dates = sorted(set().union(*(set(s.index) for s in series.values())))
            dates = pd.DatetimeIndex([d for d in dates if entry <= d <= exit_date])
            if entry not in dates or exit_date not in dates:
                raise RuntimeError(f"{sample_id} {horizon}: entry/exit session absent from price path")
            price_matrix = pd.DataFrame({ticker: s.reindex(dates).ffill() for ticker, s in series.items()})
            if price_matrix.isna().any().any() or not np.isfinite(price_matrix.to_numpy()).all():
                raise RuntimeError(f"{sample_id} {horizon}: non-finite daily mark in reconstructed basket")
            normalized = price_matrix.copy()
            for ticker in normalized.columns:
                normalized[ticker] = normalized[ticker] / entry_prices[ticker]
            equity = normalized.mean(axis=1)
            path = pd.concat([pd.Series([1.0], index=[entry - pd.Timedelta(days=1)]), equity])
            running_peak = path.cummax()
            drawdown = path / running_peak - 1.0
            trough_date = drawdown.idxmin()
            peak_date = path.loc[:trough_date].idxmax()
            output.append({
                "sample_id": sample_id,
                "horizon": horizon,
                "signal_date": rows[0]["signal_date"],
                "entry_date": entry.date().isoformat(),
                "exit_date": exit_date.date().isoformat(),
                "holdings": len(rows),
                "max_drawdown_pct": round(float(drawdown.min() * 100), 4),
                "peak_date": pd.Timestamp(peak_date).date().isoformat(),
                "trough_date": pd.Timestamp(trough_date).date().isoformat(),
                "daily_marks": len(equity),
            })

    result = pd.DataFrame(output)
    if result.empty:
        raise RuntimeError("No complete sample paths were reconstructed")
    result.to_csv(SAMPLE_DIR / "intra_window_drawdown.csv", index=False)
    lines = [
        "# Intra-window drawdown study",
        "",
        f"Dataset revision: `{PIN}`",
        "Method: equal-weight buy-and-hold basket from adjusted next-session entry open; daily adjusted close marks; "
        "missing daily closes are carried forward only for held-position valuation. No incomplete horizon basket is reweighted.",
        "",
        "| Horizon | Complete baskets | Mean max DD | Median max DD | Worst max DD |",
        "|---|---:|---:|---:|---:|",
    ]
    for horizon in ("1M", "3M", "6M"):
        group = result.loc[result["horizon"].eq(horizon), "max_drawdown_pct"]
        if group.empty:
            continue
        lines.append(
            f"| {horizon} | {len(group)} | {group.mean():.2f}% | "
            f"{group.median():.2f}% | {group.min():.2f}% |"
        )
    lines.extend(["", "Per-sample peak/trough dates and drawdowns are in `intra_window_drawdown.csv`."])
    (SAMPLE_DIR / "intra_window_drawdown.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
