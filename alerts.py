"""
Discord webhook alerting. Set DISCORD_WEBHOOK_URL as a GitHub Actions
repo secret (Settings > Secrets and variables > Actions) — never hardcode
it here or paste it anywhere outside that settings page.
"""
import os
import json
import urllib.request


def send_discord_alert(flagged: list[dict], webhook_url: str | None = None) -> None:
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("[alerts] DISCORD_WEBHOOK_URL not set, skipping alert")
        return

    if not flagged:
        content = "EOD screen: no tickers cleared the checklist today."
    else:
        lines = [f"**EOD screen — {len(flagged)} flagged**"]
        for r in flagged:
            lines.append(
                f"`{r['ticker']}` @ {r['close']} — {r['pattern']} | "
                f"trend: {r['trend']} | vol: {r['volume_ratio']}x | "
                f"support: {r['support_level']} | "
                f"{r['checks_passed']}/{r['checks_total']} checks"
            )
        content = "\n".join(lines)

    payload = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=10)
