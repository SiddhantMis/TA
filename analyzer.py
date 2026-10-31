"""
EOD Technical Screener (analyzer.py)

Fetches daily OHLCV via yfinance, computes indicators + candlestick
patterns per Zerodha Varsity Module 2 definitions, detects multi-touch
Support & Resistance zones with touch histories & weekly MTF confluence,
evaluates causal geometric chart patterns (double bottoms, flags, triangles),
ranks Relative Strength vs the index, and constructs high-conviction trade plans
with position sizing for downstream ChatGPT daily tasks and Discord alerts.
"""

from __future__ import annotations
import json
import math
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import Optional, Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from geo_patterns import detect_all
from position_sizer import calculate_position_size
from relative_strength import compute_stock_momentum, RSProfile

IST = ZoneInfo("Asia/Kolkata")

try:
    import yfinance as yf
except ImportError:
    yf = None  # lets test_patterns.py import this module without yfinance installed


# ---------------------------------------------------------------------------
# Config — edit WATCHLIST to grow/shrink coverage.
# ---------------------------------------------------------------------------

WATCHLIST = [
    "ETERNAL.NS", "DLF.NS", "IEX.NS", "UTTAMSUGAR.NS",
    "IDFCFIRSTB.NS", "BANDHANBNK.NS", "CENTRALBK.NS",
    "HDFCBANK.NS", "TITAN.NS", "MCX.NS", "BSE.NS",
    "LT.NS", "GOLDBEES.NS", "SILVERBEES.NS", "ADANIENSOL.NS",
    "ADANIENT.NS", "ADANIGREEN.NS", "ADANIPORTS.NS", "ADANIPOWER.NS",
    "VOLTAS.NS", "BAJAJHFL.NS", "PFC.NS", "IDEA.NS", "PNB.NS",
    "IRFC.NS", "TATASTEEL.NS", "ARE&M.NS", "RBLBANK.NS", "JIOFIN.NS",
    "ITC.NS", "TATAPOWER.NS", "TMPV.NS", "JSWSTEEL.NS", "PIDILITIND.NS",
    "INDUSINDBK.NS", "AXISBANK.NS", "TATACHEM.NS", "EXIDEIND.NS",
    "CIPLA.NS", "JUBLFOOD.NS", "ASHOKLEY.NS", "APOLLOTYRE.NS",
    "IREDA.NS", "BALRAMCHIN.NS", "MAXHEALTH.NS", "DEEPAKNTR.NS",
    "RELIANCE.NS", "COALINDIA.NS",
]

LOOKBACK_PERIOD = "2y"          # yfinance's vocabulary (2y)
SR_WINDOW = 20                  # legacy rolling min/max fallback
SR_LOOKBACK = 480               # ~2 years of trading days for pivot-based S/R
PIVOT_WINDOW = 3                # bars each side for local pivot
CLUSTER_TOLERANCE_PCT = 0.015   # pivots within 1.5% of each other = same zone
SR_MAX_DISTANCE_PCT = 0.05      # ignore zone >5% from current close for checklist
SR_LEVELS_PER_SIDE = 3          # how many support/resistance levels to report in ladder
SUPPORT_PROXIMITY_PCT = 0.02
SR_TOUCH_STRENGTH_CAP = 5       # touches at/above this get full confidence credit
VOLUME_MA_WINDOW = 20
RSI_WINDOW = 14
EMA_SHORT = 20
SMA_MED = 50
TREND_WINDOW = 15
TREND_MIN_R2 = 0.35              # minimum linear fit quality to call it a trend at all
TREND_SLOPE_PCT_THRESHOLD = 0.0015  # min |slope|/mean(close) per bar to not be "choppy"
YF_SLEEP_SECONDS = 1.5

