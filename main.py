import json
import os
import sys
from datetime import date, datetime, time as dt_time

import analyzer as analyzer_module
from analyzer import WATCHLIST, IST, RS_BENCHMARK, RS_LEADER_BOARD_SIZE, run_screen
from alerts import send_discord_alert, send_discord_failure
import leaders as wide

OUTPUT_PATH = "docs/latest_screen.json"
EOD_CUTOFF = dt_time(19, 0)


def summarize_scan_coverage(watchlist: list[str], results: list[dict]) -> dict:
    """Report configured symbols that did not produce a screen result."""
    expected = list(dict.fromkeys(watchlist))
    expected_set = set(expected)
    scored = {r.get("ticker") for r in results if r.get("ticker") in expected_set}
    missing = [ticker for ticker in expected if ticker not in scored]
    requested = len(expected)
    scored_count = requested - len(missing)
    return {
        "requested": requested,
        "scored": scored_count,
        "coverage_pct": round(100 * scored_count / requested, 1) if requested else None,
        "missing_tickers": missing,
    }


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


EXIT_NOT_READY = 75          # EX_TEMPFAIL: today's session data is not available yet; nothing was saved, retry later


def already_published(expected, history_dir: str = "docs/history") -> bool:
    """True once the paper-log snapshot for the expected session exists, so later retry attempts exit immediately."""
    return os.path.exists(os.path.join(history_dir, f"leaders_{expected.isoformat()}.json"))


def session_gate(diag: dict, expected) -> dict:
    """Decide whether the scan has the expected session. Never accepts an older session as a substitute."""
    chosen = (diag or {}).get("chosen_session")
    if chosen is None:
        return {"ready": False, "message": f"No session shared by the benchmark and 90% of stocks "
                                           f"(candidates {(diag or {}).get('candidates')}); expected {expected.isoformat()}."}
    got = date.fromisoformat(chosen)
    if got < expected:
        return {"ready": False, "message": f"Latest complete session in the data is {got.isoformat()}; expected {expected.isoformat()}."}
    return {"ready": True, "message": ""}


