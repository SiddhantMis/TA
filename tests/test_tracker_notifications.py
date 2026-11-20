from unittest.mock import Mock

import pytest
import requests

from scanner_tracker.notifications import event_digest, publish_updates


class FakeService:
    def __init__(self):
        self.documents = {}
        self.repo = Mock()
        self.repo.candidates.return_value = [{"id": "one", "symbol": "X.NS", "family": "reversal",
            "actual_capital": "SECRET_ACCOUNT_VALUE", "events": [{"type": "confirmed", "session": "2026-11-05", "details": {"cash": "PRIVATE_CASH"}}]}]
        self.repo.document.side_effect = lambda namespace, key, default=None: self.documents.get((namespace, key), default)
        self.repo.save_document.side_effect = lambda namespace, key, value: self.documents.__setitem__((namespace, key), value)
        self.momentum_report = lambda scope: {}


def test_notification_allowlist_excludes_private_values_and_enforces_limit():
    service = FakeService()
    content = event_digest(service, {"as_of": "2026-11-05", "status": "complete"})["content"]
    assert "confirmed" in content and "PRIVATE_CASH" not in content and "SECRET_ACCOUNT_VALUE" not in content
    service.repo.candidates.return_value *= 1000
    assert len(event_digest(service, {"as_of": "2026-11-05", "status": "complete"})["content"]) <= 2000


def test_notifications_are_disabled_by_default_and_unchanged_events_are_deduplicated(monkeypatch):
    monkeypatch.delenv("TRACKER_NOTIFY_ENABLED", raising=False)
    post = Mock(return_value=Mock(status_code=204))
    service = FakeService()
    assert publish_updates(service, {"as_of": "2026-11-05"}, post=post)["status"] == "disabled"
    post.assert_not_called()
    monkeypatch.setenv("TRACKER_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/private-webhook")
    report = {"as_of": "2026-11-05", "status": "complete"}
    assert publish_updates(service, report, post=post)["status"] == "sent"
    assert publish_updates(service, report, post=post)["status"] == "already_sent"
    assert post.call_count == 1


def test_delivery_failure_is_recorded_and_can_be_retried(monkeypatch):
    monkeypatch.setenv("TRACKER_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/private-webhook")
    service = FakeService()
    report = {"as_of": "2026-11-05", "status": "complete"}
    with pytest.raises(RuntimeError, match="saved"):
        publish_updates(service, report, post=Mock(side_effect=requests.Timeout()))
    assert list(service.documents.values())[0]["status"] == "failed"
    assert publish_updates(service, report, post=Mock(return_value=Mock(status_code=204)))["status"] == "sent"
