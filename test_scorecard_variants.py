"""Deterministic unit tests for side-by-side paper-log momentum variants (Simple A vs Live B)."""
import json
import os
import sys
import tempfile

import numpy as np
import pandas as pd

import analyzer as A
import leaders as LD


def _make_world(start="2025-01-01", end="2026-04-15", bench_daily=0.001, tickers=None, bench_override=None):
    """Build deterministic business-day price frames with >200 warmup bars for benchmark 200-DMA."""
    idx = pd.bdate_range(start=start, end=end)
    n = len(idx)
    bench_close = 100.0 * (1.0 + bench_daily) ** np.arange(n)
    if bench_override is not None:
        bench_close = bench_override(idx, bench_close.copy())
    bench = pd.DataFrame({
        "Open": bench_close,
        "High": bench_close * 1.01,
        "Low": bench_close * 0.99,
        "Close": bench_close,
        "Volume": np.full(n, 1e6),
    }, index=idx)
    tickers = tickers or {"A": 0.004, "B": 0.002, "C": 0.0}
    frames = {}
    for name, daily in tickers.items():
        c = 100.0 * (1.0 + daily) ** np.arange(n)
        frames[name] = pd.DataFrame({
            "Open": c,
            "High": c * 1.01,
            "Low": c * 0.99,
            "Close": c,
            "Volume": np.full(n, 1e6),
        }, index=idx)
    return frames, bench, idx


def _make_snap(as_of, ranked_tickers, liquid_tickers=None, legacy_top20_only=False):
    ranked = [
        {"ticker": t, "rank": i + 1, "rs12_1": float(100 - i), "close": 100.0}
        for i, t in enumerate(ranked_tickers)
    ]
    leaders = [dict(x, fired=[]) for x in ranked[:20]]
    liquid = [{"ticker": t, "close": 100.0} for t in (liquid_tickers or ranked_tickers)]
    snap = {
        "as_of": as_of,
        "benchmark": "NIFTYBEES.NS",
        "counts": {},
        "leaders": leaders,
        "liquid": liquid,
    }
    if not legacy_top20_only:
        snap["ranked"] = ranked[:40]
    return snap


def test_entry_on_first_session_after_signal_and_open_period_marked_to_latest_close():
    frames, bench, idx = _make_world(start="2025-01-01", end="2026-03-10")
    snaps = [
        _make_snap(d.date().isoformat(), ["A", "B"], ["A", "B", "C"])
        for d in idx if d >= pd.Timestamp("2026-01-01")
    ]
    sc = LD.build_scorecard(snaps, frames, bench, cost_pct=0.30, n_hold=2)
    simple = sc["variants"]["simple"]
    live = sc["variants"]["live"]

    assert [m["signal_date"] for m in simple["monthly"]] == ["2026-01-30", "2026-02-27"]
    assert simple["monthly"][0]["entry_date"] == "2026-02-02"
    assert simple["monthly"][0]["exit_date"] == "2026-03-02"
    assert simple["monthly"][0]["status"] == "closed"
    assert simple["monthly"][1]["status"] == "open"
    assert simple["monthly"][1]["exit_date"] == "2026-03-10"

    assert [m["signal_date"] for m in live["monthly"]] == ["2026-01-28", "2026-02-27"]
    assert live["monthly"][0]["entry_date"] == "2026-01-29"
    assert live["monthly"][0]["exit_date"] == "2026-03-02"
    assert live["monthly"][0]["status"] == "closed"
    assert live["monthly"][1]["status"] == "open"
    assert live["monthly"][1]["exit_date"] == "2026-03-10"

    assert len(sc["comparison"]) == 2
    assert sc["comparison"][0]["month"] == "2026-01"
    assert sc["comparison"][0]["simple_signal_date"] == "2026-01-30"
    assert sc["comparison"][0]["live_signal_date"] == "2026-01-28"
    assert sc["comparison"][0]["regime"] == "BULL"
    assert sc["comparison"][0]["raw_top20_net"] is not None
    assert sc["comparison"][0]["same_universe_equal_weight"] is not None
    assert sc["comparison"][0]["nifty50"] is not None
    json.dumps(LD.sanitize_json(sc), allow_nan=False)