def abort_not_ready(message: str, run_ts, final_attempt: bool) -> None:
    """Abort WITHOUT saving or publishing anything. The scheduled retries (every ~2.5h) try again; only the last
    attempt of the day sends a Discord message, so a late data feed does not spam you."""
    print(f"[not ready] {message} Nothing saved or published.", file=sys.stderr)
    if final_attempt:
        send_discord_failure(message + " This was the last attempt for today and nothing was saved. If it was an NSE holiday, add the date to "
                             "universe/nse_holidays.txt; otherwise the data feed is late.", run_timestamp=run_ts)
    sys.exit(EXIT_NOT_READY)


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
    expected = analyzer_module.expected_session(run_ts)
    final_attempt = os.environ.get("FINAL_ATTEMPT") == "true"
    if os.environ.get("FORCE_RERUN") != "true" and already_published(expected):
        print(f"Session {expected.isoformat()} is already published; nothing to do.")
        sys.exit(0)
    if run_ts.time() >= EOD_CUTOFF or expected < run_ts.date():
        enable_settled_daily_candle()

    results = run_screen(max_session=expected)

    failure_message = check_total_failure(WATCHLIST, results)
    if failure_message:
        send_discord_failure(failure_message, run_timestamp=run_ts)
        raise RuntimeError(failure_message)

    gate = session_gate(analyzer_module.LAST_SESSION_DIAGNOSTICS, expected)
    if not gate["ready"]:                 # checked BEFORE the 30-minute wide scan so a late feed costs ~2 minutes, not 30
        abort_not_ready(gate["message"], run_ts, final_attempt)

    # flag = pattern/checklist gate; trade_ok = R:R gate (analyzer.build_trade_plan).
    # Only setups passing both are "flagged"; the rest are listed as watch-only so
    # a near-miss is visible instead of silently vanishing.
    flagged = [r for r in results if r["flag"] and r.get("trade_ok")]
    watch = [r for r in results if r["flag"] and not r.get("trade_ok")]
    momentum_leaders = sorted(
        (r for r in results if r.get("leader_rank") is not None),
        key=lambda r: (r.get("leader_rank") or float("inf"), r["ticker"]),
    )[:RS_LEADER_BOARD_SIZE]
    scan_coverage = summarize_scan_coverage(WATCHLIST, results)
    # Wide-universe leaders (the evidence-backed part). A failure here must never cost the legacy
    # screen's output, so it is isolated and reported inside the JSON/alert instead of raising.
    wide_leaders = None
    if os.environ.get("SKIP_WIDE_LEADERS") != "1":
        try:
            wide_leaders = wide.run_leaders(history_dir="docs/history", max_session=expected, require_session=expected)
        except Exception as e:
            print(f"[warning] wide leaders failed: {e}", file=sys.stderr)
            wide_leaders = {"error": str(e)}
    if wide_leaders and wide_leaders.get("not_ready"):
        abort_not_ready(f"The wide scan ended on {wide_leaders['as_of']}; expected {expected.isoformat()}.", run_ts, final_attempt)
    breadth = (round(sum(1 for r in results if r["above_sma50"]) / len(results), 2)
               if results else None)

    # Write results BEFORE attempting the Discord post. A dead webhook or
    # a network blip shouldn't cost you the actual screening output --
    # that's the thing this whole pipeline exists to produce. The alert
    # is a notification on top of that, not a precondition for it.
    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(wide.sanitize_json({
            "run_timestamp": run_ts.isoformat(),
            "note": "Every 'date'/'close' below is the last COMPLETE session as of run_timestamp, "
                     "never a same-day live price. The momentum leaderboard ranks 12-1 adjusted "
                     "returns relative to NIFTYBEES within this fixed watchlist; it is descriptive "
                     "and is not a validated buy signal. It ranks equities only; commodity ETFs "
                     "are excluded. 'flagged' remains the legacy reversal "
                     "checklist and is also for manual review only.",
            "all": results,
            "scan_coverage": scan_coverage,
            "momentum": {
                "benchmark": RS_BENCHMARK,
                "available": bool(momentum_leaders),
                "definition": (
                    "12-1 adjusted return excess versus benchmark on benchmark sessions; "
                    "latest 21 sessions skipped. 1m and 6m excess are separate context fields; "
                    "stale and <95% coverage rows excluded"
                ),
                "universe": "equities in the configured watchlist; commodity ETFs excluded",
                "leader_universe_size": sum(1 for r in results if r.get("leader_rank") is not None),
                "status_counts": {
                    status: sum(1 for r in results if r.get("relative_strength_status") == status)
                    for status in sorted({r.get("relative_strength_status", "unavailable") for r in results})
                },
                "unavailable_reason": (
                    None if momentum_leaders else
                    "No equity rows passed benchmark, freshness, history, and coverage checks. See per-ticker status."
                ),
                "excluded_non_equity_tickers": [
                    r["ticker"] for r in results if r.get("instrument_type") != "equity"
                ],
            },
            "momentum_leaders": momentum_leaders,
            "wide_leaders": wide_leaders,
            "flagged": flagged,
            "watch": watch,
            "breadth_above_sma50": breadth,
        }), f, indent=2, default=str, allow_nan=False)

    send_discord_alert(flagged, run_timestamp=run_ts, watch=watch, breadth=breadth,
                       leaders=momentum_leaders, benchmark=RS_BENCHMARK,
                       scan_coverage=scan_coverage, wide_leaders=wide_leaders)
    print(f"Screened {scan_coverage['scored']}/{scan_coverage['requested']} watchlist instruments, "
          f"{len(momentum_leaders)} equity momentum leaders, "
          f"{len(flagged)} flagged, {len(watch)} watch-only (failed R:R gate), "
          f"breadth {breadth}. Data as of run at {run_ts.isoformat()}.")
    print(f"Written to {OUTPUT_PATH} for the Pages site.")
