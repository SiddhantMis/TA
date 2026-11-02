#!/usr/bin/env python3
"""NSE-sourced NIFTYBEES daily history with explicit corporate-action adjustment.

Uses NSE's historical trade endpoint (getHistoricalTradeData, NIFTYBEES, EQ).
The 10:1 face-value subdivision was effective 2019-12-19 (NSE circular CML/42873).
For prices in today's unit basis, pre-ex-date OHLC is multiplied by 0.1 and
volume by 10. No price-jump heuristic is used.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from time import sleep
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

NSE_BASE = "https://www.nseindia.com"
NSE_HISTORY_URL = f"{NSE_BASE}/api/NextApi/apiClient/GetQuoteApi"
NSE_BOOTSTRAP_URL = f"{NSE_BASE}/option-chain"
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
        "source": SOURCE_NAME,
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
    raw = fetch_niftybees_history(
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
