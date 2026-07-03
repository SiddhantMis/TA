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

Scoring produces a `confidence` (0-100) and `recommendation` string per
ticker, not a bare pass/fail — see README "What flagged means" for the
5 weighted checks and known limits (long-only by construction, check-5
still correlated with check-1, S/R and trend logic untested on live
data as of this commit).
"""

from __future__ import annotations
import json
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

IST = ZoneInfo("Asia/Kolkata")

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
SR_WINDOW = 20                  # legacy rolling min/max — kept only as a fallback
SR_LOOKBACK = 60                # bars scanned for pivot-based S/R
PIVOT_WINDOW = 3                # bars each side that must be higher/lower for a pivot
CLUSTER_TOLERANCE_PCT = 0.015   # pivots within 1.5% of each other = same zone
SR_MAX_DISTANCE_PCT = 0.05      # ignore a zone more than 5% from current close
SUPPORT_PROXIMITY_PCT = 0.02
VOLUME_MA_WINDOW = 20
RSI_WINDOW = 14
EMA_SHORT = 20
SMA_MED = 50
TREND_WINDOW = 15
TREND_MIN_R2 = 0.35              # minimum linear fit quality to call it a trend at all
TREND_SLOPE_PCT_THRESHOLD = 0.0015  # min |slope|/mean(close) per bar to not be "choppy"
YF_SLEEP_SECONDS = 1.5


# ---------------------------------------------------------------------------
# Indicators — same formulas as TA_Notes.md Ch.12/13
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"] = df["Close"].ewm(span=EMA_SHORT, adjust=False).mean()
    df["sma50"] = df["Close"].rolling(SMA_MED).mean()
    df["vol_ma20"] = df["Volume"].rolling(VOLUME_MA_WINDOW).mean()

    # RSI: Wilder's original smoothing (alpha = 1/N), not a plain SMA of
    # gains/losses. The previous version used .rolling().mean(), a
    # different, non-standard formula that won't match RSI on any
    # standard charting platform. min_periods seeds the first value with
    # a simple average, matching Wilder's bootstrap.
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_WINDOW, adjust=False, min_periods=RSI_WINDOW).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_WINDOW, adjust=False, min_periods=RSI_WINDOW).mean()
    # avg_loss == 0 means zero down-bars in the smoothing window (a clean
    # run of gains) -- that's RSI=100 by definition, not an undefined
    # division. Only avg_gain==avg_loss==0 (no movement at all) is truly
    # undefined; leave that as NaN rather than fabricating 50.
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    df["rsi14"] = rsi

    # Legacy rolling min/max — retained only as a fallback for score_ticker
    # when pivot-based S/R (get_sr_levels) finds no usable cluster.
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


def trend_metrics(df: pd.DataFrame, idx: int, window: int = TREND_WINDOW) -> Optional[dict]:
    """Linear regression of Close over the `window` bars immediately
    before idx (idx itself excluded). Returns slope normalized to
    %/bar and R^2 as a fit-quality/confidence measure.

    Replaces the old higher-high/lower-high counting method, which
    counted direction changes but never measured magnitude or
    consistency — a stock chopping +1/-1 nine times then +8 once
    scored identically to one that rallied steadily, as long as the
    up-count edged out the down-count by the 1.3x cutoff.
    """
    if idx < window:
        return None
    seg = df.iloc[idx - window: idx]
    y = seg["Close"].values.astype(float)
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    slope_pct = slope / y.mean() if y.mean() != 0 else 0.0
    return {"slope_pct": float(slope_pct), "r2": float(r2)}


def trend_direction(df: pd.DataFrame, idx: int, window: int = TREND_WINDOW) -> str:
    """Direction label derived from trend_metrics. Requires BOTH a slope
    beyond TREND_SLOPE_PCT_THRESHOLD and a fit quality (R^2) above
    TREND_MIN_R2 — low R^2 means the "slope" is being dragged by noise
    or a couple of outlier bars, not a real drift, and gets called
    choppy regardless of sign."""
    m = trend_metrics(df, idx, window)
    if m is None:
        return "insufficient_data"
    if m["r2"] < TREND_MIN_R2:
        return "choppy"
    if m["slope_pct"] > TREND_SLOPE_PCT_THRESHOLD:
        return "uptrend"
    if m["slope_pct"] < -TREND_SLOPE_PCT_THRESHOLD:
        return "downtrend"
    return "choppy"


# ---------------------------------------------------------------------------
# Support/resistance — pivot clustering. The old approach was
# df["Low"].rolling(20).min(): a level counts as "support" even if price
# touched it exactly once, on the single lowest day of the window, and
# it changes every bar as the window slides. That's not what a trader
# means by a support zone. This finds local swing lows/highs, clusters
# ones that sit within CLUSTER_TOLERANCE_PCT of each other, and treats
# a cluster's touch count as a rough confidence signal — a level tested
# 3 times is more credible than one touched once.
# ---------------------------------------------------------------------------

def _find_pivots(values: np.ndarray, window: int, mode: str) -> list[float]:
    """mode='low' finds swing lows (local minima), mode='high' finds
    swing highs. A point is a pivot only if it's the extreme value in
    its full window on both sides — interior points of a flat run don't
    all qualify, which avoids over-counting a single multi-day plateau
    as several independent touches."""
    pivots = []
    n = len(values)
    for i in range(window, n - window):
        seg = values[i - window: i + window + 1]
        if mode == "low" and values[i] == seg.min():
            pivots.append(float(values[i]))
        elif mode == "high" and values[i] == seg.max():
            pivots.append(float(values[i]))
    return pivots


def _cluster_levels(prices: list[float], tolerance_pct: float) -> list[dict]:
    if not prices:
        return []
    prices = sorted(prices)
    clusters, current = [], [prices[0]]
    for p in prices[1:]:
        if abs(p - current[-1]) / current[-1] <= tolerance_pct:
            current.append(p)
        else:
            clusters.append(current)
            current = [p]
    clusters.append(current)
    return [{"level": float(np.mean(c)), "touches": len(c)} for c in clusters]


def get_sr_levels(df: pd.DataFrame, idx: int) -> dict:
    """Returns nearest credible support (below close) and resistance
    (above close) using pivot clustering over the SR_LOOKBACK bars
    before idx. Falls back to simple rolling min/max (already in df)
    if no pivot cluster exists within SR_MAX_DISTANCE_PCT — e.g. too
    little history, or a stock trending too cleanly to have set a
    recent swing point nearby."""
    start = max(0, idx - SR_LOOKBACK)
    seg = df.iloc[start:idx]  # excludes idx itself, same convention as trend_metrics
    close = float(df.iloc[idx]["Close"])

    low_pivots = _find_pivots(seg["Low"].values, PIVOT_WINDOW, "low")
    high_pivots = _find_pivots(seg["High"].values, PIVOT_WINDOW, "high")
    support_clusters = _cluster_levels(low_pivots, CLUSTER_TOLERANCE_PCT)
    resistance_clusters = _cluster_levels(high_pivots, CLUSTER_TOLERANCE_PCT)

    def nearest(clusters, side):
        candidates = [c for c in clusters if (c["level"] <= close if side == "support" else c["level"] >= close)]
        if not candidates:
            return None
        candidates.sort(key=lambda c: abs(close - c["level"]))
        best = candidates[0]
        if close == 0 or abs(close - best["level"]) / close > SR_MAX_DISTANCE_PCT:
            return None
        return best

    support = nearest(support_clusters, "support")
    resistance = nearest(resistance_clusters, "resistance")
    return {
        "support": support["level"] if support else None,
        "support_touches": support["touches"] if support else 0,
        "resistance": resistance["level"] if resistance else None,
        "resistance_touches": resistance["touches"] if resistance else 0,
    }


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
    trend_r2: Optional[float]
    pattern: Optional[str]
    pattern_matches_trend: bool
    near_support: bool
    support_level: Optional[float]
    support_touches: int
    resistance_level: Optional[float]
    resistance_touches: int
    volume_ratio: Optional[float]
    above_ema20: bool
    above_sma50: bool
    rsi: Optional[float]
    rsi_confirms: bool
    checks_passed: int
    checks_total: int
    confidence: float
    recommendation: str
    notes: list[str]
    flag: bool


def score_ticker(df: pd.DataFrame, ticker: str) -> Optional[ScreenResult]:
    df = compute_indicators(df)
    if len(df) < max(SMA_MED, TREND_WINDOW, SR_LOOKBACK) + 2:
        return None

    idx = len(df) - 1
    curr = df.iloc[idx]
    prev = df.iloc[idx - 1]

    trend = trend_direction(df, idx)
    tmetrics = trend_metrics(df, idx)
    trend_r2 = round(tmetrics["r2"], 2) if tmetrics else None

    pattern = classify_two_candle(prev, curr) or classify_single(curr)

    pattern_ok = False
    if pattern in ("bullish_engulfing", "piercing_pattern", "bullish_marubozu"):
        pattern_ok = trend in ("downtrend", "choppy")
    elif pattern == "hammer_or_hanging_man":
        pattern_ok = trend == "downtrend"  # Hanging Man (uptrend case) is a warning, not a signal here
    # NOTE: no bearish-pattern branch exists (bearish_engulfing,
    # dark_cloud_cover, bearish_marubozu, shooting_star_or_inverted_hammer
    # always fall through to pattern_ok=False). This screener is
    # structurally long-only. Unresolved: intentional, or a second
    # instance of the same scope bug the reversal-MA fix caught. Not
    # guessing at this without a decision — see conversation.

    sr = get_sr_levels(df, idx)
    support = sr["support"]
    support_touches = sr["support_touches"]
    resistance = sr["resistance"]
    resistance_touches = sr["resistance_touches"]
    # fallback to legacy rolling min if pivot clustering found nothing usable
    if support is None and not np.isnan(curr["support"]):
        support = float(curr["support"])
        support_touches = 0  # flag as unconfirmed — single rolling-window low, not a tested zone
    if resistance is None and not np.isnan(curr["resistance"]):
        resistance = float(curr["resistance"])
        resistance_touches = 0

    near_support = bool(
        support is not None and support > 0 and
        abs(float(curr["Close"]) - support) / support <= SUPPORT_PROXIMITY_PCT
    )

    vol_ratio = (
        curr["Volume"] / curr["vol_ma20"]
        if curr["vol_ma20"] and not np.isnan(curr["vol_ma20"]) else np.nan
    )
    # bool(...) wrapper matters: a numpy.float64 comparison returns
    # numpy.bool_, which leaks into sum()/json.dumps and silently
    # stringifies ("checks_passed": "2" instead of 2). See commit 966e7dd.
    volume_ok = bool(not np.isnan(vol_ratio) and vol_ratio >= 1.0)

    above_ema20 = bool(curr["Close"] > curr["ema20"])
    above_sma50 = bool(curr["Close"] > curr["sma50"]) if not np.isnan(curr["sma50"]) else False

    rsi_val = float(curr["rsi14"]) if not np.isnan(curr["rsi14"]) else None
    # Check 5 used to be "above both MAs" unconditionally, then briefly
    # "below both MAs when trend is downtrend" — but trend_direction()
    # is itself derived from price, and audit (500 synthetic walks)
    # showed downtrend and below-both-MAs coincide ~84% of the time.
    # Counting both as separate checks mostly double-counts the same
    # information. RSI is a different input (momentum, not price level),
    # so it adds independent evidence: in a downtrend context, RSI <=45
    # supports the "selling is exhausted" reversal thesis without just
    # restating "price is below its averages" a second time.
    if trend == "downtrend":
        rsi_confirms = rsi_val is not None and rsi_val <= 45
    elif trend == "choppy":
        rsi_confirms = rsi_val is not None and 35 <= rsi_val <= 65
    else:
        rsi_confirms = False

    checks = [
        trend in ("uptrend", "downtrend"),   # 1. defined trend (regression R^2 above threshold)
        bool(pattern) and pattern_ok,        # 2. pattern present, matches context
        near_support,                        # 3. near a pivot-confirmed S/R zone
        volume_ok,                           # 4. volume confirms
        rsi_confirms,                        # 5. momentum (RSI) agrees with the reversal read
    ]
    # Checks aren't equally informative — pattern presence and a defined
    # trend are the core structural claims; proximity to a real S/R zone
    # matters more than a single day's volume ratio, which is noisy.
    weights = [2.0, 2.0, 1.5, 1.0, 1.0]
    total_weight = sum(weights)
    passed = int(sum(checks))
    weighted = sum(w for c, w in zip(checks, weights) if c)
    confidence = round(100 * weighted / total_weight, 1)

    notes = []
    if trend == "choppy" and tmetrics is not None:
        notes.append(f"trend fit is weak (R^2={tmetrics['r2']:.2f}, threshold {TREND_MIN_R2}) — direction read is uncertain")
    if near_support and support_touches < 2:
        notes.append("support zone based on <2 historical touches — thin evidence, treat as tentative")
    if pattern is None:
        notes.append("no candlestick pattern on the latest bar")
    if not pattern_ok and pattern is not None:
        notes.append(f"pattern '{pattern}' detected but doesn't match trend context — not scored as a signal")

    # Advisory threshold, not a decision: this narrows the watchlist to
    # what's worth the manual checklist (sections 6-9: R:R, position
    # size, time stop) — it does not tell you to enter anything.
    if confidence >= 75 and checks[0] and checks[1]:
        recommendation = "Worth a manual look — most criteria align"
    elif confidence >= 50:
        recommendation = "Borderline — some criteria miss, verify each by hand before acting"
    else:
        recommendation = "Weak match on this checklist — likely not worth the manual review"

    return ScreenResult(
        ticker=ticker,
        date=str(curr.name.date()) if hasattr(curr.name, "date") else str(curr.name),
        close=round(float(curr["Close"]), 2),
        trend=trend,
        trend_r2=trend_r2,
        pattern=pattern,
        pattern_matches_trend=pattern_ok,
        near_support=near_support,
        support_level=round(support, 2) if support is not None else None,
        support_touches=support_touches,
        resistance_level=round(resistance, 2) if resistance is not None else None,
        resistance_touches=resistance_touches,
        volume_ratio=round(float(vol_ratio), 2) if not np.isnan(vol_ratio) else None,
        above_ema20=above_ema20,
        above_sma50=above_sma50,
        rsi=round(rsi_val, 2) if rsi_val is not None else None,
        rsi_confirms=rsi_confirms,
        checks_passed=passed,
        checks_total=len(checks),
        confidence=confidence,
        recommendation=recommendation,
        notes=notes,
        flag=bool(passed >= 4),  # kept for backward compat with main.py's alert filter
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


def _drop_unsettled_today(data: pd.DataFrame) -> pd.DataFrame:
    """Yahoo can hand back a same-day row with an understated Volume figure
    (partial session, or an intraday snapshot) and there's no wall-clock
    time at which that's guaranteed safe to trust -- the 4pm IST cron slot
    is only 30 min after NSE close and isn't a reliable settlement point
    either. Drop any row stamped with today's IST calendar date so every
    run, scheduled or manual, always scores the last *completed* session.
    Trade-off: a run on the same day as a real close will report T-1, not
    T-0, until the next day's row exists."""
    if data.empty:
        return data
    today_ist = datetime.now(IST).date()
    if data.index[-1].date() == today_ist:
        data = data.iloc[:-1]
    return data


def fetch_ticker(ticker: str) -> Optional[pd.DataFrame]:
    if yf is None:
        raise RuntimeError("yfinance not installed — pip install yfinance")
    data = yf.download(ticker, period=f"{LOOKBACK_DAYS}d", interval="1d", progress=False)
    if data.empty:
        return None
    data = _drop_unsettled_today(data)
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
    flagged = sorted((r for r in out if r["flag"]), key=lambda r: -r["confidence"])
    print(json.dumps({"all": out, "flagged": flagged}, indent=2, default=str))
