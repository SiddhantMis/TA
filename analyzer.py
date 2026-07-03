"""
EOD Technical Screener

Fetches daily OHLCV via yfinance, computes indicators + candlestick
patterns per the Zerodha Varsity Module 2 definitions, and applies a
checklist-based scoring function (mirrors Trade_Evaluation_Sheet.xlsx
sections 1-5) to flag candidates worth a manual look.

IMPORTANT — what has and hasn't been verified:
yfinance needs open internet access to Yahoo's finance endpoints. The
sandbox this was built in does NOT have that access (restricted to
package registries), so the live data fetch path has NOT been run
against real data. Pattern-detection math HAS been verified against
synthetic + real historical OHLC (see test_patterns.py, which runs
with zero network access and passes). Test fetch_ticker()/run_screen()
for real inside GitHub Actions or locally before trusting the schedule.

What this does NOT do: decide entries, set stops, or size positions.
Sections 6-9 of the checklist (risk:reward, position size, time stop)
are trade-specific and still need to be done by hand once a ticker is
flagged. This narrows 100+ tickers to a handful worth that manual work
— it doesn't replace it.
"""

from __future__ import annotations
import json
import sys
import time
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None  # lets test_patterns.py import this module without yfinance installed


# ---------------------------------------------------------------------------
# Config — edit WATCHLIST to grow/shrink coverage. No other code changes
# needed to scale from 10 tickers to 100+. Watch YF_SLEEP_SECONDS if you
# do scale up — yfinance rate-limits, this hasn't been stress-tested past
# a small list.
# ---------------------------------------------------------------------------

WATCHLIST = [
    "ETERNAL.NS", "DLF.NS", "IEX.NS", "UTTAMSUGAR.NS",
    "IDFCFIRSTB.NS", "BANDHANBNK.NS", "CENTRALBK.NS",
    "HDFCBANK.NS", "TITAN.NS", "MCX.NS", "BSE.NS",
]

LOOKBACK_DAYS = 120
SR_WINDOW = 20
SUPPORT_PROXIMITY_PCT = 0.02
VOLUME_MA_WINDOW = 20
RSI_WINDOW = 14
EMA_SHORT = 20
SMA_MED = 50
TREND_WINDOW = 15
YF_SLEEP_SECONDS = 1.5


# ---------------------------------------------------------------------------
# Indicators — same formulas as TA_Notes.md Ch.12/13
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"] = df["Close"].ewm(span=EMA_SHORT, adjust=False).mean()
    df["sma50"] = df["Close"].rolling(SMA_MED).mean()
    df["vol_ma20"] = df["Volume"].rolling(VOLUME_MA_WINDOW).mean()

    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(RSI_WINDOW).mean()
    avg_loss = loss.rolling(RSI_WINDOW).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi14"] = 100 - (100 / (1 + rs))

    df["support"] = df["Low"].rolling(SR_WINDOW).min()
    df["resistance"] = df["High"].rolling(SR_WINDOW).max()
    return df


# ---------------------------------------------------------------------------
# Candlestick patterns — pure OHLC math, same checks done by hand on
# HDFCBANK/ETERNAL/MCX earlier this week. Thresholds are approximations
# (Ch.4 Rule 2: "be flexible, quantify") — not a substitute for eyeballing
# a flagged candle before acting on it.
# ---------------------------------------------------------------------------

def _body(row) -> float:
    return abs(row["Close"] - row["Open"])

def _upper_wick(row) -> float:
    return row["High"] - max(row["Open"], row["Close"])

def _lower_wick(row) -> float:
    return min(row["Open"], row["Close"]) - row["Low"]

def _bullish(row) -> bool:
    return row["Close"] > row["Open"]

def _bearish(row) -> bool:
    return row["Close"] < row["Open"]


def classify_single(row) -> Optional[str]:
    rng = row["High"] - row["Low"]
    if rng <= 0:
        return None
    b = _body(row)
    uw = _upper_wick(row)
    lw = _lower_wick(row)

    if b / rng > 0.85:
        return "bullish_marubozu" if _bullish(row) else "bearish_marubozu"

    if b / rng < 0.10:
        wick_ratio = max(uw, lw) / (min(uw, lw) + 1e-9)
        if wick_ratio < 2.0:
            return "doji"

    if b > 0 and lw >= 2 * b and uw <= 0.5 * lw:
        return "hammer_or_hanging_man"   # direction resolved by prior trend in score_ticker()
    if b > 0 and uw >= 2 * b and lw <= 0.5 * uw:
        return "shooting_star_or_inverted_hammer"

    if b / rng < 0.35:
        return "spinning_top"
    return None


def classify_two_candle(prev, curr) -> Optional[str]:
    if _bearish(prev) and _bullish(curr):
        if curr["Open"] <= prev["Close"] and curr["Close"] >= prev["Open"]:
            return "bullish_engulfing"
        midpoint = (prev["Open"] + prev["Close"]) / 2
        if curr["Open"] < prev["Low"] and curr["Close"] > midpoint:
            return "piercing_pattern"

    if _bullish(prev) and _bearish(curr):
        if curr["Open"] >= prev["Close"] and curr["Close"] <= prev["Open"]:
            return "bearish_engulfing"
        midpoint = (prev["Open"] + prev["Close"]) / 2
        if curr["Open"] > prev["High"] and curr["Close"] < midpoint:
            return "dark_cloud_cover"

    return None


