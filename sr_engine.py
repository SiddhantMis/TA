"""
Advanced Support & Resistance Engine (sr_engine.py)

Institutional-grade Support & Resistance analysis:
1. Multi-scale pivot detection (minor, intermediate, major swings)
2. Touch Ledger: tracks exact touch dates and lookback trading days
3. Bounce Quality: rejection wick size, close location, and subsequent velocity
4. Volume Confirmation: volume expansion at touch points (> 1.1x MA)
5. Role Reversal / Polarity Flips: prior resistance broken and retested as support
6. Multi-Timeframe Confluence: Weekly chart pivots confirming daily levels
7. Composite Zone Strength: 0-100 score weighing touches, recency, quality, and MTF confluence
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Union
import numpy as np
import pandas as pd


@dataclass
class SRTouch:
    bar_idx: int
    date: str
    price: float
    kind: str  # "low" (support) or "high" (resistance)
    days_ago: int
    wick_ratio: float
    vol_ratio: float
    bounce_velocity: float  # return away from level over next 3 bars


@dataclass
class SRZone:
    level: float
    side: str  # "support" or "resistance"
    touches: int
    touch_dates: list[str]
    days_ago: list[int]
    bounce_quality: str  # "High", "Moderate", "Tentative"
    volume_confirmed: bool
    role_reversal: bool  # True if broken prior resistance became support, or vice versa
    weekly_confluence: bool
    strength_score: float  # 0 to 100
    description: str


def _find_pivots_multi_scale(
    df: pd.DataFrame,
    idx: int,
    lookback: int = 480,
    windows: tuple[int, ...] = (3, 8, 20),
) -> list[SRTouch]:
    """Finds swing pivots across multiple time horizons without lookahead.
    Only data up to `idx` is evaluated.
    """
    start = max(0, idx - lookback)
    seg = df.iloc[start:idx]
    if len(seg) < min(windows) * 2 + 1:
        return []

    highs = seg["High"].values.astype(float)
    lows = seg["Low"].values.astype(float)
    closes = seg["Close"].values.astype(float)
    opens = seg["Open"].values.astype(float)
    volumes = seg["Volume"].values.astype(float) if "Volume" in seg else np.ones(len(seg))
    vol_ma = seg["vol_ma20"].values.astype(float) if "vol_ma20" in seg else volumes

    n_bars = len(seg)
    seen_lows: set[int] = set()
    seen_highs: set[int] = set()
    touches: list[SRTouch] = []

    for w in sorted(windows):
        for i in range(w, n_bars - w):
            # Check for swing low
            window_lows = lows[i - w : i + w + 1]
            if window_lows.max() > window_lows.min() and lows[i] == window_lows.min():
                if i not in seen_lows:
                    seen_lows.add(i)
                    bar_rng = max(highs[i] - lows[i], 1e-6)
                    lower_wick = min(opens[i], closes[i]) - lows[i]
                    wick_ratio = lower_wick / bar_rng
                    vr = volumes[i] / vol_ma[i] if vol_ma[i] > 0 and not np.isnan(vol_ma[i]) else 1.0

                    # 3-bar forward bounce velocity within available seg
                    fwd_idx = min(n_bars - 1, i + 3)
                    bounce_vel = (closes[fwd_idx] - lows[i]) / lows[i] if lows[i] > 0 else 0.0

                    abs_idx = start + i
                    date_val = str(seg.index[i].date()) if hasattr(seg.index[i], "date") else str(seg.index[i])
                    days_ago = idx - abs_idx

                    touches.append(SRTouch(
                        bar_idx=abs_idx,
                        date=date_val,
                        price=round(float(lows[i]), 2),
                        kind="low",
                        days_ago=days_ago,
                        wick_ratio=round(float(wick_ratio), 2),
                        vol_ratio=round(float(vr), 2),
                        bounce_velocity=round(float(bounce_vel), 4),
                    ))

            # Check for swing high
            window_highs = highs[i - w : i + w + 1]
            if window_highs.max() > window_highs.min() and highs[i] == window_highs.max():
                if i not in seen_highs:
                    seen_highs.add(i)
                    bar_rng = max(highs[i] - lows[i], 1e-6)
                    upper_wick = highs[i] - max(opens[i], closes[i])
                    wick_ratio = upper_wick / bar_rng
                    vr = volumes[i] / vol_ma[i] if vol_ma[i] > 0 and not np.isnan(vol_ma[i]) else 1.0

                    fwd_idx = min(n_bars - 1, i + 3)
                    bounce_vel = (highs[i] - closes[fwd_idx]) / highs[i] if highs[i] > 0 else 0.0

                    abs_idx = start + i
                    date_val = str(seg.index[i].date()) if hasattr(seg.index[i], "date") else str(seg.index[i])
                    days_ago = idx - abs_idx

                    touches.append(SRTouch(
                        bar_idx=abs_idx,
                        date=date_val,
                        price=round(float(highs[i]), 2),
                        kind="high",
                        days_ago=days_ago,
                        wick_ratio=round(float(wick_ratio), 2),
                        vol_ratio=round(float(vr), 2),
                        bounce_velocity=round(float(bounce_vel), 4),
                    ))

    touches.sort(key=lambda t: t.price)
    return touches


def _cluster_touches(
    touches: list[SRTouch],
    current_close: float,
    tolerance_pct: float = 0.015,
) -> list[SRZone]:
    """Clusters touches into distinct S/R zones and scores their quality."""
    if not touches or current_close <= 0:
        return []

    clusters: list[list[SRTouch]] = []
    current_cluster: list[SRTouch] = [touches[0]]

    for t in touches[1:]:
        anchor = current_cluster[0].price
        if abs(t.price - anchor) / anchor <= tolerance_pct:
            current_cluster.append(t)
        else:
            clusters.append(current_cluster)
            current_cluster = [t]
    clusters.append(current_cluster)

    zones: list[SRZone] = []
    for c in clusters:
        prices = [t.price for t in c]
        mean_level = float(np.mean(prices))
        side = "support" if mean_level <= current_close else "resistance"

        # Sort touches chronologically
        c_by_time = sorted(c, key=lambda t: t.bar_idx)
        dates = [t.date for t in c_by_time]
        days = [t.days_ago for t in c_by_time]
        kinds = [t.kind for t in c_by_time]

        # Role reversal: contains both "high" and "low" pivots
        role_reversal = ("high" in kinds and "low" in kinds)

        # Average metrics
        avg_wick = np.mean([t.wick_ratio for t in c])
        avg_vol = np.mean([t.vol_ratio for t in c])
        avg_vel = np.mean([t.bounce_velocity for t in c])
        volume_confirmed = bool(avg_vol >= 1.10)

        # Bounce Quality
        if avg_wick >= 0.35 and avg_vel >= 0.015:
            bounce_quality = "High"
        elif avg_wick >= 0.20 or avg_vel >= 0.008:
            bounce_quality = "Moderate"
        else:
            bounce_quality = "Tentative"

        # Recency bonus: recent touches (<= 30 days) are weighted higher
        min_days_ago = min(days)
        if min_days_ago <= 15:
            recency_weight = 1.3
        elif min_days_ago <= 45:
            recency_weight = 1.1
        elif min_days_ago <= 120:
            recency_weight = 1.0
        else:
            recency_weight = 0.75

        # Strength score (0 to 100)
        touch_pts = min(len(c) * 18, 54)  # 1 touch = 18, 2 = 36, 3+ = 54
        qual_pts = 18 if bounce_quality == "High" else (10 if bounce_quality == "Moderate" else 4)
        vol_pts = 12 if volume_confirmed else 4
        reversal_pts = 16 if role_reversal else 0

        raw_score = (touch_pts + qual_pts + vol_pts + reversal_pts) * recency_weight
        strength_score = round(min(100.0, max(10.0, raw_score)), 1)

        # Description string
        desc_parts = [
            f"{len(c)} touches ({min(days)}d ago)",
            f"Quality: {bounce_quality}",
        ]
        if role_reversal:
            desc_parts.append("Role Reversal")
        if volume_confirmed:
            desc_parts.append(f"Vol {avg_vol:.1f}x")
        description = " | ".join(desc_parts)

        zones.append(SRZone(
            level=round(mean_level, 2),
            side=side,
            touches=len(c),
            touch_dates=dates,
            days_ago=days,
            bounce_quality=bounce_quality,
            volume_confirmed=volume_confirmed,
            role_reversal=role_reversal,
            weekly_confluence=False,
            strength_score=strength_score,
            description=description,
        ))

    return zones


def _compute_weekly_pivots(df: pd.DataFrame, idx: int) -> list[float]:
    """Resamples daily bars up to `idx` into weekly bars and detects weekly swing points."""
    seg = df.iloc[:idx]
    if len(seg) < 30:
        return []

    # Ensure DatetimeIndex for resample
    if not isinstance(seg.index, pd.DatetimeIndex):
        try:
            seg = seg.copy()
            seg.index = pd.to_datetime(seg.index)
        except Exception:
            return []

    weekly = seg.resample("W-FRI").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()

    if len(weekly) < 10:
        return []

    w_highs = weekly["High"].values.astype(float)
    w_lows = weekly["Low"].values.astype(float)
    pivots = []
    # Window of 2 weekly bars each side (~1 month swing)
    w = 2
    for i in range(w, len(weekly) - w):
        hl = w_lows[i - w : i + w + 1]
        if hl.max() > hl.min() and w_lows[i] == hl.min():
            pivots.append(float(w_lows[i]))
        hh = w_highs[i - w : i + w + 1]
        if hh.max() > hh.min() and w_highs[i] == hh.max():
            pivots.append(float(w_highs[i]))

    return pivots


def analyze_sr(
    df: pd.DataFrame,
    idx: Optional[int] = None,
    lookback: int = 480,
    tolerance_pct: float = 0.015,
    max_distance_pct: float = 0.05,
    levels_per_side: int = 3,
) -> dict:
    """Master S/R analysis returning nearest levels, touch histories, and multi-timeframe confluence."""
    if idx is None:
        idx = len(df) - 1

    if idx < 30 or df.empty:
        return {
            "support": None, "support_touches": None, "support_dates": [], "support_days_ago": [],
            "support_quality": None, "support_role_reversal": False, "support_weekly_confluence": False,
            "resistance": None, "resistance_touches": None, "resistance_dates": [], "resistance_days_ago": [],
            "resistance_quality": None, "resistance_role_reversal": False, "resistance_weekly_confluence": False,
            "support_ladder": [], "resistance_ladder": [],
        }

    close = float(df.iloc[idx]["Close"]) if not np.isnan(df.iloc[idx]["Close"]) else 0.0
    if close <= 0:
        return {
            "support": None, "support_touches": None, "support_dates": [], "support_days_ago": [],
            "support_quality": None, "support_role_reversal": False, "support_weekly_confluence": False,
            "resistance": None, "resistance_touches": None, "resistance_dates": [], "resistance_days_ago": [],
            "resistance_quality": None, "resistance_role_reversal": False, "resistance_weekly_confluence": False,
            "support_ladder": [], "resistance_ladder": [],
        }

    # 1. Detect daily multi-scale pivots
    touches = _find_pivots_multi_scale(df, idx, lookback=lookback)

    # 2. Cluster into zones
    zones = _cluster_touches(touches, current_close=close, tolerance_pct=tolerance_pct)

    # 3. Weekly pivots for MTF confluence
    weekly_pivots = _compute_weekly_pivots(df, idx)
    for z in zones:
        for wp in weekly_pivots:
            if abs(z.level - wp) / wp <= 0.02:
                z.weekly_confluence = True
                z.strength_score = min(100.0, z.strength_score + 20.0)
                z.description += " | Weekly Confluence"
                break

    # Separate into support (<= close) and resistance (>= close)
    supports = [z for z in zones if z.level <= close]
    resistances = [z for z in zones if z.level >= close]

    # Sort supports by descending level (closest to price first)
    supports.sort(key=lambda z: abs(close - z.level))
    resistances.sort(key=lambda z: abs(close - z.level))

    # Filter nearest within max_distance_pct for trade checklist
    nearest_sup = None
    if supports and abs(close - supports[0].level) / close <= max_distance_pct:
        nearest_sup = supports[0]

    nearest_res = None
    if resistances and abs(close - resistances[0].level) / close <= max_distance_pct:
        nearest_res = resistances[0]

    def _ladder_format(zone_list: list[SRZone], n: int) -> list[dict]:
        out = []
        for z in zone_list[:n]:
            out.append({
                "level": z.level,
                "touches": z.touches,
                "touch_dates": z.touch_dates,
                "days_ago": z.days_ago,
                "bounce_quality": z.bounce_quality,
                "volume_confirmed": z.volume_confirmed,
                "role_reversal": z.role_reversal,
                "weekly_confluence": z.weekly_confluence,
                "strength_score": z.strength_score,
                "description": z.description,
            })
        return out

    return {
        "support": nearest_sup.level if nearest_sup else None,
        "support_touches": nearest_sup.touches if nearest_sup else None,
        "support_dates": nearest_sup.touch_dates if nearest_sup else [],
        "support_days_ago": nearest_sup.days_ago if nearest_sup else [],
        "support_quality": nearest_sup.bounce_quality if nearest_sup else None,
        "support_role_reversal": nearest_sup.role_reversal if nearest_sup else False,
        "support_weekly_confluence": nearest_sup.weekly_confluence if nearest_sup else False,
        "support_strength": nearest_sup.strength_score if nearest_sup else None,
        "resistance": nearest_res.level if nearest_res else None,
        "resistance_touches": nearest_res.touches if nearest_res else None,
        "resistance_dates": nearest_res.touch_dates if nearest_res else [],
        "resistance_days_ago": nearest_res.days_ago if nearest_res else [],
        "resistance_quality": nearest_res.bounce_quality if nearest_res else None,
        "resistance_role_reversal": nearest_res.role_reversal if nearest_res else False,
        "resistance_weekly_confluence": nearest_res.weekly_confluence if nearest_res else False,
        "resistance_strength": nearest_res.strength_score if nearest_res else None,
        "support_ladder": _ladder_format(supports, levels_per_side),
        "resistance_ladder": _ladder_format(resistances, levels_per_side),
    }
