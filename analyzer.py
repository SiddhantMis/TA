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
from datetime import datetime, timedelta
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
    # added from Kite watchlist group 2 — see conversation for the
    # 4 flagged uncertainties (GOLDBEES/SILVERBEES are commodity ETFs,
    # not equities; ARE&M has an unverified special character; TMPV is
    # an OCR guess; IDEA/JUBLFOOD showed as BSE-listed in the source
    # screenshot but are added here as .NS for consistency)
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

LOOKBACK_PERIOD = "2y"          # yfinance's own vocabulary (1d/5d/1mo/.../2y/5y/max) -
                                 # an arbitrary "730d" string isn't in that documented
                                 # set and isn't worth the risk of finding out it's
                                 # handled differently from the small values already
                                 # tested against real data
SR_WINDOW = 20                  # legacy rolling min/max — kept only as a fallback
SR_LOOKBACK = 480                # ~2 years of trading days for pivot-based S/R.
                                 # TREND_WINDOW below is deliberately NOT changed —
                                 # short-term momentum and multi-year S/R are different
                                 # questions; conflating them would break the trend
                                 # read, not improve it. SR_MAX_DISTANCE_PCT already
                                 # filters out old levels that are no longer near
                                 # price, so age isn't a separate problem to solve —
                                 # a level from 18 months ago only survives the filter
                                 # if it's still relevant today.
PIVOT_WINDOW = 3                # bars each side that must be higher/lower for a pivot
CLUSTER_TOLERANCE_PCT = 0.015   # pivots within 1.5% of each other = same zone
SR_MAX_DISTANCE_PCT = 0.05      # ignore a zone more than 5% from current close
SR_LEVELS_PER_SIDE = 3          # how many support/resistance levels to report
                                 # per side for display (S1/S2/S3, R1/R2/R3).
                                 # Unrelated to SR_MAX_DISTANCE_PCT above --
                                 # that filter is what score_ticker's checklist
                                 # trades against (proximity matters for a
                                 # signal), this is for seeing the ladder
                                 # regardless of distance, which is the entire
                                 # point of asking for S2/S3.
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

    return _harami(prev, curr)


