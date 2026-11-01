#!/usr/bin/env python3
"""Daily momentum leaders over a WIDE, LIQUID universe -- the part of this project with evidence.

Rule (the same one tested in portfolio.py, 'liquid500' universe, 2017-2026):
  universe  Nifty 500 list (universe/nifty500.txt, versioned)
  liquid    the top LIQUID_TOP names by trailing 126-day average traded value, as of the latest close
  trend     close above its own 200-day average
  rank      12-1 return (252 sessions back to 21 back) relative to NIFTYBEES -- highest first

What the backtest said (see results/portfolio_report_liquid500.md): holding the top 20 of this list
monthly beat holding the same universe equal-weight by roughly 12 points a year over 9 years, but with
a deeper drawdown (about -34% vs -13% for the Nifty 50 in the held-out period), and survivorship bias
(failed companies are missing) means the true edge is smaller. It is a ranking, not an entry signal.
Each leader also gets the existing structure read (trend, support/resistance ladders with touches).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

import analyzer as A
from position_sizer import calculate_position_size, DEFAULT_ACCOUNT_CAPITAL, DEFAULT_RISK_PCT
import research as R

UNIVERSE_FILE = "universe/nifty500.txt"
FALLBACK_UNIVERSE_FILES = (
    "universe/nifty500.txt",
    "results/nifty500_symbols.txt",
    "results/nifty200_symbols.txt",
)
LIQUID_TOP = 200
BOARD_SIZE = 20
TV_WINDOW = 126
EVIDENCE = (
    "Backtest 2017-2026, monthly top-20 by 12-1 relative strength among the point-in-time top-200 liquid "
    "Nifty 500 names above their 200-day average: ~28.3%/yr vs ~15.3% for holding the same universe equal-weight "
    "and ~10.5% for the Nifty 50 (with market regime filter >200-DMA cutting OOS max drawdown from -33.6% to -14.8%). "
    "Survivorship bias remains (failed companies are missing), the held-out period is 3 years, and nothing here is "
    "validated live. See results/portfolio_report_liquid500.md."
)

# Track record of the two entry setups INSIDE the leaders, filled from results/leader_setups_report.md.
# Until that test has been read, they are shown as unvalidated.
SETUP_RECORD = (
    "Tested 2017-26 inside the leaders: breakout55 and pullback20 did not beat entering on any leader day "
    "(last 3 yrs avg R -0.06 / -0.04 vs -0.02, all within noise). Both are unvalidated; the plan is a risk calculator."
)


def sanitize_json(obj):
    """Recursively convert NaN/Infinity/numpy scalars to RFC-8259 compliant JSON types."""
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(x) for x in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        val = float(obj)
        return val if math.isfinite(val) else None
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def load_universe(path: str = UNIVERSE_FILE) -> list[str]:
    candidates = [path] + [f for f in FALLBACK_UNIVERSE_FILES if f != path]
    for p in candidates:
        if os.path.exists(p):
            with open(p) as fh:
                symbols = list(dict.fromkeys(s.strip() for s in fh if s.strip() and not s.startswith("#")))
                if symbols:
                    return symbols
    return []


def evaluate_benchmark_regime(benchmark_df: pd.DataFrame) -> dict:
    """Evaluates whether the market regime filter (>200-DMA) from mom12_1+mkt is active."""
    if benchmark_df is None or benchmark_df.empty:
        return {"regime_ok": False, "above_sma200": False, "benchmark": A.RS_BENCHMARK, "reason": "No benchmark data"}
    close = pd.to_numeric(benchmark_df["Close"], errors="coerce").dropna()
    if len(close) < 200:
        return {"regime_ok": False, "above_sma200": False, "benchmark": A.RS_BENCHMARK, "reason": "Benchmark history < 200 bars"}
    sma200 = float(close.rolling(200).mean().iloc[-1])
    last_close = float(close.iloc[-1])
    is_bull = last_close > sma200
    return {
        "benchmark": A.RS_BENCHMARK,
        "last_close": round(last_close, 2),
        "sma200": round(sma200, 2),
        "above_sma200": is_bull,
        "regime": "bull" if is_bull else "bear",
        "regime_ok": is_bull,
        "filter_active": is_bull,
        "description": "Benchmark > 200-DMA (Market regime filter active; risk-on)" if is_bull else "Benchmark <= 200-DMA (Market regime filter triggers cash/defensive posture)",
    }


def entry_plan(df: pd.DataFrame, benchmark_df: pd.DataFrame) -> dict:
    """What would be a buy today, and what the risk would be. Uses research.py's rules unchanged:
    entry next open; initial stop 2 x ATR14 below the fill; exit if price falls to the highest close minus
    3 x ATR14 (ATR fixed at the signal); 60-session time stop. Sizing is per Rs 1,000 of risk so it scales to any account."""
    bc = pd.to_numeric(benchmark_df["Close"], errors="coerce")
    d = R.prep(df, bc > bc.rolling(200).mean())
    d["rs"] = np.nan
    sg = R.signals(d)
    last = d.iloc[-1]
    close, atr = float(last.Close), float(last.atr)
    risk = R.ATR_STOP * atr
    fired = [n for n in ("breakout55", "pullback20") if bool(sg[n].iloc[-1])]
    return {
        "fired": fired,
        "ref_close": round(close, 2), "atr14": round(atr, 2),
        "stop_if_filled_at_ref": round(close - risk, 2),
        "risk_per_share": round(risk, 2), "risk_pct": round(100 * risk / close, 1),
        "shares_per_1000_risk": int(1000 // round(risk, 2)) if round(risk, 2) > 0 else None,   # from the number shown
        "triggers": {"breakout55_close_above": round(float(d.High.rolling(55).max().iloc[-1]), 2),
                     "pullback20_ema20": round(float(last.ema20), 2)},
        "exit_rule": f"stop {R.ATR_STOP}xATR under the fill; then exit at highest close - {R.ATR_TRAIL}xATR; 60-session time stop",
    }


def classify_swing_setup(df: pd.DataFrame, structure: Optional[dict] = None, atr: Optional[float] = None) -> dict:
    """Classifies leader price action into an actionable swing state."""
    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    vol = pd.to_numeric(df["Volume"], errors="coerce")
    last_c = float(close.iloc[-1])

    ema20_series = close.ewm(span=20, adjust=False).mean()
    ema20 = float(ema20_series.iloc[-1])
    ema20_prev = float(ema20_series.iloc[-2]) if len(ema20_series) > 1 else ema20
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else last_c

    if atr is None:
        tr = np.maximum(high - low, np.maximum((high - close.shift(1)).abs(), (low - close.shift(1)).abs()))
        atr = float(tr.rolling(14).mean().iloc[-1])

    # Check 1: Extended wait for pullback (stretched > 12% above 20-EMA)
    pct_from_ema20 = (last_c - ema20) / ema20 if ema20 > 0 else 0.0
    if pct_from_ema20 > 0.12:
        return {
            "setup": "extended_wait_for_pullback",
            "actionable_now": False,
            "pct_from_ema20": round(pct_from_ema20 * 100, 1),
            "reason": f"Stretched {pct_from_ema20*100:.1f}% above 20-EMA; wait for pullback to avoid chasing",
        }

    # Check 2: Breakout 55d
    if len(high) >= 56:
        prior_55_high = float(high.iloc[-56:-1].max())
        vol_ma20 = float(vol.rolling(20).mean().iloc[-1]) if len(vol) >= 20 else 1.0
        last_vol = float(vol.iloc[-1])
        if last_c >= prior_55_high and last_vol >= 1.0 * vol_ma20:
            return {
                "setup": "breakout_55d",
                "actionable_now": True,
                "breakout_level": round(prior_55_high, 2),
                "volume_expansion": round(last_vol / vol_ma20, 2) if vol_ma20 > 0 else 1.0,
                "reason": f"Fresh 55-day high breakout above {prior_55_high:.2f} on {last_vol/vol_ma20:.1f}x volume",
            }

    # Check 3: Pullback 20-EMA or support
    near_ema20 = abs(last_c - ema20) / ema20 <= 0.025 and ema20 >= ema20_prev
    sup_level = structure.get("support_level") if structure else None
    sup_touches = structure.get("support_touches", 0) if structure else 0
    near_sup = False
    if sup_level is not None and sup_level > 0:
        near_sup = abs(last_c - sup_level) / last_c <= 0.025 and (sup_touches or 0) >= 2

    if near_ema20 or near_sup:
        return {
            "setup": "pullback_20ema_or_support",
            "actionable_now": True,
            "ema20": round(ema20, 2),
            "support_level": round(sup_level, 2) if sup_level else None,
            "support_touches": sup_touches,
            "reason": "Pullback within 2.5% of rising 20-EMA or testing multi-touch support zone",
        }

    # Check 4: Tight consolidation (5-day range <= 1.8 * ATR14 above 50-DMA)
    if len(high) >= 5 and last_c > sma50:
        range_5d = float(high.iloc[-5:].max() - low.iloc[-5:].min())
        if range_5d <= 1.8 * atr:
            return {
                "setup": "tight_consolidation",
                "actionable_now": True,
                "range_5d": round(range_5d, 2),
                "atr14": round(atr, 2),
                "ratio_to_atr": round(range_5d / atr, 2) if atr > 0 else 1.0,
                "reason": f"5-day consolidation range ({range_5d:.2f}) <= 1.8x ATR ({atr:.2f}) above 50-DMA",
            }

    # Default
    return {
        "setup": "trend_continuation",
        "actionable_now": False,
        "reason": "Trending above 200-DMA; no specific entry trigger fired",
    }


def build_leader_trade_plan(
    df: pd.DataFrame,
    structure: Optional[dict] = None,
    capital: float = DEFAULT_ACCOUNT_CAPITAL,
    risk_pct: float = DEFAULT_RISK_PCT,
) -> dict:
    """Builds an actionable trade & position sizing plan for a momentum leader."""
    close = float(df["Close"].iloc[-1])
    high = float(df["High"].iloc[-1])
    low = float(df["Low"].iloc[-1])

    # ATR14
    h_s = pd.to_numeric(df["High"], errors="coerce")
    l_s = pd.to_numeric(df["Low"], errors="coerce")
    c_s = pd.to_numeric(df["Close"], errors="coerce")
    tr = np.maximum(h_s - l_s, np.maximum((h_s - c_s.shift(1)).abs(), (l_s - c_s.shift(1)).abs()))
    atr14 = float(tr.rolling(14).mean().iloc[-1])
    if not np.isfinite(atr14) or atr14 <= 0:
        atr14 = max(0.01 * close, 1.0)

    entry_buy_stop = round(high * 1.002, 2)
    support_lvl = (structure or {}).get("support_level")
    if support_lvl is not None and 0 < (entry_buy_stop - support_lvl) <= 3.0 * atr14:
        stop_loss = round(support_lvl * 0.995, 2)
    else:
        stop_loss = round(entry_buy_stop - 2.0 * atr14, 2)

    risk_per_share = entry_buy_stop - stop_loss
    if risk_per_share <= 0:
        risk_per_share = 2.0 * atr14
        stop_loss = round(entry_buy_stop - risk_per_share, 2)

    resistance_ladder = (structure or {}).get("resistance_ladder") or []
    valid_res = [r["level"] for r in resistance_ladder if r.get("level", 0) > entry_buy_stop + 1.2 * risk_per_share]
    if valid_res:
        target_price = round(min(valid_res), 2)
    else:
        target_price = round(entry_buy_stop + 2.5 * risk_per_share, 2)

    sizing = calculate_position_size(
        entry=entry_buy_stop,
        stop=stop_loss,
        target=target_price,
        capital=capital,
        risk_pct=risk_pct,
    )

    gross_rr = round((target_price - entry_buy_stop) / risk_per_share, 2) if risk_per_share > 0 else 0.0
    cost_per_share = entry_buy_stop * 0.0030
    net_reward = max(0.0, (target_price - entry_buy_stop) - cost_per_share)
    net_risk = risk_per_share + cost_per_share
    net_rr = round(net_reward / net_risk, 2) if net_risk > 0 else 0.0

    return {
        "entry_buy_stop": entry_buy_stop,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "atr14": round(atr14, 2),
        "risk_per_share": round(risk_per_share, 2),
        "risk_pct": round(100 * risk_per_share / entry_buy_stop, 2),
        "gross_rr": gross_rr,
        "net_rr": net_rr,
        "suggested_shares": sizing.shares,
        "capital_required": sizing.capital_required,
        "capital_pct": sizing.capital_pct,
        "rupee_risk": sizing.risk_amount,
        "sizing_warning": sizing.warning,
    }


def leader_metrics(df: pd.DataFrame, benchmark_df: pd.DataFrame, ticker: str = "") -> dict:
    """Relative strength (analyzer's stale/coverage-gated version) plus liquidity and trend for one stock."""
    m = A.relative_strength_metrics(df, benchmark_df)
    close = pd.to_numeric(df["Close"], errors="coerce")
    vol = pd.to_numeric(df["Volume"], errors="coerce")
    sma200 = close.rolling(200, min_periods=200).mean().iloc[-1]
    tv = (close * vol).rolling(TV_WINDOW, min_periods=100).mean().iloc[-1]
    hi252 = pd.to_numeric(df["High"], errors="coerce").rolling(252, min_periods=200).max().iloc[-1]
    last = float(close.iloc[-1])
    m.update({
        "last_close": round(last, 2),
        "sma200": round(float(sma200), 2) if np.isfinite(sma200) else None,
        "above_sma200": bool(np.isfinite(sma200) and last > sma200),
        "traded_value_126d": float(tv) if np.isfinite(tv) else None,
        "pct_below_52w_high": round(100 * (1 - last / float(hi252)), 1) if np.isfinite(hi252) and hi252 > 0 else None,
    })
    return m


def enrich_leader_with_swing_plan(
    r: dict,
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    account_capital: float = DEFAULT_ACCOUNT_CAPITAL,
    risk_pct: float = DEFAULT_RISK_PCT,
) -> dict:
    """Enriches a leader row dictionary with structure, research entry plan, swing setup, and trade plan."""
    t = r.get("ticker", "")
    s = None
    if df is not None:
        try:
            res = A.score_ticker(df, t, benchmark_df)
            s = A.asdict(res) if res else None
        except Exception as e:
            print(f"[structure] {t}: {e}", file=sys.stderr)
    r["structure"] = None if s is None else {k: s.get(k) for k in (
        "trend", "support_level", "support_touches", "support_dates", "support_days_ago",
        "support_quality", "support_ladder", "resistance_ladder",
        "volume_ratio", "rsi", "above_sma50", "support_weekly_confluence", "support_role_reversal")}
    r["traded_value_cr"] = round(r["traded_value_126d"] / 1e7, 1) if r.get("traded_value_126d") else None
    if df is not None:
        try:
            r["plan"] = entry_plan(df, benchmark_df)
            res_levels = [x["level"] for x in ((r["structure"] or {}).get("resistance_ladder") or []) if x["level"] > r["plan"]["ref_close"]]
            r["plan"]["rr_to_next_resistance"] = (round((min(res_levels) - r["plan"]["ref_close"]) / r["plan"]["risk_per_share"], 1)
                                                  if res_levels and r["plan"]["risk_per_share"] else None)
            r["swing_setup"] = classify_swing_setup(df, r["structure"], r["plan"].get("atr14"))
            r["trade_plan"] = build_leader_trade_plan(df, r["structure"], capital=account_capital, risk_pct=risk_pct)
        except Exception as e:
            r["plan"] = None
            r["swing_setup"] = None
            r["trade_plan"] = None
            print(f"[plan] {t}: {e}", file=sys.stderr)
    return r


def select_leaders(rows: list, liquid_top: int = LIQUID_TOP, board: int = BOARD_SIZE):
    """rows: [{'ticker', **leader_metrics}] -> (leaders, counts). Pure function, no I/O."""
    ok = [r for r in rows if r.get("relative_strength_status") == "ok"
          and r.get("relative_strength_12_1_pct") is not None and r.get("traded_value_126d")]
    ok.sort(key=lambda r: -r["traded_value_126d"])
    for i, r in enumerate(ok, 1):
        r["liquidity_rank"] = i
    liquid = [r for r in ok if r["liquidity_rank"] <= liquid_top]
    trend = [r for r in liquid if r["above_sma200"]]
    trend.sort(key=lambda r: (-r["relative_strength_12_1_pct"], r["ticker"]))
    for i, r in enumerate(trend, 1):
        r["leader_rank"] = i
    counts = {"universe": len(rows), "rankable": len(ok), "liquid": len(liquid), "above_200dma": len(trend)}
    return trend[:board], counts


def run_leaders(universe=None, benchmark_df=None, liquid_top=LIQUID_TOP, board=BOARD_SIZE, sleep=None,
                max_seconds=2700, capital=DEFAULT_ACCOUNT_CAPITAL, risk_pct=DEFAULT_RISK_PCT):
    universe = universe or load_universe()
    if benchmark_df is None:
        benchmark_df = A.fetch_ticker(A.RS_BENCHMARK)
    if benchmark_df is None or benchmark_df.empty:
        raise RuntimeError(f"no benchmark data for {A.RS_BENCHMARK}")
    sleep = A.YF_SLEEP_SECONDS if sleep is None else sleep
    regime = evaluate_benchmark_regime(benchmark_df)
    rows, frames, failed = [], {}, []
    started, partial = time.time(), False
    for t in universe:
        if time.time() - started > max_seconds:        # a slow Yahoo day must not hold the whole daily run hostage
            partial = True
            failed.append(t)
            continue
        try:
            df = A.fetch_ticker(t)
            if df is None or df.empty or len(df) < 260:
                failed.append(t)
            else:
                rows.append({"ticker": t, **leader_metrics(df, benchmark_df)})
                frames[t] = df
        except Exception as e:                                   # one bad symbol must not sink the run
            failed.append(t)
            print(f"[error] {t}: {e}", file=sys.stderr)
        time.sleep(sleep)
    leaders, counts = select_leaders(rows, liquid_top, board)
    for r in leaders:
        t = r["ticker"]
        df_t = frames.get(t)
        enrich_leader_with_swing_plan(r, df_t, benchmark_df, account_capital=capital, risk_pct=risk_pct)
    counts["failed_to_load"] = len(failed)
    counts["partial_scan_time_limit"] = partial
    counts["load_coverage_pct"] = round(100 * (len(universe) - len(failed)) / len(universe), 1) if universe else 0.0
    out = {
        "as_of": benchmark_df.index[-1].date().isoformat(), "benchmark": A.RS_BENCHMARK,
        "market_regime": regime,
        "definition": (f"Top {liquid_top} by 126-day traded value of the Nifty 500 list, close above 200-day average, "
                       "ranked by 12-1 return relative to the benchmark (latest 21 sessions skipped)."),
        "evidence": EVIDENCE, "setup_record": SETUP_RECORD, "counts": counts, "failed_tickers": failed[:60], "leaders": leaders,
    }
    return sanitize_json(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--universe", default=UNIVERSE_FILE, help="path to universe text file")
    ap.add_argument("--liquid-top", type=int, default=LIQUID_TOP, help="top liquid count")
    ap.add_argument("--board", type=int, default=BOARD_SIZE, help="board size")
    ap.add_argument("--capital", type=float, default=1_000_000.0, help="account capital in INR")
    ap.add_argument("--risk-pct", type=float, default=0.01, help="risk percentage per trade")
    ap.add_argument("--out", default="results/leaders_preview.json")
    ap.add_argument("--limit", type=int, help="only the first N symbols (for quick checks)")
    a = ap.parse_args(argv)
    uni = load_universe(a.universe)
    if a.limit:
        uni = uni[:a.limit]
    t0 = datetime.now()
    out = run_leaders(universe=uni, liquid_top=a.liquid_top, board=a.board, capital=a.capital, risk_pct=a.risk_pct)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"as of {out['as_of']}  counts {out['counts']}  ({(datetime.now() - t0).seconds}s)")
    for r in out["leaders"]:
        plan = r.get("trade_plan") or {}
        setup = r.get("swing_setup") or {}
        setup_tag = f"[{setup.get('setup', '')}]" if setup.get('actionable_now') else ""
        shares = f"{plan.get('suggested_shares')} sh (₹{plan.get('capital_required'):,.0f})" if plan.get('suggested_shares') else ""
        print(f"#{r['leader_rank']:>2} {r['ticker']:<14} RS12-1 {r['relative_strength_12_1_pct']:>+7.1f}pp  "
              f"6m {r.get('relative_strength_6m_pct') or 0:>+6.1f}  1m {r.get('relative_strength_1m_pct') or 0:>+6.1f}  "
              f"{r['pct_below_52w_high']}% off high  value {r['traded_value_cr']} cr {setup_tag} {shares}")


if __name__ == "__main__":
    main()
