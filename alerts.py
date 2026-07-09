"""
Discord webhook alerting. Set DISCORD_WEBHOOK_URL as a GitHub Actions
repo secret (Settings > Secrets and variables > Actions) — never hardcode
it here or paste it anywhere outside that settings page.
"""
import os
import json
import urllib.error
import urllib.request


DISCORD_CONTENT_LIMIT = 2000


def build_alert_content(flagged: list[dict], session_note: str) -> str:
    """Pure function, no network -- separated specifically so the
    truncation logic can be unit-tested without a webhook, a mock
    server, or letting a test actually hit Discord."""
    if not flagged:
        return f"EOD screen: nothing worth a manual look today (this is a pre-filter, not a verdict). {session_note}"

    lines = [f"**EOD screen — {len(flagged)} worth a manual look** {session_note}"]
    for r in flagged:
        lines.append(
            f"`{r['ticker']}` @ {r['close']} — {r['pattern']} | "
            f"trend: {r['trend']} | vol: {r['volume_ratio']}x | "
            f"support: {r['support_level']} ({r['support_touches']} touches) | "
            f"{r['checks_passed']}/{r['checks_total']} checks, confidence {r['confidence']}% | "
            f"{r['recommendation']}"
        )
    footer = "\n_Pre-filter output — sections 6-9 (R:R, sizing, stop) still need to be done by hand._"
    content = "\n".join(lines) + footer

    # Discord's hard content limit is 2000 chars. At 48 tickers this
    # isn't hypothetical anymore -- before this, an oversized payload
    # meant the whole alert silently failed (caught by the network
    # except block, logged to an Actions run nobody's watching live),
    # with no indication in Discord itself that anything was missed.
    if len(content) > DISCORD_CONTENT_LIMIT:
        shown = []
        budget = DISCORD_CONTENT_LIMIT - len(footer) - 100  # room for the truncation line + footer
        running = len(lines[0]) + 1
        for line in lines[1:]:
            if running + len(line) + 1 > budget:
                break
            shown.append(line)
            running += len(line) + 1
        omitted = len(lines) - 1 - len(shown)
        content = "\n".join([lines[0]] + shown)
        content += f"\n_...+{omitted} more flagged, truncated for Discord's message limit — see the full list on the Pages site._"
        content += footer

    return content


def send_discord_alert(flagged: list[dict], webhook_url: str | None = None, run_timestamp=None) -> None:
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("[alerts] DISCORD_WEBHOOK_URL not set, skipping alert")
        return

    ts_str = run_timestamp.strftime("%Y-%m-%d %H:%M IST") if run_timestamp else "unknown time"
    session_note = f"(last COMPLETE session as of {ts_str} — for planning tomorrow's open, not today's close)"
    content = build_alert_content(flagged, session_note)

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


def send_discord_failure(message: str, webhook_url: str | None = None, run_timestamp=None) -> None:
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("[alerts] DISCORD_WEBHOOK_URL not set, skipping failure alert")
        return

    ts_str = run_timestamp.strftime("%Y-%m-%d %H:%M IST") if run_timestamp else "unknown time"
    payload = json.dumps({
        "content": f"**EOD screen failed** at {ts_str}: {message}"
    }).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; TA-screener-bot/1.0)",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"[alerts] Discord failure post failed: HTTP {e.code} — {body}")
    except urllib.error.URLError as e:
        print(f"[alerts] Discord failure post failed: {e.reason}")
