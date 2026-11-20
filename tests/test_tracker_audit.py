"""Security and state-preservation regressions from the final integration audit."""
from copy import deepcopy
from io import BytesIO
import sys
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

import pandas as pd
import pytest

from scanner_tracker.db import make_engine
from scanner_tracker.ledger import new_ledger, record_cash_event, record_corporate_action, record_fill
from scanner_tracker.service import TrackerService
from scanner_tracker.storage import InputArchive


@pytest.fixture
def private_service(tmp_path):
    service = TrackerService("sqlite:///" + (tmp_path / "source" / "tracker.db").as_posix(),
                             archive=InputArchive(local_directory=tmp_path / "source-inputs"))
    yield service
    service.engine.dispose()


def idea():
    return {"id": "audit-idea", "mode": "TA", "symbol": "FIXTURE.NS", "family": "reversal",
            "signal_session": "2026-11-02", "status": "awaiting_confirmation", "scopes": ["personal"],
            "original_plan": {"entry": 100.0, "stop": 95.0, "target": 115.0},
            "current": {"last_processed_session": "2026-11-02"}, "events": [], "model_trade": None}


@pytest.mark.parametrize("sslmode", ["prefer", "allow", "disable"])
def test_production_connection_never_accepts_plaintext_fallback(monkeypatch, sslmode):
    monkeypatch.setenv("TRACKER_ENV", "production")
    with patch("scanner_tracker.db.create_engine") as factory:
        with pytest.raises(ValueError, match="TLS|Unencrypted"):
            make_engine(f"postgresql+psycopg://fixture:fixture@example.invalid/fixture?sslmode={sslmode}")
        factory.assert_not_called()


@pytest.mark.parametrize("database_url", ["sqlite:///:memory:", "postgresql+psycopg://fixture:fixture@example.invalid/fixture"])
def test_demo_cannot_construct_any_configured_account_database(monkeypatch, database_url):
    monkeypatch.setenv("TRACKER_DEMO", "1")
    values = {"TRACKER_ENV": "local", "DATABASE_URL": database_url}
    with patch("scanner_tracker.service.secret_value", side_effect=lambda name, default=None: values.get(name, default)), \
         patch.object(TrackerService, "__init__", return_value=None) as constructor:
        with pytest.raises(ValueError, match="Demo mode"):
            TrackerService.from_env()
        constructor.assert_not_called()


def test_demo_authentication_cannot_bypass_guard_for_a_configured_database(monkeypatch):
    from scanner_tracker.security import require_app_access

    class AccessStopped(Exception):
        pass

    def stop():
        raise AccessStopped

    fake_streamlit = SimpleNamespace(error=lambda message: None, stop=stop,
        warning=lambda message: pytest.fail("Configured account storage reached the anonymous demo path"))
    monkeypatch.setenv("TRACKER_DEMO", "1")
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    values = {"TRACKER_ENV": "local", "DATABASE_URL": "postgresql://fixture@example.invalid/fixture"}
    with patch("scanner_tracker.security.secret_value", side_effect=lambda name, default=None: values.get(name, default)):
        with pytest.raises(AccessStopped):
            require_app_access()


def test_stale_worker_update_keeps_owner_note_and_original_plan(private_service):
    original = idea()
    private_service.repo.save_candidates([original])
    worker_copy = private_service.repo.candidate(original["id"])
    private_service.save_note(original["id"], "Owner note added during the worker scan")
    worker_copy["current"]["last_processed_session"] = "2026-11-03"
    private_service.repo.save_candidates([worker_copy])
    stored = private_service.repo.candidate(original["id"])
    assert [event["details"]["text"] for event in stored["events"] if event["type"] == "note"] == [
        "Owner note added during the worker scan"]
    assert stored["original_plan"] == original["original_plan"]


def test_stale_worker_cannot_reopen_an_invalidated_candidate(private_service):
    original = idea()
    private_service.repo.save_candidates([original])
    worker_copy = private_service.repo.candidate(original["id"])
    terminal = deepcopy(original)
    terminal["status"] = "invalidated"
    terminal["events"].append({"type": "corporate_action_reconciled", "session": "2026-11-03", "details": {}})
    private_service.repo.save_candidates([terminal])
    worker_copy["current"]["last_processed_session"] = "2026-11-03"
    with pytest.raises(ValueError):
        private_service.repo.save_candidates([worker_copy])
    assert private_service.repo.candidate(original["id"])["status"] == "invalidated"


