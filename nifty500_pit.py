"""Point-in-time Nifty 500 membership calendar helpers.

Intervals are [valid_from, valid_to): membership starts on valid_from and
stops immediately before valid_to. A blank valid_to is open-ended.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_MEMBERSHIP_FILE = "universe/nifty500_membership_history.csv"
MEMBERSHIP_COVERAGE_THROUGH = pd.Timestamp("2026-10-13")
EXPECTED_INDEX_SIZE = 500


def normalise_symbol(ticker: str) -> str:
    """Convert Yahoo tickers such as RELIANCE.NS to the NSE cash symbol."""
    value = str(ticker).strip().upper()
    return value[:-3] if value.endswith(".NS") else value


def validate_membership_calendar(calendar: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "valid_from", "valid_to", "source", "source_url", "notes"}
    missing = required - set(calendar.columns)
    if missing:
        raise ValueError(f"membership calendar is missing columns: {sorted(missing)}")

    out = calendar.copy()
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    out["source"] = out["source"].astype(str).str.strip()
    out["valid_from"] = pd.to_datetime(out["valid_from"], errors="coerce")
    out["valid_to"] = pd.to_datetime(out["valid_to"], errors="coerce")
    if out["symbol"].eq("").any() or out["valid_from"].isna().any():
        raise ValueError("membership calendar contains a blank symbol or invalid valid_from")
    bad_range = out["valid_to"].notna() & (out["valid_to"] <= out["valid_from"])
    if bad_range.any():
        raise ValueError("membership calendar contains an empty or reversed interval")

    out = out.sort_values(["symbol", "valid_from", "valid_to"], na_position="last").reset_index(drop=True)
    for symbol, group in out.groupby("symbol", sort=False):
        previous_end = None
        for i, row in enumerate(group.itertuples(index=False)):
            if i > 0 and previous_end is None:
                raise ValueError(f"{symbol} has an open-ended interval followed by another interval")
            if i > 0 and row.valid_from < previous_end:
                raise ValueError(f"{symbol} has overlapping membership intervals")
            previous_end = row.valid_to
    return out


def load_membership_calendar(path: str | Path = DEFAULT_MEMBERSHIP_FILE) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Nifty 500 membership calendar not found: {path}")
    calendar = pd.read_csv(path, dtype=str, keep_default_na=False)
    calendar["valid_to"] = calendar["valid_to"].replace("", pd.NA)
    return validate_membership_calendar(calendar)


def _naive_index(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(index)
    return idx.tz_localize(None) if idx.tz is not None else idx


def build_membership_mask(index, tickers, calendar: pd.DataFrame) -> pd.DataFrame:
    """Return a date x ticker mask using the published half-open intervals."""
    idx = _naive_index(index)
    cal = validate_membership_calendar(calendar)
    grouped = {symbol: group for symbol, group in cal.groupby("symbol", sort=False)}
    values = np.zeros((len(idx), len(tickers)), dtype=bool)

    for j, ticker in enumerate(tickers):
        group = grouped.get(normalise_symbol(ticker))
        if group is None:
            continue
        member = np.zeros(len(idx), dtype=bool)
        for row in group.itertuples(index=False):
            active = idx >= row.valid_from
            if pd.notna(row.valid_to):
                active &= idx < row.valid_to
            member |= active
        values[:, j] = member

    return pd.DataFrame(values, index=idx, columns=list(tickers))


def expected_member_counts(index, calendar: pd.DataFrame) -> np.ndarray:
    """Number of calendar constituents expected on each exchange session."""
    idx = _naive_index(index)
    cal = validate_membership_calendar(calendar)
    counts = np.zeros(len(idx), dtype=np.int32)
    for row in cal.itertuples(index=False):
        active = idx >= row.valid_from
        if pd.notna(row.valid_to):
            active &= idx < row.valid_to
        counts += active.astype(np.int32)
    return counts
