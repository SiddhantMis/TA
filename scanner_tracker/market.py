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
OHLC_FLOAT_EPSILON = 1e-9
REPAIR_LOOKBACK_DAYS = 7


def _format_fetch_error(exc):
    name = type(exc).__name__
    message = " ".join(str(exc).split()).strip()
    if not message:
        return name
    if len(message) > 240:
        message = message[:237] + "..."
    return f"{name}: {message}"


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


def _prepare_frame(frame, as_of):
    if frame is None or frame.empty:
        raise ValueError("No market history returned.")
    d = frame.copy()
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d.columns = [str(c).title() for c in d.columns]
    drop_cols = [c for c in d.columns if c.lower() == "repaired?"]
    if drop_cols:
        d = d.drop(columns=drop_cols)
    d.index = pd.to_datetime(d.index)
    if d.index.tz is not None:
        d.index = d.index.tz_convert(IST).tz_localize(None)
    d.index = d.index.normalize()
    d = d.loc[d.index <= pd.Timestamp(as_of)].sort_index()
    if d.index.has_duplicates:
        dupes = sorted({stamp.date().isoformat() for stamp in d.index[d.index.duplicated()]})
        raise ValueError(f"Duplicate source sessions: {', '.join(dupes[:5])}.")
    if not set(OHLCV).issubset(d.columns):
        missing = sorted(set(OHLCV) - set(d.columns))
        raise ValueError(f"Market history lacks required OHLCV fields: {', '.join(missing)}.")
    for col in d.columns:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    return d


def _invalid_ohlcv_mask(d):
    observed = d[OHLCV]
    missing_or_nonfinite = observed.isna().any(axis=1) | ~np.isfinite(observed).all(axis=1)
    non_positive = (d[["Open", "High", "Low", "Close"]] <= 0).any(axis=1) | (d.Volume < 0)
    inconsistent_ohlc = (
        (d.High + OHLC_FLOAT_EPSILON < d[["Open", "Close", "Low"]].max(axis=1))
        | (d.Low - OHLC_FLOAT_EPSILON > d[["Open", "Close", "High"]].min(axis=1))
    )
    return missing_or_nonfinite, non_positive, inconsistent_ohlc


def _validate_prepared_frame(d):
    missing_or_nonfinite, non_positive, inconsistent_ohlc = _invalid_ohlcv_mask(d)
    bad = missing_or_nonfinite | non_positive | inconsistent_ohlc
    if bad.any():
        reasons = []
        if missing_or_nonfinite.any():
            reasons.append("missing/non-finite")
        if non_positive.any():
            reasons.append("non-positive")
        if inconsistent_ohlc.any():
            reasons.append("inconsistent OHLC")
        bad_index = d.index[bad]
        bad_dates = [stamp.date().isoformat() for stamp in bad_index[:5]]
        sample_stamp = bad_index[0]
        sample = d.loc[sample_stamp, OHLCV].to_dict()
        detail = ", ".join(f"{col}={sample[col]}" for col in OHLCV)
        raise ValueError(
            f"Source history contains {', '.join(reasons)} OHLCV bars "
            f"on {', '.join(bad_dates)} (first bad: {sample_stamp.date().isoformat()} {detail})."
        )
    return d


def normalize_frame(frame, as_of):
    return _validate_prepared_frame(_prepare_frame(frame, as_of))


def _no_corporate_actions_on_date(d, stamp):
    for col in ("Dividends", "Stock Splits", "Capital Gains"):
        if col in d.columns:
            val = d.at[stamp, col]
            if pd.notna(val) and float(val) != 0.0:
                return False
    return True


def _can_recover_latest_close(d, cutoff):
    if d.empty or d.index[-1] != cutoff:
        return False
    if len(d) > 1:
        missing, non_pos, inconsistent = _invalid_ohlcv_mask(d.iloc[:-1])
        if (missing | non_pos | inconsistent).any():
            return False
    close_val = d.at[cutoff, "Close"]
    if pd.notna(close_val) and np.isfinite(close_val):
        return False
    open_v = d.at[cutoff, "Open"]
    high_v = d.at[cutoff, "High"]
    low_v = d.at[cutoff, "Low"]
    vol_v = d.at[cutoff, "Volume"]
    if any(pd.isna(v) or not np.isfinite(v) for v in (open_v, high_v, low_v, vol_v)):
        return False
    if open_v <= 0 or high_v <= 0 or low_v <= 0 or vol_v < 0:
        return False
    if high_v + OHLC_FLOAT_EPSILON < max(open_v, low_v) or low_v - OHLC_FLOAT_EPSILON > min(open_v, high_v):
        return False
    return True


