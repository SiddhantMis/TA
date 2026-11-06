"""Transactional storage; retrying a run never replaces its original decision."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from .db import transaction
from .models import (Account, BasketSnapshot, Candidate, CandidateEvent, Document,
                     LedgerEvent, ModelTrade, PriceSnapshot, Run, WatchItem, utcnow)


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "item"):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def digest(value):
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class TrackerRepository:
    def __init__(self, engine):
        self.engine = engine

    def document(self, namespace, key, default=None):
        with transaction(self.engine) as session:
            record = session.scalar(select(Document).where(Document.namespace == namespace, Document.key == key))
            return clean(record.payload) if record else default

    def documents(self, namespace):
        with transaction(self.engine) as session:
            return [{**clean(x.payload), "key": x.key} for x in session.scalars(select(Document).where(Document.namespace == namespace))]

    @staticmethod
    def put_document(session, namespace, key, payload):
        record = session.scalar(select(Document).where(Document.namespace == namespace, Document.key == key).with_for_update())
        if record is None:
            record = Document(namespace=namespace, key=key, payload=clean(payload))
            session.add(record)
        else:
            record.payload, record.updated_at = clean(payload), utcnow()
        return record

    def save_document(self, namespace, key, payload):
        with transaction(self.engine) as session:
            self.put_document(session, namespace, key, payload)

    def candidates(self, mode=None, symbol=None, status=None, scope=None):
        query = select(Candidate).order_by(Candidate.signal_session.desc(), Candidate.symbol)
        for field, value in ((Candidate.mode, mode), (Candidate.symbol, symbol), (Candidate.status, status)):
            if value:
                query = query.where(field == value)
        with transaction(self.engine) as session:
            result = [clean(x.payload) for x in session.scalars(query)]
        return [x for x in result if not scope or scope in x.get("scopes", [])]

    def candidate(self, candidate_id):
        with transaction(self.engine) as session:
            record = session.get(Candidate, candidate_id)
            return clean(record.payload) if record else None

    @staticmethod
    def put_candidate(session, payload):
        payload = clean(payload)
        record = session.scalar(select(Candidate).where(Candidate.id == payload["id"]).with_for_update())
        if record:
            old = record.payload
            if old.get("original_plan") != payload.get("original_plan"):
                raise ValueError("An existing original plan is immutable; create a dated revision instead.")
            terminal = {"closed", "expired", "invalidated", "skipped"}
            if record.status in terminal and payload["status"] != record.status:
                raise ValueError("A terminal setup cannot be reactivated by a stale update; create a new setup identity.")
            old_session = old.get("current", {}).get("last_processed_session", "")
            new_session = payload.get("current", {}).get("last_processed_session", "")
            if old_session and new_session < old_session:
                raise ValueError("A stale candidate update cannot move its lifecycle backward.")
            events = list(old.get("events", []))
            event_ids = {digest(event) for event in events}
            for event in payload.get("events", []):
                if digest(event) not in event_ids:
                    events.append(event)
                    event_ids.add(digest(event))
            payload["events"] = events
            payload["scopes"] = sorted(set(old.get("scopes", [])) | set(payload.get("scopes", [])))
            record.payload, record.status = payload, payload["status"]
        else:
            record = Candidate(id=payload["id"], symbol=payload["symbol"], mode=payload.get("mode", "TA"),
                               family=payload["family"], signal_session=payload["signal_session"],
                               status=payload["status"], payload=payload)
            session.add(record)
            session.flush()
        for event in payload.get("events", []):
            event_id = digest([payload["id"], event])
            if session.get(CandidateEvent, event_id) is None:
                session.add(CandidateEvent(id=event_id, candidate_id=payload["id"],
                    session=str(event.get("session", payload["signal_session"]))[:10],
                    type=event.get("type", "observation"), payload=event))
        trade = payload.get("model_trade")
        if trade:
            saved = session.get(ModelTrade, payload["id"])
            if saved:
                saved.payload = trade
            else:
                session.add(ModelTrade(candidate_id=payload["id"], payload=trade))

    def save_candidates(self, candidates):
        with transaction(self.engine) as session:
            for candidate in candidates:
                self.put_candidate(session, candidate)

    def set_watch(self, candidate_id, watched=True, note=None):
        with transaction(self.engine) as session:
            if session.get(Candidate, candidate_id) is None:
                raise ValueError("Unknown candidate.")
            record = session.get(WatchItem, candidate_id)
            if record is None:
                record = WatchItem(candidate_id=candidate_id, watched=watched, note=note or "")
                session.add(record)
            else:
                record.watched = watched
                if note is not None:
                    record.note = note

    def watch_items(self):
        with transaction(self.engine) as session:
            return [{**clean(candidate.payload), "watched": watch.watched, "note": watch.note}
                    for watch, candidate in session.execute(select(WatchItem, Candidate).join(Candidate).where(WatchItem.watched.is_(True)))]

    def runs(self, limit=30):
        with transaction(self.engine) as session:
            return [{**clean(x.payload), "id": x.id, "as_of": x.as_of, "status": x.status}
                    for x in session.scalars(select(Run).order_by(Run.created_at.desc()).limit(limit))]

    def record_run(self, run_id, as_of, status, payload):
        with transaction(self.engine) as session:
            existing = session.get(Run, run_id)
            if existing is None:
                session.add(Run(id=run_id, as_of=as_of, status=status, payload=clean(payload)))
            elif existing.status != "complete":
                existing.status, existing.payload = status, clean(payload)

    def prices(self, symbol):
        return self.document("latest_prices", symbol, {})

    def save_snapshot(self, symbol, as_of, payload):
        snapshot_id = digest([symbol, as_of, payload])
        with transaction(self.engine) as session:
            if session.get(PriceSnapshot, snapshot_id) is None:
                metadata = {key: value for key, value in payload.items() if key != "bars"}
                session.add(PriceSnapshot(id=snapshot_id, symbol=symbol, as_of=as_of, payload=clean(metadata)))
            self.put_document(session, "latest_prices", symbol, dict(payload, snapshot_id=snapshot_id))
        return snapshot_id

    def account(self, mode, kind="actual"):
        with transaction(self.engine) as session:
            account = session.get(Account, f"{kind}:{mode.upper()}")
            return clean(account.payload) if account else None

    def change_account(self, mode, operation, kind="actual", create=False):
        account_id = f"{kind}:{mode.upper()}"
        with transaction(self.engine) as session:
            record = session.scalar(select(Account).where(Account.id == account_id).with_for_update())
            if record is None and not create:
                raise ValueError("Configure this account's opening cash and positions first.")
            original = clean(record.payload) if record else None
            payload = clean(operation(original))
            if record is None:
                record = Account(id=account_id, mode=mode.upper(), kind=kind, payload=payload)
                session.add(record)
                session.flush()
            else:
                record.payload, record.revision = payload, record.revision + 1
            for item in payload.get("events", []):
                external_id = str(item.get("event_id") or item.get("execution_id") or digest(item))
                item_id = digest([account_id, external_id])
                saved = session.get(LedgerEvent, item_id)
                if saved is not None and saved.payload != item:
                    raise ValueError("A recorded ledger event cannot be overwritten.")
                if saved is None:
                    session.add(LedgerEvent(id=item_id, account_id=account_id, external_id=external_id, payload=item))
            return payload

    def save_basket(self, scope, payload):
        basket_id = digest([scope, payload.get("as_of"), payload.get("rule_version"), payload.get("model"), payload.get("actual_target")])
        with transaction(self.engine) as session:
            if session.get(BasketSnapshot, basket_id) is None:
                session.add(BasketSnapshot(id=basket_id, scope=scope, as_of=payload["as_of"], payload=clean(payload)))
            self.put_document(session, "momentum", scope, payload)
        return basket_id
