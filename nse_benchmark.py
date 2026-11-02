#!/usr/bin/env python3
"""NSE-sourced NIFTYBEES daily history with explicit corporate-action adjustment.

Uses NSE's historical trade endpoint (getHistoricalTradeData, NIFTYBEES, EQ).
The 10:1 face-value subdivision was effective 2019-12-19 (NSE circular CML/42873).
For prices in today's unit basis, pre-ex-date OHLC is multiplied by 0.1 and
volume by 10. No price-jump heuristic is used.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import os
from time import sleep
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

NSE_BASE = "https://www.nseindia.com"
NSE_HISTORY_URL = f"{NSE_BASE}/api/NextApi/apiClient/GetQuoteApi"
NSE_BOOTSTRAP_URL = f"{NSE_BASE}/option-chain"
NSE_INDEX_HISTORY_URL = f"{NSE_BASE}/api/historicalOR/indicesHistory"
NSE_INDEX_BOOTSTRAP_URL = f"{NSE_BASE}/reports-indices-historical-index-data"
NIFTY50_INDEX_NAME = "NIFTY 50"
NSE_INDEX_SOURCE_NAME = "NSE historicalOR/indicesHistory (NIFTY 50)"
SOURCE_NAME = "NSE NextApi getHistoricalTradeData (NIFTYBEES, EQ)"
NSE_SPLIT_CIRCULAR = "https://archives.nseindia.com/content/circulars/CML42873.pdf"
NIFTYBEES_SPLITS = ({
    "ex_date": date(2019, 12, 19),
    "price_factor": 0.1,
    "volume_factor": 10.0,
    "source": NSE_SPLIT_CIRCULAR,
},)
PRICE_COLUMNS = ("Open", "High", "Low", "Close")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/get-quotes/equity?symbol=NIFTYBEES",
}
INDEX_HEADERS = {
    **HEADERS,
    "Referer": "https://www.nseindia.com/reports-indices-historical-index-data",
}


def date_chunks(start: date, end: date, max_days: int = 100) -> list[tuple[date, date]]:
    """Split an inclusive range into non-overlapping NSE-sized requests."""
    if max_days < 1:
        raise ValueError("max_days must be positive")
    if start > end:
        raise ValueError("start date must not be after end date")
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=max_days - 1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _bootstrap(session: requests.Session, timeout: int) -> None:
    response = session.get(NSE_BOOTSTRAP_URL, timeout=timeout)
    response.raise_for_status()


def _request_chunk(session, start, end, timeout, retries):
    params = {
        "functionName": "getHistoricalTradeData",
        "symbol": "NIFTYBEES",
        "series": "EQ",
        "fromDate": start.strftime("%d-%m-%Y"),
        "toDate": end.strftime("%d-%m-%Y"),
    }
    retryable = {401, 403, 429, 500, 502, 503, 504}
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = session.get(NSE_HISTORY_URL, params=params, timeout=timeout)
            if response.status_code in retryable:
                last_error = requests.HTTPError(
                    f"NSE historical API returned HTTP {response.status_code}"
                )
                if response.status_code in {401, 403}:
                    _bootstrap(session, timeout)
                if attempt < retries:
                    sleep(min(2 ** attempt, 15))
                    continue
                raise last_error
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                payload = payload.get("data", payload.get("equityResponse"))
            if not isinstance(payload, list):
                raise RuntimeError(f"Unexpected NSE response type: {type(payload).__name__}")
            if not payload:
                raise RuntimeError(f"NSE returned no rows for {start} through {end}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            sleep(min(2 ** attempt, 15))
    raise RuntimeError(f"NSE request failed for {start} through {end}: {last_error}") from last_error


def _row_date(row: dict[str, Any]) -> pd.Timestamp:
    value = row.get("CH_TIMESTAMP") or row.get("chTimestamp") or row.get("mTIMESTAMP") or row.get("mtimestamp") or row.get("Date") or row.get("date")
    if value is None:
        raise ValueError("NSE row is missing its trade date")
    parsed = pd.to_datetime(value, format="%Y-%m-%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, format="%d-%b-%Y", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Could not parse NSE trade date: {value!r}")
    return pd.Timestamp(parsed).normalize()


def _number(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return float(str(row[key]).replace(",", "").strip())
    raise ValueError(f"NSE row is missing all fields {keys}")


def parse_nse_rows(rows: list[dict[str, Any]], start: date, end: date) -> pd.DataFrame:
    """Convert NSE historical trade rows to the backtest OHLCV shape."""
    records = []
    for row in rows:
        # NSE can include non-trade metadata rows in the response envelope.
        # Ignore those only when they carry neither a symbol nor any trade date.
        has_trade_date = any(row.get(key) for key in ("CH_TIMESTAMP", "chTimestamp", "mTIMESTAMP", "mtimestamp", "Date", "date"))
        has_symbol = any(row.get(key) for key in ("CH_SYMBOL", "chSymbol", "symbol"))
        if not has_trade_date and not has_symbol:
            continue
        symbol_value = row.get("CH_SYMBOL", row.get("chSymbol", row.get("symbol")))
        if symbol_value is None:
            continue
        series_value = row.get("CH_SERIES", row.get("chSeries", row.get("series", "EQ")))
        symbol = str(symbol_value).upper()
        series = str(series_value).upper()
        if symbol != "NIFTYBEES" or series != "EQ":
            continue
        day = _row_date(row)
        if day.date() < start or day.date() > end:
            continue
        records.append({
            "Date": day,
            "Open": _number(row, "CH_OPENING_PRICE", "chOpeningPrice", "Open", "open"),
            "High": _number(row, "CH_TRADE_HIGH_PRICE", "chTradeHighPrice", "High", "high"),
            "Low": _number(row, "CH_TRADE_LOW_PRICE", "chTradeLowPrice", "Low", "low"),
            "Close": _number(row, "CH_CLOSING_PRICE", "chClosingPrice", "Close", "close"),
            "Volume": _number(row, "CH_TOT_TRADED_QTY", "chTotTradedQty", "Volume", "volume"),
        })
    if not records:
        raise RuntimeError(f"NSE returned no parseable NIFTYBEES EQ rows; sample={rows[:3]!r}")
    frame = pd.DataFrame.from_records(records).set_index("Date").sort_index()
    if frame.index.has_duplicates:
        dates = frame.index[frame.index.duplicated()].strftime("%Y-%m-%d").tolist()
        raise RuntimeError(f"Duplicate NIFTYBEES dates: {dates[:8]}")
    if frame[list(PRICE_COLUMNS)].isna().any().any():
        raise RuntimeError("NSE NIFTYBEES history has missing OHLC prices")
    if (frame[list(PRICE_COLUMNS)] <= 0).any().any():
        raise RuntimeError("NSE NIFTYBEES history has non-positive OHLC prices")
    return frame


def fetch_niftybees_history(
    start_date: date,
    end_date: date,
    *,
    session: requests.Session | None = None,
    timeout: int = 25,
    retries: int = 3,
    pause_seconds: float = 1.0,
) -> pd.DataFrame:
    """Fetch raw, unadjusted NIFTYBEES EQ OHLCV from NSE in 100-day chunks."""
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    owns_session = session is None
    client = session or requests.Session()
    client.headers.update(HEADERS)
    try:
        _bootstrap(client, timeout)
        chunks = date_chunks(start_date, end_date)
        parsed_chunks = []
        for position, (chunk_start, chunk_end) in enumerate(chunks):
            rows = _request_chunk(client, chunk_start, chunk_end, timeout, retries)
            try:
                parsed_chunks.append(parse_nse_rows(rows, chunk_start, chunk_end))
            except Exception as exc:
                raise RuntimeError(
                    f"Could not parse NSE NIFTYBEES response for "
                    f"{chunk_start} through {chunk_end}: {exc}"
                ) from exc
            if position < len(chunks) - 1 and pause_seconds > 0:
                sleep(pause_seconds)
        frame = pd.concat(parsed_chunks).sort_index()
        if frame.index.has_duplicates:
            duplicates = frame.index[frame.index.duplicated()].strftime("%Y-%m-%d").tolist()
            raise RuntimeError(f"Duplicate NIFTYBEES sessions across NSE chunks: {duplicates[:8]}")
        frame.attrs.update({
            "source": SOURCE_NAME,
            "raw_exchange_prices": True,
            "split_adjusted": False,
            "requested_start": start_date.isoformat(),
            "requested_end": end_date.isoformat(),
        })
        return frame
    finally:
        if owns_session:
            client.close()


def _bootstrap_index(session: requests.Session, timeout: int) -> None:
    response = session.get(NSE_INDEX_BOOTSTRAP_URL, timeout=timeout)
    response.raise_for_status()


def parse_nse_index_rows(rows: list[dict[str, Any]], start: date, end: date) -> pd.DataFrame:
    """Parse the official NSE historical NIFTY 50 index response."""
    required = {
        "EOD_INDEX_NAME", "EOD_TIMESTAMP", "EOD_OPEN_INDEX_VAL",
        "EOD_HIGH_INDEX_VAL", "EOD_LOW_INDEX_VAL", "EOD_CLOSE_INDEX_VAL",
    }
    records = []
    for row in rows:
        if not isinstance(row, dict) or not required.issubset(row):
            raise RuntimeError("NSE NIFTY 50 response is missing required EOD fields")
        index_name = " ".join(str(row["EOD_INDEX_NAME"]).upper().split())
        if index_name != NIFTY50_INDEX_NAME:
            raise RuntimeError(f"Unexpected NSE index name: {row['EOD_INDEX_NAME']!r}")
        value = row["EOD_TIMESTAMP"]
        day = pd.to_datetime(value, format="%d-%b-%Y", errors="coerce")
        if pd.isna(day):
            day = pd.to_datetime(value, dayfirst=True, errors="coerce")
        if pd.isna(day):
            raise RuntimeError(f"Could not parse NSE index date: {value!r}")
        day = pd.Timestamp(day).normalize()
        if day.date() < start or day.date() > end:
            raise RuntimeError(f"NSE index date {day.date()} is outside requested window")
        try:
            opening, high, low, close = (
                float(str(row[field]).replace(",", "").strip())
                for field in (
                    "EOD_OPEN_INDEX_VAL", "EOD_HIGH_INDEX_VAL",
                    "EOD_LOW_INDEX_VAL", "EOD_CLOSE_INDEX_VAL",
                )
            )
        except (TypeError, ValueError):
            raise RuntimeError(f"Invalid NSE NIFTY 50 OHLC row for {day.date()}") from None
        if min(opening, high, low, close) <= 0:
            raise RuntimeError(f"Non-positive NSE NIFTY 50 OHLC row for {day.date()}")
        if high + 0.01 < max(opening, low, close) or low - 0.01 > min(opening, high, close):
            raise RuntimeError(f"Invalid NSE NIFTY 50 OHLC range for {day.date()}")
        records.append({"Date": day, "Open": opening, "High": high, "Low": low, "Close": close})
    if not records:
        raise RuntimeError(f"NSE returned no NIFTY 50 rows for {start} through {end}")
    frame = pd.DataFrame.from_records(records).set_index("Date").sort_index()
    if frame.index.has_duplicates:
        dates = frame.index[frame.index.duplicated()].strftime("%Y-%m-%d").tolist()
        raise RuntimeError(f"Duplicate NSE NIFTY 50 dates: {dates[:8]}")
    return frame


def _request_index_chunk(session, start, end, timeout, retries):
    params = {
        "indexType": NIFTY50_INDEX_NAME,
        "from": start.strftime("%d-%m-%Y"),
        "to": end.strftime("%d-%m-%Y"),
    }
    retryable = {401, 403, 429, 500, 502, 503, 504}
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = session.get(NSE_INDEX_HISTORY_URL, params=params, timeout=timeout)
            if response.status_code in retryable:
                last_error = requests.HTTPError(
                    f"NSE index history returned HTTP {response.status_code}"
                )
                if response.status_code in {401, 403}:
                    _bootstrap_index(session, timeout)
                if attempt < retries:
                    sleep(min(2 ** attempt, 15))
                    continue
                raise last_error
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                rows = payload
            elif isinstance(payload, dict):
                data = payload.get("data")
                if isinstance(data, list):
                    rows = data
                elif isinstance(data, dict):
                    rows = data.get("indexCloseOnlineRecords")
                else:
                    rows = payload.get("indexCloseOnlineRecords")
            else:
                rows = None
            if not isinstance(rows, list) or not rows:
                raise RuntimeError(
                    f"NSE returned an empty/invalid NIFTY 50 response for {start} through {end}"
                )
            return rows
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            sleep(min(2 ** attempt, 15))
    raise RuntimeError(f"NSE NIFTY 50 request failed for {start} through {end}: {last_error}") from last_error


def fetch_nifty50_index_history(
    start_date: date, end_date: date, *, session: requests.Session | None = None,
    timeout: int = 25, retries: int = 3, pause_seconds: float = 0.2, max_days: int = 365,
) -> pd.DataFrame:
    """Fetch official NSE NIFTY 50 index OHLC and its exchange-session dates."""
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    owns_session = session is None
    client = session or requests.Session()
    client.headers.update(INDEX_HEADERS)
    try:
        _bootstrap_index(client, timeout)
        chunks = date_chunks(start_date, end_date, max_days=max_days)
        parsed = []
        for position, (chunk_start, chunk_end) in enumerate(chunks):
            rows = _request_index_chunk(client, chunk_start, chunk_end, timeout, retries)
            parsed.append(parse_nse_index_rows(rows, chunk_start, chunk_end))
            if position < len(chunks) - 1 and pause_seconds > 0:
                sleep(pause_seconds)
        frame = pd.concat(parsed).sort_index()
        if frame.index.has_duplicates:
            dates = frame.index[frame.index.duplicated()].strftime("%Y-%m-%d").tolist()
            raise RuntimeError(f"Duplicate NSE NIFTY 50 dates across chunks: {dates[:8]}")
        frame.attrs.update({
            "source": NSE_INDEX_SOURCE_NAME, "index_name": NIFTY50_INDEX_NAME,
            "requested_start": start_date.isoformat(), "requested_end": end_date.isoformat(),
        })
        return frame
    finally:
        if owns_session:
            client.close()


def load_niftybees_raw_history(
    start_date: date, end_date: date, *, cache_path: str | None = None,
    refresh: bool = False, session: requests.Session | None = None,
    pause_seconds: float = 1.0,
) -> pd.DataFrame:
    """Load raw NSE NIFTYBEES trades, using a private local cache when supplied."""
    if cache_path and os.path.exists(cache_path) and not refresh:
        try:
            cached = pd.read_csv(cache_path, parse_dates=["Date"]).set_index("Date")
            cached.index = pd.DatetimeIndex(cached.index).normalize()
            start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
            if (not cached.empty and not cached.index.has_duplicates
                and cached.index.min() <= start + pd.Timedelta(days=15)
                and cached.index.max() >= end - pd.Timedelta(days=10)):
                frame = cached.loc[(cached.index >= start) & (cached.index <= end)].copy()
                if not frame.empty:
                    frame.attrs.update({
                        "source": SOURCE_NAME, "raw_exchange_prices": True,
                        "split_adjusted": False, "cache_hit": True,
                    })
                    return frame
        except (OSError, ValueError, KeyError, TypeError):
            pass
    frame = fetch_niftybees_history(start_date, end_date, session=session, pause_seconds=pause_seconds)
    if cache_path:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        frame.rename_axis("Date").to_csv(cache_path)
    return frame


def load_nifty50_index_history(
    start_date: date, end_date: date, *, cache_path: str | None = None,
    refresh: bool = False, session: requests.Session | None = None,
    pause_seconds: float = 0.2,
) -> pd.DataFrame:
    """Load official NSE NIFTY 50 history, cached privately outside the repository."""
    if cache_path and os.path.exists(cache_path) and not refresh:
        try:
            cached = pd.read_csv(cache_path, parse_dates=["Date"]).set_index("Date")
            cached.index = pd.DatetimeIndex(cached.index).normalize()
            start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
            if (not cached.empty and not cached.index.has_duplicates
                and cached.index.min() <= start + pd.Timedelta(days=15)
                and cached.index.max() >= end - pd.Timedelta(days=10)):
                frame = cached.loc[(cached.index >= start) & (cached.index <= end)].copy()
                if not frame.empty:
                    frame.attrs.update({
                        "source": NSE_INDEX_SOURCE_NAME, "index_name": NIFTY50_INDEX_NAME,
                        "cache_hit": True,
                    })
                    return frame
        except (OSError, ValueError, KeyError, TypeError):
            pass
    frame = fetch_nifty50_index_history(start_date, end_date, session=session, pause_seconds=pause_seconds)
    if cache_path:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        frame.rename_axis("Date").to_csv(cache_path)
    return frame


def _normalise_niftybees_frame(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise RuntimeError(f"{label} NIFTYBEES history is empty")
    out = frame.copy()
    idx = pd.DatetimeIndex(pd.to_datetime(out.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    idx = idx.normalize()
    if idx.has_duplicates:
        dates = idx[idx.duplicated()].strftime("%Y-%m-%d").tolist()
        raise RuntimeError(f"{label} NIFTYBEES history has duplicate sessions: {dates[:8]}")
    out.index = idx
    return out.sort_index()


def reconcile_niftybees_sources(
    nse_raw: pd.DataFrame, tejhq_raw: pd.DataFrame, *,
    absolute_tolerance: float = 0.05, relative_tolerance: float = 0.0005,
    min_common_fraction: float = 0.98,
    allowed_extra_sessions: pd.DatetimeIndex | None = None,
) -> dict[str, Any]:
    """Cross-check common raw bars; permit TejHQ-only bars only on official NSE sessions."""
    nse = _normalise_niftybees_frame(nse_raw, "NSE NextApi")
    tej = _normalise_niftybees_frame(tejhq_raw, "TejHQ")
    nse_dates, tej_dates = pd.DatetimeIndex(nse.index), pd.DatetimeIndex(tej.index)
    nse_only, tejhq_only = nse_dates.difference(tej_dates), tej_dates.difference(nse_dates)

    if len(tejhq_only):
        if allowed_extra_sessions is None:
            sample = tejhq_only.strftime("%Y-%m-%d").tolist()[:8]
            raise RuntimeError(
                f"TejHQ has {len(tejhq_only)} NIFTYBEES dates absent from NSE NextApi "
                f"without an official-session allowlist: {sample}"
            )
        allowed = pd.DatetimeIndex(pd.to_datetime(allowed_extra_sessions))
        if allowed.tz is not None:
            allowed = allowed.tz_localize(None)
        unsupported = tejhq_only.difference(allowed.normalize())
        if len(unsupported):
            sample = unsupported.strftime("%Y-%m-%d").tolist()[:8]
            raise RuntimeError(
                f"TejHQ has {len(unsupported)} NIFTYBEES dates absent from NSE NextApi "
                f"and outside the official NSE session calendar: {sample}"
            )

    common = nse_dates.intersection(tej_dates).sort_values()
    common_nse = len(common) / len(nse_dates)
    common_tej = len(common) / len(tej_dates)
    if len(common) == 0 or min(common_nse, common_tej) < min_common_fraction:
        raise RuntimeError(
            f"NIFTYBEES source overlap is insufficient: {len(common)}/{len(nse_dates)} "
            f"NSE bars ({common_nse:.2%}) and {len(common)}/{len(tej_dates)} "
            f"TejHQ bars ({common_tej:.2%}); required {min_common_fraction:.0%}"
        )
    left, right = nse.reindex(common), tej.reindex(common)
    max_abs, max_rel = 0.0, 0.0
    for column in PRICE_COLUMNS:
        if column not in left or column not in right:
            raise RuntimeError(f"NIFTYBEES reconciliation is missing {column}")
        a = pd.to_numeric(left[column], errors="coerce").to_numpy(float)
        b = pd.to_numeric(right[column], errors="coerce").to_numpy(float)
        if not (pd.Series(a).notna().all() and pd.Series(b).notna().all()):
            raise RuntimeError(f"NIFTYBEES reconciliation has missing {column} values")
        absolute = abs(a - b)
        relative = absolute / pd.Series(abs(a)).clip(lower=1e-12).to_numpy(float)
        max_abs = max(max_abs, float(absolute.max()))
        max_rel = max(max_rel, float(relative.max()))
    if max_abs > absolute_tolerance or max_rel > relative_tolerance:
        raise RuntimeError(
            f"NIFTYBEES source reconciliation failed: max absolute OHLC difference={max_abs:.4f}, "
            f"max relative={max_rel:.6%}"
        )
    return {
        "nse_api_bars": int(len(nse_dates)),
        "tejhq_bars": int(len(tej_dates)),
        "common_bars": int(len(common)),
        "nse_api_only_bars": int(len(nse_only)),
        "tejhq_only_bars": int(len(tejhq_only)),
        "common_fraction_of_nse": float(common_nse),
        "common_fraction_of_tejhq": float(common_tej),
        "max_abs_ohlc_diff": max_abs,
        "max_rel_ohlc_diff": max_rel,
        "nse_api_only_dates": nse_only.strftime("%Y-%m-%d").tolist()[:20],
        "tejhq_only_dates": tejhq_only.strftime("%Y-%m-%d").tolist()[:20],
    }


def merge_niftybees_sources(
    nse_raw: pd.DataFrame, tejhq_raw: pd.DataFrame, *,
    allowed_extra_sessions: pd.DatetimeIndex | None = None,
    absolute_tolerance: float = 0.05, relative_tolerance: float = 0.0005,
    min_common_fraction: float = 0.98,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Keep NSE bars and supplement only missing dates validated by the NSE index calendar."""
    nse = _normalise_niftybees_frame(nse_raw, "NSE NextApi")
    tej = _normalise_niftybees_frame(tejhq_raw, "TejHQ")
    audit = reconcile_niftybees_sources(
        nse, tej,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        min_common_fraction=min_common_fraction,
        allowed_extra_sessions=allowed_extra_sessions,
    )
    extra = pd.DatetimeIndex(pd.to_datetime(audit["tejhq_only_dates"]))
    if len(extra):
        missing = [column for column in nse.columns if column not in tej.columns]
        if missing:
            raise RuntimeError(f"TejHQ NIFTYBEES supplement is missing columns: {missing}")
        merged = pd.concat([nse, tej.loc[extra, nse.columns]]).sort_index()
    else:
        merged = nse.copy()
    if merged.index.has_duplicates:
        raise RuntimeError("Merged NIFTYBEES benchmark contains duplicate sessions")
    merged.attrs.update(nse_raw.attrs)
    merged.attrs.update({
        "source": "NSE NextApi raw NIFTYBEES with official-session TejHQ bhavcopy supplements",
        "supplemental_source": "TejHQ raw NSE bhavcopy fields",
        "supplemental_dates": audit["tejhq_only_dates"],
        "raw_exchange_prices": True,
        "split_adjusted": False,
        "source_reconciliation": audit,
    })
    return merged, audit


