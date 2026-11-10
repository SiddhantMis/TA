"""Relational identities plus immutable JSON decision and event payloads."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Run(Base):
    __tablename__ = "tracker_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    as_of: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON)


class Document(Base):
    __tablename__ = "tracker_documents"
    __table_args__ = (UniqueConstraint("namespace", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    namespace: Mapped[str] = mapped_column(String(50), index=True)
    key: Mapped[str] = mapped_column(String(160))
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Candidate(Base):
    __tablename__ = "tracker_candidates"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    family: Mapped[str] = mapped_column(String(50), index=True)
    signal_session: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class CandidateEvent(Base):
    __tablename__ = "tracker_candidate_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("tracker_candidates.id"), index=True)
    session: Mapped[str] = mapped_column(String(10), index=True)
    type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)


class WatchItem(Base):
    __tablename__ = "tracker_watch_items"
    candidate_id: Mapped[str] = mapped_column(ForeignKey("tracker_candidates.id"), primary_key=True)
    watched: Mapped[bool] = mapped_column(default=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Account(Base):
    __tablename__ = "tracker_accounts"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class LedgerEvent(Base):
    __tablename__ = "tracker_ledger_events"
    __table_args__ = (UniqueConstraint("account_id", "external_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("tracker_accounts.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(160))
    payload: Mapped[dict] = mapped_column(JSON)


class PriceSnapshot(Base):
    __tablename__ = "tracker_price_snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    as_of: Mapped[str] = mapped_column(String(10), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ModelTrade(Base):
    __tablename__ = "tracker_model_trades"
    candidate_id: Mapped[str] = mapped_column(ForeignKey("tracker_candidates.id"), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class BasketSnapshot(Base):
    __tablename__ = "tracker_basket_snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(30), index=True)
    as_of: Mapped[str] = mapped_column(String(10), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
