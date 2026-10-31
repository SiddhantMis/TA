import json
import os
from datetime import date, datetime, time as dt_time

import analyzer as analyzer_module
from analyzer import WATCHLIST, IST, RS_BENCHMARK, RS_LEADER_BOARD_SIZE, run_screen
from alerts import send_discord_alert, send_discord_failure

OUTPUT_PATH = "docs/latest_screen.json"
EOD_CUTOFF = dt_time(19, 0)


def enable_settled_daily_candle() -> None:
    """After the EOD cutoff, keep today's completed daily bar if Yahoo has it."""

    def _identity(data):
        return data

    analyzer_module._drop_unsettled_today = _identity


def check_total_failure(watchlist: list, results: list) -> str | None:
    """Returns a failure message if every ticker in a non-empty watchlist
    produced zero results, else None. Pulled out of the __main__ block
    specifically so this can be unit-tested directly -- it previously
    lived inline, untestable without a subprocess or a full yfinance
    mock, and shipped with zero test coverage despite being the
    highest-severity fix in that commit."""
    if watchlist and not results:
        return (
            f"0 of {len(watchlist)} tickers produced a score. Treat this as a data "
            "fetch/scoring failure, not a normal zero-candidate day."
        )
    return None


def check_stale_after_cutoff(run_ts: datetime, results: list, cutoff: dt_time) -> str | None:
    """After the EOD cutoff, today's candle should be present -- the
    drop-unsettled-today guard was disabled specifically to allow it
    through. This verifies that assumption held: if it's past cutoff
    and the latest scored date still isn't today, Yahoo genuinely
    hasn't published yet, and that needs to fail loudly rather than
    silently ship yesterday's close as if it were current. Pulled out
    for the same reason as check_total_failure -- this shipped with
    zero test coverage inside the __main__ block, untestable without
    a subprocess or a full yfinance mock."""
    if run_ts.time() < cutoff or not results:
        return None
    latest_score_date = max(date.fromisoformat(r["date"]) for r in results)
    if latest_score_date != run_ts.date():
        return (
            f"Latest screener data is {latest_score_date.isoformat()}, not today's close "
            f"({run_ts.date().isoformat()}). Yahoo has not published the completed EOD candle yet."
        )
    return None


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

    # flag = pattern/checklist gate; trade_ok = R:R gate (analyzer.build_trade_plan).
    # Only setups passing both are "flagged"; the rest are listed as watch-only so
    # a near-miss is visible instead of silently vanishing.
    flagged = [r for r in results if r["flag"] and r.get("trade_ok")]
    watch = [r for r in results if r["flag"] and not r.get("trade_ok")]
    momentum_leaders = sorted(
        (r for r in results if r.get("relative_strength_12_1_pct") is not None),
        key=lambda r: (r.get("leader_rank") or float("inf"), r["ticker"]),
    )[:RS_LEADER_BOARD_SIZE]
    breadth = (round(sum(1 for r in results if r["above_sma50"]) / len(results), 2)
               if results else None)

    # Write results BEFORE attempting the Discord post. A dead webhook or
    # a network blip shouldn't cost you the actual screening output --
    # that's the thing this whole pipeline exists to produce. The alert
    # is a notification on top of that, not a precondition for it.
    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump({
            "run_timestamp": run_ts.isoformat(),
            "note": "Every 'date'/'close' below is the last COMPLETE session as of run_timestamp, "
                     "never a same-day live price. The momentum leaderboard ranks 12-1 adjusted "
                     "returns relative to NIFTYBEES within this fixed watchlist; it is descriptive "
                     "and is not a validated buy signal. 'flagged' remains the legacy reversal "
                     "checklist and is also for manual review only.",
            "all": results,
            "momentum": {
                "benchmark": RS_BENCHMARK,
                "available": bool(momentum_leaders),
                "definition": "12-1 adjusted return excess versus benchmark; latest 21 sessions skipped",
                "leader_universe_size": sum(1 for r in results if r.get("leader_rank") is not None),
            },
            "momentum_leaders": momentum_leaders,
            "flagged": flagged,
            "watch": watch,
            "breadth_above_sma50": breadth,
        }, f, indent=2, default=str)

    send_discord_alert(flagged, run_timestamp=run_ts, watch=watch, breadth=breadth,
                       leaders=momentum_leaders, benchmark=RS_BENCHMARK)
    print(f"Screened {len(results)} tickers, {len(momentum_leaders)} momentum leaders, "
          f"{len(flagged)} flagged, {len(watch)} watch-only (failed R:R gate), "
          f"breadth {breadth}. Data as of run at {run_ts.isoformat()}.")
    print(f"Written to {OUTPUT_PATH} for the Pages site.")