# --- Trade plan gate (checklist section 6, R:R) ------------------------------
MIN_RR = 2.0                  # reward:risk to the chosen target must be at least this
MAX_RISK_PCT = 0.08           # skip if entry-to-stop is wider than this fraction of entry
ENTRY_BUFFER_PCT = 0.001      # buy-stop sits this far above signal candle's high
STOP_BUFFER_PCT = 0.005       # stop sits this far under lower of candle low / support
TARGET_LADDER_INDEX = 0       # 0 = nearest resistance above entry, 1 = the one after it


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"] = df["Close"].ewm(span=EMA_SHORT, adjust=False).mean()
    df["sma50"] = df["Close"].rolling(SMA_MED).mean()
    df["vol_ma20"] = df["Volume"].rolling(VOLUME_MA_WINDOW).mean()

    # Wilder's original smoothing (alpha = 1/N)
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_WINDOW, adjust=False, min_periods=RSI_WINDOW).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_WINDOW, adjust=False, min_periods=RSI_WINDOW).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    df["rsi14"] = rsi

    # Legacy rolling min/max fallback
    df["support"] = df["Low"].rolling(SR_WINDOW).min()
    df["resistance"] = df["High"].rolling(SR_WINDOW).max()
    return df


# ---------------------------------------------------------------------------
# Candlestick patterns
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
        return "hammer_or_hanging_man"
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

    return _harami(prev, curr)


def _harami(prev, curr) -> Optional[str]:
    prev_top, prev_bot = max(prev["Open"], prev["Close"]), min(prev["Open"], prev["Close"])
    curr_top, curr_bot = max(curr["Open"], curr["Close"]), min(curr["Open"], curr["Close"])
    prev_body = prev_top - prev_bot
    curr_body = curr_top - curr_bot
    if prev_body <= 0:
        return None
    contained = curr_top <= prev_top and curr_bot >= prev_bot
    if not contained or curr_body > 0.5 * prev_body:
        return None
    if _bearish(prev):
        return "bullish_harami"
    if _bullish(prev):
        return "bearish_harami"
    return None


def classify_three_candle(c1, c2, c3) -> Optional[str]:
    def body_ratio(row):
        rng = row["High"] - row["Low"]
        return (abs(row["Close"] - row["Open"]) / rng) if rng > 0 else 0.0

    if body_ratio(c1) < 0.5 or body_ratio(c3) < 0.5:
        return None
    if body_ratio(c2) >= 0.35:
        return None

    c1_mid = (c1["Open"] + c1["Close"]) / 2

    if _bearish(c1) and _bullish(c3) and c3["Close"] > c1_mid:
        return "morning_star"
    if _bullish(c1) and _bearish(c3) and c3["Close"] < c1_mid:
        return "evening_star"
    return None


def trend_metrics(df: pd.DataFrame, idx: int, window: int = TREND_WINDOW) -> Optional[dict]:
    if idx < window:
        return None
    seg = df.iloc[idx - window : idx]
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
# Support/resistance — Pivot clustering with touch tracking
# ---------------------------------------------------------------------------

def _find_pivots(values: np.ndarray, window: int, mode: str) -> list[float]:
    """mode='low' finds swing lows (local minima), mode='high' finds swing highs."""
    pivots = []
    n = len(values)
    i = window
    while i < n - window:
        seg = values[i - window : i + window + 1]
        if seg.max() == seg.min():
            i += 1
            continue
        found = False
        if mode == "low" and values[i] == seg.min():
            pivots.append(float(values[i]))
            found = True
        elif mode == "high" and values[i] == seg.max():
            pivots.append(float(values[i]))
            found = True
        if found:
            pivot_value = values[i]
            while i < n - window and values[i] == pivot_value:
                i += 1
        else:
            i += 1
    return pivots


