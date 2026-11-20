"""Database configuration shared by the application and scheduled workers."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import make_url


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if not url:
        raise ValueError("DATABASE_URL is required. Configure private durable storage first.")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    kwargs = {"pool_pre_ping": True, "hide_parameters": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if url.endswith(":memory:"):
            kwargs["poolclass"] = StaticPool
        elif ":///" in url:
            Path(url.split(":///", 1)[1]).expanduser().parent.mkdir(parents=True, exist_ok=True)
    else:
        parsed = make_url(url)
        sslmode = parsed.query.get("sslmode", "require")
        local_test = os.environ.get("TRACKER_ENV") == "test" and parsed.host in {"localhost", "127.0.0.1", "postgres", "test-db"}
        if sslmode not in {"require", "verify-ca", "verify-full"} and not (local_test and sslmode == "disable"):
            raise ValueError("Database connections require TLS; only an explicit local CI test database may disable it.")
        kwargs["connect_args"] = {"sslmode": sslmode, "connect_timeout": 15}
        kwargs.update(pool_size=3, max_overflow=2)
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
    return engine


@contextmanager
def transaction(engine, isolation=None):
    with engine.connect() as connection:
        if isolation and engine.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level=isolation)
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.begin()
        with Session(bind=connection, expire_on_commit=False) as session:
            try:
                yield session
                session.flush()
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def assert_ready(engine):
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:
        raise RuntimeError("Tracker database is not initialized. Run `python -m scanner_tracker migrate`.") from exc
    if version != "0001_tracker":
        raise RuntimeError("Tracker database schema is incompatible with this application release.")
