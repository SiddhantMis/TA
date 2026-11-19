"""One closed-session data contract for live scans and deterministic replay."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import time
import json
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

from .repository import clean, digest

IST = ZoneInfo("Asia/Kolkata")
BENCHMARK = "NIFTYBEES.NS"
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def symbol_name(value):
    symbol = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z0-9&._-]{1,32}", symbol):
        raise ValueError("Invalid NSE instrument symbol.")
    if not symbol.endswith(".NS"):
        symbol += ".NS"
    return symbol


def session_schedule(start, end):
    calendar = mcal.get_calendar("NSE")
    schedule = calendar.schedule(start_date=start, end_date=end)
    from .security import secret_value
    configured = secret_value("TRACKER_SESSION_OVERRIDES", "{}")
    overrides = json.loads(configured) if isinstance(configured, str) else configured
    if not isinstance(overrides, dict):
        raise ValueError("Session overrides must map dates to approved exchange sessions.")
    for day, entry in overrides.items():
        stamp = pd.Timestamp(day).normalize()
        source = urlparse(str(entry.get("source_url", "")))
        if source.scheme != "https" or source.hostname not in {"www.nseindia.com", "nseindia.com", "archives.nseindia.com", "nsearchives.nseindia.com"}:
            raise ValueError("Session overrides require an official NSE HTTPS source URL.")
        if not pd.Timestamp(start) <= stamp <= pd.Timestamp(end):
            continue
        if entry.get("closed") is True:
            schedule = schedule.drop(stamp, errors="ignore")
            continue
        opening, closing = pd.Timestamp(entry.get("market_open")), pd.Timestamp(entry.get("market_close"))
        if opening.tzinfo is None or closing.tzinfo is None or not opening < closing:
            raise ValueError("Special sessions require explicit timezone-aware opening and closing times.")
        if opening.tz_convert(IST).date() != stamp.date() or closing.tz_convert(IST).date() != stamp.date():
            raise ValueError("Special-session dates and exchange-local timestamps must agree.")
        schedule.loc[stamp, "market_open"] = opening.tz_convert("UTC")
        schedule.loc[stamp, "market_close"] = closing.tz_convert("UTC")
    return schedule.sort_index()


def latest_completed_session(now=None):
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        raise ValueError("Session lookup requires a timezone-aware timestamp.")
    schedule = session_schedule((now - timedelta(days=15)).date(), now.date())
    eligible = schedule.loc[schedule.market_close <= pd.Timestamp(now).tz_convert("UTC") - pd.Timedelta(hours=3, minutes=30)]
    if eligible.empty:
        raise RuntimeError("The exchange calendar has no completed, settled session.")
    return eligible.index[-1].date().isoformat()


def expected_sessions(start, end):
    return pd.DatetimeIndex(session_schedule(start, end).index).normalize()


def normalize_frame(frame, as_of):
    if frame is None or frame.empty:
        raise ValueError("No market history returned.")
    d = frame.copy()
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d.columns = [str(c).title() for c in d.columns]
    d.index = pd.to_datetime(d.index)
    if d.index.tz is not None:
        d.index = d.index.tz_convert(IST).tz_localize(None)
    d.index = d.index.normalize()
    d = d.loc[d.index <= pd.Timestamp(as_of)].sort_index()
    if d.index.has_duplicates:
        raise ValueError("Duplicate source sessions.")
    if not set(OHLCV).issubset(d.columns):
        raise ValueError("Market history lacks required OHLCV fields.")
    for col in d.columns:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    observed = d[OHLCV]
    bad = observed.isna().any(axis=1) | ~np.isfinite(observed).all(axis=1)
    bad |= (d[["Open", "High", "Low", "Close"]] <= 0).any(axis=1) | (d.Volume < 0)
    bad |= (d.High < d[["Open", "Close", "Low"]].max(axis=1)) | (d.Low > d[["Open", "Close", "High"]].min(axis=1))
    if bad.any():
        raise ValueError("Source history contains missing, non-positive or inconsistent OHLCV bars.")
    return d


def adjustment_status(frame, since=None):
    actions = {}
    since_date = pd.Timestamp(since) if since else frame.index.max() - pd.Timedelta(days=7)
    for column in ("Stock Splits", "Capital Gains"):
        if column in frame:
            values = frame.loc[frame.index > since_date, column].dropna()
            values = values[values != 0]
            for stamp, value in values.items():
                actions[stamp.date().isoformat()] = {"type": column, "value": float(value)}
    return actions


def frame_payload(frame, source="Yahoo Finance via yfinance"):
    bars = []
    for stamp, row in frame.iterrows():
        item = {"date": stamp.date().isoformat()}
        item.update({str(key): clean(frame.at[stamp, key]) for key in frame.columns})
        bars.append(item)
    return {"source": source, "price_basis": "reported OHLCV; Adj Close retained separately", "index_name": frame.index.name,
            "columns": list(frame.columns), "dtypes": {str(k): str(v) for k, v in frame.dtypes.items()}, "bars": bars}


def payload_frame(payload):
    rows = payload.get("bars", [])
    if not rows:
        return pd.DataFrame(columns=OHLCV)
    d = pd.DataFrame(rows).set_index("date")
    d.index = pd.DatetimeIndex(d.index)
    d.index.name = payload.get("index_name")
    if payload.get("columns"):
        d = d.reindex(columns=payload["columns"])
    for column, dtype in payload.get("dtypes", {}).items():
        if column in d and dtype in {"int64", "int32", "uint64", "float64", "float32", "Int64", "Float64"}:
            d[column] = d[column].astype(dtype)
    return d


class YahooProvider:
    source = "Yahoo Finance via yfinance"

    def fetch(self, symbol, as_of, previous=None):
        import yfinance as yf
        cutoff = pd.Timestamp(as_of)
        if previous is not None:
            previous = previous.loc[previous.index <= cutoff]
        start = cutoff - pd.Timedelta(days=900)
        if previous is not None and not previous.empty:
            start = max(start, previous.index[-1] - pd.Timedelta(days=14))
        errors = []
        for attempt in range(3):
            try:
                d = yf.download(symbol, start=start.date().isoformat(),
                    end=(cutoff + pd.Timedelta(days=1)).date().isoformat(), interval="1d",
                    auto_adjust=False, actions=True, progress=False, threads=False, timeout=25)
                d = normalize_frame(d, as_of)
                if previous is not None and not previous.empty:
                    overlap = previous.index.intersection(d.index)
                    revised = False
                    for column in ("Close", "Adj Close"):
                        if column in previous and column in d and len(overlap):
                            revised |= not np.allclose(previous.loc[overlap, column], d.loc[overlap, column], rtol=1e-8, atol=1e-8, equal_nan=True)
                    if revised:
                        full = yf.download(symbol, start=(cutoff - pd.Timedelta(days=900)).date().isoformat(),
                            end=(cutoff + pd.Timedelta(days=1)).date().isoformat(), interval="1d",
                            auto_adjust=False, actions=True, progress=False, threads=False, timeout=25)
                        return normalize_frame(full, as_of)
                    old = previous.loc[previous.index < d.index.min()]
                    d = pd.concat([old, d]).sort_index()
                return d.loc[d.index >= cutoff - pd.Timedelta(days=900)]
            except Exception as exc:
                errors.append(type(exc).__name__)
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"{symbol}: history unavailable after three attempts ({','.join(errors)}).")