def _find_pivots_detailed(df_seg: pd.DataFrame, start_offset: int, window: int, mode: str) -> list[dict]:
    """Finds pivots with exact bar index, timestamp, and candle metrics."""
    values = df_seg["Low" if mode == "low" else "High"].values.astype(float)
    highs = df_seg["High"].values.astype(float)
    lows = df_seg["Low"].values.astype(float)
    opens = df_seg["Open"].values.astype(float)
    closes = df_seg["Close"].values.astype(float)

    n = len(values)
    i = window
    pivots = []
    while i < n - window:
        seg_vals = values[i - window : i + window + 1]
        if seg_vals.max() == seg_vals.min():
            i += 1
            continue
        found = False
        if mode == "low" and values[i] == seg_vals.min():
            found = True
        elif mode == "high" and values[i] == seg_vals.max():
            found = True

        if found:
            pivot_val = float(values[i])
            bar_rng = max(highs[i] - lows[i], 1e-6)
            if mode == "low":
                wick = min(opens[i], closes[i]) - lows[i]
            else:
                wick = highs[i] - max(opens[i], closes[i])
            wick_ratio = max(0.0, min(1.0, wick / bar_rng))

            abs_idx = start_offset + i
            date_str = str(df_seg.index[i].date()) if hasattr(df_seg.index[i], "date") else str(df_seg.index[i])

            pivots.append({
                "price": pivot_val,
                "abs_idx": abs_idx,
                "date": date_str,
                "wick_ratio": round(float(wick_ratio), 2),
                "mode": mode,
            })
            while i < n - window and values[i] == pivot_val:
                i += 1
        else:
            i += 1
    return pivots


def _cluster_levels(prices: list[float], tolerance_pct: float) -> list[dict]:
    if not prices:
        return []
    prices = sorted(prices)
    clusters, current = [], [prices[0]]
    for p in prices[1:]:
        anchor = current[0]
        if abs(p - anchor) / anchor <= tolerance_pct:
            current.append(p)
        else:
            clusters.append(current)
            current = [p]
    clusters.append(current)
    return [{"level": float(np.mean(c)), "touches": len(c)} for c in clusters]


def _cluster_levels_detailed(pivots: list[dict], current_close: float, tolerance_pct: float, current_idx: int) -> list[dict]:
    if not pivots:
        return []
    pivots_sorted = sorted(pivots, key=lambda x: x["price"])
    clusters, current = [], [pivots_sorted[0]]

    for p in pivots_sorted[1:]:
        anchor = current[0]["price"]
        if abs(p["price"] - anchor) / anchor <= tolerance_pct:
            current.append(p)
        else:
            clusters.append(current)
            current = [p]
    clusters.append(current)

    out = []
    for c in clusters:
        prices = [x["price"] for x in c]
        level = float(np.mean(prices))
        c_by_time = sorted(c, key=lambda x: x["abs_idx"])
        dates = [x["date"] for x in c_by_time]
        days_ago = [current_idx - x["abs_idx"] for x in c_by_time]
        modes = [x["mode"] for x in c_by_time]

        role_reversal = ("low" in modes and "high" in modes)
        avg_wick = np.mean([x["wick_ratio"] for x in c])

        if avg_wick >= 0.35:
            quality = "High"
        elif avg_wick >= 0.20:
            quality = "Moderate"
        else:
            quality = "Tentative"

        out.append({
            "level": round(level, 2),
            "touches": len(c),
            "touch_dates": dates,
            "days_ago": days_ago,
            "bounce_quality": quality,
            "role_reversal": role_reversal,
            "weekly_confluence": False,
        })
    return out


