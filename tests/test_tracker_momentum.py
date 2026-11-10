"""Synthetic end-to-end checks for frozen monthly targets and separate ledgers."""
from copy import deepcopy
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
import sys
from types import ModuleType

import numpy as np
import pandas as pd

from scanner_tracker.ledger import configure_opening_positions, new_ledger, record_fill
from scanner_tracker.momentum import RULE_VERSION, rebalance_month_due, reconcile_actual_proposals, run_momentum


def market(n=25, end="2026-11-05"):
    index = pd.bdate_range(end=end, periods=330)
    def frame(rate):
        close = 80 * np.exp(np.arange(len(index)) * rate)
        return pd.DataFrame({"Open": close * 0.999, "High": close * 1.01, "Low": close * 0.99,
                             "Close": close, "Adj Close": close, "Volume": 1_000_000}, index=index)
    return {f"S{i:02}.NS": frame(0.0005 + (n - i) * 0.00004) for i in range(n)}, frame(0.0002)


class MomentumTests(unittest.TestCase):
    def test_months_never_move_backwards_and_february_catches_up(self):
        self.assertEqual(rebalance_month_due("2026-11-02"), "2026-11")
        self.assertIsNone(rebalance_month_due("2026-11-03", "2026-11"))
        self.assertIsNone(rebalance_month_due("2026-11-27", "2026-10"))
        self.assertEqual(rebalance_month_due("2026-11-30", "2026-10"), "2026-11")
        self.assertEqual(rebalance_month_due("2026-03-02", "2026-01"), "2026-02")
        self.assertIsNone(rebalance_month_due("2026-03-03", "2026-02"))
        self.assertEqual(rebalance_month_due("2026-03-30", "2026-02"), "2026-03")

    def test_signal_then_exact_next_open_with_fees_and_cash_nonnegative(self):
        frames, benchmark = market()
        first = run_momentum(frames, benchmark, "2026-11-02", model_capital=100000)
        self.assertEqual(first["coverage"]["coverage_pct"], 100)
        self.assertEqual(len(first["model"]["target_holdings"]), 20)
        self.assertEqual(first["model"]["ledger"]["holdings"], {})
        self.assertAlmostEqual(sum(first["model"]["target_weights"].values()), 1)
        second = run_momentum(frames, benchmark, "2026-11-03", previous_model=first["model"])
        ledger = second["model"]["ledger"]
        self.assertGreaterEqual(Decimal(ledger["cash_balance_inr"]), 0)
        self.assertTrue(all(e["executed_at"] == "2026-11-03" for e in ledger["execution_history"]))
        self.assertGreater(sum(Decimal(e["fees_inr"]) for e in ledger["execution_history"]), 0)
        self.assertEqual(len(second["model"]["rebalance_history"]), 1)
        rebalance = second["model"]["rebalance_history"][0]
        exact_notional = sum(Decimal(event["price_inr"]) * event["quantity"] for event in ledger["execution_history"])
        self.assertEqual(Decimal(rebalance["pre_execution_equity_inr"]), 100000)
        self.assertEqual(Decimal(rebalance["traded_notional_inr"]), exact_notional)
        self.assertAlmostEqual(rebalance["weight_turnover"], float(exact_notional / Decimal(100000)))
        self.assertEqual(second["model"]["history"][-1]["previous_benchmark_session"], "2026-11-02")
        self.assertIsNotNone(second["model"]["history"][-1]["benchmark_adjusted_close"])
        self.assertEqual(first["model"]["ledger"]["holdings"], {})
        json.dumps(second, allow_nan=False)
        self.assertEqual(run_momentum(frames, benchmark, "2026-11-03", previous_model=second["model"])["model"], second["model"])

    def test_small_basket_leaves_unused_slots_cash(self):
        frames, benchmark = market(2)
        first = run_momentum(frames, benchmark, "2026-11-02", model_capital=100000)
        second = run_momentum(frames, benchmark, "2026-11-03", previous_model=first["model"])
        self.assertAlmostEqual(sum(first["model"]["target_weights"].values()), .1)
        self.assertGreater(Decimal(second["model"]["ledger"]["cash_balance_inr"]), 89000)

    def test_missing_open_blocks_whole_basket_then_retries_original_session(self):
        frames, benchmark = market(3)
        first = run_momentum(frames, benchmark, "2026-11-02", model_capital=100000)
        incomplete = deepcopy(frames)
        incomplete["S00.NS"].loc["2026-11-03", "Open"] = np.nan
        blocked = run_momentum(incomplete, benchmark, "2026-11-03", previous_model=first["model"])
        self.assertEqual(blocked["model"]["ledger"]["holdings"], {})
        self.assertEqual(blocked["model"]["pending_rebalance"]["status"], "BLOCKED_MISSING_OPEN")
        self.assertIsNone(blocked["model"]["history"][-1]["equity_inr"])
        recovered = run_momentum(frames, benchmark, "2026-11-04", previous_model=blocked["model"])
        self.assertTrue(all(e["executed_at"] == "2026-11-03" for e in recovered["model"]["ledger"]["execution_history"]))
        revised = next(row for row in recovered["model"]["history"] if row["as_of"] == "2026-11-03")
        self.assertIn("revision_reason", revised)
        self.assertIsNotNone(revised["equity_inr"])
        self.assertNotEqual(revised["equity_inr"], "100000.00")

    def test_scope_coverage_and_missing_current_benchmark_fail_closed(self):
        frames, benchmark = market(19)
        self.assertEqual(run_momentum(frames, benchmark, "2026-11-02", universe_size=20)["status"], "READY")
        self.assertEqual(run_momentum(frames, benchmark, "2026-11-02", universe_size=21)["status"], "BLOCKED_INCOMPLETE_UNIVERSE")
        stale = run_momentum(frames, benchmark.loc[:"2026-10-30"], "2026-11-02", model_capital=100000)
        self.assertEqual(stale["status"], "BLOCKED_BENCHMARK")
        self.assertIsNone(stale["model"]["pending_rebalance"])

    def test_actual_inheritance_retention_and_resize_are_separate_from_model(self):
        frames, benchmark = market(35)
        actual = configure_opening_positions(new_ledger("MOMENTUM", 100000), [
            {"symbol": "S21.NS", "quantity": 100, "average_cost_inr": 100},
            {"symbol": "S34.NS", "quantity": 10, "average_cost_inr": 100},
        ])
        saved = deepcopy(actual)
        result = run_momentum(frames, benchmark, "2026-11-02", model_capital=100000, actual_ledger=actual)
        self.assertNotIn("S21.NS", result["model"]["target_holdings"])
        self.assertIn("S21.NS", result["actual_target"]["holdings"])
        self.assertNotIn("S34.NS", result["actual_target"]["holdings"])
        self.assertTrue(any(p["symbol"] == "S21.NS" and p["side"] == "SELL" and p["target_quantity"] > 0 for p in result["proposals"]))
        self.assertTrue(any(p["symbol"] == "S34.NS" and p["target_quantity"] == 0 for p in result["proposals"]))
        self.assertEqual(actual, saved)

    def test_missing_held_mark_blocks_all_actual_sizing_even_with_95pct_scope(self):
        frames, benchmark = market(20)
        actual = configure_opening_positions(new_ledger("MOMENTUM", 100000), [{"symbol": "MISSING.NS", "quantity": 3}])
        result = run_momentum(frames, benchmark, "2026-11-02", actual_ledger=actual)
        self.assertEqual(result["actual_target"]["status"], "BLOCKED_MISSING_MARKS")
        self.assertEqual(result["proposals"], [])

    def test_later_actual_account_configuration_gets_its_own_initial_target(self):
        frames, benchmark = market(3)
        first = run_momentum(frames, benchmark, "2026-11-02", model_capital=100000)
        actual = new_ledger("MOMENTUM", 20000)
        second = run_momentum(frames, benchmark, "2026-11-03", previous_model=first["model"], actual_ledger=actual)
        self.assertEqual(second["actual_target"]["as_of"], "2026-11-03")
        self.assertEqual(second["proposal_status"], "READY")
        self.assertTrue(second["proposals"])

    def test_auxiliary_held_history_is_valued_but_excluded_from_scope_ranks(self):
        frames, benchmark = market(25)
        scope = list(frames)[:20]
        actual = configure_opening_positions(new_ledger("MOMENTUM", 100000), [{"symbol": "S24.NS", "quantity": 10}])
        result = run_momentum(frames, benchmark, "2026-11-02", actual_ledger=actual,
                              universe_symbols=scope, universe_size=20)
        self.assertEqual(result["coverage"]["valid"], 20)
        self.assertEqual(result["coverage"]["coverage_pct"], 100)
        self.assertNotIn("S24.NS", [row["symbol"] for row in result["ranks"]])
        self.assertNotIn("S24.NS", result["actual_target"]["holdings"])
        self.assertTrue(any(p["symbol"] == "S24.NS" and p["side"] == "SELL" for p in result["proposals"]))

    def test_model_rebalance_sells_before_buys_and_resizes_retained_names(self):
        frames, benchmark = market(25, end="2026-11-30")
        first = run_momentum(frames, benchmark, "2026-11-02", model_capital=100000)
        second = run_momentum(frames, benchmark, "2026-11-03", previous_model=first["model"])
        # An executed incumbent can drift far from its equal slot weight.
        frames["S00.NS"].loc["2026-11-27":, ["Open", "High", "Low", "Close", "Adj Close"]] *= 2
        target = run_momentum(frames, benchmark, "2026-11-27", previous_model=second["model"], force=True)
        completed = run_momentum(frames, benchmark, "2026-11-30", previous_model=target["model"])
        new_events = completed["model"]["ledger"]["execution_history"][len(second["model"]["ledger"]["execution_history"]):]
        self.assertTrue(any(e["side"] == "SELL" and e["symbol"] == "S00.NS" for e in new_events))
        sides = [e["side"] for e in new_events]
        self.assertEqual(sides, sorted(sides, key=lambda side: side != "SELL"))
        self.assertGreaterEqual(Decimal(completed["model"]["ledger"]["cash_balance_inr"]), 0)

    def test_analytical_adjusted_prices_do_not_change_execution_basis(self):
        frames, benchmark = market(2)
        split = deepcopy(frames)
        split["S00.NS"].loc[:"2026-10-01", ["Open", "High", "Low", "Close"]] *= 2
        original = run_momentum(frames, benchmark, "2026-11-02", model_capital=100000)
        adjusted = run_momentum(split, benchmark, "2026-11-02", model_capital=100000)
        self.assertEqual(original["ranks"][0]["relative_strength_12_1_pct"], adjusted["ranks"][0]["relative_strength_12_1_pct"])
        self.assertEqual(adjusted["ranks"][0]["indicator_price_basis"], "Adj Close")
        self.assertEqual(adjusted["ranks"][0]["liquidity_basis"], "reported_close_times_volume_proxy")

    def test_force_has_explicit_label_and_same_day_retry_is_idempotent(self):
        frames, benchmark = market(2)
        first = run_momentum(frames, benchmark, "2026-11-02", model_capital=100000, force=True)
        self.assertEqual(first["model"]["pending_rebalance"]["rule_version"], RULE_VERSION + ":FORCED")
        retried = run_momentum(frames, benchmark, "2026-11-02", previous_model=first["model"], force=True)
        self.assertEqual(first["model"], retried["model"])

    def test_daily_bear_warning_does_not_liquidate_existing_model(self):
        frames, benchmark = market(2)
        first = run_momentum(frames, benchmark, "2026-11-02", model_capital=100000)
        second = run_momentum(frames, benchmark, "2026-11-03", previous_model=first["model"])
        bear = benchmark.copy()
        bear.loc["2026-11-04", ["Open", "High", "Low", "Close", "Adj Close"]] = 20
        result = run_momentum(frames, bear, "2026-11-04", previous_model=second["model"])
        self.assertEqual(result["regime"]["regime"], "BEAR")
        self.assertEqual(result["model"]["ledger"], second["model"]["ledger"])
        self.assertIsNone(result["model"]["pending_rebalance"])

    def test_research_variants_only_change_ranking_and_cannot_touch_actual_accounts(self):
        frames, benchmark = market(25)
        symbols = list(reversed(list(frames)))
        comparison = {"rankings": {"volatility_adjusted": [
            {"symbol": symbol, "rank": i + 1, "score": 100 - i} for i, symbol in enumerate(symbols)
        ], "fip": [{"symbol": "S24.NS", "rank": 1, "score": 1}]}}
        fake = ModuleType("scanner_tracker.research")
        fake.compare_momentum_rankings = lambda *args: comparison
        with patch.dict(sys.modules, {"scanner_tracker.research": fake}):
            result = run_momentum(frames, benchmark, "2026-11-02", model_capital=100000, ranking_method="volatility_adjusted")
            self.assertEqual(result["ranks"][0]["symbol"], "S24.NS")
            self.assertIn(":research:volatility_adjusted", result["rule_version"])
            next_day = run_momentum(frames, benchmark, "2026-11-03", previous_model=result["model"], ranking_method="volatility_adjusted")
            self.assertGreaterEqual(Decimal(next_day["model"]["ledger"]["cash_balance_inr"]), 0)
            fip = run_momentum(frames, benchmark, "2026-11-02", ranking_method="fip")
            self.assertEqual(fip["model"]["target_holdings"], ["S24.NS"])
        with self.assertRaisesRegex(ValueError, "actual-account"):
            run_momentum(frames, benchmark, "2026-11-02", ranking_method="fip", actual_ledger=new_ledger("MOMENTUM", 100))

    def test_actual_proposals_reserve_fees_before_proportional_buy_sizing(self):
        symbols = [f"S{i:02}.NS" for i in range(20)]
        frames = {symbol: pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-11-02"])) for symbol in symbols}
        ledger = new_ledger("MOMENTUM", 20000)
        target = {"status": "READY", "as_of": "2026-11-02", "holdings": symbols,
                  "quantities": {symbol: 10 for symbol in symbols}}
        original_target, original_ledger = deepcopy(target), deepcopy(ledger)
        result = reconcile_actual_proposals(ledger, target, frames, "2026-11-02")
        self.assertEqual(result["requested_buy_quantity"], 200)
        self.assertEqual(result["fundable_buy_quantity"], 180)
        self.assertEqual(result["funding_status"], "SCALED_TO_REFERENCE_CASH")
        self.assertEqual(len(result["unfunded"]), 20)
        for row in result["proposals"]:
            ledger = record_fill(ledger, {"execution_id": row["symbol"], "executed_at": "2026-11-02",
                "symbol": row["symbol"], "side": row["side"], "quantity": row["quantity"],
                "price_inr": row["reference_price_inr"], "fees_inr": row["estimated_fees_inr"]})
        self.assertEqual(ledger["cash_balance_inr"], result["estimated_cash_after_inr"])
        self.assertGreaterEqual(Decimal(ledger["cash_balance_inr"]), 0)
        self.assertEqual(target, original_target)
        self.assertEqual(original_ledger["cash_balance_inr"], "20000.00")

    def test_read_reconciliation_removes_filled_buy_without_changing_frozen_target(self):
        frames = {"ABC.NS": pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-11-02"]))}
        ledger = new_ledger("MOMENTUM", 10000)
        target = {"status": "READY", "as_of": "2026-10-30", "holdings": ["ABC.NS"], "quantities": {"ABC.NS": 10}}
        frozen = deepcopy(target)
        before = reconcile_actual_proposals(ledger, target, frames, "2026-11-02")
        self.assertEqual(before["proposals"][0]["quantity"], 10)
        filled = record_fill(ledger, {"execution_id": "confirmed", "executed_at": "2026-11-02",
            "symbol": "ABC.NS", "side": "BUY", "quantity": 10, "price_inr": 100, "fees_inr": "1.50"})
        saved = deepcopy(filled)
        reconciled = reconcile_actual_proposals(filled, target, frames, "2026-11-02")
        self.assertEqual(reconciled["status"], "READY")
        self.assertEqual(reconciled["proposals"], [])
        self.assertEqual(reconciled, reconcile_actual_proposals(filled, target, frames, "2026-11-02"))
        self.assertEqual(filled, saved)
        self.assertEqual(target, frozen)


if __name__ == "__main__":
    unittest.main()
