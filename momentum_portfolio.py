#!/usr/bin/env python3
"""Momentum Portfolio Builder & Daily Rotation Engine (momentum_portfolio.py).

Shifts the project from a standalone Technical Analysis pattern scanner to an institutional
Momentum Portfolio Manager built around the repo's empirically validated edge (`mom12_1+mkt`):

1. Universe & Ranking (`Top 20` of Liquid Nifty 500 / 200):
   - Point-in-time Top 200 most liquid NSE stocks by 126-day average traded value.
   - Hard Trend Eligibility: `Close > SMA200`.
   - Ranked by `12-1M` Relative Strength vs `NIFTYBEES.NS` (skipping the latest 21 sessions).

2. Daily Health Monitoring & Hysteresis Buffer (Anti-Churn):
   - Evaluates the currently held 20 portfolio stocks every day against 4 health gates:
     a) `TREND_BROKEN`: Close falls below its 200-day SMA (or >3% below 50-DMA with negative 1M RS).
     b) `RANK_DECAY`: Stock drops below the hysteresis rank buffer (`rank > 30`, i.e. top-30 buffer
        for a 20-stock portfolio so #19 <-> #22 daily noise never triggers unnecessary turnover).
     c) `STOP_HIT`: Close breaches the stock's behavior-adapted trailing stop band.
     d) `REGIME_CASH`: Benchmark (`NIFTYBEES.NS`) falls below its 200-DMA (`mom12_1+mkt` rule).
   - Assigns a 0-100 `momentum_health_score` and explicit status:
     `HOLD_STRONG`, `HOLD_EXTENDED_TRIM_WATCH`, `WARNING_WATCH`, or `EXIT_AND_REPLACE`.

3. Replacement / Cash Fallback Engine:
   - For every stock flagged `EXIT_AND_REPLACE` (or any empty slot below 20 holdings), selects the
     highest-ranked eligible candidate not already in the portfolio that:
     * Is in the Top 20 by `12-1M RS`
     * Has `Close > SMA200` and `Close > SMA50`
     * Is NOT over-extended (`dist_from_20ema_pct <= 12%`)
   - If the market regime is defensive (`NIFTYBEES < 200-DMA`) or no eligible candidate exists,
     explicitly instructs: `REMOVE_TO_CASH` (never forces a sub-par trade).

4. Stock-Behavior-Adapted Entry, Trailing Stop, and Profit-Taking Bands:
   - Rather than a rigid fixed percentage across low-beta and high-beta stocks, computes each
     stock's 60-day annualized volatility and `ATR14 % of price` (`atr_pct`), classifying its
     behavior profile into `Low-Beta Steady`, `Core Trend`, or `High-Beta Momentum`:
     * Ideal Entry Zone: Pullback band (`20-EMA` to `+2%` above `20-EMA` / nearest multi-touch Support)
     * Hard / Trailing Exit Percentage: `max(8.0%, min(18.0%, 3.0 * atr_pct))` below peak close
       (or structural 50-DMA / 200-DMA invalidation)
     * Partial Profit / Trim Band: `+20%` to `+35%` swing extension (`> 15%` above 20-EMA).

5. Multi-AI Workflow Export (Gemini Gem Brief + ChatGPT Daily Task Brief -> Claude Synthesis):
   - Generates `docs/gemini_gem_brief.md` (Deep Fundamental, Sector & Institutional Flow Prompt)
   - Generates `docs/chatgpt_task_brief.md` (72-Hour Live News, Earnings, SEBI/Pledge & Red-Flag Audit)
   - Generates `docs/momentum_portfolio_state.json` (Full machine-readable portfolio state + history).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
from datetime import datetime
import json
import math
import os
import sys
from typing import Optional

import numpy as np
import pandas as pd

import analyzer as A
import leaders as LD
from position_sizer import DEFAULT_ACCOUNT_CAPITAL

PORTFOLIO_SIZE = 20
HYSTERESIS_BUFFER_RANK = 30     # Keep existing holding as long as it stays inside Top 30 and > 200-DMA
MAX_ENTRY_EXTENSION_EMA20_PCT = 12.0
DEFAULT_STATE_PATH = "docs/momentum_portfolio_state.json"
DEFAULT_GEMINI_BRIEF_PATH = "docs/gemini_gem_brief.md"
DEFAULT_CHATGPT_BRIEF_PATH = "docs/chatgpt_task_brief.md"


@dataclass
class StockBehaviorBand:
    behavior_profile: str           # 'Low-Beta Steady', 'Core Trend', 'High-Beta Momentum'
    atr14_pct: float                # Daily ATR14 as % of close
    annualized_vol_pct: float       # 60-day annualized return volatility (%)
    ideal_entry_low: float          # 20-EMA or nearest support
    ideal_entry_high: float         # Max buy limit (+2.5% above 20-EMA or +1% above close if pullback)
    max_chase_limit_pct: float      # Max % above 20-EMA before waiting
    trailing_stop_pct: float        # Behavior-adapted trailing stop % from highest close (8% - 18%)
    trailing_stop_price: float      # Exact price level of trailing stop from 20-day peak
    structural_stop_price: float    # Hard structural invalidation (min of 50-DMA - 1*ATR or Support)
    trim_extension_pct: float       # Gain/extension % above 50-DMA where partial profit-taking triggers
    trim_target_price: float        # Price level where stock becomes over-extended

    def to_dict(self) -> dict:
        return asdict(self)


def compute_stock_behavior_bands(df: pd.DataFrame, structure: dict | None = None) -> dict:
    """Compute stock-specific entry, trailing stop %, and profit-trim bands based on its volatility behavior."""
    C = pd.to_numeric(df["Close"], errors="coerce").dropna()
    H = pd.to_numeric(df["High"], errors="coerce").reindex(C.index)
    L = pd.to_numeric(df["Low"], errors="coerce").reindex(C.index)

    last_c = float(C.iloc[-1])
    ema20 = float(C.ewm(span=20, adjust=False).mean().iloc[-1])
    sma50 = float(C.rolling(50, min_periods=20).mean().iloc[-1])
    sma200 = float(C.rolling(200, min_periods=50).mean().iloc[-1])
    peak20 = float(H.iloc[-20:].max()) if len(H) >= 20 else float(H.max())

    pc = C.shift(1).fillna(C.iloc[0])
    tr = np.maximum.reduce([H - L, (H - pc).abs(), (L - pc).abs()])
    atr14 = float(pd.Series(tr, index=C.index).rolling(14, min_periods=5).mean().iloc[-1])
    atr_pct = (atr14 / last_c * 100.0) if last_c > 0 else 2.5

    rets = C.pct_change().dropna().iloc[-60:]
    ann_vol = float(rets.std(ddof=1) * np.sqrt(252) * 100.0) if len(rets) > 5 else 28.0

    if ann_vol < 24.0 and atr_pct < 2.2:
        profile = "Low-Beta Steady"
    elif ann_vol <= 38.0 and atr_pct <= 3.5:
        profile = "Core Trend"
    else:
        profile = "High-Beta Momentum"

    # Behavior-adapted trailing stop %: 3.2x daily ATR%, clamped between 8.0% and 18.0%
    trail_pct = round(float(np.clip(3.2 * atr_pct, 8.0, 18.0)), 1)
    trail_price = round(peak20 * (1.0 - trail_pct / 100.0), 2)

    sup_level = (structure or {}).get("support_level")
    if sup_level is not None and np.isfinite(sup_level) and sup_level < last_c:
        struct_stop = round(min(float(sup_level) * 0.985, sma50 * 0.97), 2)
    else:
        struct_stop = round(max(sma200 * 0.99, sma50 * 0.96), 2)

    ideal_low = round(min(ema20, float(sup_level)) if (sup_level and sup_level > sma50) else ema20, 2)
    ideal_high = round(ema20 * 1.025, 2)

    # Profit-taking / trim extension threshold: 6x ATR% above 50-DMA (clamped 18% to 35%)
    trim_pct = round(float(np.clip(6.5 * atr_pct, 18.0, 35.0)), 1)
    trim_price = round(sma50 * (1.0 + trim_pct / 100.0), 2)

    band = StockBehaviorBand(
        behavior_profile=profile,
        atr14_pct=round(atr_pct, 2),
        annualized_vol_pct=round(ann_vol, 1),
        ideal_entry_low=ideal_low,
        ideal_entry_high=ideal_high,
        max_chase_limit_pct=MAX_ENTRY_EXTENSION_EMA20_PCT,
        trailing_stop_pct=trail_pct,
        trailing_stop_price=trail_price,
        structural_stop_price=struct_stop,
        trim_extension_pct=trim_pct,
        trim_target_price=trim_price,
    )
    return band.to_dict()


def rate_momentum_stock(
    row: dict,
    df: pd.DataFrame,
    is_current_holding: bool,
    hysteresis_rank: int = HYSTERESIS_BUFFER_RANK,
    board_size: int = PORTFOLIO_SIZE,
) -> dict:
    """Compute a 0-100 `momentum_health_score` and determine whether a stock is fit to hold/enter."""
    C = pd.to_numeric(df["Close"], errors="coerce").dropna()
    last_c = float(C.iloc[-1])
    ema20 = float(C.ewm(span=20, adjust=False).mean().iloc[-1])
    sma50 = float(C.rolling(50, min_periods=20).mean().iloc[-1])
    sma200_s = C.rolling(200, min_periods=200).mean()
    sma200 = float(sma200_s.iloc[-1]) if np.isfinite(sma200_s.iloc[-1]) else float(C.mean())

    above_200 = bool(last_c > sma200)
    above_50 = bool(last_c > sma50)
    dist_ema20_pct = (last_c - ema20) / ema20 * 100.0 if ema20 > 0 else 0.0
    dist_sma50_pct = (last_c - sma50) / sma50 * 100.0 if sma50 > 0 else 0.0

    rs_12_1 = float(row.get("relative_strength_12_1_pct") or 0.0)
    rs_6m = float(row.get("relative_strength_6m_pct") or 0.0)
    rs_3m = float(row.get("relative_strength_3m_pct") or 0.0)
    rs_1m = float(row.get("relative_strength_1m_pct") or 0.0)
    rs_line_ok = bool(row.get("rs_line_above_ema50", True))
    rank = row.get("leader_rank")

    structure = row.get("structure") or {}
    bands = compute_stock_behavior_bands(df, structure=structure)

    # Health Score Breakdown (0 - 100):
    # 1) 12-1M RS rank strength (0 - 40 pts)
    if rank is not None and rank <= 50:
        rank_pts = max(0.0, 40.0 * (1.0 - (rank - 1) / 45.0))
    else:
        rank_pts = 0.0

    # 2) Multi-horizon RS consistency (6M > 0, 3M > 0, 1M > -5, RS line > EMA50) (0 - 30 pts)
    horiz_pts = 0.0
    if rs_6m > 0:
        horiz_pts += 10.0
    if rs_3m > 0:
        horiz_pts += 10.0
    if rs_1m >= -3.0:
        horiz_pts += 5.0
    if rs_line_ok:
        horiz_pts += 5.0

    # 3) Trend & Pullback Geometry (0 - 30 pts)
    trend_pts = 0.0
    if above_200:
        trend_pts += 12.0
    if above_50:
        trend_pts += 10.0
    if -2.5 <= dist_ema20_pct <= 8.0:
        trend_pts += 8.0
    elif dist_ema20_pct > 15.0:
        trend_pts += 2.0  # stretched

    health_score = int(round(min(100.0, max(0.0, rank_pts + horiz_pts + trend_pts))))

    # Check disqualifying exit triggers for existing holdings
    exit_reasons = []
    warnings = []

    if not above_200:
        exit_reasons.append(f"Broke below 200-DMA ({last_c:.2f} < {sma200:.2f})")
    if rank is None or rank > hysteresis_rank:
        exit_reasons.append(f"Momentum rank decayed outside Top-{hysteresis_rank} buffer (rank={rank})")
    if last_c < bands["trailing_stop_price"] and not above_50:
        exit_reasons.append(
            f"Breached {bands['trailing_stop_pct']}% volatility trailing stop ({bands['trailing_stop_price']:.2f}) & 50-DMA"
        )
    if rs_3m < -8.0 and rs_1m < -6.0:
        exit_reasons.append(f"Severe medium-term RS breakdown (3M RS {rs_3m:+.1f}%, 1M RS {rs_1m:+.1f}%)")

    if not exit_reasons:
        if not above_50:
            warnings.append(f"Trading below 50-DMA ({sma50:.2f}); tighten stop to {bands['structural_stop_price']:.2f}")
        if rank is not None and board_size < rank <= hysteresis_rank:
            warnings.append(f"In hysteresis buffer zone (#{rank} of Top {board_size}); watch for further RS slip")
        if rs_1m < -5.0:
            warnings.append(f"Short-term 1M relative return lagging ({rs_1m:+.1f}%)")

    if exit_reasons:
        status = "EXIT_AND_REPLACE"
        action = "REMOVE / REPLACE"
    elif last_c >= bands["trim_target_price"] or dist_ema20_pct > MAX_ENTRY_EXTENSION_EMA20_PCT:
        status = "HOLD_EXTENDED_TRIM_WATCH"
        action = "HOLD (DO NOT ADD / WATCH FOR PARTIAL TRIM)" if is_current_holding else "WAIT FOR PULLBACK"
    elif warnings:
        status = "WARNING_WATCH"
        action = "HOLD ON TIGHT LEASH"
    else:
        status = "HOLD_STRONG"
        action = "HOLD" if is_current_holding else "BUY / ENTER"

    return {
        "health_score": health_score,
        "status": status,
        "recommended_action": action,
        "exit_reasons": exit_reasons,
        "warnings": warnings,
        "above_sma50": above_50,
        "above_sma200": above_200,
        "dist_from_20ema_pct": round(dist_ema20_pct, 2),
        "dist_from_50sma_pct": round(dist_sma50_pct, 2),
        "behavior_bands": bands,
    }


def evaluate_portfolio_rotation(
    frames_by_ticker: dict[str, pd.DataFrame],
    benchmark_df: pd.DataFrame,
    current_holdings: list[str] | None = None,
    liquid_top: int = LD.LIQUID_TOP,
    portfolio_size: int = PORTFOLIO_SIZE,
    hysteresis_rank: int = HYSTERESIS_BUFFER_RANK,
    account_capital: float = DEFAULT_ACCOUNT_CAPITAL,
) -> dict:
    """Build or update the 20-stock momentum portfolio, flagging exits, replacements, and cash slots."""
    universe = list(frames_by_ticker.keys())
    rows = []
    valid_frames = {}

    for t in universe:
        df = frames_by_ticker.get(t)
        if df is None or df.empty or len(df) < 260:
            continue
        m = LD.leader_metrics(df, benchmark_df, ticker=t)
        rows.append({"ticker": t, **m})
        valid_frames[t] = df

    # Rank all liquid stocks above 200-DMA (up to hysteresis_rank + 20 so we can see ranks 1..50)
    all_ranked, counts = LD.select_leaders(rows, liquid_top=liquid_top, board=max(len(rows), hysteresis_rank + 25))
    rank_by_ticker = {r["ticker"]: r for r in all_ranked}
    raw_by_ticker = {r["ticker"]: r for r in rows}

    # Enrich the top 40 ranked stocks + any current holdings with structure & behavior bands
    inspect_tickers = set(r["ticker"] for r in all_ranked[: max(portfolio_size * 2, hysteresis_rank + 10)])
    if current_holdings:
        inspect_tickers.update(current_holdings)

    enriched_by_ticker: dict[str, dict] = {}
    per_slot_capital = account_capital / max(portfolio_size, 1)

    for t in sorted(inspect_tickers):
        df = valid_frames.get(t)
        if df is None:
            continue
        base_row = dict(rank_by_ticker.get(t) or raw_by_ticker.get(t) or {"ticker": t})
        if "leader_rank" not in base_row:
            base_row["leader_rank"] = None
        LD.enrich_leader_with_swing_plan(base_row, df, benchmark_df, account_capital=account_capital)
        is_held = bool(current_holdings and t in current_holdings)
        rating = rate_momentum_stock(
            base_row,
            df,
            is_current_holding=is_held,
            hysteresis_rank=hysteresis_rank,
            board_size=portfolio_size,
        )
        base_row["portfolio_rating"] = rating
        last_c = float(base_row.get("last_close") or df["Close"].iloc[-1])
        target_shares = int(math.floor(per_slot_capital / last_c)) if last_c > 0 else 0
        base_row["slot_allocation"] = {
            "slot_weight_pct": round(100.0 / portfolio_size, 2),
            "slot_capital_inr": round(per_slot_capital, 2),
            "target_shares": target_shares,
            "deployed_capital_inr": round(target_shares * last_c, 2),
        }
        enriched_by_ticker[t] = base_row

    mkt_regime = LD.evaluate_benchmark_regime(benchmark_df)
    regime_bullish = bool(mkt_regime.get("above_sma200", True))

    # Determine initial vs existing portfolio state
    is_initial_build = not current_holdings
    held_list = list(dict.fromkeys(current_holdings or []))

    retained_holdings = []
    flagged_exits = []

    if is_initial_build:
        # Initial build: pick top `portfolio_size` eligible leaders (or 0 if regime is defensive cash)
        if regime_bullish:
            for r in all_ranked:
                if len(retained_holdings) >= portfolio_size:
                    break
                t = r["ticker"]
                er = enriched_by_ticker.get(t)
                if er and er["portfolio_rating"]["status"] != "EXIT_AND_REPLACE":
                    retained_holdings.append(er)
    else:
        for t in held_list:
            er = enriched_by_ticker.get(t)
            if er is None:
                flagged_exits.append({
                    "ticker": t,
                    "status": "EXIT_AND_REPLACE",
                    "exit_reasons": ["Missing or insufficient market data (<260 sessions)"],
                    "leader_rank": None,
                    "last_close": None,
                })
                continue
            rt = er["portfolio_rating"]
            if not regime_bullish:
                rt["status"] = "EXIT_AND_REPLACE"
                rt["exit_reasons"].append("Benchmark NIFTYBEES.NS below 200-DMA (mom12_1+mkt cash rule)")
            if rt["status"] == "EXIT_AND_REPLACE":
                flagged_exits.append(er)
            else:
                retained_holdings.append(er)

    # Identify replacement candidates for open slots
    open_slots = max(0, portfolio_size - len(retained_holdings))
    retained_set = {r["ticker"] for r in retained_holdings}
    replacements = []

    if regime_bullish and open_slots > 0 and not is_initial_build:
        for r in all_ranked[:portfolio_size]:
            if len(replacements) >= open_slots:
                break
            t = r["ticker"]
            if t in retained_set:
                continue
            er = enriched_by_ticker.get(t)
            if not er:
                continue
            rt = er["portfolio_rating"]
            # Replacement candidate must be healthy, above 50-DMA, and not overly extended
            if (
                rt["status"] == "HOLD_STRONG"
                and rt["above_sma50"]
                and rt["dist_from_20ema_pct"] <= MAX_ENTRY_EXTENSION_EMA20_PCT
            ):
                replacements.append(er)

    # Pair each flagged exit with a replacement or explicit cash fallback
    rotation_actions = []
    for idx, ex in enumerate(flagged_exits):
        rep = replacements[idx] if idx < len(replacements) else None
        if rep is not None:
            rotation_actions.append({
                "action_type": "REPLACE",
                "exit_ticker": ex["ticker"],
                "exit_close": ex.get("last_close"),
                "exit_rank": ex.get("leader_rank"),
                "exit_reasons": ex.get("portfolio_rating", {}).get("exit_reasons", ex.get("exit_reasons", [])),
                "enter_ticker": rep["ticker"],
                "enter_close": rep.get("last_close"),
                "enter_rank": rep.get("leader_rank"),
                "enter_rs_12_1_pct": rep.get("relative_strength_12_1_pct"),
                "enter_health_score": rep["portfolio_rating"]["health_score"],
                "enter_behavior_bands": rep["portfolio_rating"]["behavior_bands"],
                "enter_shares": rep["slot_allocation"]["target_shares"],
            })
        else:
            rotation_actions.append({
                "action_type": "REMOVE_TO_CASH",
                "exit_ticker": ex["ticker"],
                "exit_close": ex.get("last_close"),
                "exit_rank": ex.get("leader_rank"),
                "exit_reasons": ex.get("portfolio_rating", {}).get("exit_reasons", ex.get("exit_reasons", [])),
                "enter_ticker": None,
                "reason_no_replacement": (
                    "Benchmark below 200-DMA (Defensive Cash Regime)"
                    if not regime_bullish
                    else "No unheld Top-20 candidate meets entry & extension gates; hold slot in cash"
                ),
            })

    final_portfolio = retained_holdings + replacements
    final_portfolio.sort(key=lambda r: (r.get("leader_rank") or 999, r["ticker"]))
    cash_slots = max(0, portfolio_size - len(final_portfolio))

    # Next-in-line watchlist (ranks 1..30 not currently in final_portfolio)
    final_set = {r["ticker"] for r in final_portfolio}
    bench_candidates = [
        enriched_by_ticker[r["ticker"]]
        for r in all_ranked[:30]
        if r["ticker"] not in final_set and r["ticker"] in enriched_by_ticker
    ][:10]

    last_idx = benchmark_df.index[-1]
    as_of_str = last_idx.date().isoformat() if hasattr(last_idx, "date") else str(last_idx)[:10]

    out = {
        "as_of": as_of_str,
        "benchmark": A.RS_BENCHMARK,
        "market_regime": mkt_regime,
        "portfolio_rules": {
            "target_slots": portfolio_size,
            "hysteresis_hold_buffer_rank": hysteresis_rank,
            "liquidity_filter_top_n": liquid_top,
            "trend_gate": "Close > 200-DMA (entry also requires Close > 50-DMA & <= +12% from 20-EMA)",
            "regime_gate": "NIFTYBEES.NS > 200-DMA (else raise cash per mom12_1+mkt)",
        },
        "summary": {
            "mode": "INITIAL_BUILD" if is_initial_build else "DAILY_ROTATION_CHECK",
            "active_stock_slots": len(final_portfolio),
            "cash_slots": cash_slots,
            "cash_allocation_pct": round(100.0 * cash_slots / portfolio_size, 1),
            "retained_count": len(retained_holdings),
            "exits_flagged_count": len(flagged_exits),
            "replacements_found_count": len(replacements),
        },
        "rotation_actions": rotation_actions,
        "holdings": final_portfolio,
        "flagged_exits": flagged_exits,
        "replacements": replacements,
        "next_in_line_watchlist": bench_candidates,
    }
    return LD.sanitize_json(out)


def generate_gemini_gem_brief(portfolio_state: dict) -> str:
    """Generate File #1: Markdown Brief for a Gemini Gem (Deep Fundamental, Sector & Catalyst Analysis)
    designed so its output can be pasted directly into Claude alongside the ChatGPT Task output.
    """
    as_of = portfolio_state.get("as_of")
    mkt = portfolio_state.get("market_regime") or {}
    summary = portfolio_state.get("summary") or {}
    holdings = portfolio_state.get("holdings") or []
    actions = portfolio_state.get("rotation_actions") or []

    lines = [
        f"# Gemini Gem Task: Momentum Portfolio Fundamental & Sector Durability Audit ({as_of})",
        "",
        "## Instructions for Gemini Gem",
        "You are acting as the **Fundamental & Sector Durability Analyst** in a 3-AI committee (Gemini Gem + ChatGPT Task -> synthesized by Claude).",
        "Below is today's quantitative state of my **20-Stock NSE Momentum Portfolio** (`mom12_1+mkt` strategy).",
        "",
        "Please produce a structured Markdown report (`gemini_fundamental_audit.md`) that I can feed directly to Claude:",
        "1. **Rotation & Replacement Verdict**: For every stock flagged in **Section A (Today's Rotation Actions)**, evaluate whether the momentum breakdown/breakout is driven by a structural business shift (earnings deceleration, margin compression, sector headwinds) or temporary noise.",
        "2. **Earnings & Institutional Quality Score (1-5)**: For the active holdings in **Section B**, check recent quarterly revenue/EPS YoY growth, order-book/guidance visibility, and FII/DII/Mutual Fund ownership trends.",
        "3. **Sector Concentration Risk**: Identify if >25% of the active holdings cluster in a single theme (e.g., PSU Defense, Capital Goods, EMS, Pharma) and highlight which names have the strongest fundamental moat.",
        "4. **Behavior-Band Adjustment**: Recommend whether each stock deserves its full **High-Beta / Core / Low-Beta trailing stop buffer** or a tighter stop due to valuation stretch.",
        "",
        "## Quantitative Portfolio Summary",
        f"- **As of Date**: {as_of}",
        f"- **Market Regime (`{portfolio_state.get('benchmark')}`)**: {mkt.get('regime')} (Close: {mkt.get('benchmark_close')}, 200-DMA: {mkt.get('benchmark_sma200')})",
        f"- **Portfolio Occupancy**: {summary.get('active_stock_slots')}/20 Active Stocks | {summary.get('cash_slots')}/20 Cash Slots ({summary.get('cash_allocation_pct')}% Cash)",
        f"- **Today's Turnover**: {summary.get('exits_flagged_count')} Exits Flagged | {summary.get('replacements_found_count')} Replacements Queued",
        "",
        "## Section A: Today's Flagged Rotation Actions (Priority Review)",
    ]

    if not actions:
        lines.append("- **No rotation changes today.** All current holdings remain inside the Top-30 hysteresis buffer and above their 200-DMA.")
    else:
        for act in actions:
            if act["action_type"] == "REPLACE":
                lines.append(
                    f"- **REPLACE `{act['exit_ticker']}` -> BUY `{act['enter_ticker']}`**: "
                    f"Exit `{act['exit_ticker']}` (@ {act['exit_close']}, Rank #{act['exit_rank']}) due to `{'; '.join(act['exit_reasons'])}`. "
                    f"Replace with `{act['enter_ticker']}` (@ {act['enter_close']}, Rank #{act['enter_rank']}, 12-1 RS {act['enter_rs_12_1_pct']:+.1f}%, "
                    f"Health {act['enter_health_score']}/100, {act['enter_shares']} shares)."
                )
            else:
                lines.append(
                    f"- **REMOVE TO CASH `{act['exit_ticker']}`**: "
                    f"Exit `{act['exit_ticker']}` (@ {act['exit_close']}, Rank #{act['exit_rank']}) due to `{'; '.join(act['exit_reasons'])}`. "
                    f"No replacement (`{act['reason_no_replacement']}`)."
                )

    lines.extend([
        "",
        "## Section B: Active 20-Stock Momentum Portfolio & Behavior Bands",
        "",
        "| Slot | Ticker | RS Rank | Close | 12-1M RS | 6M RS | Health | Status | Profile | Ideal Entry Band | Trailing Stop (%) | Profit Trim Target |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for idx, h in enumerate(holdings, 1):
        rt = h.get("portfolio_rating") or {}
        bd = rt.get("behavior_bands") or {}
        lines.append(
            f"| {idx} | `{h['ticker']}` | #{h.get('leader_rank')} | {h.get('last_close'):.2f} | "
            f"{h.get('relative_strength_12_1_pct') or 0:+.1f}% | {h.get('relative_strength_6m_pct') or 0:+.1f}% | "
            f"{rt.get('health_score')}/100 | {rt.get('status')} | {bd.get('behavior_profile')} | "
            f"{bd.get('ideal_entry_low'):.1f}–{bd.get('ideal_entry_high'):.1f} | "
            f"{bd.get('trailing_stop_price'):.1f} (-{bd.get('trailing_stop_pct')}%) | "
            f"{bd.get('trim_target_price'):.1f} (+{bd.get('trim_extension_pct')}%) |"
        )

    return "\n".join(lines) + "\n"


def generate_chatgpt_task_brief(portfolio_state: dict) -> str:
    """Generate File #2: Markdown Brief for ChatGPT Daily Tasks (Live 72-Hour News, Earnings Calendar,
    Corporate Filings, Block Deals & Event Veto Audit) to pass to Claude alongside the Gemini Gem output.
    """
    as_of = portfolio_state.get("as_of")
    holdings = portfolio_state.get("holdings") or []
    actions = portfolio_state.get("rotation_actions") or []
    watchlist = portfolio_state.get("next_in_line_watchlist") or []

    priority_tickers = []
    for act in actions:
        if act.get("exit_ticker"):
            priority_tickers.append(act["exit_ticker"])
        if act.get("enter_ticker"):
            priority_tickers.append(act["enter_ticker"])
    for h in holdings:
        rt = h.get("portfolio_rating") or {}
        if rt.get("status") in ("WARNING_WATCH", "HOLD_EXTENDED_TRIM_WATCH") and h["ticker"] not in priority_tickers:
            priority_tickers.append(h["ticker"])
    if not priority_tickers:
        priority_tickers = [h["ticker"] for h in holdings[:8]]

    lines = [
        f"# ChatGPT Scheduled Task: 72-Hour News, Earnings & Event-Risk Veto Audit ({as_of})",
        "",
        "## Instructions for ChatGPT",
        "You are acting as the **Real-Time News, Corporate Filing & Event-Risk Auditor** in a 3-AI workflow (Gemini Gem + ChatGPT Task -> synthesized by Claude).",
        "Search live web sources, NSE/BSE corporate announcements, and financial news from the **last 72 hours** for the tickers below and output a clean Markdown report (`chatgpt_news_audit.md`) that I can upload directly to Claude:",
        "",
        "1. **Upcoming Earnings / Board Meetings (Next 7 Days)**: Flag exact quarterly results or dividend/split dates. (Rule: **VETO new entry** if earnings are within 3 trading sessions).",
        "2. **Regulatory, SEBI, Tax, or Auditor Red Flags**: Check for show-cause notices, plant inspections (USFDA/EHS), auditor resignations, or credit rating downgrades.",
        "3. **Promoter Pledges, Block/Bulk Deals & Insider Selling**: Report any block deals, QIP/OFS dilutions, or promoter stake sales.",
        "4. **Catalyst Classification (`Noise` vs `Structural`)**: For each priority ticker, label the current news environment as `CLEAR`, `POSITIVE_CATALYST`, `EARNINGS_IMMINENT_WAIT`, or `HARD_VETO`.",
        "",
        f"## Priority Audit List ({len(priority_tickers)} Focus Tickers Today)",
    ]

    for t in priority_tickers:
        lines.append(
            f"- **`{t}`**: Search `\"{t.replace('.NS', '')}\" NSE news filings earnings block deal last 7 days`"
        )

    lines.extend([
        "",
        "## Complete Active Holdings Reference & Stop/Target Levels",
        "",
        "| Ticker | Action / Status | Close | Entry Zone | Behavior Stop Price (%) | Trim Target Price (%) | Warnings / Notes |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for h in holdings:
        rt = h.get("portfolio_rating") or {}
        bd = rt.get("behavior_bands") or {}
        warn_str = "; ".join(rt.get("warnings") or []) or "Clean trend"
        lines.append(
            f"| `{h['ticker']}` | {rt.get('recommended_action')} | {h.get('last_close'):.2f} | "
            f"{bd.get('ideal_entry_low'):.1f}–{bd.get('ideal_entry_high'):.1f} | "
            f"{bd.get('trailing_stop_price'):.1f} (-{bd.get('trailing_stop_pct')}%) | "
            f"{bd.get('trim_target_price'):.1f} (+{bd.get('trim_extension_pct')}%) | {warn_str} |"
        )

    if watchlist:
        lines.extend([
            "",
            "## Next-in-Line Replacement Bench (Pre-Screen for Upcoming Rotations)",
            "- " + ", ".join(f"`{w['ticker']}` (#{w.get('leader_rank')}, Health {w['portfolio_rating']['health_score']}/100)" for w in watchlist[:5]),
        ])

    return "\n".join(lines) + "\n"


def format_portfolio_cli_report(state: dict) -> str:
    """Format a scannable terminal dashboard of the 20-stock momentum portfolio & daily rotation actions."""
    s = state.get("summary") or {}
    mkt = state.get("market_regime") or {}
    lines = [
        f"=== MOMENTUM PORTFOLIO BUILDER & DAILY ROTATION MONITOR (as of {state.get('as_of')}) ===",
        f"Mode: {s.get('mode')} | Benchmark: {state.get('benchmark')} @ {mkt.get('benchmark_close')} ({mkt.get('regime')})",
        f"Active Stock Slots: {s.get('active_stock_slots')}/20 | Cash Slots: {s.get('cash_slots')}/20 ({s.get('cash_allocation_pct')}% Cash) | "
        f"Exits Flagged: {s.get('exits_flagged_count')} | Replacements: {s.get('replacements_found_count')}",
        "",
    ]

    actions = state.get("rotation_actions") or []
    if actions:
        lines.append("--- TODAY'S ROTATION ACTIONS ---")
        for act in actions:
            if act["action_type"] == "REPLACE":
                lines.append(
                    f"  [REPLACE] SELL {act['exit_ticker']:<14} (@ {act['exit_close']}, Rk #{act['exit_rank']}) -> "
                    f"BUY {act['enter_ticker']:<14} (@ {act['enter_close']}, Rk #{act['enter_rank']}, "
                    f"Health {act['enter_health_score']}/100, {act['enter_shares']} sh) | Reason: {'; '.join(act['exit_reasons'])}"
                )
            else:
                lines.append(
                    f"  [TO CASH] SELL {act['exit_ticker']:<14} (@ {act['exit_close']}, Rk #{act['exit_rank']}) -> "
                    f"HOLD CASH ({act['reason_no_replacement']}) | Reason: {'; '.join(act['exit_reasons'])}"
                )
        lines.append("")
    else:
        lines.append("--- TODAY'S ROTATION ACTIONS: None (All holdings healthy inside Top-30 buffer) ---")
        lines.append("")

    hdr = (
        f"{'Slot':>4} {'Ticker':<14} {'Rk':>3} {'Close':>8} {'RS12-1':>8} {'Hlth':>4} "
        f"{'Status':<24} {'Profile':<18} {'Entry Band':<15} {'Trail Stop (%)':<16} {'Trim Target (%)'}"
    )
    lines.append(hdr)
    lines.append("-" * len(hdr))

    for i, h in enumerate(state.get("holdings", []), 1):
        rt = h.get("portfolio_rating") or {}
        bd = rt.get("behavior_bands") or {}
        eb = f"{bd.get('ideal_entry_low'):.0f}-{bd.get('ideal_entry_high'):.0f}"
        ts = f"{bd.get('trailing_stop_price'):.1f} (-{bd.get('trailing_stop_pct')}%)"
        tt = f"{bd.get('trim_target_price'):.1f} (+{bd.get('trim_extension_pct')}%)"
        lines.append(
            f"{i:>4} {h['ticker']:<14} #{h.get('leader_rank') or '-':>2} {h.get('last_close'):>8.2f} "
            f"{h.get('relative_strength_12_1_pct') or 0:>+7.1f}% {rt.get('health_score'):>4} "
            f"{rt.get('status'):<24} {bd.get('behavior_profile'):<18} {eb:<15} {ts:<16} {tt}"
        )

    return "\n".join(lines)


def load_previous_holdings(state_path: str) -> list[str] | None:
    if not os.path.exists(state_path):
        return None
    try:
        with open(state_path) as fh:
            data = json.load(fh)
        holdings = data.get("holdings") or []
        tickers = [h["ticker"] for h in holdings if isinstance(h, dict) and h.get("ticker")]
        return tickers if tickers else None
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--universe", default=LD.UNIVERSE_FILE, help="Path to Nifty 500 / 200 universe file")
    ap.add_argument("--holdings", help="Comma-separated list of current holdings (or auto-loads from --state-file)")
    ap.add_argument("--state-file", default=DEFAULT_STATE_PATH, help="Path to portfolio state JSON")
    ap.add_argument("--gemini-out", default=DEFAULT_GEMINI_BRIEF_PATH, help="Output Markdown brief for Gemini Gem")
    ap.add_argument("--chatgpt-out", default=DEFAULT_CHATGPT_BRIEF_PATH, help="Output Markdown brief for ChatGPT Task")
    ap.add_argument("--capital", type=float, default=DEFAULT_ACCOUNT_CAPITAL, help="Total portfolio capital (INR)")
    ap.add_argument("--portfolio-size", type=int, default=PORTFOLIO_SIZE, help="Target number of momentum stocks (default 20)")
    ap.add_argument("--hysteresis-rank", type=int, default=HYSTERESIS_BUFFER_RANK, help="Hold buffer rank (default 30)")
    ap.add_argument("--limit", type=int, help="Limit universe symbols for quick testing")
    args = ap.parse_args(argv)

    uni = LD.load_universe(args.universe)
    if args.limit:
        uni = uni[: args.limit]

    if args.holdings:
        curr_holdings = [s.strip() for s in args.holdings.split(",") if s.strip()]
    else:
        curr_holdings = load_previous_holdings(args.state_file)

    bench_df = A.fetch_ticker(A.RS_BENCHMARK)
    if bench_df is None or bench_df.empty:
        raise RuntimeError(f"Could not fetch benchmark {A.RS_BENCHMARK}")

    frames = {}
    for sym in uni:
        try:
            df = A.fetch_ticker(sym)
            if df is not None and not df.empty:
                frames[sym] = df
        except Exception as e:
            print(f"[warn] {sym}: {e}", file=sys.stderr)

    state = evaluate_portfolio_rotation(
        frames_by_ticker=frames,
        benchmark_df=bench_df,
        current_holdings=curr_holdings,
        portfolio_size=args.portfolio_size,
        hysteresis_rank=args.hysteresis_rank,
        account_capital=args.capital,
    )

    os.makedirs(os.path.dirname(args.state_file) or ".", exist_ok=True)
    with open(args.state_file, "w") as fh:
        json.dump(state, fh, indent=2, allow_nan=False)

    gem_md = generate_gemini_gem_brief(state)
    os.makedirs(os.path.dirname(args.gemini_out) or ".", exist_ok=True)
    with open(args.gemini_out, "w") as fh:
        fh.write(gem_md)

    gpt_md = generate_chatgpt_task_brief(state)
    os.makedirs(os.path.dirname(args.chatgpt_out) or ".", exist_ok=True)
    with open(args.chatgpt_out, "w") as fh:
        fh.write(gpt_md)

    print(format_portfolio_cli_report(state))
    print(f"\nSaved state -> {args.state_file}")
    print(f"Saved Gemini Gem brief -> {args.gemini_out}")
    print(f"Saved ChatGPT Task brief -> {args.chatgpt_out}")


if __name__ == "__main__":
    main()