def get_sr_levels(df: pd.DataFrame, idx: int) -> dict:
    """Returns nearest credible support/resistance plus ranked ladders with touch dates & bounce quality."""
    start = max(0, idx - SR_LOOKBACK)
    seg = df.iloc[start:idx]
    close = float(df.iloc[idx]["Close"]) if not np.isnan(df.iloc[idx]["Close"]) else 0.0

    low_pivots_detail = _find_pivots_detailed(seg, start, PIVOT_WINDOW, "low")
    high_pivots_detail = _find_pivots_detailed(seg, start, PIVOT_WINDOW, "high")

    # Combine for role-reversal detection
    all_pivots = low_pivots_detail + high_pivots_detail
    all_clusters = _cluster_levels_detailed(all_pivots, close, CLUSTER_TOLERANCE_PCT, idx)

    # Separate into support (<= close) and resistance (>= close)
    support_clusters = [c for c in all_clusters if c["level"] <= close]
    resistance_clusters = [c for c in all_clusters if c["level"] >= close]

    # Weekly chart confluence check if enough history
    if idx >= 60 and isinstance(df.index, pd.DatetimeIndex):
        try:
            weekly = df.iloc[:idx].resample("W-FRI").agg({"High": "max", "Low": "min"}).dropna()
            if len(weekly) >= 8:
                w_highs = weekly["High"].values
                w_lows = weekly["Low"].values
                w_pivots = _find_pivots(w_highs, 2, "high") + _find_pivots(w_lows, 2, "low")
                for c in all_clusters:
                    for wp in w_pivots:
                        if abs(c["level"] - wp) / wp <= 0.02:
                            c["weekly_confluence"] = True
                            break
        except Exception:
            pass

    def nearest(clusters, side):
        candidates = [c for c in clusters if (c["level"] <= close if side == "support" else c["level"] >= close)]
        if not candidates:
            return None
        candidates.sort(key=lambda c: abs(close - c["level"]))
        best = candidates[0]
        if close == 0 or abs(close - best["level"]) / close > SR_MAX_DISTANCE_PCT:
            return None
        return best

    def ladder(clusters, side, n):
        candidates = [c for c in clusters if (c["level"] <= close if side == "support" else c["level"] >= close)]
        candidates.sort(key=lambda c: abs(close - c["level"]))
        return [{
            "level": round(c["level"], 2),
            "touches": c["touches"],
            "touch_dates": c.get("touch_dates", []),
            "days_ago": c.get("days_ago", []),
            "bounce_quality": c.get("bounce_quality", "Moderate"),
            "role_reversal": c.get("role_reversal", False),
            "weekly_confluence": c.get("weekly_confluence", False),
        } for c in candidates[:n]]

    support = nearest(support_clusters, "support")
    resistance = nearest(resistance_clusters, "resistance")

    return {
        "support": support["level"] if support else None,
        "support_touches": support["touches"] if support else None,
        "support_dates": support["touch_dates"] if support else [],
        "support_days_ago": support["days_ago"] if support else [],
        "support_quality": support["bounce_quality"] if support else None,
        "support_role_reversal": support["role_reversal"] if support else False,
        "support_weekly_confluence": support["weekly_confluence"] if support else False,
        "resistance": resistance["level"] if resistance else None,
        "resistance_touches": resistance["touches"] if resistance else None,
        "resistance_dates": resistance["touch_dates"] if resistance else [],
        "resistance_days_ago": resistance["days_ago"] if resistance else [],
        "resistance_quality": resistance["bounce_quality"] if resistance else None,
        "resistance_role_reversal": resistance["role_reversal"] if resistance else False,
        "resistance_weekly_confluence": resistance["weekly_confluence"] if resistance else False,
        "support_ladder": ladder(support_clusters, "support", SR_LEVELS_PER_SIDE),
        "resistance_ladder": ladder(resistance_clusters, "resistance", SR_LEVELS_PER_SIDE),
    }


# ---------------------------------------------------------------------------
# Trade Plan Construction & Gate
# ---------------------------------------------------------------------------

