import json
from analyzer import run_screen
from alerts import send_discord_alert

if __name__ == "__main__":
    results = run_screen()
    flagged = [r for r in results if r["flag"]]

    # Write results BEFORE attempting the Discord post. A dead webhook or
    # a network blip shouldn't cost you the actual screening output --
    # that's the thing this whole pipeline exists to produce. The alert
    # is a notification on top of that, not a precondition for it.
    with open("latest_screen.json", "w") as f:
        json.dump({"all": results, "flagged": flagged}, f, indent=2, default=str)

    send_discord_alert(flagged)
    print(f"Screened {len(results)} tickers, {len(flagged)} flagged.")
