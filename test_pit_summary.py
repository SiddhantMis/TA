import math
import unittest

import numpy as np
import pandas as pd

from pit_summary import block_bootstrap_ci, summarize_returns


def _returns(n=12, label="1M"):
    rows = []
    for i in range(n):
        bull = i % 3 != 0
        raw = 10.0 if i % 2 == 0 else -2.0
        rows.append({"sample_id": f"S{i + 1}", "signal_date": f"2021-{(i % 12) + 1:02d}-15", "market_regime": "BULL" if bull else "BEAR",
                     "horizon": label, "complete_stock_prices": True, "raw_top20_equal_weight_net_return_pct": raw,
                     "market_filter_portfolio_net_return_pct": raw if bull else 0.0,
                     "nifty500_tri_return_pct": 3.0, "nifty500_tri_entry_aligned_return_pct": 2.0})
    return pd.DataFrame(rows)


class SummaryTests(unittest.TestCase):
    def test_distribution_win_rates_and_regime_split(self):
        text, out = summarize_returns(_returns(), pd.DataFrame(), min_gap=21, horizons={"1M": 21})
        h = out["horizons"]["1M"]
        self.assertEqual((h["samples"], h["complete_samples"], h["incomplete_samples"]), (12, 12, 0))
        self.assertAlmostEqual(h["raw"]["mean"], 4.0)
        self.assertAlmostEqual(h["raw"]["median"], 4.0)
        self.assertAlmostEqual(h["raw_beats_benchmark_pct"], 50.0)          # 6 samples at +10 beat the 3.0 TRI; 6 at -2 do not
        self.assertEqual(out["benchmark_column"], "nifty500_tri_return_pct")
        self.assertEqual(h["by_regime"]["BULL"]["n"] + h["by_regime"]["BEAR"]["n"], 12)
        self.assertIn("### 1M", text)

    def test_like_for_like_series_is_primary_when_present(self):
        r = _returns()
        r["raw_top20_close_to_close_net_return_pct"] = r["raw_top20_equal_weight_net_return_pct"] - 3.0     # the overnight effect is +3 pts
        r["market_filter_close_to_close_net_return_pct"] = r["market_filter_portfolio_net_return_pct"] - 3.0
        _, out = summarize_returns(r, pd.DataFrame(), min_gap=21, horizons={"1M": 21})
        h = out["horizons"]["1M"]
        self.assertEqual(out["primary_basket_column"], "raw_top20_close_to_close_net_return_pct")
        self.assertAlmostEqual(h["raw"]["mean"], 1.0)                                  # like-for-like mean
        self.assertAlmostEqual(h["as_traded_next_open"]["mean"], 4.0)
        self.assertAlmostEqual(h["as_traded_next_open"]["overnight_execution_effect_mean"], 3.0)

    def test_incomplete_baskets_are_excluded_not_reweighted(self):
        r = _returns()
        r.loc[0, "complete_stock_prices"] = False
        r.loc[0, "raw_top20_equal_weight_net_return_pct"] = np.nan
        _, out = summarize_returns(r, pd.DataFrame(), min_gap=21, horizons={"1M": 21})
        h = out["horizons"]["1M"]
        self.assertEqual((h["complete_samples"], h["incomplete_samples"]), (11, 1))

    def test_effective_sample_size_and_bootstrap_block(self):
        both = pd.concat([_returns(40, "1M"), _returns(40, "6M")], ignore_index=True)
        _, out = summarize_returns(both, pd.DataFrame(), min_gap=21, horizons={"1M": 21, "6M": 126})
        self.assertAlmostEqual(out["horizons"]["1M"]["effective_independent_samples"], 40.0)
        self.assertAlmostEqual(out["horizons"]["6M"]["effective_independent_samples"], 40 * 21 / 126)
        self.assertEqual(out["horizons"]["6M"]["bootstrap_block"], 6)

    def test_block_bootstrap_constant_series_and_small_n(self):
        lo, hi = block_bootstrap_ci(np.full(30, 1.5), block=6)
        self.assertAlmostEqual(lo, 1.5)
        self.assertAlmostEqual(hi, 1.5)
        self.assertTrue(math.isnan(block_bootstrap_ci([1, 2, 3], block=2)[0]))

    def test_exclusion_counts_come_from_stock_statuses(self):
        stocks = pd.DataFrame({"1M_return_status": ["ok"] * 18 + ["unsupported_corporate_action_during_hold"] * 2})
        _, out = summarize_returns(_returns(), stocks, min_gap=21, horizons={"1M": 21})
        self.assertEqual(out["horizons"]["1M"]["stock_return_status_counts"]["unsupported_corporate_action_during_hold"], 2)


if __name__ == "__main__":
    unittest.main()
