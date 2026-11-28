"""Offline provider revisions and EOD publication/locking regressions."""
from copy import deepcopy
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from scanner_tracker.demo import synthetic_frames
from scanner_tracker.market import BENCHMARK, YahooProvider, normalize_frame
from scanner_tracker.service import TrackerService
from scanner_tracker.storage import InputArchive
from scanner_tracker.worker import run_eod, worker_lock


@pytest.fixture
def service(tmp_path):
    instance = TrackerService("sqlite:///" + (tmp_path / "worker.db").as_posix(),
                              archive=InputArchive(local_directory=tmp_path / "inputs"))
    yield instance
    instance.engine.dispose()


@pytest.fixture
def exchange(monkeypatch):
    monkeypatch.setattr("scanner_tracker.worker.latest_completed_session", lambda: "2026-11-03")
    monkeypatch.setattr("scanner_tracker.worker.expected_sessions",
                        lambda start, end: pd.bdate_range(start, end))
    monkeypatch.setattr("scanner_tracker.worker.time.sleep", lambda seconds: None)


class SyntheticProvider:
    source = "SYNTHETIC OFFLINE FIXTURE"

    def __init__(self, frames, benchmark, *, stale_benchmark=False, failure=None):
        self.frames = {**frames, BENCHMARK: benchmark}
        self.calls = []
        self.stale_benchmark = stale_benchmark
        self.failure = failure

    def fetch(self, symbol, as_of, previous=None):
        self.calls.append((symbol, as_of))
        if symbol == self.failure:
            raise RuntimeError("Synthetic provider failure")
        result = self.frames[symbol].loc[:as_of].copy()
        return result.iloc[:-1] if symbol == BENCHMARK and self.stale_benchmark else result


def test_adjusted_close_revision_refreshes_entire_window_without_mixing_vintages(monkeypatch):
    frames, _ = synthetic_frames("2026-11-03")
    previous = frames["DEMOB.NS"].copy()
    original = previous.copy(deep=True)
    full_revision = previous.copy()
    full_revision["Adj Close"] *= .9
    incremental = full_revision.iloc[-12:].copy()
    download = Mock(side_effect=[incremental, full_revision])
    monkeypatch.setattr("yfinance.download", download)
    result = YahooProvider().fetch("DEMOB.NS", "2026-11-03", previous)
    assert download.call_count == 2
    assert download.call_args_list[1].kwargs["start"] == (pd.Timestamp("2026-11-03") - pd.Timedelta(days=900)).date().isoformat()
    assert download.call_args_list[1].kwargs["auto_adjust"] is False
    assert download.call_args_list[1].kwargs["actions"] is True
    pd.testing.assert_frame_equal(result, full_revision, check_freq=False)
    pd.testing.assert_frame_equal(previous, original)


def test_provider_clips_future_cached_and_downloaded_rows_before_historical_asof(monkeypatch):
    frames, _ = synthetic_frames("2026-11-06")
    previous = frames["DEMOB.NS"].copy()
    original = previous.copy(deep=True)
    cutoff = pd.Timestamp("2026-11-03")
    download = Mock(return_value=previous.loc["2026-10-23":].copy())
    monkeypatch.setattr("yfinance.download", download)
    result = YahooProvider().fetch("DEMOB.NS", "2026-11-03", previous)
    assert download.call_count == 1
    assert download.call_args.kwargs["start"] == (cutoff - pd.Timedelta(days=14)).date().isoformat()
    assert download.call_args.kwargs["end"] == "2026-11-04"
    assert result.index.max() == cutoff
    assert not (result.index > cutoff).any()
    pd.testing.assert_frame_equal(previous, original)


