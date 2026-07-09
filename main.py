import json
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


if __name__ == "__main__":
    run_ts = datetime.now(IST)
    if run_ts.time() >= EOD_CUTOFF:
        enable_settled_daily_candle()

    results = run_screen()

    failure_message = check_total_failure(WATCHLIST, results)
    if failure_message:
        send_discord_failure(failure_message, run_timestamp=run_ts)
        raise RuntimeError(failure_message)

    if run_ts.time() >= EOD_CUTOFF and results:
        latest_score_date = max(date.fromisoformat(r["date"]) for r in results)
        if latest_score_date != run_ts.date():
            failure_message = (
                f"Latest screener data is {latest_score_date.isoformat()}, not today's close ({run_ts.date().isoformat()}). "
                "Yahoo has not published the completed EOD candle yet."
            )
            send_discord_failure(failure_message, run_timestamp=run_ts)
            raise RuntimeError(failure_message)

    flagged = [r for r in results if r["flag"]]

    # Write results BEFORE attempting the Discord post. A dead webhook or
    # a network blip shouldn't cost you the actual screening output --
    # that's the thing this whole pipeline exists to produce. The alert
    # is a notification on top of that, not a precondition for it.
    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump({
            "run_timestamp": run_ts.isoformat(),
            "note": "Every 'date'/'close' below is the last COMPLETE session as of run_timestamp, "
                     "never a same-day live price. A flag here is for planning tomorrow's open — "
                     "not for acting before today's 3:30 PM close.",
            "all": results,
            "flagged": flagged,
        }, f, indent=2, default=str)

    send_discord_alert(flagged, run_timestamp=run_ts)
    print(f"Screened {len(results)} tickers, {len(flagged)} flagged. Data as of run at {run_ts.isoformat()}.")
    print(f"Written to {OUTPUT_PATH} for the Pages site.")