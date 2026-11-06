"""Headless EOD jobs; the browser never owns the scheduler or account state."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import time

import pandas as pd
from sqlalchemy import text

import leaders

from .market import BENCHMARK, YahooProvider, expected_sessions, latest_completed_session, payload_frame
from .repository import digest


@contextmanager
def worker_lock(engine):
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            acquired = connection.execute(text("SELECT pg_try_advisory_lock(739210)")).scalar()
            connection.commit()
            if not acquired:
                raise RuntimeError("Another tracker worker is active; no overlapping scan was started.")
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(739210)"))
                connection.commit()
    else:
        import os
        from pathlib import Path
        lockfile = Path(engine.url.database or ".local/tracker.db").with_suffix(".worker.lock")
        lockfile.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("Local worker lock exists. Confirm the earlier worker stopped before removing its lock.") from exc
        try:
            os.write(descriptor, str(os.getpid()).encode())
            yield
        finally:
            os.close(descriptor)
            lockfile.unlink(missing_ok=True)


def run_eod(service, *, as_of=None, mode="both", scope="all", provider=None, request_id=None, sleep=1.5):
    provider = provider or YahooProvider()
    target = as_of or latest_completed_session()
    latest = latest_completed_session()
    if pd.Timestamp(target) > pd.Timestamp(latest):
        raise ValueError("Cannot scan a future or unsettled session.")
    if pd.Timestamp(target) not in expected_sessions(target, target):
        raise ValueError("Requested date is not an approved exchange session.")
    settings = service.settings()
    scopes = {}
    if scope in {"all", "wide"}:
        scopes["wide"] = leaders.load_universe()
    if scope in {"all", "personal"}:
        scopes["personal"] = settings["personal_symbols"]
    if not scopes:
        raise ValueError("Scope must be all, wide or personal.")
    symbols = set().union(*map(set, scopes.values()))
    for account_mode in ("TA", "MOMENTUM"):
        symbols.update(service.ledger(account_mode).get("holdings", {}))
    symbols.update(x["symbol"] for x in service.repo.candidates() if x["status"] not in {"closed", "expired", "invalidated", "skipped"})
    for report in service.repo.documents("momentum"):
        symbols.update((report.get("model", {}).get("ledger") or {}).get("holdings", {}))
    attempt = digest([target, mode, scope, datetime.now(timezone.utc).isoformat()])
    with worker_lock(service.engine):
        if as_of is None and request_id is None:
            published = next((run for run in service.repo.runs() if run["as_of"] == target and run["status"] == "complete"
                              and run.get("mode") == mode and run.get("scopes") == {key: sorted(set(value)) for key, value in scopes.items()}), None)
            if published:
                from .notifications import publish_updates
                try:
                    publish_updates(service, published)
                except (ValueError, RuntimeError) as exc:
                    service.repo.save_document("health", "notifications", {"status": "failed", "error": type(exc).__name__})
                return dict(published, skipped_already_complete=True)
        service.repo.record_run(attempt, target, "running", {"mode": mode, "scope": scope, "request_id": request_id})
        try:
            previous = payload_frame(service.repo.prices(BENCHMARK))
            benchmark = provider.fetch(BENCHMARK, target, previous)
            if benchmark.empty or benchmark.index[-1] != pd.Timestamp(target):
                raise ValueError("Benchmark did not publish the exact required session.")
            frames, errors = {}, {}
            for symbol in sorted(symbols):
                try:
                    previous = payload_frame(service.repo.prices(symbol))
                    frames[symbol] = provider.fetch(symbol, target, previous)
                except (ValueError, RuntimeError) as exc:
                    errors[symbol] = str(exc)
                if sleep:
                    time.sleep(sleep)
            result = service.scan_frames(frames, benchmark, target, scopes=scopes, diagnostics=errors,
                source=provider.source, request_id=request_id, mode=mode)
            service.repo.record_run(attempt, target, result["status"], {**{k: v for k, v in result.items() if k not in {"id", "status", "as_of"}}, "published_run": result["id"]})
            from .notifications import publish_updates
            try:
                delivery = publish_updates(service, result)
                service.repo.save_document("health", "notifications", delivery)
            except (ValueError, RuntimeError) as exc:
                service.repo.save_document("health", "notifications", {"status": "failed", "error": type(exc).__name__})
            return result
        except Exception as exc:
            service.repo.record_run(attempt, target, "failed", {"mode": mode, "scope": scope,
                "error": type(exc).__name__, "message": "EOD processing failed; previous published decisions are preserved."})
            raise