def test_top30_buffer_keeps_rank_25_and_drops_rank_35_and_fills_only_from_top_20():
    all_tickers = [f"S{i:02d}" for i in range(1, 41)]
    tickers_growth = {t: 0.001 + (40 - i) * 0.00005 for i, t in enumerate(all_tickers)}
    frames, bench, idx = _make_world(start="2025-01-01", end="2026-03-10", tickers=tickers_growth)

    jan_order = list(all_tickers)
    feb_order = (
        [f"S{i:02d}" for i in range(1, 19)]
        + ["S21", "S22"]
        + ["S23", "S24", "S25", "S26"]
        + ["S19"]
        + [f"S{i:02d}" for i in range(27, 36)]
        + ["S20"]
        + [f"S{i:02d}" for i in range(36, 41)]
    )
    assert len(feb_order) == 40
    assert feb_order.index("S19") + 1 == 25
    assert feb_order.index("S20") + 1 == 35
    assert feb_order.index("S23") + 1 == 21

    snaps = [
        _make_snap("2026-01-30", jan_order, all_tickers),
        _make_snap("2026-02-27", feb_order, all_tickers),
    ]
    sc = LD.build_scorecard(snaps, frames, bench, cost_pct=0.30, n_hold=20, retain_rank=30)

    simple_feb = sc["variants"]["simple"]["monthly"][1]
    live_feb = sc["variants"]["live"]["monthly"][1]

    assert "S19" not in simple_feb["holding_tickers"]
    assert "S20" not in simple_feb["holding_tickers"]
    assert "S21" in simple_feb["holding_tickers"] and "S22" in simple_feb["holding_tickers"]
    assert len(simple_feb["holding_tickers"]) == 20

    assert "S19" in live_feb["holding_tickers"]
    assert "S20" not in live_feb["holding_tickers"]
    assert "S21" in live_feb["holding_tickers"]
    assert "S22" not in live_feb["holding_tickers"]
    assert "S23" not in live_feb["holding_tickers"]
    assert len(live_feb["holding_tickers"]) == 20
    assert live_feb["turnover_l1"] < simple_feb["turnover_l1"]


def test_legacy_top20_only_snapshots_behave_as_no_buffer():
    all_tickers = [f"S{i:02d}" for i in range(1, 41)]
    tickers_growth = {t: 0.001 for t in all_tickers}
    frames, bench, _ = _make_world(start="2025-01-01", end="2026-03-10", tickers=tickers_growth)
    jan_order = list(all_tickers)
    feb_order = (
        [f"S{i:02d}" for i in range(1, 19)]
        + ["S21", "S22", "S23", "S24", "S25", "S26", "S19"]
        + [f"S{i:02d}" for i in range(27, 36)]
        + ["S20"]
        + [f"S{i:02d}" for i in range(36, 41)]
    )
    snaps = [
        _make_snap("2026-01-30", jan_order, all_tickers, legacy_top20_only=True),
        _make_snap("2026-02-27", feb_order, all_tickers, legacy_top20_only=True),
    ]
    sc = LD.build_scorecard(snaps, frames, bench, cost_pct=0.30, n_hold=20, retain_rank=30)
    assert set(sc["variants"]["live"]["monthly"][1]["holding_tickers"]) == set(
        sc["variants"]["simple"]["monthly"][1]["holding_tickers"]
    )


def test_february_catchup_when_28th_is_weekend():
    frames, bench, idx = _make_world(start="2025-01-01", end="2026-04-05")
    snaps = [
        _make_snap(d.date().isoformat(), ["A", "B"], ["A", "B", "C"])
        for d in idx if d >= pd.Timestamp("2026-01-20")
    ]
    sc = LD.build_scorecard(snaps, frames, bench, cost_pct=0.30, n_hold=2)
    live_dates = [m["signal_date"] for m in sc["variants"]["live"]["monthly"]]
    assert live_dates == ["2026-01-28", "2026-02-27", "2026-03-30"], live_dates
    feb_row = sc["variants"]["live"]["monthly"][1]
    assert feb_row["entry_date"] == "2026-03-02"
    assert feb_row["exit_date"] == "2026-03-31"