def build_trade_plan(signal_high: float, signal_low: float, support: Optional[float],
                     resistance_ladder: list) -> dict:
    """Entry / stop / target from the signal candle and S/R ladder."""
    entry = signal_high * (1 + ENTRY_BUFFER_PCT)
    stop_base = signal_low if support is None else min(signal_low, support)
    stop = stop_base * (1 - STOP_BUFFER_PCT)
    risk = entry - stop
    risk_pct = risk / entry if entry > 0 else None
    above = sorted(l["level"] for l in resistance_ladder if l["level"] > entry)
    target = above[TARGET_LADDER_INDEX] if len(above) > TARGET_LADDER_INDEX else None
    rr = (target - entry) / risk if (target is not None and risk > 0) else None

    why_not = None
    if risk <= 0 or risk_pct is None:
        why_not = "stop is not below entry"
    elif risk_pct > MAX_RISK_PCT:
        why_not = f"stop is {risk_pct:.1%} below entry (max {MAX_RISK_PCT:.0%})"
    elif rr is None:
        why_not = "no resistance zone above entry in the lookback — set a target by hand"
    elif rr < MIN_RR:
        why_not = f"R:R {rr:.1f} to nearest target (need {MIN_RR:.1f})"

    # Calculate position sizing guide
    sizing = None
    if why_not is None and target is not None:
        try:
            sizing = calculate_position_size(entry, stop, target)
        except Exception:
            sizing = None

    return {
        "entry": round(entry, 2), "stop": round(stop, 2),
        "target": round(target, 2) if target is not None else None,
        "risk_pct": round(risk_pct, 4) if risk_pct is not None else None,
        "rr": round(rr, 2) if rr is not None else None,
        "trade_ok": why_not is None, "why_not": why_not,
        "suggested_shares": sizing.shares if sizing else None,
        "capital_required": sizing.capital_required if sizing else None,
        "risk_amount_rupees": sizing.risk_amount if sizing else None,
    }


@dataclass
class ScreenResult:
    ticker: str
    date: str
    data_stale_days: Optional[int]
    close: float
    trend: str
    trend_r2: Optional[float]
    pattern: Optional[str]
    pattern_matches_trend: bool
    near_support: bool
    support_level: Optional[float]
    support_touches: Optional[int]
    resistance_level: Optional[float]
    resistance_touches: Optional[int]
    support_ladder: list
    resistance_ladder: list
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
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    risk_pct: Optional[float] = None
    rr: Optional[float] = None
    trade_ok: bool = False
    # Enhanced S/R tracking
    support_dates: list = field(default_factory=list)
    support_days_ago: list = field(default_factory=list)
    support_quality: Optional[str] = None
    support_role_reversal: bool = False
    support_weekly_confluence: bool = False
    resistance_dates: list = field(default_factory=list)
    resistance_days_ago: list = field(default_factory=list)
    resistance_quality: Optional[str] = None
    resistance_role_reversal: bool = False
    resistance_weekly_confluence: bool = False
    # Geometric patterns (from geo_patterns.py)
    geo_pattern: Optional[str] = None
    geo_pattern_key: Optional[float] = None
    geo_pattern_target: Optional[float] = None
    geo_pattern_stop: Optional[float] = None
    geo_pattern_status: Optional[str] = None
    # Relative Strength & Market Leader Ranking
    rs_rank: Optional[int] = None
    rs_percentile: Optional[float] = None
    rs_trend: Optional[str] = None
    is_leader: bool = False
    # Position sizing guide
    suggested_shares: Optional[int] = None
    capital_required: Optional[float] = None
    risk_amount_rupees: Optional[float] = None
    # ChatGPT Daily Task prompts
    ai_audit_prompt: Optional[str] = None
    ai_veto_checklist: Optional[str] = None


