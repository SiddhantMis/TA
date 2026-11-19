from datetime import datetime
import io
import json
import zipfile

import pandas as pd
import pytest

from scanner_tracker.demo import synthetic_frames
from scanner_tracker.market import IST, latest_completed_session, normalize_frame, payload_frame, frame_payload, symbol_name
from scanner_tracker.repository import clean, digest
from scanner_tracker.security import hash_password, verify_password
from scanner_tracker.service import TrackerService
from scanner_tracker.storage import InputArchive


@pytest.fixture
def service(tmp_path):
    return TrackerService(f"sqlite:///{tmp_path / 'tracker.db'}", archive=InputArchive(local_directory=tmp_path / "inputs"))


def test_completed_session_uses_exchange_calendar_and_settlement_window():
    assert latest_completed_session(datetime(2026, 11, 6, 18, 59, tzinfo=IST)) == "2026-11-05"
    assert latest_completed_session(datetime(2026, 11, 6, 19, 15, tzinfo=IST)) == "2026-11-06"
    assert latest_completed_session(datetime(2026, 11, 7, 12, tzinfo=IST)) == "2026-11-06"
    with pytest.raises(ValueError):
        latest_completed_session(datetime(2026, 11, 6))


def test_market_data_rejects_invalid_bars_and_truncates_future():
    frames, _ = synthetic_frames()
    frame = frames["DEMOB.NS"]
    as_of = frame.index[-2].date().isoformat()
    assert normalize_frame(frame, as_of).index[-1] == pd.Timestamp(as_of)
    bad = frame.copy()
    bad.iloc[-1, bad.columns.get_loc("Low")] = -1
    with pytest.raises(ValueError):
        normalize_frame(bad, frame.index[-1].date().isoformat())
    with pytest.raises(ValueError):
        normalize_frame(pd.concat([frame, frame.iloc[-1:]]), "2026-10-30")
    pd.testing.assert_frame_equal(payload_frame(frame_payload(frame)), frame, check_freq=False)


def test_private_input_archive_is_content_addressed_and_detects_corruption(tmp_path):
    archive = InputArchive(local_directory=tmp_path)
    key = archive.put({"source": "synthetic", "bars": [{"Close": 10}]})
    assert archive.put({"bars": [{"Close": 10}], "source": "synthetic"}) == key
    assert archive.get(key)["bars"][0]["Close"] == 10
    with pytest.raises(ValueError):
        archive.get("../../secret")
    (tmp_path / key).write_bytes(b"not a valid gzip record")
    with pytest.raises((ValueError, OSError)):
        archive.get(key)


