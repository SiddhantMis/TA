"""Private service integration using real temporary SQLite and compressed inputs."""
from copy import deepcopy
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import uuid
import zipfile

import pytest
from sqlalchemy import func, select, text

from scanner_tracker.db import make_engine, transaction
from scanner_tracker.demo import synthetic_frames
from scanner_tracker.models import CandidateEvent, LedgerEvent, PriceSnapshot
from scanner_tracker.service import TrackerService
from scanner_tracker.storage import InputArchive


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKER_ENV", "local")
    archive = InputArchive(local_directory=tmp_path / "inputs")
    app = TrackerService("sqlite:///" + (tmp_path / "tracker.db").as_posix(), archive=archive)
    yield app
    app.engine.dispose()


def setup_candidate(identity="signal-1", symbol="DEMOA.NS"):
    return {"id": identity, "symbol": symbol, "mode": "TA", "family": "breakout55",
            "strategy_version": "ta-v1", "signal_session": "2026-11-02", "status": "awaiting_entry",
            "original_plan": {"entry": 100, "stop": 95, "target": None, "signal_atr": 2.5},
            "current": {"last_processed_session": "2026-11-02", "data_status": "complete"},
            "events": [{"type": "detected", "session": "2026-11-02", "details": {}}],
            "model_trade": None, "scopes": ["wide"]}


def csv_text(rows):
    return "execution_id,mode,executed_at,symbol,side,quantity,price_inr,fees_inr,signal_id\n" + "\n".join(rows) + "\n"


def configure(app, mode="TA", amount=10000):
    return app.configure_ledger(mode, amount, as_of="2026-11-01")


def test_fill_import_is_previewed_atomic_idempotent_and_mode_isolated(service):
    configure(service)
    configure(service, "MOMENTUM", 20000)
    content = csv_text(["buy,TA,2026-11-02,DEMOA,BUY,10,100,1,"])
    preview = service.preview_import("TA", content)
    assert preview["valid"]
    assert service.ledger("TA")["holdings"] == {}
    assert service.commit_import("TA", content)["valid"]
    state = service.ledger("TA")
    assert state["holdings"]["DEMOA.NS"]["quantity"] == 10
    assert state["cash_balance_inr"] == "8999.00"
    service.commit_import("TA", content)
    assert service.ledger("TA") == state
    assert service.ledger("MOMENTUM")["cash_balance_inr"] == "20000.00"
    bad = csv_text(["other,TA,2026-11-03,DEMOB,BUY,5,100,0,",
                    "oversell,TA,2026-11-03,DEMOA,SELL,11,100,0,"])
    with pytest.raises(ValueError, match="validation"):
        service.commit_import("TA", bad)
    assert service.ledger("TA") == state
    with transaction(service.engine) as session:
        assert session.scalar(select(func.count()).select_from(LedgerEvent)) == 1


def test_import_signal_must_exist_and_match_symbol_and_mode(service):
    configure(service)
    configure(service, "MOMENTUM")
    service.repo.save_candidates([setup_candidate()])
    for row, mode in [
        ("unknown,TA,2026-11-02,DEMOA,BUY,1,100,0,missing", "TA"),
        ("wrong,TA,2026-11-02,DEMOB,BUY,1,100,0,signal-1", "TA"),
        ("other,MOMENTUM,2026-11-02,DEMOA,BUY,1,100,0,signal-1", "MOMENTUM"),
    ]:
        content = csv_text([row])
        assert service.preview_import(mode, content)["valid"] is False
        with pytest.raises(ValueError):
            service.commit_import(mode, content)
        assert not service.ledger(mode)["holdings"]