def test_next_daily_scan_still_detects_new_setups_after_a_completed_run(private_service):
    dates = pd.bdate_range("2023-01-02", periods=510)
    frame = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000.0}, index=dates)
    benchmark = frame.copy()
    first = private_service.scan_frames({"FIXTURE.NS": frame}, benchmark, dates[-2].date().isoformat(),
                                        scopes={"personal": ["FIXTURE.NS"]}, mode="ta")
    assert first["status"] == "complete"
    assert private_service.repo.candidates() == []
    frame.loc[dates[-1], ["Open", "High", "Low", "Close", "Volume"]] = [100.0, 104.0, 99.0, 103.0, 2000.0]
    private_service.scan_frames({"FIXTURE.NS": frame}, benchmark, dates[-1].date().isoformat(),
                                scopes={"personal": ["FIXTURE.NS"]}, mode="ta")
    assert any(item["family"] == "breakout55" and item["signal_session"] == dates[-1].date().isoformat()
               for item in private_service.repo.candidates())


def test_momentum_only_run_does_not_advance_ta_detection_checkpoint(private_service):
    dates = pd.bdate_range("2023-01-02", periods=510)
    frame = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000.0}, index=dates)
    benchmark = frame.copy()
    scopes = {"personal": ["FIXTURE.NS"]}
    private_service.scan_frames({"FIXTURE.NS": frame}, benchmark, dates[-4].date().isoformat(), scopes=scopes, mode="ta")
    frame.loc[dates[-3], ["Open", "High", "Low", "Close", "Volume"]] = [100.0, 104.0, 99.0, 103.0, 2000.0]
    private_service.scan_frames({"FIXTURE.NS": frame}, benchmark, dates[-2].date().isoformat(), scopes=scopes, mode="momentum")
    assert private_service.repo.candidates() == []
    private_service.scan_frames({"FIXTURE.NS": frame}, benchmark, dates[-1].date().isoformat(), scopes=scopes, mode="ta")
    assert any(item["family"] == "breakout55" and item["signal_session"] == dates[-3].date().isoformat()
               for item in private_service.repo.candidates()), "The intervening momentum scan did not observe TA signals."


@pytest.mark.parametrize("kind", ["fill", "cash", "corporate_action"])
def test_business_events_cannot_spend_or_transform_future_opening_balances(kind):
    state = new_ledger("TA", 1000)
    state["opening_as_of"] = "2026-11-06"
    original = deepcopy(state)
    with pytest.raises(ValueError, match="opening|Opening"):
        if kind == "fill":
            record_fill(state, {"execution_id": "early", "executed_at": "2026-11-01", "symbol": "FIXTURE.NS",
                                "side": "BUY", "quantity": 1, "price_inr": 100, "fees_inr": 0})
        elif kind == "cash":
            record_cash_event(state, {"event_id": "early", "executed_at": "2026-11-01",
                                      "cash_type": "DEPOSIT", "amount_inr": 100})
        else:
            state["opening_positions"] = {"FIXTURE.NS": {"symbol": "FIXTURE.NS", "quantity": 1,
                "average_cost_inr": "100.00", "cost_basis_inr": "100.00"}}
            original = deepcopy(state)
            record_corporate_action(state, {"event_id": "early", "executed_at": "2026-11-01",
                                            "symbol": "FIXTURE.NS", "action_type": "SPLIT", "ratio": 2})
    assert state == original


def test_restore_rejects_a_manifest_whose_referenced_private_input_is_missing(private_service, tmp_path):
    key = private_service.archive.put({"source": "synthetic", "bars": [{"Close": 10}]})
    private_service.repo.save_snapshot("FIXTURE.NS", "2026-11-02", {"archive_key": key, "bars": []})
    incomplete = BytesIO()
    with zipfile.ZipFile(BytesIO(private_service.export_bundle())) as exported, zipfile.ZipFile(incomplete, "w") as target:
        target.writestr("tracker.json", exported.read("tracker.json"))
    restored = TrackerService("sqlite:///" + (tmp_path / "destination" / "tracker.db").as_posix(),
                              archive=InputArchive(local_directory=tmp_path / "destination-inputs"))
    try:
        with pytest.raises(ValueError, match="archive|input|missing"):
            restored.restore_bundle(incomplete.getvalue())
        assert restored.repo.documents("latest_prices") == []
    finally:
        restored.engine.dispose()


def test_failed_scan_never_leaves_a_successful_publication(private_service):
    dates = pd.bdate_range("2023-01-02", periods=510)
    frame = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000.0}, index=dates)
    with patch("scanner_tracker.research.compare_momentum_rankings", side_effect=RuntimeError("synthetic failure")):
        try:
            result = private_service.scan_frames({"FIXTURE.NS": frame}, frame, dates[-1].date().isoformat(),
                                                 scopes={"personal": ["FIXTURE.NS"]}, mode="ta")
        except RuntimeError:
            assert not any(run["status"] == "complete" for run in private_service.repo.runs())
        else:
            # A noncritical research failure may instead be an explicit, recorded diagnostic.
            diagnostics = str(result.get("diagnostics", {})) + str(private_service.repo.documents("data_issues"))
            assert "research" in diagnostics.lower() and any(word in diagnostics.lower() for word in ("fail", "unavailable"))