def score_ticker(
    df: pd.DataFrame,
    ticker: str,
    rs_profile: Optional[RSProfile] = None,
) -> Optional[ScreenResult]:
    df = compute_indicators(df)
    if len(df) < max(SMA_MED, TREND_WINDOW, SR_LOOKBACK) + 2:
        return None

    idx = len(df) - 1
    curr = df.iloc[idx]
    prev = df.iloc[idx - 1]
    prev2 = df.iloc[idx - 2] if idx >= 2 else None

    # Safe close price
    raw_close = curr["Close"]
    if np.isnan(raw_close) or raw_close <= 0:
        valid_closes = df["Close"].dropna()
        close_val = round(float(valid_closes.iloc[-1]), 2) if not valid_closes.empty else 0.0
    else:
        close_val = round(float(raw_close), 2)

    trend = trend_direction(df, idx)
    tmetrics = trend_metrics(df, idx)
    trend_r2 = round(tmetrics["r2"], 2) if tmetrics else None

    # Candlestick pattern precedence: 3-candle > 2-candle > single
    three_candle = classify_three_candle(prev2, prev, curr) if prev2 is not None else None
    two_candle = classify_two_candle(prev, curr)
    single = classify_single(curr)
    pattern = three_candle or two_candle or single

    suppressed = None
    if three_candle and (two_candle or single) and (two_candle or single) != three_candle:
        suppressed = two_candle or single

    pattern_ok = False
    if pattern in ("bullish_engulfing", "piercing_pattern", "bullish_marubozu", "morning_star", "bullish_harami"):
        pattern_ok = trend in ("downtrend", "choppy")
    elif pattern in ("hammer_or_hanging_man", "shooting_star_or_inverted_hammer"):
        pattern_ok = trend == "downtrend"

    sr = get_sr_levels(df, idx)
    support = sr["support"]
    support_touches = sr["support_touches"]
    resistance = sr["resistance"]
    resistance_touches = sr["resistance_touches"]
    support_ladder = sr["support_ladder"]
    resistance_ladder = sr["resistance_ladder"]

    used_fallback_support = False
    used_fallback_resistance = False
    if support is None and not np.isnan(curr["support"]):
        support = float(curr["support"])
        support_touches = None
        used_fallback_support = True
    if resistance is None and not np.isnan(curr["resistance"]):
        resistance = float(curr["resistance"])
        resistance_touches = None
        used_fallback_resistance = True

    near_support = bool(
        support is not None and support > 0 and close_val > 0 and
        abs(close_val - support) / support <= SUPPORT_PROXIMITY_PCT
    )

    if near_support and not used_fallback_support and support_touches is not None:
        support_strength = min(support_touches, SR_TOUCH_STRENGTH_CAP) / SR_TOUCH_STRENGTH_CAP
    elif near_support:
        support_strength = 1.0
    else:
        support_strength = 0.0

    vol_ratio = (
        curr["Volume"] / curr["vol_ma20"]
        if curr["vol_ma20"] and not np.isnan(curr["vol_ma20"]) else np.nan
    )
    volume_ok = bool(not np.isnan(vol_ratio) and vol_ratio >= 1.0)

    above_ema20 = bool(close_val > curr["ema20"]) if not np.isnan(curr["ema20"]) else False
    above_sma50 = bool(close_val > curr["sma50"]) if not np.isnan(curr["sma50"]) else False

    rsi_val = float(curr["rsi14"]) if not np.isnan(curr["rsi14"]) else None
    if trend == "downtrend":
        rsi_confirms = rsi_val is not None and rsi_val <= 45
    elif trend == "choppy":
        rsi_confirms = rsi_val is not None and 35 <= rsi_val <= 65
    else:
        rsi_confirms = False

    checks = [
        trend in ("uptrend", "downtrend"),
        bool(pattern) and pattern_ok,
        near_support,
        volume_ok,
        rsi_confirms,
    ]
    weights = [2.0, 2.0, 1.5, 1.0, 1.0]
    total_weight = sum(weights)
    passed = int(sum(checks))
    weighted = sum(
        (support_strength * w if idx_c == 2 else w)
        for idx_c, (c, w) in enumerate(zip(checks, weights)) if c
    )
    confidence = round(100 * weighted / total_weight, 1)

    notes = []
    if trend == "choppy" and tmetrics is not None:
        notes.append(f"trend fit is weak (R^2={tmetrics['r2']:.2f}, threshold {TREND_MIN_R2}) — direction read is uncertain")
    if used_fallback_support:
        notes.append("support level is an estimate (rolling low, no confirmed pivot cluster found nearby) — not a tested zone")
    elif near_support and support_touches is not None and support_touches < 2:
        notes.append("support zone based on <2 historical touches — thin evidence, treat as tentative")
    if pattern is None:
        notes.append("no candlestick pattern on the latest bar")
    if not pattern_ok and pattern is not None:
        notes.append(f"pattern '{pattern}' detected but doesn't match trend context — not scored as a signal")
    if pattern in ("bullish_harami", "bearish_harami"):
        notes.append("Harami is a lower-conviction reversal signal than engulfing/piercing")
    if suppressed:
        notes.append(f"'{suppressed}' also matched on this candle but was suppressed by 3-candle precedence ({pattern})")

    # Add S/R notes if high-conviction structural features present
    if sr.get("support_weekly_confluence"):
        notes.append("support level has major weekly chart confluence")
    if sr.get("support_role_reversal"):
        notes.append("support was previously a major resistance level (role reversal / polarity flip)")

    data_date = curr.name.date() if hasattr(curr.name, "date") else None
    data_stale_days = None
    if data_date is not None:
        data_stale_days = _data_staleness_business_days(data_date, datetime.now(IST).date())
        if data_stale_days > 1:
            notes.append(
                f"data is {data_stale_days} trading day(s) old, not the most recent close — "
                f"yfinance likely hadn't posted the newer session at fetch time."
            )

    worth_manual_look = bool(pattern is not None and pattern_ok and passed >= 4)

    if worth_manual_look:
        recommendation = "Worth a manual look — most criteria align"
    elif confidence >= 50:
        recommendation = "Borderline — some criteria miss, verify each by hand before acting"
    else:
        recommendation = "Weak match on this checklist — likely not worth the manual review"

    plan = build_trade_plan(float(curr["High"]), float(curr["Low"]), support, resistance_ladder)
    if worth_manual_look and not plan["trade_ok"]:
        notes.append(f"trade plan fails the gate: {plan['why_not']}")

    # Causal geometric chart pattern detection
    geo_pattern_name = None
    geo_pattern_key = None
    geo_pattern_target = None
    geo_pattern_stop = None
    geo_pattern_status = None
    try:
        if len(df) >= 60:
            sub = df.iloc[:idx + 1]
            events = detect_all(sub["Open"], sub["High"], sub["Low"], sub["Close"])
            recent = [e for e in events if e["t"] >= len(sub) - 3]
            if recent:
                ev = recent[-1]
                geo_pattern_name = ev["name"]
                geo_pattern_key = round(float(ev["key"]), 2)
                geo_pattern_target = round(float(ev["target"]), 2)
                geo_pattern_stop = round(float(ev["stop"]), 2)
                geo_pattern_status = "unvalidated_context"
                notes.append(f"chart pattern context: {geo_pattern_name} (breakout @ {geo_pattern_key}, target {geo_pattern_target})")
    except Exception:
        pass

    # AI daily task prompts
    ai_audit_prompt = (
        f"Audit {ticker} news and corporate actions in the last 72 hours: "
        f"1. Upcoming quarterly earnings or board meeting dates in next 5 days. "
        f"2. Regulatory, tax, or court notices (SEBI, CCI, etc.). "
        f"3. Promoter pledge changes, block deals, or bulk deals."
    )
    ai_veto_checklist = (
        f"VETO trade on {ticker} if: (a) Earnings announcement within 3 trading days, "
        f"(b) Adverse regulatory action or investigation, (c) Promoter net selling > 0.5%."
    )

    return ScreenResult(
        ticker=ticker,
        date=str(curr.name.date()) if hasattr(curr.name, "date") else str(curr.name),
        data_stale_days=data_stale_days,
        close=close_val,
        trend=trend,
        trend_r2=trend_r2,
        pattern=pattern,
        pattern_matches_trend=pattern_ok,
        near_support=near_support,
        support_level=round(support, 2) if support is not None else None,
        support_touches=support_touches,
        resistance_level=round(resistance, 2) if resistance is not None else None,
        resistance_touches=resistance_touches,
        support_ladder=support_ladder,
        resistance_ladder=resistance_ladder,
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
        flag=worth_manual_look,
        entry=plan["entry"], stop=plan["stop"], target=plan["target"],
        risk_pct=plan["risk_pct"], rr=plan["rr"], trade_ok=plan["trade_ok"],
        support_dates=sr.get("support_dates", []),
        support_days_ago=sr.get("support_days_ago", []),
        support_quality=sr.get("support_quality"),
        support_role_reversal=sr.get("support_role_reversal", False),
        support_weekly_confluence=sr.get("support_weekly_confluence", False),
        resistance_dates=sr.get("resistance_dates", []),
        resistance_days_ago=sr.get("resistance_days_ago", []),
        resistance_quality=sr.get("resistance_quality"),
        resistance_role_reversal=sr.get("resistance_role_reversal", False),
        resistance_weekly_confluence=sr.get("resistance_weekly_confluence", False),
        geo_pattern=geo_pattern_name,
        geo_pattern_key=geo_pattern_key,
        geo_pattern_target=geo_pattern_target,
        geo_pattern_stop=geo_pattern_stop,
        geo_pattern_status=geo_pattern_status,
        rs_rank=rs_profile.rank if rs_profile else None,
        rs_percentile=rs_profile.rs_percentile if rs_profile else None,
        rs_trend=rs_profile.rs_trend if rs_profile else None,
        is_leader=rs_profile.is_leader if rs_profile else False,
        suggested_shares=plan.get("suggested_shares"),
        capital_required=plan.get("capital_required"),
        risk_amount_rupees=plan.get("risk_amount_rupees"),
        ai_audit_prompt=ai_audit_prompt,
        ai_veto_checklist=ai_veto_checklist,
    )


