from copy import deepcopy
import json
import unittest

from scanner_tracker.ledger import (
    configure_opening_positions, correct_fill, ledger_as_of, new_ledger,
    record_cash_event, record_corporate_action, record_fill,
)
from scanner_tracker.performance import account_performance, summarize_momentum, summarize_ta


def candidate(identity, value, **changes):
    trade = {"status": "closed", "net_R": value, "gross_R": value + .1 if value is not None else None,
             "initial_risk": 10, "total_cost_per_share": 1,
             "mfe_R": 2, "mae_R": -.5, "mfe_pct": 20, "mae_pct": -5,
             "bars_after_entry": 4, "ambiguities": [], "excursion_basis": "complete_held_bars"}
    return {"id": identity, "mode": "TA", "family": "reversal", "strategy_version": "ta-v1",
            "status": "closed", "current": {"data_status": "complete", "confirmation_sessions": 2},
            "model_trade": trade, **changes}


class PerformanceTests(unittest.TestCase):
    def test_ta_expectancy_median_win_loss_excursions_and_cost_stress(self):
        candidates = [candidate("win", 2), candidate("loss", -1), candidate("flat", 0)]
        candidates[0]["model_trade"]["ambiguities"] = [{"type": "stop_and_target_same_bar"}]
        saved = deepcopy(candidates)
        report = summarize_ta(candidates)
        row = report["families"]["reversal"]
        self.assertEqual(row["n_closed"], 3)
        self.assertAlmostEqual(row["mean_net_R"], 1 / 3)
        self.assertEqual(row["median_net_R"], 0)
        self.assertAlmostEqual(row["win_rate_pct"], 100 / 3)
        self.assertEqual(row["avg_win_R"], 2)
        self.assertEqual(row["avg_loss_R"], -1)
        self.assertEqual(row["profit_factor"], 2)
        self.assertEqual(row["ambiguities"], 1)
        self.assertEqual(row["mean_wait_sessions"], 3)
        self.assertEqual(row["mean_hold_sessions"], 5)
        self.assertAlmostEqual(row["double_cost_stress"]["mean_net_R"], 1 / 3 - .1)
        self.assertEqual(candidates, saved)
        self.assertEqual(report["basis"], "independent_unit_risk_not_funded_portfolio")
        json.dumps(report, allow_nan=False)

    def test_ta_incomplete_open_and_no_loss_cohorts_are_not_fabricated(self):
        unavailable = candidate("gap", 5, status="data_unavailable")
        missing = candidate("missing", None)
        opened = candidate("open", None, status="model_open")
        opened["model_trade"]["status"] = "open"
        report = summarize_ta([candidate("win", 1), unavailable, missing, opened])
        self.assertEqual(report["overall"]["n_closed"], 1)
        self.assertEqual(report["overall"]["incomplete"], 2)
        self.assertEqual(report["overall"]["model_open"], 1)
        self.assertIsNone(report["overall"]["profit_factor"])
        self.assertEqual(report["overall"]["profit_factor_status"], "no_losses")
        self.assertIsNone(report["families"]["breakout55"]["mean_net_R"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            summarize_ta([candidate("same", 1), candidate("same", 1)])

    def test_cash_flows_are_excluded_but_dividends_remain_income(self):
        ledger = new_ledger("TA", 100)
        for identity, kind, amount, day in [("deposit", "DEPOSIT", 100, "2026-11-02"),
                                             ("withdraw", "WITHDRAWAL", 20, "2026-11-03"),
                                             ("dividend", "DIVIDEND", 10, "2026-11-04")]:
            ledger = record_cash_event(ledger, {"event_id": identity, "cash_type": kind, "amount_inr": amount, "executed_at": day})
        valuations = [{"as_of": day, "equity_inr": value, "complete": True} for day, value in
                      [("2026-10-30", "100"), ("2026-11-02", "220"), ("2026-11-03", "200"), ("2026-11-04", "210")]]
        result = account_performance(valuations, ledger)
        self.assertEqual(result["status"], "complete")
        self.assertAlmostEqual(result["intervals"][0]["return"], .1)
        self.assertAlmostEqual(result["intervals"][1]["return"], 0)
        self.assertAlmostEqual(result["intervals"][2]["return"], .05)
        self.assertAlmostEqual(result["cumulative_twr"], .155)
        self.assertEqual(result["max_drawdown"], 0)

    def test_missing_valuation_suppresses_entire_chain_without_stitching(self):
        rows = [{"as_of": "2026-11-02", "equity_inr": "100", "complete": True},
                {"as_of": "2026-11-03", "equity_inr": None, "complete": False},
                {"as_of": "2026-11-04", "equity_inr": "121", "complete": True},
                {"as_of": "2026-11-05", "equity_inr": "133.10", "complete": True}]
        result = account_performance(rows, new_ledger("TA", 100))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["missing_intervals"], 2)
        self.assertIsNone(result["cumulative_twr"])
        self.assertIsNone(result["max_drawdown"])
        self.assertAlmostEqual(result["intervals"][-1]["return"], .1)
        self.assertIsNone(result["history"][-1]["cumulative_twr"])

    def test_drawdown_uses_flow_neutral_wealth_index(self):
        ledger = record_cash_event(new_ledger("TA", 100), {"event_id": "transfer:1:TA", "cash_type": "DEPOSIT", "executed_at": "2026-11-03", "amount_inr": 100})
        rows = [{"as_of": day, "equity_inr": value, "complete": True} for day, value in
                [("2026-11-02", 100), ("2026-11-03", 180), ("2026-11-04", 198)]]
        report = account_performance(rows, ledger)
        self.assertAlmostEqual(report["max_drawdown"], -.1)
        self.assertAlmostEqual(report["cumulative_twr"], -.01)

    def test_future_cash_and_other_allocation_do_not_change_past_returns(self):
        ledger = record_cash_event(new_ledger("TA", 100), {"event_id": "future", "cash_type": "DEPOSIT", "executed_at": "2026-11-20", "amount_inr": 10000})
        rows = [{"as_of": "2026-11-02", "equity_inr": 100, "complete": True, "mode": "TA"},
                {"as_of": "2026-11-03", "equity_inr": 110, "complete": True, "mode": "TA"},
                {"as_of": "2026-11-03", "equity_inr": 999999, "complete": True, "mode": "MOMENTUM"}]
        self.assertAlmostEqual(account_performance(rows, ledger)["cumulative_twr"], .1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            account_performance(rows[:2] + rows[:1], ledger)

    def test_unfunded_and_preopening_dates_are_not_returns(self):
        ledger = new_ledger("TA", 100)
        ledger["opening_as_of"] = "2026-11-03"
        rows = [{"as_of": "2026-11-02", "equity_inr": 100, "complete": True},
                {"as_of": "2026-11-03", "equity_inr": 100, "complete": True}]
        self.assertEqual(account_performance(rows, ledger)["status"], "incomplete")
        zero = [{"as_of": "2026-11-02", "equity_inr": 0, "complete": True},
                {"as_of": "2026-11-03", "equity_inr": 0, "complete": True}]
        self.assertIsNone(account_performance(zero, new_ledger("TA"))["cumulative_twr"])

    def test_momentum_summary_uses_model_only_with_costs_and_cash(self):
        ledger = record_fill(new_ledger("MOMENTUM", 1000, "model"), {"execution_id": "model", "executed_at": "2026-11-03", "symbol": "ABC.NS", "side": "BUY", "quantity": 5, "price_inr": 100, "fees_inr": 1})
        report = {"model": {"ledger": ledger, "capital_configured": True, "target_holdings": ["ABC.NS"],
                  "history": [{"as_of": "2026-11-02", "equity_inr": "1000", "cash_inr": "1000", "status": "COMPLETE"},
                              {"as_of": "2026-11-03", "equity_inr": "1049", "cash_inr": "499", "status": "COMPLETE"}],
                  "rebalance_history": [{"status": "EXECUTED"}]}}
        result = summarize_momentum(report)
        self.assertAlmostEqual(result["cumulative_return"], .049)
        self.assertEqual(result["fees_inr"], "1.00")
        self.assertEqual(result["turnover"]["traded_notional_inr"], "500.00")
        self.assertAlmostEqual(result["cash_pct"], 499 / 1049 * 100)
        self.assertEqual(result["target_cash_pct"], 95)

    def test_momentum_turnover_aggregates_exact_execution_weights(self):
        report = {"model": {"ledger": new_ledger("MOMENTUM", 1000, "model"), "history": [],
                  "rebalance_history": [
                      {"status": "EXECUTED", "execution_date": "2026-11-03", "pre_execution_equity_inr": "1000", "traded_notional_inr": "500"},
                      {"status": "EXECUTED", "execution_date": "2026-12-01", "pre_execution_equity_inr": "2000", "traded_notional_inr": "1000"},
                  ]}}
        turnover = summarize_momentum(report)["turnover"]
        self.assertEqual(turnover["status"], "complete")
        self.assertEqual(turnover["weight_turnover"], 1)
        self.assertEqual(turnover["mean_weight_turnover"], .5)
        self.assertEqual([item["weight_turnover"] for item in turnover["per_rebalance"]], [.5, .5])
        report["model"]["rebalance_history"].append({"status": "EXECUTED"})
        incomplete = summarize_momentum(report)["turnover"]
        self.assertEqual(incomplete["status"], "incomplete")
        self.assertIsNone(incomplete["weight_turnover"])

    def test_momentum_benchmark_uses_same_window_and_price_proxy_labels(self):
        report = {"benchmark": "NIFTYBEES.NS", "model": {
            "ledger": new_ledger("MOMENTUM", 1000, "model"), "capital_configured": True,
            "history": [
                {"as_of": "2026-11-02", "equity_inr": "1000", "cash_inr": "1000", "status": "COMPLETE", "benchmark_close": 100, "benchmark_adjusted_close": 100},
                {"as_of": "2026-11-03", "equity_inr": "1100", "cash_inr": "100", "status": "COMPLETE", "benchmark_close": 105, "benchmark_adjusted_close": 106,
                 "previous_benchmark_session": "2026-11-02"},
            ],
        }}
        result = summarize_momentum(report)
        self.assertAlmostEqual(result["cumulative_return"], .1)
        self.assertAlmostEqual(result["benchmark_return"], .05)
        self.assertAlmostEqual(result["excess_return"], .05)
        self.assertAlmostEqual(result["benchmark_adjusted_reference_return"], .06)
        self.assertIn("Price proxy", result["benchmark_comparison"]["basis"])
        self.assertIn("not a validated TRI", result["benchmark_comparison"]["adjusted_reference_basis"])
        json.dumps(result, allow_nan=False)

    def test_benchmark_or_model_gaps_withhold_comparison_without_endpoint_stitching(self):
        report = {"model": {"ledger": new_ledger("MOMENTUM", 1000, "model"), "history": [
            {"as_of": "2026-11-02", "equity_inr": "1000", "status": "COMPLETE", "benchmark_close": 100},
            {"as_of": "2026-11-03", "equity_inr": "1050", "status": "COMPLETE", "benchmark_close": None},
            {"as_of": "2026-11-04", "equity_inr": "1100", "status": "COMPLETE", "benchmark_close": 110},
        ]}}
        result = summarize_momentum(report)
        self.assertEqual(result["benchmark_comparison"]["status"], "incomplete")
        self.assertIsNone(result["benchmark_return"])
        self.assertIsNone(result["excess_return"])
        self.assertTrue(all(row["benchmark_cumulative_return"] is None for row in result["history"]))
        # A known unobserved model session cannot be hidden by adjacent endpoints.
        report["model"]["history"].pop(1)
        report["model"]["history"][-1]["previous_benchmark_session"] = "2026-11-03"
        gap = summarize_momentum(report)
        self.assertEqual(gap["status"], "incomplete")
        self.assertIsNone(gap["cumulative_return"])
        self.assertIsNone(gap["benchmark_return"])
        self.assertEqual(len(gap["model_history_gaps"]), 1)


class HistoricalLedgerTests(unittest.TestCase):
    def test_future_fills_and_cash_are_excluded_without_mutating_source(self):
        state = new_ledger("TA", 1000)
        state["opening_as_of"] = "2026-11-01"
        state = record_fill(state, {"execution_id": "buy", "executed_at": "2026-11-02", "symbol": "ABC.NS", "side": "BUY", "quantity": 5, "price_inr": 100, "fees_inr": 1})
        state = record_fill(state, {"execution_id": "sell", "executed_at": "2026-11-04", "symbol": "ABC.NS", "side": "SELL", "quantity": 5, "price_inr": 110, "fees_inr": 1})
        saved = deepcopy(state)
        past = ledger_as_of(state, "2026-11-02")
        self.assertEqual(past["holdings"]["ABC.NS"]["quantity"], 5)
        self.assertEqual(past["cash_balance_inr"], "499.00")
        self.assertEqual(past["realized_pnl_inr"], "0.00")
        self.assertEqual(state, saved)
        with self.assertRaisesRegex(ValueError, "projections"):
            record_fill(past, {"execution_id": "new"})
        before = ledger_as_of(state, "2026-10-30")
        self.assertEqual(before["projection_status"], "BEFORE_OPENING")
        self.assertEqual(before["cash_balance_inr"], "0.00")
        self.assertEqual(before["opening_as_of"], "2026-11-01")

    def test_corrections_restate_economic_history_and_unknown_sales_are_date_specific(self):
        state = record_fill(new_ledger("TA", 1000), {"execution_id": "buy", "executed_at": "2026-11-02", "symbol": "ABC.NS", "side": "BUY", "quantity": 5, "price_inr": 100, "fees_inr": 0})
        corrected = correct_fill(state, "buy", "fix", {"execution_id": "replaced", "executed_at": "2026-11-02", "symbol": "ABC.NS", "side": "BUY", "quantity": 5, "price_inr": 90, "fees_inr": 0}, "2026-11-05")
        self.assertEqual(ledger_as_of(corrected, "2026-11-02")["cash_balance_inr"], "550.00")
        unknown = configure_opening_positions(new_ledger("TA"), [{"symbol": "ABC.NS", "quantity": 5}], "2026-11-01")
        unknown = record_fill(unknown, {"execution_id": "sale", "executed_at": "2026-11-04", "symbol": "ABC.NS", "side": "SELL", "quantity": 2, "price_inr": 100, "fees_inr": 0})
        self.assertEqual(ledger_as_of(unknown, "2026-11-02")["unknown_cost_sales"], 0)
        self.assertIsNone(ledger_as_of(unknown, "2026-11-04")["realized_pnl_inr"])

    def test_split_has_no_effect_before_its_effective_session(self):
        state = configure_opening_positions(new_ledger("TA"), [{"symbol": "ABC.NS", "quantity": 5, "average_cost_inr": 100}], "2026-11-01")
        state = record_corporate_action(state, {"event_id": "split", "executed_at": "2026-11-03", "symbol": "ABC.NS", "ratio": 2})
        self.assertEqual(ledger_as_of(state, "2026-11-02")["holdings"]["ABC.NS"]["quantity"], 5)
        self.assertEqual(ledger_as_of(state, "2026-11-03")["holdings"]["ABC.NS"]["quantity"], 10)


if __name__ == "__main__":
    unittest.main()
