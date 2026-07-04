"""
Discord webhook alerting. Set DISCORD_WEBHOOK_URL as a GitHub Actions
repo secret (Settings > Secrets and variables > Actions) — never hardcode
it here or paste it anywhere outside that settings page.
"""
import os
import json
import urllib.error
import urllib.request


def send_discord_alert(flagged: list[dict], webhook_url: str | None = None, run_timestamp=None) -> None:
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("[alerts] DISCORD_WEBHOOK_URL not set, skipping alert")
        return

    ts_str = run_timestamp.strftime("%Y-%m-%d %H:%M IST") if run_timestamp else "unknown time"
    session_note = f"(last COMPLETE session as of {ts_str} — for planning tomorrow's open, not today's close)"

    if not flagged:
        content = f"EOD screen: nothing worth a manual look today (this is a pre-filter, not a verdict). {session_note}"
    else:
        lines = [f"**EOD screen — {len(flagged)} worth a manual look** {session_note}"]
        for r in flagged:
            lines.append(
                f"`{r['ticker']}` @ {r['close']} — {r['pattern']} | "
                f"trend: {r['trend']} | vol: {r['volume_ratio']}x | "
                f"support: {r['support_level']} ({r['support_touches']} touches) | "
                f"{r['checks_passed']}/{r['checks_total']} checks, confidence {r['confidence']}% | "
                f"{r['recommendation']}"
            )
        content = "\n".join(lines) + "\n_Pre-filter output — sections 6-9 (R:R, sizing, stop) still need to be done by hand._"

    payload = json.dumps({"content": content}).encode()
    # Discord's endpoint sits behind Cloudflare, which has been known to
    # 403 the default urllib User-Agent ("Python-urllib/3.x") outright,
    # independent of whether the webhook URL itself is valid. A real UA
    # string avoids that specific false-positive block.
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; TA-screener-bot/1.0)",
        },
    )
    # A failed alert should never take down the whole run -- by the time
    # this is called, main.py has already written latest_screen.json, so
    # the only thing lost on failure is the notification, not the data.
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"[alerts] Discord post failed: HTTP {e.code} — {body}")
    except urllib.error.URLError as e:
        print(f"[alerts] Discord post failed: {e.reason}")
