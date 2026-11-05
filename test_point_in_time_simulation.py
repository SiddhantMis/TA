import unittest

import numpy as np
import pandas as pd

from point_in_time_simulation import choose_sample_positions, max_feasible_samples, score_snapshot, simulate_sample


class PointInTimeSimulationTests(unittest.TestCase):
    def setUp(self):
        self.sessions = pd.bdate_range("2024-01-01", periods=253)
        self.as_of = self.sessions[-1]
        benchmark_close = np.linspace(100, 130, len(self.sessions))
        self.benchmark = pd.DataFrame({"Close": benchmark_close}, index=self.sessions)
        self.frames = {}
        for symbol, end_value in (("AAA", 220.0), ("BBB", 165.0)):
            close = np.linspace(100, end_value, len(self.sessions))
            self.frames[f"{symbol}.NS"] = pd.DataFrame({
                "Open": close * 0.999,
                "High": close * 1.01,
                "Low": close * 0.99,
                "Close": close,
                "RawClose": close,
                "Volume": np.full(len(close), 100_000.0),
            }, index=self.sessions)
        self.actions = pd.DataFrame(columns=["symbol", "ex_date", "type"])

    def test_future_corporate_action_does_not_change_historical_rank(self):
        future_actions = pd.DataFrame([{
            "symbol": "AAA", "ex_date": self.as_of + pd.Timedelta(days=10), "type": "demerger"
        }])
        result = score_snapshot(
            self.as_of, ["AAA", "BBB"], self.frames, self.benchmark, future_actions
        )
        self.assertEqual(result["ranked"][0]["ticker"], "AAA.NS")
        self.assertIsNone(result["ranked"][0]["unsupported_action_reset_date"])

    def test_known_unsupported_action_resets_lookback(self):
        known_actions = pd.DataFrame([{
            "symbol": "AAA", "ex_date": self.as_of - pd.Timedelta(days=30), "type": "rights"
        }])
        result = score_snapshot(
            self.as_of, ["AAA", "BBB"], self.frames, self.benchmark, known_actions
        )
        self.assertNotIn("AAA.NS", [row["ticker"] for row in result["ranked"]])
        self.assertTrue(any(
            item["symbol"] == "AAA" and item["reason"] == "not_253_consecutive_observed_sessions"
            for item in result["excluded"]
        ))

    def test_missing_session_is_not_forward_filled(self):
        broken = {key: value.copy() for key, value in self.frames.items()}
        broken["AAA.NS"].loc[self.sessions[-100], "Close"] = np.nan
        result = score_snapshot(
            self.as_of, ["AAA", "BBB"], broken, self.benchmark, self.actions
        )
        self.assertNotIn("AAA.NS", [row["ticker"] for row in result["ranked"]])
        self.assertTrue(any(
            item["symbol"] == "AAA" and item["reason"] == "not_253_consecutive_observed_sessions"
            for item in result["excluded"]
        ))

    def test_future_unsupported_action_invalidates_affected_horizon_only(self):
        sessions = pd.bdate_range("2023-01-02", periods=400)
        signal_pos = 260
        signal_date = sessions[signal_pos]
        frames = {}
        picks = []
        for i in range(20):
            symbol = f"S{i:02d}"
            ticker = f"{symbol}.NS"
            picks.append({"symbol": symbol, "ticker": ticker, "leader_rank": i + 1})
            frames[ticker] = pd.DataFrame({
                "Open": np.full(len(sessions), 100.0),
                "Close": np.full(len(sessions), 110.0),
            }, index=sessions)
        tri = pd.DataFrame({"Close": np.linspace(100, 120, len(sessions))}, index=sessions)
        actions = pd.DataFrame([{
            "symbol": "S00", "ex_date": sessions[signal_pos + 40], "type": "demerger"
        }])
        snapshot = {"signal_date": signal_date, "market_regime": "BULL", "ranked": picks}
        stocks, returns = simulate_sample(snapshot, sessions, frames, tri, "S1", actions)
        first = next(row for row in stocks if row["ticker"] == "S00.NS")
        self.assertEqual(first["1M_return_status"], "ok")
        self.assertEqual(first["3M_return_status"], "unsupported_corporate_action_during_hold")
        self.assertTrue(returns[0]["complete_stock_prices"])
        self.assertFalse(returns[1]["complete_stock_prices"])

    def test_random_samples_are_reproducible_and_six_month_windows_do_not_overlap(self):
        eligible = np.arange(300, 1800)
        first = choose_sample_positions(eligible, sample_count=5, seed=42)
        second = choose_sample_positions(eligible, sample_count=5, seed=42)
        self.assertEqual(first.tolist(), second.tolist())
        self.assertEqual(len(first), 5)
        self.assertTrue(all((right - left) >= 127 for left, right in zip(first, first[1:])))


    # ------------------------------------------------------------------ audit regressions ---
    def _flat_world(self, n_picks=20, regime="BULL", break_exit_for=None):
        sessions = pd.bdate_range("2023-01-02", periods=400)
        signal_pos = 260
        frames, picks = {}, []
        for i in range(n_picks):
            ticker = f"S{i:02d}.NS"
            picks.append({"symbol": f"S{i:02d}", "ticker": ticker, "leader_rank": i + 1})
            close = np.full(len(sessions), 110.0)
            if ticker == break_exit_for:
                close[signal_pos + 21] = np.nan
            frames[ticker] = pd.DataFrame({"Open": np.full(len(sessions), 100.0), "Close": close}, index=sessions)
        snapshot = {"signal_date": sessions[signal_pos], "market_regime": regime, "ranked": picks}
        return sessions, signal_pos, frames, snapshot

    def test_liquidity_first_ranks_liquidity_before_the_trend_filter(self):
        frames = {}
        for symbol, start, end, volume in (("AAA", 200.0, 100.0, 1_000_000.0), ("BBB", 200.0, 100.0, 1_000_000.0),
                                           ("CCC", 100.0, 200.0, 100_000.0), ("DDD", 100.0, 190.0, 100_000.0)):
            close = np.linspace(start, end, len(self.sessions))
            frames[f"{symbol}.NS"] = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close,
                                                  "RawClose": close, "Volume": np.full(len(close), volume)}, index=self.sessions)
        names = ["AAA", "BBB", "CCC", "DDD"]
        liq_first = score_snapshot(self.as_of, names, frames, self.benchmark, self.actions, "liquidity_first", liquid_top=2)
        trend_first = score_snapshot(self.as_of, names, frames, self.benchmark, self.actions, "trend_first", liquid_top=2)
        # AAA and BBB are the two most liquid but below their 200-DMA: the live/engine order leaves NOTHING to rank ...
        self.assertEqual(liq_first["ranked_count"], 0)
        self.assertEqual(liq_first["pool_size"], 4)
        # ... while the original five-date order filtered by trend first and then admitted the less-liquid survivors.
        self.assertEqual({r["ticker"] for r in trend_first["ranked"]}, {"CCC.NS", "DDD.NS"})
        three = score_snapshot(self.as_of, names, frames, self.benchmark, self.actions, "liquidity_first", liquid_top=3)
        self.assertEqual([r["ticker"] for r in three["ranked"]], ["CCC.NS"])      # third most liquid (tie broken by symbol), above its 200-DMA

    def test_benchmark_is_aligned_to_the_entry_open_not_the_signal_close(self):
        sessions, pos, frames, snapshot = self._flat_world()
        tri_close = np.full(len(sessions), 100.0)
        tri_close[pos + 21] = 110.0
        tri = pd.DataFrame({"Close": tri_close}, index=sessions)
        bees_open, bees_close = np.full(len(sessions), 50.0), np.full(len(sessions), 50.0)
        bees_open[pos + 1], bees_close[pos + 21] = 51.0, 53.55               # +2% overnight gap, then +5% entry open -> exit close
        bees = pd.DataFrame({"Open": bees_open, "Close": bees_close}, index=sessions)
        _, returns = simulate_sample(snapshot, sessions, frames, tri, "S1", self.actions, bees)
        one = returns[0]
        cost = (1 - 0.003 / 2) / (1 + 0.003 / 2)
        self.assertAlmostEqual(one["nifty500_tri_return_pct"], 10.0)                              # includes the overnight gap
        self.assertAlmostEqual(one["niftybees_overnight_pct"], 2.0)                                # the gap used for the alignment is reported
        self.assertAlmostEqual(one["nifty500_tri_entry_aligned_return_pct"], (110 / (100 * 51 / 50) - 1) * 100)
        self.assertAlmostEqual(one["niftybees_entry_to_exit_net_return_pct"], ((53.55 / 51) * cost - 1) * 100)
        stock_net = (1.10 * cost - 1) * 100                                                      # 9.67%: beats 7.84% (aligned) but not 10.0% (unaligned)
        self.assertAlmostEqual(one["raw_top20_equal_weight_net_return_pct"], stock_net)
        self.assertTrue(one["raw_outperformed_tri"])

    def test_bear_regime_is_cash_even_when_the_stock_basket_is_incomplete(self):
        sessions, pos, frames, snapshot = self._flat_world(regime="BEAR", break_exit_for="S03.NS")
        tri = pd.DataFrame({"Close": np.linspace(100, 120, len(sessions))}, index=sessions)
        _, returns = simulate_sample(snapshot, sessions, frames, tri, "S1", self.actions)
        one = returns[0]
        self.assertFalse(one["complete_stock_prices"])
        self.assertIsNone(one["raw_top20_equal_weight_net_return_pct"])
        self.assertEqual(one["market_filter_portfolio_net_return_pct"], 0.0)                     # cash is certain; not "unknown"
        self.assertEqual(one["available_stocks"], 19)
        self.assertEqual(one["excluded_missing_price"], 1)

    def test_fewer_than_twenty_qualifiers_leave_cash_slots_instead_of_reweighting(self):
        sessions, pos, frames, snapshot = self._flat_world(n_picks=5)
        tri = pd.DataFrame({"Close": np.linspace(100, 120, len(sessions))}, index=sessions)
        _, returns = simulate_sample(snapshot, sessions, frames, tri, "S1", self.actions)
        cost = (1 - 0.003 / 2) / (1 + 0.003 / 2)
        one = returns[0]
        self.assertEqual(one["slots_filled"], 5)
        self.assertTrue(one["complete_stock_prices"])
        self.assertAlmostEqual(one["raw_top20_equal_weight_net_return_pct"], 5 * (1.10 * cost - 1) * 100 / 20)   # 5 of 20 slots invested, 15 in cash

    def test_thirty_to_fifty_non_overlapping_six_month_windows_are_impossible(self):
        self.assertEqual(max_feasible_samples(1600, 127), 13)
        eligible = np.arange(300, 1900)
        with self.assertRaises(ValueError) as ctx:
            choose_sample_positions(eligible, sample_count=40, seed=1, min_gap=127)
        self.assertIn("at most 13", str(ctx.exception))
        dense = choose_sample_positions(eligible, sample_count=40, seed=1, min_gap=21)
        self.assertEqual(len(dense), 40)
        self.assertTrue(all(b - a >= 21 for a, b in zip(dense, dense[1:])))
        self.assertEqual(dense.tolist(), choose_sample_positions(eligible, sample_count=40, seed=1, min_gap=21).tolist())


if __name__ == "__main__":
    unittest.main()