def test_transfer_is_atomic_on_both_balance_and_target_id_conflicts(service):
    configure(service, "TA", 1000)
    configure(service, "MOMENTUM", 100)
    before_ta, before_momentum = service.ledger("TA"), service.ledger("MOMENTUM")
    with pytest.raises(ValueError, match="overdraw"):
        service.transfer(1001, "TA", "MOMENTUM", "too-big", "2026-11-02")
    assert service.ledger("TA") == before_ta
    assert service.ledger("MOMENTUM") == before_momentum
    service.cash_event("MOMENTUM", {"event_id": "transfer:conflict:MOMENTUM", "cash_type": "DEPOSIT",
                                    "amount_inr": 25, "executed_at": "2026-11-02"})
    target = service.ledger("MOMENTUM")
    with pytest.raises(ValueError, match="different payload"):
        service.transfer(10, "TA", "MOMENTUM", "conflict", "2026-11-02")
    assert service.ledger("TA") == before_ta
    assert service.ledger("MOMENTUM") == target
    service.transfer(50, "TA", "MOMENTUM", "ok", "2026-11-03")
    ta, momentum = service.ledger("TA"), service.ledger("MOMENTUM")
    assert Decimal(ta["cash_balance_inr"]) + Decimal(momentum["cash_balance_inr"]) == Decimal("1125")
    service.transfer(50, "TA", "MOMENTUM", "ok", "2026-11-03")
    assert service.ledger("TA") == ta
    assert service.ledger("MOMENTUM") == momentum


def test_original_plan_and_existing_events_remain_immutable(service):
    candidate = setup_candidate()
    service.repo.save_candidates([candidate])
    service.repo.save_candidates([candidate])
    with transaction(service.engine) as session:
        assert session.scalar(select(func.count()).select_from(CandidateEvent)) == 1
    changed = deepcopy(candidate)
    changed["original_plan"]["stop"] = 90
    with pytest.raises(ValueError, match="immutable"):
        service.repo.save_candidates([changed])
    assert service.repo.candidate(candidate["id"])["original_plan"] == candidate["original_plan"]
    service.set_watch(candidate["id"], note="Private working note")
    watched = service.watch_items()
    assert len(watched) == 1
    assert watched[0]["note"] == "Private working note"
    assert service.repo.candidate(candidate["id"])["original_plan"] == candidate["original_plan"]
    service.set_watch(candidate["id"], watched=False)
    assert not service.watch_items()


def test_initial_model_capital_can_be_configured_after_first_unfunded_scan(service):
    frames, benchmark = synthetic_frames("2026-11-03")
    scope = {"wide": list(frames)}
    service.scan_frames(frames, benchmark, "2026-11-02", scopes=scope, mode="momentum", source="SYNTHETIC")
    assert service.momentum_report()["model"]["capital_configured"] is False
    service.update_settings({"momentum_capital_inr": 100000})
    service.scan_frames(frames, benchmark, "2026-11-03", scopes=scope, mode="momentum", source="SYNTHETIC")
    model = service.momentum_report()["model"]
    assert model["capital_configured"] is True
    assert model["ledger"]["opening_cash_inr"] == "100000.00"
    assert model["pending_rebalance"]["signal_date"] == "2026-11-03"
    assert service.repo.account("MOMENTUM") is None
    with pytest.raises(ValueError, match="fixed"):
        service.update_settings({"momentum_capital_inr": 200000})


def test_scan_retry_keeps_run_identity_and_actual_account_unchanged(service):
    frames, benchmark = synthetic_frames("2026-11-03")
    configure(service, "TA", 12345)
    configure(service, "MOMENTUM", 23456)
    original = {mode: service.ledger(mode) for mode in ("TA", "MOMENTUM")}
    scope = {"wide": list(frames)}
    first = service.scan_frames(frames, benchmark, "2026-11-03", scopes=scope, mode="momentum", source="SYNTHETIC")
    report = service.momentum_report()
    second = service.scan_frames(frames, benchmark, "2026-11-03", scopes=scope, mode="momentum", source="SYNTHETIC")
    assert first["id"] == second["id"]
    assert len(service.repo.runs()) == 1
    assert service.momentum_report()["model"] == report["model"]
    for mode in original:
        assert service.ledger(mode) == original[mode]