def _recover_latest_close_from_adj_close(d, cutoff):
    if "Adj Close" not in d.columns or not _no_corporate_actions_on_date(d, cutoff):
        return False
    adj = d.at[cutoff, "Adj Close"]
    if pd.isna(adj) or not np.isfinite(adj) or adj <= 0:
        return False
    low_v, high_v = d.at[cutoff, "Low"], d.at[cutoff, "High"]
    if low_v - OHLC_FLOAT_EPSILON <= adj <= high_v + OHLC_FLOAT_EPSILON:
        d.at[cutoff, "Close"] = float(adj)
        return True
    return False


def _recover_latest_close_via_repair(yf, symbol, d, cutoff):
    try:
        repaired_raw = yf.download(
            symbol,
            start=(cutoff - pd.Timedelta(days=REPAIR_LOOKBACK_DAYS)).date().isoformat(),
            end=(cutoff + pd.Timedelta(days=1)).date().isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=True,
            repair=True,
            keepna=True,
            progress=False,
            threads=False,
            timeout=25,
        )
        repaired = _prepare_frame(repaired_raw, cutoff)
        if cutoff not in repaired.index:
            return False
        row = _validate_prepared_frame(repaired.loc[[cutoff]])
    except Exception:
        return False
    for col in d.columns:
        if col in row.columns:
            val = row.at[cutoff, col]
            if pd.notna(val) and np.isfinite(val):
                if pd.api.types.is_integer_dtype(d[col].dtype):
                    if float(val).is_integer():
                        d.at[cutoff, col] = int(val)
                    else:
                        d[col] = d[col].astype("float64")
                        d.at[cutoff, col] = float(val)
                else:
                    d.at[cutoff, col] = float(val)
    if (
        "Adj Close" in d.columns
        and (pd.isna(d.at[cutoff, "Adj Close"]) or not np.isfinite(d.at[cutoff, "Adj Close"]))
        and _no_corporate_actions_on_date(d, cutoff)
    ):
        d.at[cutoff, "Adj Close"] = float(d.at[cutoff, "Close"])
    return True


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
        return pd.DataFrame(columns=OHLCV, index=pd.DatetimeIndex([]))
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

    def _download_and_normalize(self, yf, symbol, start, cutoff):
        raw = yf.download(
            symbol,
            start=start.date().isoformat(),
            end=(cutoff + pd.Timedelta(days=1)).date().isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=False,
            timeout=25,
        )
        d = _prepare_frame(raw, cutoff)
        if _can_recover_latest_close(d, cutoff):
            if not _recover_latest_close_from_adj_close(d, cutoff):
                _recover_latest_close_via_repair(yf, symbol, d, cutoff)
        return _validate_prepared_frame(d)

    def fetch(self, symbol, as_of, previous=None):
        import yfinance as yf
        cutoff = pd.Timestamp(as_of)
        if previous is not None and not previous.empty:
            previous = previous.loc[previous.index <= cutoff]
        else:
            previous = None
        start = cutoff - pd.Timedelta(days=900)
        if previous is not None and not previous.empty:
            start = max(start, previous.index[-1] - pd.Timedelta(days=14))
        errors = []
        for attempt in range(3):
            try:
                d = self._download_and_normalize(yf, symbol, start, cutoff)
                if previous is not None and not previous.empty:
                    overlap = previous.index.intersection(d.index)
                    revised = False
                    for column in ("Close", "Adj Close"):
                        if column in previous and column in d and len(overlap):
                            revised |= not np.allclose(previous.loc[overlap, column], d.loc[overlap, column], rtol=1e-8, atol=1e-8, equal_nan=True)
                    if revised:
                        return self._download_and_normalize(yf, symbol, cutoff - pd.Timedelta(days=900), cutoff)
                    old = previous.loc[previous.index < d.index.min()]
                    d = pd.concat([old, d]).sort_index()
                return d.loc[d.index >= cutoff - pd.Timedelta(days=900)]
            except Exception as exc:
                errors.append(_format_fetch_error(exc))
                if attempt < 2:
                    time.sleep(2 ** attempt)
        unique_errors = list(dict.fromkeys(errors))
        summary = "; ".join(unique_errors) if len(unique_errors) < len(errors) else " | ".join(errors)
        raise RuntimeError(f"{symbol}: history unavailable after three attempts ({summary}).")
