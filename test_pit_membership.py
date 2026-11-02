"""Offline regression tests for point-in-time Nifty 500 membership."""
import unittest

import numpy as np
import pandas as pd

from nifty500_pit import (
    build_membership_mask,
    expected_member_counts,
    validate_membership_calendar,
)
from portfolio_rules import prepare


def calendar(rows):
    return pd.DataFrame(rows, columns=[
        "symbol", "valid_from", "valid_to", "source", "source_url", "notes"
    ])


class PointInTimeMembershipTests(unittest.TestCase):
    def test_membership_intervals_are_start_inclusive_and_end_exclusive(self):
        idx = pd.date_range("2020-01-01", periods=4, freq="D")
        cal = calendar([
            ("AAA", "2020-01-02", "2020-01-04", "press_release", "", ""),
            ("BBB", "2020-01-03", "", "press_release", "", ""),
        ])
        mask = build_membership_mask(idx, ["AAA.NS", "BBB.NS", "NOT_IN_INDEX.NS"], cal)

        self.assertEqual(mask["AAA.NS"].tolist(), [False, True, True, False])
        self.assertEqual(mask["BBB.NS"].tolist(), [False, False, True, True])
        self.assertFalse(mask["NOT_IN_INDEX.NS"].any())
        self.assertEqual(expected_member_counts(idx, cal).tolist(), [0, 1, 2, 1])

    def test_backtest_liquidity_and_eligibility_are_limited_to_signal_date_members(self):
        idx = pd.bdate_range("2018-01-01", periods=300)
        n = len(idx)
        frames = {}
        specs = {
            "AAA.NS": (100.0, 10_000),
            "BBB.NS": (80.0, 100_000),
            "OUTSIDE.NS": (60.0, 10_000_000),
        }
        for ticker, (base, volume) in specs.items():
            close = base + np.arange(n, dtype=float) * (base / 1000)
            frames[ticker] = pd.DataFrame({
                "Open": close, "High": close * 1.01, "Low": close * 0.99,
                "Close": close, "Volume": np.full(n, volume, dtype=float),
            }, index=idx)
        bench = pd.DataFrame({"Close": np.linspace(100, 130, n)}, index=idx)
        cal = calendar([
            ("AAA", idx[0], "", "snapshot_floor", "", ""),
            ("BBB", idx[270], idx[290], "press_release", "", ""),
        ])

        prepared = prepare(frames, bench, liquid_top=1, membership_df=cal)
        cols = prepared["cols"]
        a, b, outside = (cols.index(x) for x in ("AAA.NS", "BBB.NS", "OUTSIDE.NS"))

        self.assertTrue(np.isfinite(prepared["rank"][260, a]))
        self.assertTrue(np.isnan(prepared["rank"][260, b]))
        self.assertTrue(np.isnan(prepared["rank"][260, outside]))
        self.assertTrue(np.isfinite(prepared["rank"][275, b]))
        self.assertTrue(np.isnan(prepared["rank"][275, a]))
        self.assertTrue(np.isfinite(prepared["rank"][295, a]))
        self.assertTrue(np.isnan(prepared["rank"][295, b]))

    def test_overlapping_membership_intervals_are_rejected(self):
        cal = calendar([
            ("AAA", "2020-01-01", "2020-01-05", "press_release", "", ""),
            ("AAA", "2020-01-04", "", "press_release", "", ""),
        ])
        with self.assertRaisesRegex(ValueError, "overlapping"):
            validate_membership_calendar(cal)

    def test_open_interval_cannot_be_followed_by_another_interval(self):
        cal = calendar([
            ("AAA", "2020-01-01", "", "press_release", "", ""),
            ("AAA", "2021-01-01", "", "press_release", "", ""),
        ])
        with self.assertRaisesRegex(ValueError, "open-ended"):
            validate_membership_calendar(cal)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(PointInTimeMembershipTests)
    )
    raise SystemExit(0 if result.wasSuccessful() else 1)
