"""Frozen-date ranking and replay comparisons, using synthetic prices only."""
from copy import deepcopy
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from scanner_tracker.__main__ import main
from scanner_tracker.demo import synthetic_frames
from scanner_tracker.market import BENCHMARK, frame_payload
from scanner_tracker.research import METHODS, compare_momentum_rankings
from scanner_tracker.service import TrackerService
from scanner_tracker.storage import InputArchive


def price_frame(close, dates, volume=100000):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({"Open": close * .999, "High": close * 1.01, "Low": close * .99,
                         "Close": close, "Adj Close": close, "Volume": volume}, index=dates)


def test_rankings_are_unchanged_by_future_prices_volume_and_benchmark_rows():
    frames, benchmark = synthetic_frames("2026-11-03")
    as_of = "2026-10-30"
    original = deepcopy(frames)
    before = compare_momentum_rankings({key: value.loc[:as_of] for key, value in frames.items()}, benchmark.loc[:as_of], as_of)
    altered = deepcopy(frames)
    for frame in altered.values():
        frame.loc[frame.index > as_of, ["Open", "High", "Low", "Close", "Adj Close"]] *= 500
        frame.loc[frame.index > as_of, "Volume"] *= 100000
    future_benchmark = benchmark.copy()
    future_benchmark.loc[future_benchmark.index > as_of, "Close"] *= .001
    after = compare_momentum_rankings(altered, future_benchmark, as_of)
    assert after == before
    for symbol in frames:
        pd.testing.assert_frame_equal(frames[symbol], original[symbol])


def test_liquidity_pool_precedes_trend_filter_across_more_than_200_members():
    dates = pd.bdate_range(end="2026-11-03", periods=270)
    x = np.arange(len(dates))
    frames = {f"LIQUID{i:03d}.NS": price_frame(150 - x * .1, dates, volume=1000000)
              for i in range(200)}
    frames["LOWLIQUID.NS"] = price_frame(50 + x * .2 + np.sin(x / 7) * .1, dates, volume=100)
    benchmark = price_frame(100 + x * .1, dates)
    report = compare_momentum_rankings(frames, benchmark, "2026-11-03")
    assert all(report["rankings"][method] == [] for method in METHODS)
    assert not any(row["symbol"] == "LOWLIQUID.NS" for row in report["factors"])


@pytest.mark.parametrize("invalid", [np.nan, np.inf])
def test_missing_or_nonfinite_formation_prices_have_explicit_exclusion(invalid):
    frames, benchmark = synthetic_frames("2026-11-03")
    bad = frames["DEMOB.NS"].copy()
    bad.loc[bad.index[-40], "Adj Close"] = invalid
    report = compare_momentum_rankings({"BAD.NS": bad}, benchmark, "2026-11-03")
    assert all(not report["rankings"][method] for method in METHODS)
    assert "BAD.NS" in report["excluded"]
    assert report["excluded"]["BAD.NS"]


def test_zero_volatility_has_no_division_score_and_an_explicit_disposition():
    dates = pd.bdate_range(end="2026-11-03", periods=270)
    frame = price_frame(np.full(len(dates), 100.0), dates)
    benchmark = price_frame(100 + np.arange(len(dates)) * .1, dates)
    report = compare_momentum_rankings({"FLAT.NS": frame}, benchmark, "2026-11-03")
    assert not report["rankings"]["volatility_adjusted"]
    assert "FLAT.NS" in report["excluded"]
    assert report["excluded"]["FLAT.NS"]


def test_cli_replay_preserves_actual_accounts_and_uses_same_execution_defaults(tmp_path, monkeypatch, capsys):
    import scanner_tracker.momentum as momentum

    service = TrackerService("sqlite:///" + (tmp_path / "replay.db").as_posix(),
                              archive=InputArchive(local_directory=tmp_path / "inputs"))
    try:
        for mode, amount in (("TA", 10000), ("MOMENTUM", 20000)):
            service.configure_ledger(mode, amount, as_of="2026-11-01")
        service.record_fill("TA", {"execution_id": "actual-ta", "symbol": "DEMOB.NS", "side": "BUY",
                                    "quantity": 1, "price_inr": 100, "fees_inr": 1, "executed_at": "2026-11-02"})
        frames, benchmark = synthetic_frames("2026-11-03")
        for symbol, frame in {**frames, BENCHMARK: benchmark}.items():
            service.repo.save_document("latest_prices", symbol, frame_payload(frame, "SYNTHETIC OFFLINE"))
        actual_before = {mode: deepcopy(service.ledger(mode)) for mode in ("TA", "MOMENTUM")}
        monkeypatch.setattr(TrackerService, "from_env", classmethod(lambda cls: service))
        replay_call = Mock(wraps=momentum.run_momentum)
        monkeypatch.setattr(momentum, "run_momentum", replay_call)
        assert main(["replay", "--from", "2026-11-02", "--to", "2026-11-03", "--capital", "50000"]) == 0
        assert "actual_ledgers_changed" in capsys.readouterr().out
        assert replay_call.call_count == 2 * len(METHODS)
        for call in replay_call.call_args_list:
            assert call.kwargs["model_capital"] == 50000
            assert call.kwargs["universe_size"] == len(frames)
            assert call.kwargs.get("actual_ledger") is None
            assert call.kwargs.get("force", False) is False
        assert {call.kwargs["ranking_method"] for call in replay_call.call_args_list} == set(METHODS)
        for mode in actual_before:
            assert service.ledger(mode) == actual_before[mode]
        report = service.repo.document("research", "replay:2026-11-02:2026-11-03")
        assert set(report["results"]) == set(METHODS)
        for method in METHODS:
            history = report["results"][method]
            assert [row["as_of"] for row in history] == ["2026-11-02", "2026-11-03"]
            assert history[-1]["model"]["ledger"]["kind"] == "model"
    finally:
        service.engine.dispose()