def trend_direction(df: pd.DataFrame, idx: int, window: int = TREND_WINDOW) -> str:
    """Rule 3: higher-highs/higher-lows vs lower-highs/lower-lows over the
    window immediately before idx (not including idx itself)."""
    if idx < window:
        return "insufficient_data"
    seg = df.iloc[idx - window: idx]
    highs = seg["High"].values
    up = sum(highs[i] > highs[i - 1] for i in range(1, len(highs)))
    down = sum(highs[i] < highs[i - 1] for i in range(1, len(highs)))
    if up > down * 1.3:
        return "uptrend"
    if down > up * 1.3:
        return "downtrend"
    return "choppy"


# ---------------------------------------------------------------------------
# Checklist scoring — mirrors Trade_Evaluation_Sheet.xlsx sections 1-5.
# Sections 6-9 (R:R, position size, time stop, post-trade log) are
# deliberately NOT here — those need an entry/stop you set by hand.
# ---------------------------------------------------------------------------

@dataclass
class ScreenResult:
    ticker: str
    date: str
    close: float
    trend: str
    pattern: Optional[str]
    pattern_matches_trend: bool
    near_support: bool
    support_level: Optional[float]
    resistance_level: Optional[float]
    volume_ratio: Optional[float]
    above_ema20: bool
    above_sma50: bool
    rsi: Optional[float]
    checks_passed: int
    checks_total: int
    flag: bool


def score_ticker(df: pd.DataFrame, ticker: str) -> Optional[ScreenResult]:
    df = compute_indicators(df)
    if len(df) < max(SMA_MED, TREND_WINDOW) + 2:
        return None

    idx = len(df) - 1
    curr = df.iloc[idx]
    prev = df.iloc[idx - 1]

    trend = trend_direction(df, idx)

    pattern = classify_two_candle(prev, curr) or classify_single(curr)

    pattern_ok = False
    if pattern in ("bullish_engulfing", "piercing_pattern", "bullish_marubozu"):
        pattern_ok = trend in ("downtrend", "choppy")
    elif pattern == "hammer_or_hanging_man":
        pattern_ok = trend == "downtrend"  # Hanging Man (uptrend case) is a warning, not a signal here

    support = curr["support"]
    resistance = curr["resistance"]
    near_support = bool(
        not np.isnan(support) and support > 0 and
        abs(curr["Close"] - support) / support <= SUPPORT_PROXIMITY_PCT
    )

    vol_ratio = (
        curr["Volume"] / curr["vol_ma20"]
        if curr["vol_ma20"] and not np.isnan(curr["vol_ma20"]) else np.nan
    )
    volume_ok = not np.isnan(vol_ratio) and vol_ratio >= 1.0

    above_ema20 = bool(curr["Close"] > curr["ema20"])
    above_sma50 = bool(curr["Close"] > curr["sma50"]) if not np.isnan(curr["sma50"]) else False

    checks = [
        trend in ("uptrend", "downtrend"),   # 1. defined trend, not choppy
        bool(pattern) and pattern_ok,        # 2. pattern present, matches context
        near_support,                        # 3. near a defined S/R zone
        volume_ok,                           # 4. volume confirms
        above_ema20 and above_sma50,         # 5. MA alignment
    ]
    passed = sum(checks)

    return ScreenResult(
        ticker=ticker,
        date=str(curr.name.date()) if hasattr(curr.name, "date") else str(curr.name),
        close=round(float(curr["Close"]), 2),
        trend=trend,
        pattern=pattern,
        pattern_matches_trend=pattern_ok,
        near_support=near_support,
        support_level=round(float(support), 2) if not np.isnan(support) else None,
        resistance_level=round(float(resistance), 2) if not np.isnan(resistance) else None,
        volume_ratio=round(float(vol_ratio), 2) if not np.isnan(vol_ratio) else None,
        above_ema20=above_ema20,
        above_sma50=above_sma50,
        rsi=round(float(curr["rsi14"]), 2) if not np.isnan(curr["rsi14"]) else None,
        checks_passed=passed,
        checks_total=len(checks),
        flag=passed >= 4,  # 4-of-5 threshold; R:R and sizing still manual
    )


def _flatten_columns(data: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """yfinance sometimes returns MultiIndex columns even for a single
    ticker, and the level order (field-first vs ticker-first) isn't
    consistent across versions. Flatten to plain Open/High/Low/Close/
    Volume columns regardless of which layout came back."""
    if not isinstance(data.columns, pd.MultiIndex):
        return data
    lvl0 = set(data.columns.get_level_values(0))
    if ticker in lvl0:
        return data.xs(ticker, axis=1, level=0)
    return data.droplevel(1, axis=1)


def fetch_ticker(ticker: str) -> Optional[pd.DataFrame]:
    if yf is None:
        raise RuntimeError("yfinance not installed — pip install yfinance")
    data = yf.download(ticker, period=f"{LOOKBACK_DAYS}d", interval="1d", progress=False)
    if data.empty:
        return None
    data = _flatten_columns(data, ticker)
    data = data.rename(columns=str.title)
    return data


def run_screen(watchlist: list[str] = WATCHLIST) -> list[dict]:
    results = []
    for t in watchlist:
        try:
            df = fetch_ticker(t)
            if df is None or df.empty:
                print(f"[skip] no data for {t}", file=sys.stderr)
                continue
            r = score_ticker(df, t)
            if r:
                results.append(asdict(r))
        except Exception as e:
            print(f"[error] {t}: {e}", file=sys.stderr)
        time.sleep(YF_SLEEP_SECONDS)
    return results


if __name__ == "__main__":
    out = run_screen()
    flagged = [r for r in out if r["flag"]]
    print(json.dumps({"all": out, "flagged": flagged}, indent=2, default=str))