def test_provider_exhausted_retries_raise_instead_of_returning_empty_history(monkeypatch):
    download = Mock(return_value=pd.DataFrame())
    sleeps = []
    monkeypatch.setattr("yfinance.download", download)
    monkeypatch.setattr("scanner_tracker.market.time.sleep", sleeps.append)
    with pytest.raises(RuntimeError, match="after three attempts.*ValueError: No market history returned"):
        YahooProvider().fetch("DEMOB.NS", "2026-11-03")
    assert download.call_count == 3
    assert sleeps == [1, 2]


def test_normalize_frame_reports_bad_bar_details_and_tolerates_float_epsilon():
    frames, _ = synthetic_frames("2026-11-03")
    frame = frames["DEMOB.NS"].copy()
    as_of = frame.index[-1].date().isoformat()

    # Sub-nanoscale float rounding noise on High/Low bounds is tolerated.
    noisy = frame.copy()
    noisy.iloc[-1, noisy.columns.get_loc("High")] = max(
        noisy.iloc[-1]["Open"], noisy.iloc[-1]["Close"], noisy.iloc[-1]["Low"]
    ) - 1e-12
    normalized = normalize_frame(noisy, as_of)
    assert normalized.index[-1] == pd.Timestamp(as_of)

    # Genuine OHLC bound violation still fails with the exact offending date and reason.
    bad = frame.copy()
    bad.iloc[-1, bad.columns.get_loc("High")] = bad.iloc[-1]["Close"] - 1.0
    with pytest.raises(ValueError, match=f"inconsistent OHLC.*{as_of}"):
        normalize_frame(bad, as_of)

    # Duplicate session dates still fail with the offending date listed.
    duped = pd.concat([frame, frame.iloc[-1:]])
    with pytest.raises(ValueError, match=f"Duplicate source sessions:.*{as_of}"):
        normalize_frame(duped, as_of)


def test_yahoo_provider_recovers_latest_nan_close_from_valid_adj_close(monkeypatch):
    frames, _ = synthetic_frames("2026-11-03")
    expected = frames["DEMOB.NS"].copy()
    expected["Dividends"] = 0.0
    expected["Stock Splits"] = 0.0
    broken = expected.copy()
    broken.iloc[-1, broken.columns.get_loc("Close")] = np.nan
    download = Mock(return_value=broken)
    monkeypatch.setattr("yfinance.download", download)
    result = YahooProvider().fetch("DEMOB.NS", "2026-11-03")
    assert download.call_count == 1
    pd.testing.assert_frame_equal(result, expected, check_freq=False)


