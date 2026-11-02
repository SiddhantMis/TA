from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from portfolio_rules import (
    build_comparison_sessions,
    build_daily_coverage_audit,
    build_missing_history_audit,
    build_session_calendar_audit,
    prepare,
    simulate,
)


class PortfolioMissingBarTests(unittest.TestCase):
    def setUp(self):
        self.idx = pd.bdate_range("2017-11-08", periods=270)
        close = np.linspace(100.0, 160.0, len(self.idx))
        open_ = close * 0.999
        self.missing_pos = 254
        open_[self.missing_pos] = np.nan
        close[self.missing_pos] = np.nan
        self.frame = pd.DataFrame({
            "Open": open_,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(len(close), 10000.0),
            "Turnover": np.nan_to_num(close, nan=0.0) * 10000.0,
        }, index=self.idx).drop(index=self.idx[self.missing_pos])
        self.bench = pd.DataFrame({"Close": np.linspace(100.0, 130.0, len(self.idx))}, index=self.idx)
        self.membership = pd.DataFrame([{
            "symbol": "AAA",
            "valid_from": self.idx[0],
            "valid_to": pd.NaT,
            "source": "test",
            "source_url": "fixture",
            "notes": "",
        }])

    def test_missing_open_is_not_forward_filled(self):
        prepared = prepare(
            {"AAA.NS": self.frame}, self.bench,
            membership_df=self.membership,
        )
        self.assertTrue(np.isnan(prepared["O"][self.missing_pos, 0]))
        self.assertTrue(np.isnan(prepared["C_raw"][self.missing_pos, 0]))
        self.assertFalse(prepared["univ"][self.missing_pos, 0])
        self.assertAlmostEqual(
            prepared["C"][self.missing_pos, 0],
            self.frame["Close"].loc[self.idx[self.missing_pos - 1]],
        )

    def test_simulator_does_not_execute_at_a_synthetic_open(self):
        prepared = prepare(
            {"AAA.NS": self.frame}, self.bench,
            membership_df=self.membership,
        )
        result = simulate(prepared, signals={self.missing_pos - 1}, start=253)
        self.assertAlmostEqual(result["equity"][self.missing_pos], 1.0)
        self.assertAlmostEqual(result["equity"][self.missing_pos + 1], 1.0)

    def test_official_session_with_no_stock_bar_is_retained_in_coverage_audit(self):
        prepared = prepare(
            {"AAA.NS": self.frame}, self.bench,
            membership_df=self.membership,
        )
        daily = build_daily_coverage_audit(prepared, {"AAA.NS": self.frame}, start_pos=253)
        row = daily.loc[daily["date"].eq(self.idx[self.missing_pos].strftime("%Y-%m-%d"))]
        self.assertEqual(len(row), 1)
        self.assertEqual(int(row.iloc[0]["all_loaded_symbol_bars"]), 0)
        self.assertEqual(int(row.iloc[0]["active_member_bars"]), 0)

    def test_benchmark_regime_carries_only_last_observed_state_not_a_synthetic_sma_bar(self):
        idx = pd.bdate_range("2017-01-02", periods=270)
        close = np.linspace(100.0, 160.0, len(idx))
        bench = pd.DataFrame({"Close": close}, index=idx)
        missing_pos = 255
        bench.iloc[missing_pos, bench.columns.get_loc("Close")] = np.nan
        stock_close = np.linspace(100.0, 150.0, len(idx))
        stock = pd.DataFrame({
            "Open": stock_close, "High": stock_close * 1.01,
            "Low": stock_close * 0.99, "Close": stock_close,
            "Volume": 10000.0, "Turnover": stock_close * 10000.0,
        }, index=idx)
        membership = pd.DataFrame([{
            "symbol": "AAA", "valid_from": idx[0], "valid_to": pd.NaT,
            "source": "test", "source_url": "fixture", "notes": "",
        }])
        prepared = prepare(
            {"AAA.NS": stock}, bench, index_df=pd.DataFrame({"Close": close}, index=idx),
            membership_df=membership,
        )
        self.assertTrue(prepared["bench_stale"][missing_pos])
        self.assertFalse(prepared["bench_stale"][missing_pos + 1])
        self.assertAlmostEqual(prepared["bench_close"][missing_pos], close[missing_pos - 1])
        self.assertEqual(prepared["bull"][missing_pos], prepared["bull"][missing_pos - 1])
        self.assertTrue(prepared["bull_known"][missing_pos])


    def test_insufficient_history_is_reported_even_when_some_bars_are_loaded(self):
        audit = build_missing_history_audit(
            self.membership,
            {"AAA.NS": self.frame},
            {"AAA.NS": {"status": "insufficient_history", "bars": 200, "detail": "only 200 bars"}},
            self.idx[253],
            self.idx[-1],
        )
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit.iloc[0]["load_status"], "insufficient_history")
        self.assertEqual(int(audit.iloc[0]["history_bars"]), 200)

    def test_missing_close_does_not_trigger_a_stop_and_pending_stop_waits_for_real_open(self):
        n = 260
        idx = pd.bdate_range("2020-01-01", periods=n)
        opens = np.full((n, 1), 100.0)
        raw_close = np.full((n, 1), 100.0)
        mark_close = np.full((n, 1), 100.0)
        raw_close[255, 0] = 90.0
        mark_close[255, 0] = 90.0
        opens[256, 0] = np.nan
        raw_close[256, 0] = np.nan
        mark_close[256, 0] = 90.0
        opens[257, 0] = 80.0
        raw_close[257, 0] = 80.0
        mark_close[257, 0] = 80.0
        prepared = {
            "idx": idx,
            "O": opens,
            "C": mark_close,
            "C_raw": raw_close,
            "rank": np.ones((n, 1), dtype=float),
            "bull": np.ones(n, dtype=bool),
            "bull_known": np.ones(n, dtype=bool),
            "cols": ["AAA.NS"],
        }
        result = simulate(
            prepared, signals={252}, start=253, size=1, retain=1,
            trail=0.05, cost_pct=0.0, regime="off",
        )
        self.assertEqual(result["stops"], 1)
        self.assertGreaterEqual(result["max_stale_sessions"], 1)
        self.assertAlmostEqual(result["equity"][256], result["equity"][255])
        self.assertLess(result["equity"][257], result["equity"][256])


    def test_cross_check_does_not_forward_fill_missing_benchmark_prices(self):
        from portfolio_rules import cross_check_benchmark

        idx = pd.bdate_range("2024-01-01", periods=3)
        etf = pd.DataFrame({"Close": [100.0, np.nan, 102.0]}, index=idx)
        index = pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=idx)
        with self.assertRaisesRegex(RuntimeError, "cross-check failed"):
            cross_check_benchmark(etf, index)


    def test_session_calendar_audit_uses_official_index_sessions_and_flags_gaps(self):
        nse_sessions = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])
        benchmark_sessions = pd.DatetimeIndex(["2024-01-02"])
        index_sessions = nse_sessions
        stock = pd.DataFrame(
            {"Close": [100.0, 102.0]},
            index=pd.DatetimeIndex(["2024-01-02", "2024-01-04"]),
        )
        audit = build_session_calendar_audit(
            nse_sessions, benchmark_sessions, index_sessions, {"AAA.NS": stock}
        ).set_index("date")
        self.assertEqual(int(audit.loc["2024-01-03", "stock_symbol_bars"]), 0)
        self.assertTrue(bool(audit.loc["2024-01-03", "zero_stock_bar_session"]))
        self.assertTrue(bool(audit.loc["2024-01-03", "missing_benchmark_bar"]))
        self.assertTrue(bool(audit.loc["2024-01-04", "extra_stock_session"]))
        self.assertIn("nse_nifty50_session", audit.columns)

    def test_zero_stock_bar_sessions_are_excluded_from_all_comparison_series(self):
        sessions = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"])
        stock = pd.DataFrame({"Close": [100.0, 102.0]}, index=sessions[[0, 2]])
        audit = build_session_calendar_audit(sessions, sessions, sessions, {"AAA.NS": stock})
        comparison, excluded = build_comparison_sessions(sessions, audit)
        self.assertEqual(comparison.strftime("%Y-%m-%d").tolist(), ["2024-01-02", "2024-01-04"])
        self.assertEqual(excluded.strftime("%Y-%m-%d").tolist(), ["2024-01-03"])


if __name__ == "__main__":
    unittest.main()
