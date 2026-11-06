"""Opt-in, deduplicated strategy updates. Actual account fields are never sent."""
from __future__ import annotations

import logging
import requests

from .repository import digest
from .security import secret_value

LOG = logging.getLogger(__name__)
INTERESTING = {"detected", "confirmed", "model_entered", "model_exited", "expired", "invalidated", "skipped", "data_unavailable", "data_resumed"}


def event_digest(service, report):
    as_of = report["as_of"]
    events = []
    for candidate in service.repo.candidates("TA"):
        for event in candidate.get("events", []):
            if event.get("session") == as_of and event.get("type") in INTERESTING:
                events.append({"symbol": candidate["symbol"], "family": candidate["family"],
                               "event": event["type"], "id": digest([candidate["id"], event])})
    baskets = []
    for scope in ("wide", "personal"):
        basket = service.momentum_report(scope)
        model = basket.get("model") or {}
        if model.get("target_as_of") == as_of:
            baskets.append({"scope": scope, "target_holdings": model.get("target_holdings", []),
                            "rule_version": basket.get("rule_version")})
    if not events and not baskets and report.get("status") != "partial":
        return None
    identity = digest([as_of, events, baskets, report.get("status")])
    lines = [f"Scanner update — completed NSE session {as_of}"]
    if report.get("status") == "partial":
        lines.append("PARTIAL DATA: affected observations remain unavailable; inspect the private app.")
    if events:
        lines.append(f"TA: {len(events)} lifecycle updates.")
        lines.extend(f"{event['symbol']} · {event['family']} · {event['event']}" for event in events[:12])
    for basket in baskets:
        names = ", ".join(basket["target_holdings"][:20]) or "cash"
        lines.append(f"Momentum {basket['scope']} target review: {names}")
    footer = "\nReference/model updates only. Confirmed executions and personal account values remain private."
    content = "\n".join(lines)
    if len(content) + len(footer) > 2000:
        content = content[:1999 - len(footer)] + "…"
    return {"id": identity, "content": content + footer, "as_of": as_of}


def publish_updates(service, report, *, post=None):
    if secret_value("TRACKER_NOTIFY_ENABLED", "false").lower() != "true":
        return {"status": "disabled"}
    webhook = secret_value("DISCORD_WEBHOOK_URL")
    if not webhook:
        raise ValueError("Notifications are enabled but DISCORD_WEBHOOK_URL is not configured.")
    message = event_digest(service, report)
    if message is None:
        return {"status": "unchanged"}
    old = service.repo.document("notifications", message["id"], {})
    if old.get("status") == "sent":
        return {"status": "already_sent"}
    sender = post or requests.post
    try:
        response = sender(webhook, json={"content": message["content"]}, timeout=15)
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"Strategy notification rejected (HTTP {response.status_code}).")
    except (requests.RequestException, RuntimeError) as exc:
        service.repo.save_document("notifications", message["id"], {"status": "failed", "as_of": message["as_of"], "error": type(exc).__name__})
        raise RuntimeError("Strategy notification failed; market decisions were saved and delivery can be retried.") from exc
    service.repo.save_document("notifications", message["id"], {"status": "sent", "as_of": message["as_of"]})
    return {"status": "sent"}
