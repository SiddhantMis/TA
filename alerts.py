"""
Discord webhook alerting (alerts.py)

Set DISCORD_WEBHOOK_URL as a GitHub Actions repo secret.
Formats rich alerts with Trade Plans, Support/Resistance details,
Relative Strength leadership tags, and market breadth warnings.
"""
from __future__ import annotations
import os
import json
import urllib.error
import urllib.request
from typing import Optional


DISCORD_CONTENT_LIMIT = 2000


def build_alert_content(
    flagged: list[dict],
    session_note: str,
    watch: list[dict] | None = None,
    breadth: float | None = None,
    leaders: list[dict] | None = None,
) -> str:
    """Pure function, no network -- builds formatted Discord alert within 2000 character limit."""
    watch_line = ""
    if watch:
        watch_line = "\nWatch only (pattern OK, trade plan failed the R:R gate): " + ", ".join(
            f"{w['ticker']} (R:R {w.get('rr')})" for w in watch)

    breadth_line = ""
    if breadth is not None and breadth < 0.25:
        breadth_line = (f"\n⚠ Only {breadth:.0%} of the watchlist is above its 50-day average — "
                        "reversal setups are riskier in broad weakness (see backtest by-breadth table).")

    if not flagged:
        leader_note = ""
        if leaders:
            top_3 = ", ".join(f"`{l['ticker']}` (#{l.get('rs_rank', '-')})" for l in leaders[:3])
            leader_note = f"\nTop RS Leaders today: {top_3}"
        return (f"EOD screen: nothing worth a manual look today (this is a pre-filter, not a verdict). "
                f"{session_note}{breadth_line}{watch_line}{leader_note}")

    lines = [f"**EOD screen — {len(flagged)} worth a manual look** {session_note}{breadth_line}"]
    for r in flagged:
        plan = ""
        if r.get("entry") is not None and r.get("risk_pct") is not None:
            plan = (f"buy > {r['entry']} stop {r['stop']} target {r['target']} "
                    f"R:R {r['rr']} (risk {r['risk_pct']:.1%}) | ")

        tags = []
        if r.get("is_leader"):
            tags.append(f"Leader #{r.get('rs_rank')}")
        if r.get("support_weekly_confluence"):
            tags.append("Weekly MTF")
        if r.get("support_role_reversal"):
            tags.append("Role Reversal")
        tag_str = f" [{', '.join(tags)}]" if tags else ""

        lines.append(
            f"`{r['ticker']}` @ {r['close']} — {r['pattern']} | {plan}"
            f"trend: {r['trend']} | vol: {r['volume_ratio']}x | "
            f"support: {r['support_level']} ({r['support_touches']} touches) | "
            f"{r['checks_passed']}/{r['checks_total']} checks, confidence {r['confidence']}% | "
            f"{r['recommendation']}{tag_str}"
        )

    footer = watch_line + "\n_Pre-filter output — R:R is pre-checked against the auto plan; sizing and time stop (sections 7-9) are still by hand._"
    content = "\n".join(lines) + footer

    if len(content) > DISCORD_CONTENT_LIMIT:
        shown = []
        budget = DISCORD_CONTENT_LIMIT - len(footer) - 100
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


def send_discord_alert(
    flagged: list[dict],
    webhook_url: str | None = None,
    run_timestamp=None,
    watch: list[dict] | None = None,
    breadth: float | None = None,
    leaders: list[dict] | None = None,
) -> None:
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("[alerts] DISCORD_WEBHOOK_URL not set, skipping alert")
        return

    ts_str = run_timestamp.strftime("%Y-%m-%d %H:%M IST") if run_timestamp else "unknown time"
    session_note = f"(last COMPLETE session as of {ts_str} — for planning tomorrow's open, not today's close)"
    content = build_alert_content(flagged, session_note, watch=watch, breadth=breadth, leaders=leaders)

    payload = json.dumps({"content": content}).encode()
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