def test_bear_regime_moves_simple_and_live_to_cash_with_exit_cost():
    def bear_in_feb_and_mar(idx, close):
        close[idx >= pd.Timestamp("2026-02-10")] *= 0.60
        return close

    frames, bench, _ = _make_world(
        start="2025-01-01", end="2026-04-10",
        tickers={"A": 0.005, "B": 0.003, "C": -0.002},
        bench_override=bear_in_feb_and_mar,
    )
    snaps = [
        _make_snap("2026-01-30", ["A", "B"], ["A", "B", "C"]),
        _make_snap("2026-02-27", ["A", "B"], ["A", "B", "C"]),
        _make_snap("2026-03-31", ["A", "B"], ["A", "B", "C"]),
    ]
    sc = LD.build_scorecard(snaps, frames, bench, cost_pct=0.30, n_hold=2)

    for name in ("simple", "live"):
        rows = sc["variants"][name]["monthly"]
        assert rows[0]["regime"] == "BULL" and rows[0]["in_cash"] is False and rows[0]["holdings"] == 2
        assert rows[1]["regime"] == "BEAR" and rows[1]["in_cash"] is True and rows[1]["holdings"] == 0
        assert rows[1]["gross"] == 0.0
        assert abs(rows[1]["turnover_l1"] - 1.0) < 1e-9
        assert abs(rows[1]["net"] - (-0.0015)) < 1e-9
        assert rows[2]["regime"] == "BEAR" and rows[2]["in_cash"] is True and rows[2]["holdings"] == 0
        assert rows[2]["turnover_l1"] == 0.0
        assert rows[2]["net"] == 0.0

    raw_rows = sc["monthly"]
    assert raw_rows[1]["holdings"] == 2 and raw_rows[1]["top20_gross"] > 0


def test_snapshot_record_persists_top40_eligible_ranked_stocks():
    eligible = [
        {"ticker": f"T{i:02d}.NS", "leader_rank": i, "relative_strength_12_1_pct": 100.0 - i, "last_close": 100.0 + i}
        for i in range(1, 51)
    ]
    payload = {
        "as_of": "2026-11-18",
        "benchmark": "NIFTYBEES.NS",
        "counts": {"load_coverage_pct": 99.0, "partial_scan_time_limit": False},
        "leaders": [dict(x, plan={"fired": []}) for x in eligible[:20]],
        "eligible_ranked": eligible,
        "liquid_universe": [{"ticker": x["ticker"], "close": x["last_close"]} for x in eligible],
    }
    rec = LD.snapshot_record(payload)
    assert len(rec["leaders"]) == 20
    assert len(rec["ranked"]) == 40
    assert rec["ranked"][0] == {"ticker": "T01.NS", "rank": 1, "rs12_1": 99.0, "close": 101.0}
    assert rec["ranked"][-1]["rank"] == 40

    d = tempfile.mkdtemp()
    path, reason = LD.save_snapshot(payload, d)
    assert reason == "saved" and path is not None
    saved = json.loads(open(path).read(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    assert len(saved["ranked"]) == 40


def test_run_leaders_populates_top40_ranked_while_keeping_top20_board():
    idx = pd.bdate_range(end="2026-10-30", periods=400)
    frames = {}
    for i in range(45):
        daily = 0.0005 + i * 0.00005
        c = 100.0 * (1.0 + daily) ** np.arange(400)
        frames[f"S{i:02d}.NS"] = pd.DataFrame(
            {"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx
        )
    bc = 100.0 * (1.0003) ** np.arange(400)
    bench = pd.DataFrame({"Open": bc, "High": bc * 1.01, "Low": bc * 0.99, "Close": bc, "Volume": 1e6}, index=idx)

    real_fetch = A.fetch_ticker
    A.fetch_ticker = lambda t: frames[t]
    try:
        out = LD.run_leaders(list(frames), benchmark_df=bench, liquid_top=45, board=20, sleep=0)
    finally:
        A.fetch_ticker = real_fetch
    assert len(out["leaders"]) == 20
    assert len(out["eligible_ranked"]) == 40
    assert [x["leader_rank"] for x in out["eligible_ranked"]] == list(range(1, 41))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