def _flatten_columns(data: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if not isinstance(data.columns, pd.MultiIndex):
        return data
    lvl0 = set(data.columns.get_level_values(0))
    if ticker in lvl0:
        return data.xs(ticker, axis=1, level=0)
    return data.droplevel(1, axis=1)


def _drop_unsettled_today(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return data
    today_ist = datetime.now(IST).date()
    if data.index[-1].date() == today_ist:
        data = data.iloc[:-1]
    return data


def _data_staleness_business_days(last_date, today_ist) -> int:
    d = last_date
    days = 0
    while d < today_ist:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days


def fetch_ticker(ticker: str) -> Optional[pd.DataFrame]:
    if yf is None:
        raise RuntimeError("yfinance not installed — pip install yfinance")
    data = yf.download(ticker, period=LOOKBACK_PERIOD, interval="1d", auto_adjust=True, progress=False)
    if data.empty:
        return None
    data = _drop_unsettled_today(data)
    if data.empty:
        return None
    data = _flatten_columns(data, ticker)
    data = data.rename(columns=str.title)
    return data


def run_screen(watchlist: list[str] = WATCHLIST, benchmark_ticker: str = "NIFTYBEES.NS") -> list[dict]:
    """Runs screener with Relative Strength ranking across the watchlist."""
    dfs: dict[str, pd.DataFrame] = {}
    benchmark_df = None

    # Fetch benchmark index for RS ranking if available
    try:
        benchmark_df = fetch_ticker(benchmark_ticker)
    except Exception:
        pass

    for t in watchlist:
        try:
            df = fetch_ticker(t)
            if df is not None and not df.empty:
                dfs[t] = df
            else:
                print(f"[skip] no data for {t}", file=sys.stderr)
        except Exception as e:
            print(f"[error] {t}: {e}", file=sys.stderr)
        time.sleep(YF_SLEEP_SECONDS)

    # Compute Relative Strength profiles
    rs_profiles: dict[str, RSProfile] = {}
    if dfs:
        try:
            from relative_strength import rank_universe
            rs_profiles = rank_universe(dfs, benchmark_df)
        except Exception:
            pass

    results = []
    for t, df in dfs.items():
        try:
            profile = rs_profiles.get(t)
            r = score_ticker(df, t, rs_profile=profile)
            if r:
                results.append(asdict(r))
            else:
                print(f"[skip] {t}: not enough history to score", file=sys.stderr)
        except Exception as e:
            print(f"[error] scoring {t}: {e}", file=sys.stderr)

    return results


if __name__ == "__main__":
    out = run_screen()
    flagged = sorted((r for r in out if r["flag"]), key=lambda r: -r["confidence"])
    print(f"Total screened: {len(out)}, Flagged: {len(flagged)}")
