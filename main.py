import json
import math
import os
from datetime import date, datetime, time as dt_time

import analyzer as analyzer_module
from analyzer import WATCHLIST, IST, run_screen
from alerts import send_discord_alert, send_discord_failure

OUTPUT_PATH = "docs/latest_screen.json"
EOD_CUTOFF = dt_time(19, 0)


def enable_settled_daily_candle() -> None:
    """After the EOD cutoff, keep today's completed daily bar if Yahoo has it."""

    def _identity(data):
        return data

    analyzer_module._drop_unsettled_today = _identity


def check_total_failure(watchlist: list, results: list) -> str | None:
    if watchlist and not results:
        return (
            f"0 of {len(watchlist)} tickers produced a score. Treat this as a data "
            "fetch/scoring failure, not a normal zero-candidate day."
        )
    return None


def check_stale_after_cutoff(run_ts: datetime, results: list, cutoff: dt_time) -> str | None:
    if run_ts.time() < cutoff or not results:
        return None
    latest_score_date = max(date.fromisoformat(r["date"]) for r in results)
    if latest_score_date != run_ts.date():
        return (
            f"Latest screener data is {latest_score_date.isoformat()}, not today's close "
            f"({run_ts.date().isoformat()}). Yahoo has not published the completed EOD candle yet."
        )
    return None


def sanitize_for_json(obj):
    """Recursively converts NaN and Infinity floats to None to guarantee valid RFC-8259 JSON."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    return obj


if __name__ == "__main__":
    run_ts = datetime.now(IST)
    if run_ts.time() >= EOD_CUTOFF:
        enable_settled_daily_candle()

    results = run_screen()

    failure_message = check_total_failure(WATCHLIST, results)
    if failure_message:
        send_discord_failure(failure_message, run_timestamp=run_ts)
        raise RuntimeError(failure_message)

    stale_message = check_stale_after_cutoff(run_ts, results, EOD_CUTOFF)
    if stale_message:
        send_discord_failure(stale_message, run_timestamp=run_ts)
        raise RuntimeError(stale_message)

    flagged = [r for r in results if r["flag"] and r.get("trade_ok")]
    watch = [r for r in results if r["flag"] and not r.get("trade_ok")]
    leaders = sorted(
        [r for r in results if r.get("is_leader")],
        key=lambda r: r.get("rs_rank") or 999
    )
    breadth = (round(sum(1 for r in results if r["above_sma50"]) / len(results), 2)
               if results else None)

    # ChatGPT Daily Task Payload
    chatgpt_task_payload = {
        "task_instructions": (
            "Review today's flagged setups and relative strength leaders for tomorrow's open. "
            "For each candidate: (1) Run news/catalyst search for the last 72 hours, "
            "(2) Check for upcoming earnings releases in next 3 trading days, "
            "(3) Apply the trade veto checklist."
        ),
        "market_summary": {
            "run_timestamp": run_ts.isoformat(),
            "market_breadth_above_sma50": breadth,
            "market_regime": "Favorable / Bullish" if (breadth and breadth >= 0.5) else "Defensive / Weak",
            "total_screened": len(results),
            "flagged_setups_count": len(flagged),
            "market_leaders_count": len(leaders),
        },
        "flagged_candidates": [
            {
                "ticker": r["ticker"],
                "close": r["close"],
                "candlestick_pattern": r["pattern"],
                "geometric_pattern": r.get("geo_pattern"),
                "rs_rank": r.get("rs_rank"),
                "rs_percentile": r.get("rs_percentile"),
                "is_leader": r.get("is_leader"),
                "support_level": r["support_level"],
                "support_touches": r["support_touches"],
                "support_touch_dates": r.get("support_dates", []),
                "support_bounce_quality": r.get("support_quality"),
                "support_role_reversal": r.get("support_role_reversal"),
                "support_weekly_confluence": r.get("support_weekly_confluence"),
                "trade_plan": {
                    "entry_buy_stop": r.get("entry"),
                    "stop_loss": r.get("stop"),
                    "target_price": r.get("target"),
                    "risk_reward_ratio": r.get("rr"),
                    "risk_percent": r.get("risk_pct"),
                    "suggested_shares": r.get("suggested_shares"),
                    "capital_required": r.get("capital_required"),
                    "rupee_risk": r.get("risk_amount_rupees"),
                },
                "news_audit_query": r.get("ai_audit_prompt"),
                "veto_rule": r.get("ai_veto_checklist"),
            }
            for r in flagged
        ],
        "top_market_leaders": [
            {
                "ticker": r["ticker"],
                "close": r["close"],
                "rs_rank": r.get("rs_rank"),
                "rs_percentile": r.get("rs_percentile"),
                "rs_trend": r.get("rs_trend"),
                "trend": r["trend"],
                "recommendation": r["recommendation"],
            }
            for r in leaders[:10]
        ]
    }

    raw_payload = {
        "run_timestamp": run_ts.isoformat(),
        "note": "Every 'date'/'close' below is the last COMPLETE session as of run_timestamp, "
                 "never a same-day live price. A flag here is for planning tomorrow's open — "
                 "not for acting before today's 3:30 PM close.",
        "chatgpt_daily_task": chatgpt_task_payload,
        "all": results,
        "flagged": flagged,
        "watch": watch,
        "leaders": leaders,
        "breadth_above_sma50": breadth,
    }

    clean_payload = sanitize_for_json(raw_payload)

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(clean_payload, f, indent=2, default=str)

    send_discord_alert(flagged, run_timestamp=run_ts, watch=watch, breadth=breadth)
    print(f"Screened {len(results)} tickers, {len(flagged)} flagged, {len(watch)} watch-only, {len(leaders)} leaders, breadth {breadth}. Written to {OUTPUT_PATH}.")
