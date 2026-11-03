import unittest

import numpy as np
import pandas as pd

from point_in_time_simulation import score_snapshot, simulate_sample


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


if __name__ == "__main__":
    unittest.main()
