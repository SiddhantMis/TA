"""Offline tests for the momentum portfolio state and recommendation engine."""
import unittest

from momentum_portfolio import (
    apply_scan_result, build_target_holdings, generate_chatgpt_brief,
    generate_gemini_brief, is_rebalance_due, market_regime_from_closes,
    monitor_actual_holdings, new_state, record_execution_fill, relative_context,
    scan_market,
)


def row(ticker, rank, *, above200=True, above50=True, rs=20.0, status="ok"):
    return {
        "ticker": ticker, "leader_rank": rank, "liquidity_rank": 1,
        "above_sma200": above200, "above_sma50": above50,
        "relative_strength_status": status, "relative_strength_12_1_pct": rs,
        "relative_strength_6m_pct": rs / 2, "relative_strength_3m_pct": rs / 3,
        "last_close": 100.0 + (rank or 0),
    }


class PortfolioStateTests(unittest.TestCase):
    def test_recommendations_never_become_actual_holdings(self):
        state = new_state(100_000)
        rows = {f"S{i}": row(f"S{i}", i) for i in range(1, 26)}
        ranked = sorted(rows.values(), key=lambda x: x["leader_rank"])
        result = apply_scan_result(
            state, "2026-11-02",
            {"regime": "BULL", "benchmark": "NIFTYBEES.NS", "benchmark_close": 250, "sma200": 240},
            rows, ranked, {"coverage_pct": 100, "requested": 25, "loaded": 25}, portfolio_size=20,
        )
        self.assertEqual(len(result["target_holdings"]), 20)
        self.assertEqual(result["actual_holdings"], {})
        self.assertEqual(result["summary"]["proposed_buys"], 20)
        self.assertTrue(all(x["execution_status"] == "PROPOSED_NOT_EXECUTED" for x in result["proposed_changes"]))

    def test_top30_buffer_retains_rank21_but_replaces_rank31(self):
        rows = {f"S{i}": row(f"S{i}", i) for i in range(1, 36)}
        ranked = sorted(rows.values(), key=lambda x: x["leader_rank"])
        target = build_target_holdings(ranked, rows, {"S21": {"quantity": 2}}, "BULL", 20, 30)
        self.assertIn("S21", target)
        self.assertEqual(len(target), 20)
        target = build_target_holdings(ranked, rows, {"S31": {"quantity": 2}}, "BULL", 20, 30)
        self.assertNotIn("S31", target)
        self.assertEqual(set(target), {f"S{i}" for i in range(1, 21)})

    def test_missing_or_invalid_data_does_not_force_exit(self):
        actual = {"ABC.NS": {"quantity": 5, "average_cost": 100, "high_water_mark": 110}}
        updated, report = monitor_actual_holdings(actual, {}, 20, 30)
        self.assertIn("ABC.NS", updated)
        self.assertEqual(report[0]["status"], "DATA_UNAVAILABLE")
        rows = {"ABC.NS": row("ABC.NS", None, status="insufficient_price_coverage")}
        _, report = monitor_actual_holdings(actual, rows, 20, 30)
        self.assertEqual(report[0]["status"], "DATA_UNAVAILABLE")

    def test_deterioration_is_review_not_auto_sell(self):
        actual = {"ABC.NS": {"quantity": 10, "average_cost": 100, "high_water_mark": 120}}
        updated, report = monitor_actual_holdings(actual, {"ABC.NS": row("ABC.NS", 31)}, 20, 30)
        self.assertEqual(report[0]["status"], "EXIT_REVIEW")
        self.assertEqual(updated["ABC.NS"]["quantity"], 10)

    def test_bear_regime_proposes_cash_but_preserves_actual_positions(self):
        state = new_state(100_000)
        state["actual_holdings"] = {"ABC.NS": {"ticker": "ABC.NS", "quantity": 10, "average_cost": 100, "high_water_mark": 110}}
        rows = {"ABC.NS": row("ABC.NS", 1)}
        result = apply_scan_result(
            state, "2026-11-02",
            {"regime": "BEAR", "benchmark": "NIFTYBEES.NS", "benchmark_close": 200, "sma200": 210},
            rows, [rows["ABC.NS"]], {"coverage_pct": 100, "requested": 1, "loaded": 1}, 20,
        )
        self.assertEqual(result["target_holdings"], [])
        self.assertEqual(result["actual_holdings"]["ABC.NS"]["quantity"], 10)
        self.assertEqual(result["actual_holding_monitor"][0]["status"], "MARKET_WARNING")
        self.assertEqual(result["proposed_changes"][0]["side"], "SELL")
        self.assertEqual(result["proposed_changes"][0]["execution_status"], "PROPOSED_NOT_EXECUTED")

    def test_unknown_regime_and_incomplete_scan_block_rebalance(self):
        state, rows = new_state(100_000), {"ABC.NS": row("ABC.NS", 1)}
        unknown = apply_scan_result(
            state, "2026-11-02", {"regime": "UNKNOWN"}, rows, [rows["ABC.NS"]],
            {"coverage_pct": 100, "requested": 1, "loaded": 1},
        )
        self.assertEqual(unknown["rebalance_status"], "BLOCKED_UNKNOWN_MARKET_REGIME")
        blocked = apply_scan_result(
            state, "2026-11-02", {"regime": "BULL"}, rows, [rows["ABC.NS"]],
            {"coverage_pct": 50, "requested": 2, "loaded": 1},
        )
        self.assertEqual(blocked["rebalance_status"], "BLOCKED_INCOMPLETE_UNIVERSE_SCAN")
        self.assertEqual(blocked["target_holdings"], [])
        self.assertEqual(blocked["proposed_changes"], [])

    def test_rs_line_ema_uses_full_history_not_only_recent_window(self):
        benchmark = [100.0] * 200
        ratios = [0.5] * 130 + [1.0] * 70
        stock = [b * r for b, r in zip(benchmark, ratios)]
        full = relative_context(stock, benchmark)
        short = relative_context(stock[-64:], benchmark[-64:])
        self.assertTrue(full["rs_line_above_ema50"])
        self.assertFalse(short["rs_line_above_ema50"])

    def test_90_percent_universe_coverage_blocks_monthly_rebalance(self):
        state = new_state(100_000)
        rows = {"ABC.NS": row("ABC.NS", 1)}
        result = apply_scan_result(
            state, "2026-11-02", {"regime": "BULL"},
            rows, [rows["ABC.NS"]], {"coverage_pct": 90, "requested": 10, "loaded": 9},
        )
        self.assertEqual(result["rebalance_status"], "BLOCKED_INCOMPLETE_UNIVERSE_SCAN")
        self.assertEqual(result["target_holdings"], [])
        self.assertEqual(result["proposed_changes"], [])

    def test_market_regime_calculation(self):
        self.assertEqual(market_regime_from_closes([100] * 199)["regime"], "UNKNOWN")
        self.assertEqual(market_regime_from_closes([100] * 199 + [110])["regime"], "BULL")
        self.assertEqual(market_regime_from_closes([100] * 199 + [90])["regime"], "BEAR")

    def test_three_month_rs_and_rs_line_are_calculated(self):
        stock = [100 + i * 0.5 for i in range(100)]
        bench = [100 + i * 0.2 for i in range(100)]
        result = relative_context(stock, bench)
        self.assertIsNotNone(result["relative_strength_3m_pct"])
        self.assertIsInstance(result["rs_line_above_ema50"], bool)
        missing = relative_context(stock[-20:], bench[-20:])
        self.assertIsNone(missing["relative_strength_3m_pct"])
        self.assertIsNone(missing["rs_line_above_ema50"])

    def test_confirmed_fills_update_actual_state_and_cash_idempotently(self):
        state = new_state(100_000)
        state, applied = record_execution_fill(state, "ABC.NS", "BUY", 10, 100, "2026-11-02", "order-1", 10)
        self.assertTrue(applied)
        self.assertEqual(state["actual_holdings"]["ABC.NS"]["quantity"], 10)
        self.assertEqual(state["cash_balance_inr"], 98_990)
        state, applied = record_execution_fill(state, "ABC.NS", "BUY", 10, 100, "2026-11-02", "order-1", 10)
        self.assertFalse(applied)
        self.assertEqual(state["actual_holdings"]["ABC.NS"]["quantity"], 10)
        state, applied = record_execution_fill(state, "ABC.NS", "SELL", 4, 110, "2026-11-03", "order-2", 5)
        self.assertTrue(applied)
        self.assertEqual(state["actual_holdings"]["ABC.NS"]["quantity"], 6)
        self.assertEqual(state["cash_balance_inr"], 99_425)
        self.assertEqual(state["realized_pnl_inr"], 31.0)

    def test_rejects_over_sell_and_unaffordable_buy(self):
        state = new_state(1_000)
        with self.assertRaises(ValueError):
            record_execution_fill(state, "ABC.NS", "BUY", 20, 100, execution_id="b1")
        state, _ = record_execution_fill(state, "ABC.NS", "BUY", 5, 100, execution_id="b2")
        with self.assertRaises(ValueError):
            record_execution_fill(state, "ABC.NS", "SELL", 6, 110, execution_id="s1")

    def test_rebalance_runs_once_per_month_after_day28_and_catches_up_short_february(self):
        state = new_state()
        self.assertTrue(is_rebalance_due("2026-11-02", state))
        state["last_rebalanced_month"] = "2026-11"
        self.assertFalse(is_rebalance_due("2026-11-29", state))
        state["last_rebalanced_month"] = "2026-10"
        self.assertFalse(is_rebalance_due("2026-11-27", state))
        self.assertTrue(is_rebalance_due("2026-11-28", state))
        self.assertTrue(is_rebalance_due("2026-11-02", state, True))

        # February 2026 has no trading session on/after Saturday the 28th.
        # The first scan in March catches up February exactly once.
        state["last_rebalanced_month"] = "2026-01"
        self.assertTrue(is_rebalance_due("2026-03-02", state))
        state["last_rebalanced_month"] = "2026-02"
        self.assertFalse(is_rebalance_due("2026-03-02", state))
        self.assertTrue(is_rebalance_due("2026-03-30", state))

    def test_february_catchup_records_the_prior_month_not_scan_month(self):
        state = new_state()
        state["last_rebalanced_month"] = "2026-01"
        result = apply_scan_result(
            state, "2026-03-02",
            {"regime": "BULL", "benchmark_close": 250, "sma200": 240},
            {}, [], {"coverage_pct": 100.0},
        )
        self.assertEqual(result["rebalance_status"], "REBALANCED")
        self.assertEqual(result["last_rebalanced_month"], "2026-02")

    def test_ai_briefs_handle_empty_actual_portfolio(self):
        state = new_state()
        state.update({
            "as_of": "2026-11-02",
            "market_regime": {"regime": "BEAR", "benchmark_close": 200, "sma200": 210},
            "data_quality": {"coverage_pct": 100, "loaded": 500, "requested": 500},
            "summary": {"cash_balance_inr": 1_000_000, "actual_market_value_inr": 0, "estimated_account_equity_inr": 1_000_000},
            "actual_holding_monitor": [], "target_portfolio": [], "proposed_changes": [],
            "rebalance_status": "REBALANCED",
        })
        gemini, chatgpt = generate_gemini_brief(state), generate_chatgpt_brief(state)
        self.assertIn("No executed holdings", gemini)
        self.assertIn("Regime: BEAR", gemini)
        self.assertIn("No actual holdings or proposed transactions", chatgpt)
        self.assertNotIn("all current holdings remain", gemini.lower())

    def test_hysteresis_does_not_change_actual_quantity(self):
        state = new_state(50_000)
        state["actual_holdings"] = {"S21": {"ticker": "S21", "quantity": 7, "average_cost": 100, "high_water_mark": 115}}
        rows = {f"S{i}": row(f"S{i}", i) for i in range(1, 25)}
        rows["S21"] = row("S21", 21)
        ranked = sorted(rows.values(), key=lambda x: x["leader_rank"])
        result = apply_scan_result(
            state, "2026-11-28", {"regime": "BULL", "benchmark_close": 250, "sma200": 240},
            rows, ranked, {"coverage_pct": 100, "requested": 24, "loaded": 24}, 20,
        )
        self.assertIn("S21", result["target_holdings"])
        self.assertEqual(result["actual_holdings"]["S21"]["quantity"], 7)
        self.assertFalse(any(x["side"] == "SELL" and x["ticker"] == "S21" for x in result["proposed_changes"]))


    def test_scan_market_freezes_every_series_at_requested_friday_session(self):
        import numpy as np
        import pandas as pd
        from unittest.mock import patch
        import analyzer as A
        import leaders as LD

        dates = pd.bdate_range(end="2026-11-03", periods=300)
        benchmark = pd.DataFrame({
            "Open": np.linspace(100, 130, len(dates)),
            "High": np.linspace(101, 131, len(dates)),
            "Low": np.linspace(99, 129, len(dates)),
            "Close": np.linspace(100, 130, len(dates)),
            "Volume": 1_000_000,
        }, index=dates)
        stock = pd.DataFrame({
            "Open": np.linspace(80, 120, len(dates)),
            "High": np.linspace(81, 121, len(dates)),
            "Low": np.linspace(79, 119, len(dates)),
            "Close": np.linspace(80, 120, len(dates)),
            "Volume": 2_000_000,
        }, index=dates)
        frames = {"NIFTYBEES.NS": benchmark, "AAA.NS": stock, "BBB.NS": stock * 1.01}
        observed = []

        def fake_metrics(frame, benchmark_frame):
            observed.append((frame.index[-1].date().isoformat(), benchmark_frame.index[-1].date().isoformat()))
            return {
                "relative_strength_status": "ok",
                "relative_strength_12_1_pct": 15.0,
                "relative_strength_6m_pct": 10.0,
                "traded_value_126d": 1e8,
                "above_sma200": True,
            }

        with patch.object(A, "fetch_ticker", side_effect=lambda ticker: frames[ticker]), \
             patch.object(A, "YF_SLEEP_SECONDS", 0), \
             patch.object(LD, "load_universe", return_value=["AAA.NS", "BBB.NS"]), \
             patch.object(LD, "leader_metrics", side_effect=fake_metrics):
            as_of, regime, rows, ranked, quality = scan_market(as_of="2026-10-30")

        self.assertEqual(as_of, "2026-10-30")
        self.assertEqual(regime["as_of"], "2026-10-30")
        self.assertEqual(len(observed), 2)
        self.assertTrue(all(stock_date == "2026-10-30" and bench_date == "2026-10-30"
                            for stock_date, bench_date in observed))
        self.assertTrue(all(row["data_as_of"] == "2026-10-30" for row in rows.values()))
        self.assertEqual(quality["coverage_pct"], 100.0)
        self.assertEqual(len(ranked), 2)

    def test_scan_market_rejects_requested_date_without_benchmark_session(self):
        import numpy as np
        import pandas as pd
        from unittest.mock import patch
        import analyzer as A

        dates = pd.bdate_range(end="2026-10-30", periods=260)
        benchmark = pd.DataFrame({"Close": np.linspace(100, 120, len(dates))}, index=dates)
        with patch.object(A, "fetch_ticker", return_value=benchmark):
            with self.assertRaisesRegex(RuntimeError, "Requested benchmark session"):
                scan_market(universe_path="unused", as_of="2026-11-01")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PortfolioStateTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