def test_market_snapshots_are_content_addressed_and_do_not_contain_account_data(service):
    frames, benchmark = synthetic_frames("2026-11-03")
    configure(service, "TA", 123456.78)
    service.record_fill("TA", {"execution_id": "private-fill-id", "executed_at": "2026-11-02", "symbol": "DEMOA", "side": "BUY", "quantity": 5, "price_inr": 100, "fees_inr": 1})
    root = Path(__file__).resolve().parents[1]
    public_before = (root / "docs/latest_screen.json").read_bytes()
    service.scan_frames(frames, benchmark, "2026-11-03", scopes={"wide": list(frames)}, mode="momentum", source="SYNTHETIC")
    payload = service.repo.prices("DEMOA.NS")
    archived = service.archive.get(payload["archive_key"])
    serialized = json.dumps(archived)
    for private in ("private-fill-id", "123456.78", "cash_balance_inr", "execution_history", "average_cost_inr"):
        assert private not in serialized
    assert archived["bars"][-1]["date"] == "2026-11-03"
    assert service.archive.put(archived) == payload["archive_key"]
    assert (root / "docs/latest_screen.json").read_bytes() == public_before
    with transaction(service.engine) as session:
        snapshots = list(session.scalars(select(PriceSnapshot)))
        assert snapshots
        assert all("bars" not in snap.payload for snap in snapshots)


def test_backup_restores_private_state_and_inputs_only_into_empty_store(service, tmp_path):
    configure(service)
    service.repo.save_candidates([setup_candidate()])
    service.set_watch("signal-1", note="Private note preserved by owner backup")
    frames, benchmark = synthetic_frames("2026-11-03")
    service.scan_frames(frames, benchmark, "2026-11-03", scopes={"wide": list(frames)}, mode="momentum", source="SYNTHETIC")
    bundle = service.export_bundle()
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert "tracker.json" in archive.namelist()
        assert any(name.startswith("inputs/") for name in archive.namelist())
    restored = TrackerService("sqlite:///" + (tmp_path / "restored.db").as_posix(),
                              archive=InputArchive(local_directory=tmp_path / "restored-inputs"))
    try:
        assert restored.restore_bundle(bundle)["status"] == "restored"
        assert restored.ledger("TA") == service.ledger("TA")
        assert restored.repo.candidate("signal-1") == service.repo.candidate("signal-1")
        assert restored.watch_items()[0]["note"] == service.watch_items()[0]["note"]
        key = restored.repo.prices("DEMOA.NS")["archive_key"]
        assert restored.archive.get(key) == service.archive.get(key)
        before = restored.ledger("TA")
        with pytest.raises(ValueError, match="empty"):
            restored.restore_bundle(bundle)
        assert restored.ledger("TA") == before
    finally:
        restored.engine.dispose()


def test_historical_valuation_uses_only_fills_effective_by_that_session(service):
    configure(service, amount=10000)
    service.record_fill("TA", {"execution_id": "later", "executed_at": "2026-11-04", "symbol": "DEMOA", "side": "BUY", "quantity": 5, "price_inr": 100, "fees_inr": 1})
    frames, _ = synthetic_frames("2026-11-05")
    clipped = {symbol: frame.loc[:"2026-11-02"] for symbol, frame in frames.items()}
    service._record_actual_valuations(clipped, "2026-11-02")
    mark = service.repo.document("valuations", "TA:2026-11-02")
    assert mark["complete"] is True
    assert Decimal(mark["equity_inr"]) == 10000
    assert service.ledger("TA")["holdings"]["DEMOA.NS"]["quantity"] == 5


@pytest.mark.skipif(not os.environ.get("DATABASE_TEST_URL"), reason="Set DATABASE_TEST_URL for isolated PostgreSQL integration.")
def test_postgresql_transaction_and_backup_in_isolated_schema(tmp_path):
    """An explicitly supplied test DB gets a unique disposable schema only."""
    from sqlalchemy.engine import make_url
    base_url = os.environ["DATABASE_TEST_URL"]
    admin = make_engine(base_url)
    schema = "tracker_test_" + uuid.uuid4().hex
    app = None
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(base_url)
        query = dict(url.query)
        query["options"] = "-csearch_path=" + schema
        scoped = url.set(query=query).render_as_string(hide_password=False)
        app = TrackerService(scoped, initialize=True, archive=InputArchive(local_directory=tmp_path / "pg-inputs"))
        configure(app, "TA", 1000)
        configure(app, "MOMENTUM", 100)
        with pytest.raises(ValueError):
            app.transfer(1001, "TA", "MOMENTUM", "oversized", "2026-11-02")
        assert app.ledger("TA")["cash_balance_inr"] == "1000.00"
        assert app.ledger("MOMENTUM")["cash_balance_inr"] == "100.00"
        assert app.export_bundle()
    finally:
        if app is not None:
            app.engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