def test_password_hash_does_not_store_plaintext_and_rejects_malformed_hashes():
    encoded = hash_password("a sufficiently long test password")
    assert "test password" not in encoded
    assert verify_password("a sufficiently long test password", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("wrong", "pbkdf2_sha256$999999999999$broken$broken")
    with pytest.raises(ValueError):
        hash_password("short")


def test_first_unfunded_scan_can_be_configured_later(service):
    frames, benchmark = synthetic_frames()
    report = service.scan_frames(frames, benchmark, "2026-10-30")
    assert report["status"] == "complete"
    service.update_settings({"momentum_capital_inr": 100000})
    assert service.settings()["momentum_capital_inr"] == 100000


def test_same_scan_is_idempotent_and_original_plan_is_immutable(service):
    frames, benchmark = synthetic_frames()
    service.scan_frames(frames, benchmark, "2026-10-30")
    original = service.repo.candidates()
    assert original
    service.scan_frames(frames, benchmark, "2026-10-30")
    assert service.repo.candidates() == original
    changed = json.loads(json.dumps(original[0]))
    changed["original_plan"]["signal_close"] = 99999
    with pytest.raises(ValueError, match="immutable"):
        service.repo.save_candidates([changed])


def test_stale_stock_is_unknown_and_stale_benchmark_cannot_publish(service):
    frames, benchmark = synthetic_frames()
    frames["DEMOB.NS"] = frames["DEMOB.NS"].iloc[:-1]
    report = service.scan_frames(frames, benchmark, "2026-10-30")
    assert report["status"] == "partial"
    assert "DEMOB.NS" in report["diagnostics"]
    count = len(service.repo.runs())
    with pytest.raises(ValueError, match="Benchmark"):
        service.scan_frames(frames, benchmark.iloc[:-1], "2026-10-30")
    assert len(service.repo.runs()) == count


def test_backup_restores_records_and_inputs_and_never_overwrites_nonempty_database(service, tmp_path):
    frames, benchmark = synthetic_frames()
    service.scan_frames(frames, benchmark, "2026-10-30")
    candidate = service.repo.candidates()[0]
    service.set_watch(candidate["id"], note="Preserve the original idea.")
    service.configure_ledger("TA", 10000, as_of="2026-10-01")
    service.record_fill("TA", {"execution_id": "actual-1", "symbol": candidate["symbol"], "side": "BUY",
                               "quantity": 1, "price_inr": 100, "fees_inr": 1, "executed_at": "2026-10-30", "signal_id": candidate["id"]})
    data = service.export_bundle()
    assert zipfile.ZipFile(io.BytesIO(data)).namelist()[0] == "tracker.json"
    restored = TrackerService(f"sqlite:///{tmp_path / 'restored.db'}", archive=InputArchive(local_directory=tmp_path / "restored-inputs"))
    restored.restore_bundle(data)
    assert restored.repo.candidates() == service.repo.candidates()
    assert restored.ledger("TA") == service.ledger("TA")
    assert restored.repo.watch_items() == service.repo.watch_items()
    restored.export_bundle()
    with pytest.raises(ValueError, match="empty"):
        restored.restore_bundle(data)


def test_preopening_valuation_is_withheld(service):
    frames, benchmark = synthetic_frames()
    service.configure_ledger("TA", 10000, as_of="2026-11-01")
    service._record_actual_valuations(frames, "2026-10-30")
    mark = service.repo.document("valuations", "TA:2026-10-30")
    assert mark["complete"] is False
    assert mark["equity_inr"] is None


def test_unknown_personal_instrument_requires_explicit_classification(service):
    with pytest.raises(ValueError, match="Classify"):
        service.update_settings({"personal_symbols": ["UNCLASSIFIED.NS"]})
    service.update_settings({"personal_symbols": ["UNCLASSIFIED.NS"], "instrument_types": {"UNCLASSIFIED.NS": "equity_etf"}})
    assert service.settings()["instrument_types"]["UNCLASSIFIED.NS"] == "equity_etf"


def test_modes_do_not_write_each_others_reports(service):
    frames, benchmark = synthetic_frames()
    service.scan_frames(frames, benchmark, "2026-10-30", mode="ta")
    assert service.repo.candidates()
    assert service.momentum_report() == {}
    before = service.repo.candidates()
    service.scan_frames(frames, benchmark, "2026-10-30", mode="momentum")
    assert service.momentum_report()
    assert service.repo.candidates() == before


def test_symbol_parser_and_json_contract():
    assert symbol_name(" m&m ") == "M&M.NS"
    with pytest.raises(ValueError):
        symbol_name("bad/symbol")
    assert clean({"value": float("nan")}) == {"value": None}
    assert digest({"x": 1, "y": 2}) == digest({"y": 2, "x": 1})


def test_special_session_requires_official_source_and_exact_session_times(monkeypatch):
    override = {"2026-11-07": {"source_url": "https://nsearchives.nseindia.com/test-only-official-source.pdf",
                "market_open": "2026-11-07T18:00:00+05:30", "market_close": "2026-11-07T19:00:00+05:30"}}
    monkeypatch.setenv("TRACKER_SESSION_OVERRIDES", json.dumps(override))
    assert latest_completed_session(datetime(2026, 11, 7, 23, 0, tzinfo=IST)) == "2026-11-07"
    assert latest_completed_session(datetime(2026, 11, 7, 20, 0, tzinfo=IST)) == "2026-11-06"
    override["2026-11-07"]["source_url"] = "https://example.invalid/invented-session"
    monkeypatch.setenv("TRACKER_SESSION_OVERRIDES", json.dumps(override))
    with pytest.raises(ValueError, match="official NSE"):
        latest_completed_session(datetime(2026, 11, 7, 23, 0, tzinfo=IST))


def test_actual_outside_universe_position_can_be_valued_and_proposed_for_exit(service):
    frames, benchmark = synthetic_frames()
    service.configure_ledger("MOMENTUM", 10000, as_of="2026-10-01")
    service.record_fill("MOMENTUM", {"execution_id": "outside", "symbol": "OUTSIDE.NS", "side": "BUY", "quantity": 1,
                                   "price_inr": 100, "fees_inr": 1, "executed_at": "2026-10-02"})
    frames["OUTSIDE.NS"] = frames["DEMOC.NS"].copy()
    service.scan_frames(frames, benchmark, "2026-10-30", scopes={"wide": ["DEMOA.NS", "DEMOB.NS"]}, mode="momentum")
    report = service.momentum_report()
    assert report["actual_target"]["status"] == "READY"
    assert any(x["symbol"] == "OUTSIDE.NS" and x["side"] == "SELL" for x in report["proposals"])
    assert all(x["symbol"] != "OUTSIDE.NS" for x in report["ranks"])


def test_latest_proposals_reconcile_confirmed_fills_without_waiting_for_next_scan(service):
    frames, benchmark = synthetic_frames()
    service.configure_ledger("MOMENTUM", 100000, as_of="2026-10-01")
    service.scan_frames(frames, benchmark, "2026-10-30", mode="momentum")
    before = service.momentum_report()
    buy = next(x for x in before["proposals"] if x["side"] == "BUY")
    service.record_fill("MOMENTUM", {"execution_id": "filled-proposal", "symbol": buy["symbol"], "side": "BUY",
        "quantity": buy["quantity"], "price_inr": buy["reference_price_inr"], "fees_inr": buy["estimated_fees_inr"], "executed_at": "2026-10-30"})
    after = service.momentum_report()
    assert after["actual_target"] == before["actual_target"]
    assert not any(x["symbol"] == buy["symbol"] and x["side"] == "BUY" for x in after["proposals"])
