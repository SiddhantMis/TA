import json
import os
from datetime import datetime
from analyzer import run_screen, IST
from alerts import send_discord_alert

OUTPUT_PATH = "docs/latest_screen.json"

if __name__ == "__main__":
    run_ts = datetime.now(IST)
    results = run_screen()
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
