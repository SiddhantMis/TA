"""
Relative Strength & Market Leader Ranking Engine (relative_strength.py)

Ranks stocks by Relative Strength (RS) against the benchmark index (NIFTY 50 / ^NSEI / NIFTYBEES.NS):
1. Composite RS Momentum (3m, 6m, 12-1m weighted performance)
2. RS Line = Stock Close / Benchmark Close
3. RS Trend = RS Line > 50-EMA of RS Line
4. RS New High = RS Line within 2% of 3-month high
5. Market Leader Classification = Top 20% percentile + Bullish RS Trend
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd


@dataclass
class RSProfile:
    ticker: str
    rs_score: float                # Weighted momentum score
    rs_percentile: float           # 0 to 100 relative to universe
    rs_trend: str                  # "bullish", "neutral", "bearish"
    rs_new_high: bool              # True if RS line near 60-day high
    outperforming_index: bool      # True if beating benchmark over 3M
    is_leader: bool                # Top decile/quintile + bullish trend
    rank: int                      # Rank in universe (1 = strongest)
    summary: str


def compute_stock_momentum(df: pd.DataFrame, idx: Optional[int] = None) -> float:
    """Computes composite momentum score using 3M, 6M, and 12-1M returns.
    Weights: 40% 63d (3m), 30% 126d (6m), 30% 252-21d (12-1m skip reversal).
    """
    if idx is None:
        idx = len(df) - 1
    if idx < 63 or df.empty:
        return 0.0

    closes = df["Close"].values.astype(float)
    c_now = closes[idx]
    if np.isnan(c_now) or c_now <= 0:
        return 0.0

    # 3-month (63 trading days)
    r_3m = (c_now / closes[idx - 63] - 1.0) if idx >= 63 and closes[idx - 63] > 0 else 0.0

    # 6-month (126 trading days)
    r_6m = (c_now / closes[idx - 126] - 1.0) if idx >= 126 and closes[idx - 126] > 0 else r_3m

    # 12-1 month (252 bars ago to 21 bars ago)
    if idx >= 252 and closes[idx - 252] > 0 and closes[idx - 21] > 0:
        r_12_1m = closes[idx - 21] / closes[idx - 252] - 1.0
    else:
        r_12_1m = r_6m

    score = (0.40 * r_3m) + (0.30 * r_6m) + (0.30 * r_12_1m)
    return float(score)


def compute_rs_line_metrics(stock_df: pd.DataFrame, benchmark_df: pd.DataFrame, idx: Optional[int] = None) -> dict:
    """Computes RS line = Stock Close / Benchmark Close and evaluates its trend and highs."""
    if idx is None:
        idx = len(stock_df) - 1

    common_dates = stock_df.index[:idx + 1].intersection(benchmark_df.index)
    if len(common_dates) < 30:
        return {
            "rs_trend": "neutral",
            "rs_new_high": False,
            "outperforming_index": False,
            "rs_line_slope": 0.0,
        }

    s_close = stock_df.loc[common_dates, "Close"].values.astype(float)
    b_close = benchmark_df.loc[common_dates, "Close"].values.astype(float)

    # Avoid div by zero
    valid = (b_close > 0) & np.isfinite(s_close) & np.isfinite(b_close)
    if valid.sum() < 30:
        return {
            "rs_trend": "neutral",
            "rs_new_high": False,
            "outperforming_index": False,
            "rs_line_slope": 0.0,
        }

    rs_line = s_close[valid] / b_close[valid]
    n = len(rs_line)

    # 50-EMA of RS line
    ema_span = min(50, n)
    rs_series = pd.Series(rs_line)
    rs_ema = rs_series.ewm(span=ema_span, adjust=False).mean().values

    curr_rs = rs_line[-1]
    curr_ema = rs_ema[-1]

    # Trend
    if curr_rs > curr_ema * 1.01:
        rs_trend = "bullish"
    elif curr_rs < curr_ema * 0.99:
        rs_trend = "bearish"
    else:
        rs_trend = "neutral"

    # New High check over past 60 bars
    lookback_high = min(60, n)
    max_recent_rs = np.max(rs_line[-lookback_high:])
    rs_new_high = bool(curr_rs >= max_recent_rs * 0.985)

    # 3-month performance comparison
    lookback_3m = min(63, n - 1)
    s_ret_3m = s_close[-1] / s_close[-lookback_3m] - 1.0
    b_ret_3m = b_close[-1] / b_close[-lookback_3m] - 1.0
    outperforming = bool(s_ret_3m > b_ret_3m)

    # RS Line Slope over last 15 bars
    slope_window = min(15, n)
    y = rs_line[-slope_window:]
    x = np.arange(len(y))
    slope, _ = np.polyfit(x, y, 1)
    norm_slope = float(slope / np.mean(y)) if np.mean(y) > 0 else 0.0

    return {
        "rs_trend": rs_trend,
        "rs_new_high": rs_new_high,
        "outperforming_index": outperforming,
        "rs_line_slope": norm_slope,
    }


def rank_universe(
    universe_dfs: dict[str, pd.DataFrame],
    benchmark_df: Optional[pd.DataFrame] = None,
) -> dict[str, RSProfile]:
    """Ranks all tickers in universe by Relative Strength and returns RSProfile per ticker."""
    scores: list[tuple[str, float]] = []
    for ticker, df in universe_dfs.items():
        if df is None or len(df) < 50:
            continue
        score = compute_stock_momentum(df)
        scores.append((ticker, score))

    if not scores:
        return {}

    # Sort descending by momentum score
    scores.sort(key=lambda x: x[1], reverse=True)
    n_stocks = len(scores)

    profiles: dict[str, RSProfile] = {}
    for rank_idx, (ticker, score) in enumerate(scores):
        rank = rank_idx + 1
        percentile = round(100.0 * (n_stocks - rank) / max(1, n_stocks - 1), 1)

        # RS line metrics if benchmark available
        if benchmark_df is not None and not benchmark_df.empty:
            df = universe_dfs[ticker]
            metrics = compute_rs_line_metrics(df, benchmark_df)
        else:
            metrics = {
                "rs_trend": "bullish" if percentile >= 70 else ("bearish" if percentile <= 30 else "neutral"),
                "rs_new_high": percentile >= 85,
                "outperforming_index": percentile >= 50,
                "rs_line_slope": 0.0,
            }

        is_leader = bool(percentile >= 80 and metrics["rs_trend"] != "bearish")

        if is_leader:
            status = "Market Leader (Top 20%)"
        elif percentile >= 60:
            status = "Outperformer"
        elif percentile <= 30:
            status = "Laggard"
        else:
            status = "Neutral"

        summary = f"Rank #{rank}/{n_stocks} ({percentile}th %ile) | {status} | RS Trend: {metrics['rs_trend'].title()}"

        profiles[ticker] = RSProfile(
            ticker=ticker,
            rs_score=round(score * 100, 2),
            rs_percentile=percentile,
            rs_trend=metrics["rs_trend"],
            rs_new_high=metrics["rs_new_high"],
            outperforming_index=metrics["outperforming_index"],
            is_leader=is_leader,
            rank=rank,
            summary=summary,
        )

    return profiles
