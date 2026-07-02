import json
from analyzer import run_screen
from alerts import send_discord_alert

if __name__ == "__main__":
    results = run_screen()
    flagged = [r for r in results if r["flag"]]
    send_discord_alert(flagged)
    with open("latest_screen.json", "w") as f:
        json.dump({"all": results, "flagged": flagged}, f, indent=2, default=str)
    print(f"Screened {len(results)} tickers, {len(flagged)} flagged.")
