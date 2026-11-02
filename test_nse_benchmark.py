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



def test_nse_parser_ignores_metadata_rows_without_trading_fields():
    rows = [
        {"meta": "response metadata"},
        _row("2019-12-19", 129.20, 130.33, 129.05, 130.20, 271593),
    ]
    frame = parse_nse_rows(rows, date(2019, 12, 19), date(2019, 12, 19))
    assert len(frame) == 1
    assert frame.iloc[0]["Close"] == 130.20


def test_nse_parser_accepts_actual_lower_camel_case_api_rows():
    row = {
        "chClosingPrice": 894.36,
        "chLastTradedPrice": 894.69,
        "chOpeningPrice": 895.04,
        "chPreviousClsPrice": 894.36,
        "chSeries": "EQ",
        "chSymbol": "NIFTYBEES",
        "chTotTradedQty": 18590,
        "chTradeHighPrice": 899.00,
        "chTradeLowPrice": 889.05,
        "mtimestamp": "09-Feb-2017",
    }
    frame = parse_nse_rows([row], date(2017, 2, 9), date(2017, 2, 9))
    assert frame.iloc[0]["Open"] == 895.04
    assert frame.iloc[0]["High"] == 899.00
    assert frame.iloc[0]["Low"] == 889.05
    assert frame.iloc[0]["Close"] == 894.36
    assert frame.iloc[0]["Volume"] == 18590

def _index_row(day, opening, high, low, close):
    return {
        "EOD_INDEX_NAME": "NIFTY 50", "EOD_TIMESTAMP": day,
        "EOD_OPEN_INDEX_VAL": opening, "EOD_HIGH_INDEX_VAL": high,
        "EOD_LOW_INDEX_VAL": low, "EOD_CLOSE_INDEX_VAL": close,
    }


def test_official_nifty50_index_parser_uses_exchange_local_eod_timestamp():
    from nse_benchmark import parse_nse_index_rows

    frame = parse_nse_index_rows(
        [_index_row("03-Nov-2016", 8500, 8550, 8480, 8520),
         _index_row("04-Nov-2016", 8520, 8580, 8510, 8560)],
        date(2016, 11, 3), date(2016, 11, 4),
    )
    assert frame.index.tolist() == [pd.Timestamp("2016-11-03"), pd.Timestamp("2016-11-04")]
    assert frame.iloc[0]["Close"] == 8520


def test_official_nifty50_parser_rejects_wrong_index_and_duplicate_dates():
    from nse_benchmark import parse_nse_index_rows
    import pytest

    with pytest.raises(RuntimeError, match="Unexpected NSE index name"):
        parse_nse_index_rows(
            [_index_row("03-Nov-2016", 8500, 8550, 8480, 8520) | {"EOD_INDEX_NAME": "NIFTY BANK"}],
            date(2016, 11, 3), date(2016, 11, 3),
        )
    row = _index_row("03-Nov-2016", 8500, 8550, 8480, 8520)
    with pytest.raises(RuntimeError, match="Duplicate NSE NIFTY 50 dates"):
        parse_nse_index_rows([row, row], date(2016, 11, 3), date(2016, 11, 3))


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


def test_niftybees_source_reconciliation_accepts_nse_only_bars_but_rejects_tejhq_only():
    from nse_benchmark import reconcile_niftybees_sources
    import pytest

    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])
    common = pd.DataFrame({
        "Open": [100.0, 101.0], "High": [102.0, 103.0],
        "Low": [99.0, 100.0], "Close": [101.0, 102.0],
    }, index=idx)
    nse = pd.concat([
        common,
        pd.DataFrame(
            {"Open": [102.0], "High": [104.0], "Low": [101.0], "Close": [103.0]},
            index=pd.DatetimeIndex(["2024-01-04"]),
        ),
    ])
    result = reconcile_niftybees_sources(nse, common, min_common_fraction=0.5)
    assert result["nse_api_only_bars"] == 1
    assert result["tejhq_only_bars"] == 0
    assert result["common_bars"] == 2

    bad = common.copy()
    bad.loc["2024-01-03", "Close"] += 1.0
    with pytest.raises(RuntimeError, match="source reconciliation failed"):
        reconcile_niftybees_sources(nse, bad, min_common_fraction=0.5)

    tej_extra = pd.concat([
        common,
        pd.DataFrame(
            {"Open": [102.0], "High": [104.0], "Low": [101.0], "Close": [103.0]},
            index=pd.DatetimeIndex(["2024-01-05"]),
        ),
    ])
    with pytest.raises(RuntimeError, match="absent from NSE NextApi"):
        reconcile_niftybees_sources(common, tej_extra)



def test_tejhq_only_benchmark_bars_are_supplemented_only_on_official_sessions():
    from nse_benchmark import merge_niftybees_sources
    import pytest

    common_index = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])
    common = pd.DataFrame({
        "Open": [100.0, 101.0], "High": [102.0, 103.0],
        "Low": [99.0, 100.0], "Close": [101.0, 102.0], "Volume": [1000, 1100],
    }, index=common_index)
    tejhq_extra = pd.concat([
        common,
        pd.DataFrame(
            {"Open": [102.0], "High": [104.0], "Low": [101.0], "Close": [103.0], "Volume": [1200]},
            index=pd.DatetimeIndex(["2024-01-05"]),
        ),
    ])
    allowed_sessions = common_index.append(pd.DatetimeIndex(["2024-01-05"]))

    merged, audit = merge_niftybees_sources(
        common, tejhq_extra,
        allowed_extra_sessions=allowed_sessions,
        min_common_fraction=0.5,
    )
    assert audit["tejhq_only_dates"] == ["2024-01-05"]
    assert merged.index.tolist() == [
        pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-05"),
    ]
    assert merged.loc["2024-01-05", "Close"] == 103.0
    assert merged.attrs["supplemental_dates"] == ["2024-01-05"]

    with pytest.raises(RuntimeError, match="outside the official NSE session calendar"):
        merge_niftybees_sources(
            common, tejhq_extra,
            allowed_extra_sessions=common_index,
            min_common_fraction=0.5,
        )


def test_index_chunk_accepts_nse_flattened_list_and_legacy_envelope():
    from nse_benchmark import _request_index_chunk
    import pytest

    row = {
        "EOD_INDEX_NAME": "NIFTY 50", "EOD_TIMESTAMP": "03-NOV-2016",
        "EOD_OPEN_INDEX_VAL": 8500, "EOD_HIGH_INDEX_VAL": 8550,
        "EOD_LOW_INDEX_VAL": 8480, "EOD_CLOSE_INDEX_VAL": 8520,
    }

    class Response:
        status_code = 200
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            return None
        def json(self):
            return self.payload

    class Session:
        def __init__(self, payload):
            self.payload = payload
        def get(self, *args, **kwargs):
            return Response(self.payload)

    start = date(2016, 11, 3)
    assert _request_index_chunk(Session([row]), start, start, 10, 0) == [row]
    assert _request_index_chunk(
        Session({"data": {"indexCloseOnlineRecords": [row]}}),
        start, start, 10, 0,
    ) == [row]


def test_nse_request_chunks_are_inclusive_and_non_overlapping():
    chunks = date_chunks(date(2020, 1, 1), date(2020, 4, 10), max_days=100)
    assert chunks == [
        (date(2020, 1, 1), date(2020, 4, 9)),
        (date(2020, 4, 10), date(2020, 4, 10)),
    ]
    assert sum((end - start).days + 1 for start, end in chunks) == 101