def test_yahoo_provider_rejects_adj_close_recovery_on_corporate_action(monkeypatch):
    frames, _ = synthetic_frames("2026-11-03")
    broken = frames["DEMOB.NS"].copy()
    broken["Dividends"] = 0.0
    broken["Stock Splits"] = 0.0
    broken.iloc[-1, broken.columns.get_loc("Close")] = np.nan
    broken.iloc[-1, broken.columns.get_loc("Dividends")] = 2.5
    download = Mock(return_value=broken)
    monkeypatch.setattr("yfinance.download", download)
    monkeypatch.setattr("scanner_tracker.market.time.sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="missing/non-finite.*Close=nan"):
        YahooProvider().fetch("DEMOB.NS", "2026-11-03")
    # Each of the 3 attempts tries the primary download plus the narrow repair fallback.
    assert download.call_count == 6


def test_yahoo_provider_recovers_latest_nan_close_via_narrow_repair_window(monkeypatch):
    frames, _ = synthetic_frames("2026-11-03")
    expected = frames["DEMOB.NS"].copy()
    broken = expected.copy()
    broken.iloc[-1, broken.columns.get_loc("Close")] = np.nan
    broken.iloc[-1, broken.columns.get_loc("Adj Close")] = np.nan

    repaired_window = expected.iloc[-6:].copy()
    repaired_window["Repaired?"] = False
    repaired_window.iloc[-1, repaired_window.columns.get_loc("Repaired?")] = True
    # Mutate an older row inside the repair response to confirm only the cutoff bar is spliced.
    repaired_window.iloc[0, repaired_window.columns.get_loc("Close")] *= 0.5

    download = Mock(side_effect=[broken, repaired_window])
    monkeypatch.setattr("yfinance.download", download)
    result = YahooProvider().fetch("DEMOB.NS", "2026-11-03")
    assert download.call_count == 2
    assert download.call_args_list[1].kwargs["repair"] is True
    assert download.call_args_list[1].kwargs["keepna"] is True
    assert download.call_args_list[1].kwargs["start"] == "2026-10-27"
    assert download.call_args_list[1].kwargs["end"] == "2026-11-04"
    assert "Repaired?" not in result.columns
    pd.testing.assert_frame_equal(result, expected, check_freq=False)


def test_yahoo_provider_does_not_recover_older_bar_nan_close(monkeypatch):
    frames, _ = synthetic_frames("2026-11-03")
    broken = frames["DEMOB.NS"].copy()
    broken.iloc[-2, broken.columns.get_loc("Close")] = np.nan
    download = Mock(return_value=broken)
    monkeypatch.setattr("yfinance.download", download)
    monkeypatch.setattr("scanner_tracker.market.time.sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="missing/non-finite.*Close=nan"):
        YahooProvider().fetch("DEMOB.NS", "2026-11-03")
    # Older-bar corruption never triggers repair fallback.
    assert download.call_count == 3


def test_equity_canary_aborts_early_on_market_wide_unsettled_close_nan(service, exchange, monkeypatch):
    frames, benchmark = synthetic_frames("2026-11-03")
    symbols = [f"EQ{i:02d}.NS" for i in range(8)]
    expanded_frames = {sym: frames["DEMOA.NS"].copy() for sym in symbols}
    monkeypatch.setattr("scanner_tracker.worker.leaders.load_universe", lambda: symbols)
    service.scan_frames(expanded_frames, benchmark, "2026-11-02", scopes={"wide": symbols}, mode="momentum", source="SYNTHETIC")
    published = deepcopy(service.momentum_report())
    snapshots = {sym: deepcopy(service.repo.prices(sym)) for sym in symbols + [BENCHMARK]}

    class UnsettledEquitiesProvider:
        source = "SYNTHETIC OFFLINE FIXTURE"

        def __init__(self):
            self.calls = []

        def fetch(self, symbol, as_of, previous=None):
            self.calls.append((symbol, as_of))
            if symbol == BENCHMARK:
                return benchmark.loc[:as_of].copy()
            raise RuntimeError(
                f"{symbol}: history unavailable after three attempts "
                f"(ValueError: Source history contains missing/non-finite OHLCV bars on {as_of} "
                f"(first bad: {as_of} Open=100.0, High=102.0, Low=99.0, Close=nan, Volume=1000.0).)."
            )

    provider = UnsettledEquitiesProvider()
    with pytest.raises(RuntimeError, match="unsettled Close=nan.*2026-11-03.*first 5 equities"):
        run_eod(service, as_of="2026-11-03", scope="wide", mode="momentum", provider=provider, sleep=0)
    # 1 benchmark fetch + 5 canary equities, not all 8.
    assert len(provider.calls) == 6
    assert provider.calls[0] == (BENCHMARK, "2026-11-03")
    assert service.momentum_report() == published
    assert service.status()["latest_success"]["as_of"] == "2026-11-02"
    assert service.repo.runs()[0]["status"] == "failed"
    for sym, payload in snapshots.items():
        assert service.repo.prices(sym) == payload


def test_stale_benchmark_fails_before_stock_fetch_and_preserves_prior_publication(service, exchange, monkeypatch):
    frames, benchmark = synthetic_frames("2026-11-03")
    symbols = list(frames)
    monkeypatch.setattr("scanner_tracker.worker.leaders.load_universe", lambda: symbols)
    service.scan_frames(frames, benchmark, "2026-11-02", scopes={"wide": symbols}, mode="momentum", source="SYNTHETIC")
    published = deepcopy(service.momentum_report())
    snapshots = {symbol: deepcopy(service.repo.prices(symbol)) for symbol in symbols + [BENCHMARK]}
    provider = SyntheticProvider(frames, benchmark, stale_benchmark=True)
    with pytest.raises(ValueError, match="exact required session"):
        run_eod(service, as_of="2026-11-03", scope="wide", mode="momentum", provider=provider, sleep=0)
    assert provider.calls == [(BENCHMARK, "2026-11-03")]
    assert service.momentum_report() == published
    assert service.status()["latest_success"]["as_of"] == "2026-11-02"
    assert service.repo.runs()[0]["status"] == "failed"
    for symbol, payload in snapshots.items():
        assert service.repo.prices(symbol) == payload


def test_explicit_historical_worker_session_never_uses_future_bars(service, exchange, monkeypatch):
    frames, benchmark = synthetic_frames("2026-11-03")
    monkeypatch.setattr("scanner_tracker.worker.leaders.load_universe", lambda: list(frames))
    provider = SyntheticProvider(frames, benchmark)
    result = run_eod(service, as_of="2026-11-02", scope="wide", mode="momentum", provider=provider, sleep=0)
    assert result["as_of"] == "2026-11-02"
    assert all(as_of == "2026-11-02" for _, as_of in provider.calls)
    for symbol in list(frames) + [BENCHMARK]:
        assert service.repo.prices(symbol)["bars"][-1]["date"] == "2026-11-02"


def test_future_or_nonexchange_session_is_rejected_without_fetch(service, exchange, monkeypatch):
    provider = Mock()
    with pytest.raises(ValueError, match="future or unsettled"):
        run_eod(service, as_of="2026-11-04", provider=provider)
    monkeypatch.setattr("scanner_tracker.worker.expected_sessions", lambda start, end: pd.DatetimeIndex([]))
    with pytest.raises(ValueError, match="approved exchange session"):
        run_eod(service, as_of="2026-11-02", provider=provider)
    provider.fetch.assert_not_called()
    assert service.repo.runs() == []


def test_worker_lock_prevents_overlap_and_releases_after_exception(service):
    with pytest.raises(ValueError, match="fixture"):
        with worker_lock(service.engine):
            with pytest.raises(RuntimeError, match="lock exists|overlapping"):
                with worker_lock(service.engine):
                    pytest.fail("A second worker acquired the same lock")
            raise ValueError("fixture")
    with worker_lock(service.engine):
        pass


def test_scheduled_retry_of_complete_scope_skips_fetch_and_publication(service, exchange, monkeypatch):
    frames, benchmark = synthetic_frames("2026-11-03")
    monkeypatch.setattr("scanner_tracker.worker.leaders.load_universe", lambda: list(frames))
    provider = SyntheticProvider(frames, benchmark)
    first = run_eod(service, scope="wide", mode="momentum", provider=provider, sleep=0)
    assert first["status"] == "complete"
    before_runs = deepcopy(service.repo.runs())
    before_report = deepcopy(service.momentum_report())
    provider.calls.clear()
    result = run_eod(service, scope="wide", mode="momentum", provider=provider, sleep=0)
    assert result["skipped_already_complete"] is True
    assert provider.calls == []
    assert service.repo.runs() == before_runs
    assert service.momentum_report() == before_report


def test_yahoo_provider_fetch_with_empty_payload_frame(monkeypatch):
    from scanner_tracker.market import payload_frame
    frames, _ = synthetic_frames("2026-11-03")
    data = frames["DEMOB.NS"].copy()
    empty = payload_frame({})
    mock_download = Mock(return_value=data)
    monkeypatch.setattr("yfinance.download", mock_download)
    result = YahooProvider().fetch("DEMOB.NS", "2026-11-03", previous=empty)
    assert not result.empty
    pd.testing.assert_frame_equal(result, data)
