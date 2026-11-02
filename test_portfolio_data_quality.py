from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from portfolio_rules import prepare, simulate


class PortfolioMissingBarTests(unittest.TestCase):
    def setUp(self):
        self.idx = pd.bdate_range("2017-11-08", periods=270)
        close = np.linspace(100.0, 160.0, len(self.idx))
        open_ = close * 0.999
        self.missing_pos = 254
        open_[self.missing_pos] = np.nan
        self.frame = pd.DataFrame({
            "Open": open_,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(len(close), 10000.0),
            "Turnover": close * 10000.0,
        }, index=self.idx)
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
        self.assertAlmostEqual(
            prepared["C"][self.missing_pos, 0],
            self.frame["Close"].iloc[self.missing_pos],
        )

    def test_simulator_does_not_execute_at_a_synthetic_open(self):
        prepared = prepare(
            {"AAA.NS": self.frame}, self.bench,
            membership_df=self.membership,
        )
        result = simulate(prepared, signals={self.missing_pos - 1}, start=253)
        self.assertAlmostEqual(result["equity"][self.missing_pos], 1.0)
        self.assertAlmostEqual(result["equity"][self.missing_pos + 1], 1.0)


if __name__ == "__main__":
    unittest.main()
