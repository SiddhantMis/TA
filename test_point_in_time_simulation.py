import unittest

import numpy as np
import pandas as pd

from point_in_time_simulation import score_snapshot


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


if __name__ == "__main__":
    unittest.main()
