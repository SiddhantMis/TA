"""Unit tests for NSE NIFTYBEES parsing and split adjustment."""
from datetime import date

import pandas as pd

from nse_benchmark import (
    apply_niftybees_split_adjustments,
    date_chunks,
    parse_nse_rows,
)


def _row(day, opening, high, low, close, volume):
    return {
        "CH_SYMBOL": "NIFTYBEES",
        "CH_SERIES": "EQ",
        "CH_TIMESTAMP": day,
        "CH_OPENING_PRICE": opening,
        "CH_TRADE_HIGH_PRICE": high,
        "CH_TRADE_LOW_PRICE": low,
        "CH_CLOSING_PRICE": close,
        "CH_TOT_TRADED_QTY": volume,
    }


def test_nse_parser_reads_official_historical_trade_row_schema():
    rows = [
        _row("2019-12-18", 1289.95, 1294.32, 1282.10, 1292.54, 21946),
        _row("2019-12-19", 129.20, 130.33, 129.05, 130.20, 271593),
        _row("2019-12-20", 134.95, 134.95, 129.78, 130.34, 246690),
        _row("2019-12-23", 131.20, 131.25, 129.28, 129.93, 318322),
    ]
    frame = parse_nse_rows(rows, date(2019, 12, 18), date(2019, 12, 23))
    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert frame.loc["2019-12-18", "Close"] == 1292.54
    assert frame.loc["2019-12-19", "Close"] == 130.20


def test_split_adjustment_converts_only_pre_ex_date_prices_and_volume():
    rows = [
        _row("2019-12-18", 1289.95, 1294.32, 1282.10, 1292.54, 21946),
        _row("2019-12-19", 129.20, 130.33, 129.05, 130.20, 271593),
        _row("2019-12-20", 134.95, 134.95, 129.78, 130.34, 246690),
        _row("2019-12-23", 131.20, 131.25, 129.28, 129.93, 318322),
    ]
    raw = parse_nse_rows(rows, date(2019, 12, 18), date(2019, 12, 23))
    adjusted = apply_niftybees_split_adjustments(raw)

    assert abs(adjusted.loc["2019-12-18", "Close"] - 129.254) < 1e-9
    assert abs(adjusted.loc["2019-12-18", "Open"] - 128.995) < 1e-9
    assert adjusted.loc["2019-12-18", "Volume"] == 219460
    assert adjusted.loc["2019-12-19", "Close"] == 130.20
    assert adjusted.loc["2019-12-20", "Close"] == 130.34
    assert adjusted.loc["2019-12-23", "Close"] == 129.93
    assert adjusted.attrs["split_adjusted"] is True
    assert len(adjusted.attrs["corporate_actions"]) == 1
    assert adjusted["Close"].pct_change().abs().max() < 0.02


def test_split_adjustment_is_idempotent():
    raw = parse_nse_rows(
        [_row("2019-12-18", 1289.95, 1294.32, 1282.10, 1292.54, 21946)],
        date(2019, 12, 18),
        date(2019, 12, 18),
    )
    once = apply_niftybees_split_adjustments(raw)
    twice = apply_niftybees_split_adjustments(once)
    pd.testing.assert_frame_equal(once, twice)
    assert twice.attrs["corporate_actions"] == once.attrs["corporate_actions"]


def test_nse_request_chunks_are_inclusive_and_non_overlapping():
    chunks = date_chunks(date(2020, 1, 1), date(2020, 4, 10), max_days=100)
    assert chunks == [
        (date(2020, 1, 1), date(2020, 4, 9)),
        (date(2020, 4, 10), date(2020, 4, 10)),
    ]
    assert sum((end - start).days + 1 for start, end in chunks) == 101