def _harami(prev, curr) -> Optional[str]:
    """Harami: curr's real body sits entirely inside prev's real body, and
    is meaningfully smaller (< 50% of prev's body) — an "inside candle"
    signaling the prior move has lost conviction. Direction is read off
    prev's color, not curr's: a big red candle (prev) followed by a small
    contained candle is a bullish Harami regardless of whether that small
    candle itself closed up or down.

    Weaker signal than engulfing/piercing by construction — it's "the move
    stalled," not "the move reversed." Flagged as lower-conviction in
    score_ticker's notes, not scored differently here."""
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
    """Morning Star (bullish) / Evening Star (bearish): a decisive candle,
    a small-bodied "star" that stalls the move, then a decisive candle back
    the other way that closes past the midpoint of candle 1's body.

    Deliberately NOT requiring a gap between candles — Indian cash-equity
    names frequently don't gap the way the textbook US-market version of
    this pattern assumes; the "star" (small body, low conviction) plus the
    third candle's close reclaiming candle 1's midpoint is treated as the
    load-bearing part of the definition. This is a real loosening of the
    textbook rule, not an oversight — worth knowing if you're cross-checking
    against a source that requires the gap."""
    def body_ratio(row):
        rng = row["High"] - row["Low"]
        return (abs(row["Close"] - row["Open"]) / rng) if rng > 0 else 0.0

    if body_ratio(c1) < 0.5 or body_ratio(c3) < 0.5:
        return None  # c1 and c3 must be decisive candles, not indecision
    if body_ratio(c2) >= 0.35:
        return None  # c2 must be a small-bodied "star"

    c1_mid = (c1["Open"] + c1["Close"]) / 2

    if _bearish(c1) and _bullish(c3) and c3["Close"] > c1_mid:
        return "morning_star"
    if _bullish(c1) and _bearish(c3) and c3["Close"] < c1_mid:
        return "evening_star"
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
    swing highs. A point qualifies only if it's the extreme value in
    its full window on both sides AND that window isn't perfectly
    flat -- if every value in the window is equal, there's no genuine
    local extreme to point to, and the previous version of this check
    (values[i] == seg.min()) would have every interior bar of a flat
    plateau satisfy that trivially, registering one 'pivot' per bar
    instead of recognizing there's no real swing point at all. This
    isn't just a synthetic-data edge case: a circuit-frozen NSE
    session can produce several consecutive days with Open=High=Low=
    Close, which would hit exactly this path on real data."""
    pivots = []
    n = len(values)
    i = window
    while i < n - window:
        seg = values[i - window: i + window + 1]
        if seg.max() == seg.min():
            i += 1
            continue  # flat window -- no genuine local extreme, not one pivot per bar
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


def get_sr_levels(df: pd.DataFrame, idx: int) -> dict:
    """Returns nearest credible support (below close) and resistance
    (above close) using pivot clustering over the SR_LOOKBACK bars
    before idx, PLUS a ranked ladder of up to SR_LEVELS_PER_SIDE levels
    on each side (S1 = nearest below, S2 = next below that, etc.).

    The single nearest/level fields still only count within
    SR_MAX_DISTANCE_PCT -- that's what score_ticker's checklist trades
    against. The ladder is NOT constrained by that filter, on purpose:
    seeing S2/S3 regardless of distance is the whole point of asking
    for them, not something to clip to a 5% band.

    touches is None (not 0) whenever a level came from the rolling-
    min/max fallback rather than a real pivot cluster -- a real cluster
    always has >=1 member, so touches=0 could never legitimately mean
    "a confirmed zone with zero confirmations." 0 was ambiguous with
    "thin but real"; None isn't. The ladder has no fallback equivalent
    at all: if there's no second cluster, there's no S2, full stop --
    the fallback exists so score_ticker's checklist has *something* to
    check proximity against, not to manufacture display levels that
    aren't backed by any real pivot.
    """
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

    def ladder(clusters, side, n):
        candidates = [c for c in clusters if (c["level"] <= close if side == "support" else c["level"] >= close)]
        candidates.sort(key=lambda c: abs(close - c["level"]))
        return [{"level": round(c["level"], 2), "touches": c["touches"]} for c in candidates[:n]]

    support = nearest(support_clusters, "support")
    resistance = nearest(resistance_clusters, "resistance")
    return {
        "support": support["level"] if support else None,
        "support_touches": support["touches"] if support else None,
        "resistance": resistance["level"] if resistance else None,
        "resistance_touches": resistance["touches"] if resistance else None,
        "support_ladder": ladder(support_clusters, "support", SR_LEVELS_PER_SIDE),
        "resistance_ladder": ladder(resistance_clusters, "resistance", SR_LEVELS_PER_SIDE),
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


def score_ticker(df: pd.DataFrame, ticker: str) -> Optional[ScreenResult]:
    df = compute_indicators(df)
    if len(df) < max(SMA_MED, TREND_WINDOW, SR_LOOKBACK) + 2:
        return None

    idx = len(df) - 1
    curr = df.iloc[idx]
    prev = df.iloc[idx - 1]
    prev2 = df.iloc[idx - 2] if idx >= 2 else None

    trend = trend_direction(df, idx)
    tmetrics = trend_metrics(df, idx)
    trend_r2 = round(tmetrics["r2"], 2) if tmetrics else None

    # Precedence: 3-candle beats 2-candle beats single. More candles
    # agreeing on the same read is a stronger claim than one candle's
    # shape. But compute all three regardless of which one wins — a loose
    # 3-candle match (Morning/Evening Star, no gap required) can suppress
    # a cleaner, already-validated 2-candle or single-candle match on the
    # exact same bar just by running first. "Check the flag manually"
    # only works if the report shows what got suppressed, not just the
    # winner.
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
        pattern_ok = trend == "downtrend"  # Hanging Man (uptrend case) is a warning, not a signal here
    # No bearish-pattern branch exists (bearish_engulfing, dark_cloud_cover,
    # bearish_marubozu, evening_star,
    # bearish_harami always fall through to pattern_ok=False). Deliberate,
    # not a scope bug: this trades cash equity delivery, not F&O — there's
    # no mechanism to carry a short position overnight, so a bearish signal
    # has nothing to attach an action to. Revisit only if a derivatives
    # account enters the picture.

    sr = get_sr_levels(df, idx)
    support = sr["support"]
    support_touches = sr["support_touches"]
    resistance = sr["resistance"]
    resistance_touches = sr["resistance_touches"]
    support_ladder = sr["support_ladder"]
    resistance_ladder = sr["resistance_ladder"]
    # fallback to legacy rolling min if pivot clustering found nothing usable.
    # touches stays None here, not 0 -- a real cluster always has >=1 member,
    # so 0 could never mean "confirmed zone, zero confirmations." None is the
    # only value that unambiguously means "not a real tested level."
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
    if used_fallback_support:
        notes.append("support level is an estimate (rolling low, no confirmed pivot cluster found nearby) — not a tested zone")
    elif near_support and support_touches is not None and support_touches < 2:
        notes.append("support zone based on <2 historical touches — thin evidence, treat as tentative")
    if pattern is None:
        notes.append("no candlestick pattern on the latest bar")
    if not pattern_ok and pattern is not None:
        notes.append(f"pattern '{pattern}' detected but doesn't match trend context — not scored as a signal")
    if pattern in ("bullish_harami", "bearish_harami"):
        notes.append("Harami is a lower-conviction reversal signal than engulfing/piercing — the inside candle only shows the prior move stalling, not reversing; wants more confirmation before acting on it alone")
    if suppressed:
        notes.append(f"'{suppressed}' also matched on this candle but was suppressed by 3-candle precedence ({pattern}) — check both by hand before deciding which read to trust")

    data_date = curr.name.date() if hasattr(curr.name, "date") else None
    data_stale_days = None
    if data_date is not None:
        data_stale_days = _data_staleness_business_days(data_date, datetime.now(IST).date())
        if data_stale_days > 1:
            notes.append(
                f"data is {data_stale_days} trading day(s) old, not the most recent close — "
                f"yfinance likely hadn't posted the newer session at fetch time. This flag/score "
                f"is based on stale data, not a same-day snapshot."
            )

    # Advisory threshold, not a decision: this narrows the watchlist to
    # what's worth the manual checklist (sections 6-9: R:R, position
    # size, time stop) — it does not tell you to enter anything.
    #
    # worth_manual_look is THE gate — used for both flag and the top
    # recommendation tier below. Previously these were two separate
    # conditions (flag: pattern gate + raw passed>=4; recommendation:
    # confidence>=75 + checks[0]+checks[1]) that could disagree: a
    # result could show flag=true (highlighted on the page) while its
    # own recommendation text said "Borderline" -- directly
    # self-contradictory to whoever's reading it. JIOFIN.NS on the
    # 2026-07-07 run hit exactly this (confidence 73.3, just under the
    # old 75 threshold, checks[0] failing because "choppy" doesn't
    # count as a defined trend even though it's a valid pattern
    # context) -- flagged and labeled "Borderline" at the same time.
    worth_manual_look = bool(pattern is not None and pattern_ok and passed >= 4)

    if worth_manual_look:
        recommendation = "Worth a manual look — most criteria align"
    elif confidence >= 50:
        recommendation = "Borderline — some criteria miss, verify each by hand before acting"
    else:
        recommendation = "Weak match on this checklist — likely not worth the manual review"

    return ScreenResult(
        ticker=ticker,
        date=str(curr.name.date()) if hasattr(curr.name, "date") else str(curr.name),
        data_stale_days=data_stale_days,
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
        # same boolean as the "Worth a manual look" recommendation text
        # above -- computed once, used twice, cannot diverge again.
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


def _data_staleness_business_days(last_date, today_ist) -> int:
    """Rough business-day gap between the data's actual date and now --
    weekends only, no NSE holiday calendar, so an occasional holiday
    reads as one day 'more stale' than it really is. Not meant to be a
    precise trading calendar -- meant to catch the case _drop_unsettled_
    today doesn't: yfinance simply hasn't posted the newest session yet
    at fetch time, so the data is a full day (or more) old with no
    signal of that anywhere in the output. A run at 6pm the day after a
    real close, silently scoring the day before that, is exactly this
    gap -- it already happened once, unflagged, before this existed."""
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
    # auto_adjust=True set explicitly, not relying on whatever yfinance's
    # current default happens to be. At 2 years of history the odds of a
    # split or bonus issue falling inside the window are real -- HDFCBANK's
    # own chart earlier in this build showed exactly that kind of
    # discontinuity. Unadjusted OHLC across a split would hand the S/R
    # pivot logic a fake price cliff to treat as a real level.
    data = yf.download(ticker, period=LOOKBACK_PERIOD, interval="1d", auto_adjust=True, progress=False)
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
            else:
                print(f"[skip] {t}: fetched data but not enough history to score "
                      f"(needs 2y+ for S/R; likely a recent IPO)", file=sys.stderr)
        except Exception as e:
            print(f"[error] {t}: {e}", file=sys.stderr)
        time.sleep(YF_SLEEP_SECONDS)
    return results


if __name__ == "__main__":
    out = run_screen()
    flagged = sorted((r for r in out if r["flag"]), key=lambda r: -r["confidence"])
    print(json.dumps({"all": out, "flagged": flagged}, indent=2, default=str))