def apply_niftybees_split_adjustments(frame: pd.DataFrame) -> pd.DataFrame:
    """Express raw NSE prices and volume in current NIFTYBEES unit terms."""
    if frame is None or frame.empty:
        raise ValueError("Cannot adjust an empty NIFTYBEES history")
    if frame.attrs.get("split_adjusted"):
        return frame.copy()
    out = frame.copy()
    actions_applied = []
    for action in NIFTYBEES_SPLITS:
        ex_date = pd.Timestamp(action["ex_date"])
        mask = out.index.normalize() < ex_date
        if not mask.any():
            continue
        out.loc[mask, list(PRICE_COLUMNS)] = (
            out.loc[mask, list(PRICE_COLUMNS)].astype(float) * action["price_factor"]
        )
        if "Volume" in out.columns:
            out.loc[mask, "Volume"] = (
                pd.to_numeric(out.loc[mask, "Volume"], errors="coerce")
                * action["volume_factor"]
            )
        actions_applied.append({
            "ex_date": action["ex_date"].isoformat(),
            "price_factor": action["price_factor"],
            "volume_factor": action["volume_factor"],
            "source": action["source"],
        })
    out.attrs.update(frame.attrs)
    out.attrs.update({
        "source": frame.attrs.get("source", SOURCE_NAME),
        "split_adjusted": True,
        "corporate_actions": actions_applied,
        "price_basis": "NIFTYBEES current Rs 1 face-value units",
    })
    return out


def load_niftybees_history(
    years: int = 10,
    *,
    end_date: date | None = None,
    session: requests.Session | None = None,
    pause_seconds: float = 1.0,
) -> pd.DataFrame:
    """Load NSE NIFTYBEES history and apply the documented split adjustment."""
    if years < 1:
        raise ValueError("years must be at least 1")
    end = end_date or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    start = (pd.Timestamp(end) - pd.DateOffset(years=years)).date()
    raw = load_niftybees_raw_history(
        start, end, session=session, pause_seconds=pause_seconds
    )
    adjusted = apply_niftybees_split_adjustments(raw)
    if adjusted.index[0].date() > start + timedelta(days=15):
        raise RuntimeError(
            f"NSE history starts at {adjusted.index[0].date()}, too late after requested {start}"
        )
    if (end - adjusted.index[-1].date()).days > 10:
        raise RuntimeError(
            f"NSE history is stale: latest {adjusted.index[-1].date()}, requested through {end}"
        )
    adjusted.attrs["requested_years"] = years
    return adjusted
