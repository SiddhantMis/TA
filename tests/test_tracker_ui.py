"""Offline UI behavior checks with synthetic service responses."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from scanner_tracker.charts import allocation_figure, candlestick_figure, equity_figure, trade_markers
from scanner_tracker.ui import PAGES, _parse_positions


BARS = [
    {"date": "2026-11-02", "open": 100, "high": 105, "low": 98, "close": 103},
    {"date": "2026-11-03", "open": 104, "high": 109, "low": 102, "close": 107},
]


class FakeService:
    def __init__(self):
        self.commits = []
        self.settings_updates = []
        self.pins = []
        self.notes = []
        self.openings = []
        self.corporate_issues = []
        self.reconciliations = []

    def status(self):
        return {"latest_run": {"as_of": "2026-11-03", "status": "COMPLETE", "coverage": {"requested": 2, "loaded": 2}},
                "counts": {"ta_candidates": 1, "watch": 0}, "health": {"storage": "ready"}}

    def candidates(self, **kwargs):
        return [{"id": "setup-1", "symbol": "SYNTH.NS", "family": "reversal", "scope": "watchlist",
                 "status": "awaiting_confirmation", "signal_session": "2026-11-02",
                 "original_plan": {"entry": 105, "stop": 98, "target": 125}}]

    def candidate(self, candidate_id):
        return {**self.candidates()[0], "bars": deepcopy(BARS), "events": [], "current": {"levels": {"support": 99, "resistance": 127}}}

    def watch_items(self):
        return []

    def set_watch(self, candidate_id, watched=True, note=None):
        self.pins.append((candidate_id, watched))

    def save_note(self, candidate_id, text):
        self.notes.append((candidate_id, text))

    def momentum_report(self, scope="wide"):
        return {"status": "PENDING_NEXT_SESSION_OPEN", "regime": "BULL", "as_of": "2026-11-03",
                "ranks": [{"symbol": "SYNTH.NS", "rank": 1}], "coverage": {"requested": 2, "loaded": 2},
                "model": {"target_holdings": ["SYNTH.NS"], "target_weights": {"SYNTH.NS": .05},
                          "ledger": {"cash_balance_inr": "500.00"}, "history": []}, "proposals": []}

    def ledger(self, mode):
        return {"mode": mode, "cash_balance_inr": "0.00", "holdings": {}, "events": [], "execution_history": []}

    def configure_ledger(self, *args, **kwargs):
        self.openings.append((args, kwargs))
        return {}

    def record_fill(self, *args, **kwargs):
        return {}

    def correct_fill(self, *args, **kwargs):
        return {}

    def preview_import(self, mode, text):
        return {"valid": text == "valid rows", "rows": [{"execution_id": "fixture"}] if text == "valid rows" else [],
                "errors": [] if text == "valid rows" else ["Invalid synthetic CSV"]}

    def commit_import(self, mode, text):
        self.commits.append((mode, text))
        return {"valid": True}

    def cash_event(self, *args):
        return {}

    def transfer(self, *args):
        return {}

    def settings(self):
        return {}

    def update_settings(self, values):
        self.settings_updates.append(values)

    def export_bundle(self):
        return b"synthetic-export"

    def request_refresh(self):
        return {"status": "requested"}

    def research_reports(self):
        return {}

    def corporate_action_issues(self):
        return self.corporate_issues

    def reconcile_corporate_action(self, issue_key, action_type, ratio, note, confirm_actual=False):
        self.reconciliations.append((issue_key, action_type, ratio, note, confirm_actual))
        for issue in self.corporate_issues:
            if issue["issue_key"] == issue_key:
                issue["resolved"] = True
        return {"status": "resolved"}


def render_fixture(service):
    from scanner_tracker.ui import render_app
    render_app(service)


class ChartTests(unittest.TestCase):
    def test_candles_original_current_and_recorded_fill_do_not_mutate_inputs(self):
        bars = deepcopy(BARS)
        plan = {"entry": 105, "stop": 98, "targets": [125, 135]}
        original = deepcopy(plan)
        figure = candlestick_figure(bars, plan, {"levels": {"support": 99}},
                                     [{"executed_at": "2026-11-03", "side": "BUY", "price_inr": 104, "kind": "actual"}])
        self.assertEqual(len(figure.data), 2)
        self.assertEqual(len(figure.layout.shapes), 5)
        self.assertEqual(plan, original)
        self.assertEqual(bars, BARS)
        self.assertEqual(figure.data[1].name, "actual BUY")

    def test_invalid_or_duplicate_prices_are_rejected_and_empty_history_is_absent(self):
        self.assertIsNone(candlestick_figure([]))
        with self.assertRaises(ValueError):
            candlestick_figure([BARS[0], BARS[0]])
        with self.assertRaises(ValueError):
            candlestick_figure([{**BARS[0], "low": 110}])

    def test_equity_missing_marks_are_not_connected(self):
        figure = equity_figure([{"as_of": "2026-11-02", "equity_inr": "100"},
                               {"as_of": "2026-11-03", "equity_inr": None}])
        self.assertEqual(tuple(figure.data[0].y), (100.0, None))
        self.assertFalse(figure.data[0].connectgaps)
        self.assertIsNone(equity_figure([]))

    def test_allocation_and_unknown_opening_cost(self):
        self.assertEqual(tuple(allocation_figure({"SYNTH.NS": .05}).data[0].y), (5.0,))
        positions = _parse_positions("symbol,quantity,average_cost_inr\nSYNTH.NS,2,\n")
        self.assertIsNone(positions[0]["average_cost_inr"])

    def test_trade_markers_require_recorded_fills_or_model_state(self):
        self.assertEqual(trade_markers({"bars": BARS}), [])
        candidate = {"model_trade": {"entry_session": "2026-11-03", "entry_price": 104,
                                     "exit_session": None, "exit_price": None}}
        self.assertEqual(trade_markers(candidate), [{"executed_at": "2026-11-03", "price_inr": 104.0,
                                                     "side": "BUY", "kind": "model"}])

    def test_explicit_twr_series_uses_percent_axis_and_preserves_missing_returns(self):
        rows = [{"as_of": "2026-11-04", "equity_inr": 1200, "cumulative_twr": .05},
                {"as_of": "2026-11-02", "equity_inr": 1000, "cumulative_twr": 0},
                {"as_of": "2026-11-03", "equity_inr": 1100, "cumulative_twr": None}]
        figure = equity_figure(rows, series={"cumulative_twr": "Actual net TWR"},
                               yaxis_title="Cumulative return", as_percentage=True)
        self.assertEqual(figure.data[0].name, "Actual net TWR")
        self.assertEqual(tuple(figure.data[0].y), (0.0, None, .05))
        self.assertEqual(figure.layout.yaxis.tickformat, ".2%")
        self.assertEqual(figure.layout.xaxis.type, "category")
        self.assertFalse(figure.data[0].connectgaps)
        self.assertIsNone(equity_figure([{"as_of": "2026-11-02", "equity_inr": 1000}],
                                       series={"cumulative_twr": "Actual net TWR"}, as_percentage=True))


class TrackerUiTests(unittest.TestCase):
    def app(self, service=None):
        return AppTest.from_function(render_fixture, args=(service or FakeService(),), default_timeout=15).run()

    def test_all_pages_render_offline(self):
        app = self.app()
        for page in PAGES:
            app.radio(key="workspace_navigation").set_value(page).run()
            self.assertEqual(len(app.exception), 0, f"Page {page}: {app.exception}")
            self.assertEqual(len(app.error), 0, f"Page {page}: {app.error}")

    def test_import_requires_matching_preview_and_confirmation(self):
        service = FakeService()
        app = self.app(service)
        app.radio(key="workspace_navigation").set_value("Actual journal").run()
        self.assertTrue(app.button(key="commit_TA").disabled)
        app.text_area(key="import_text_TA").set_value("valid rows").run()
        app.button(key="preview_TA").click().run()
        self.assertTrue(app.button(key="commit_TA").disabled)
        checkbox = next(item for item in app.checkbox if item.label.startswith("I reviewed"))
        checkbox.check().run()
        self.assertFalse(app.button(key="commit_TA").disabled)
        app.text_area(key="import_text_TA").set_value("changed rows").run()
        self.assertTrue(app.button(key="commit_TA").disabled)
        self.assertEqual(service.commits, [])
        app.text_area(key="import_text_TA").set_value("valid rows").run()
        app.button(key="preview_TA").click().run()
        next(item for item in app.checkbox if item.label.startswith("I reviewed")).check().run()
        app.button(key="commit_TA").click().run()
        self.assertEqual(service.commits, [("TA", "valid rows")])

    def test_zero_capital_does_not_enable_sizing(self):
        service = FakeService()
        app = self.app(service)
        app.radio(key="workspace_navigation").set_value("Settings").run()
        next(button for button in app.button if button.label == "Save risk and capital settings").click().run()
        self.assertEqual(service.settings_updates, [])
        self.assertTrue(any("positive model capitals" in item.value for item in app.error))

    def test_review_displays_computed_ta_model_and_actual_performance_separately(self):
        service = FakeService()
        group = {"n_closed": 3, "mean_net_R": .25, "median_net_R": .1, "win_rate_pct": 66.6666667,
                 "profit_factor": 2.5, "profit_factor_status": "defined", "incomplete": 1,
                 "model_open": 2, "ambiguities": 2, "mean_mfe_R": 1.5, "mean_mae_R": -.4,
                 "mean_wait_sessions": 2, "mean_hold_sessions": 5,
                 "double_cost_stress": {"mean_net_R": .15, "median_net_R": 0,
                                        "missing_cost_records": 0, "status": "complete"}}
        model = {"status": "complete", "n_intervals": 1, "valid_intervals": 1, "missing_intervals": 0,
                 "capital_configured": True, "cumulative_return": .1, "max_drawdown": -.05,
                 "benchmark_return": .05, "excess_return": .05, "fees_inr": "1.50", "cash_pct": 10,
                 "turnover": {"weight_turnover": .4, "executed_rebalances": 1, "status": "complete"},
                 "benchmark_comparison": {"status": "complete", "start": "2026-11-02", "end": "2026-11-03", "basis": "ETF price proxy, not TRI."},
                 "history": [{"as_of": "2026-11-02", "equity_inr": 1000, "cumulative_twr": 0, "benchmark_cumulative_return": 0},
                             {"as_of": "2026-11-03", "equity_inr": 1100, "cumulative_twr": .1, "benchmark_cumulative_return": .05}]}
        incomplete = {"status": "incomplete", "n_intervals": 2, "valid_intervals": 0, "missing_intervals": 2,
                      "cumulative_twr": None, "max_drawdown": None, "opening_date_known": True,
                      "history": [{"as_of": "2026-11-02", "equity_inr": 1000, "cumulative_twr": 0},
                                  {"as_of": "2026-11-03", "equity_inr": None, "cumulative_twr": None},
                                  {"as_of": "2026-11-04", "equity_inr": 1100, "cumulative_twr": None}]}
        actual_momentum = {"status": "complete", "n_intervals": 1, "valid_intervals": 1, "missing_intervals": 0,
                           "cumulative_twr": .02, "max_drawdown": 0, "opening_date_known": True,
                           "history": [{"as_of": "2026-11-02", "equity_inr": 2000, "cumulative_twr": 0},
                                       {"as_of": "2026-11-03", "equity_inr": 2040, "cumulative_twr": .02}]}
        service.research_reports = lambda: {"ta_detailed": {"overall": group, "families": {"reversal": group}},
                                            "momentum_performance": {"wide": model},
                                            "actual": {"TA": incomplete, "MOMENTUM": actual_momentum}}
        app = self.app(service)
        app.radio(key="workspace_navigation").set_value("Review").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        metrics = {item.label: item.value for item in app.metric}
        self.assertEqual(metrics["Mean net R"], "0.25R")
        self.assertEqual(metrics["Median net R"], "0.10R")
        self.assertEqual(metrics["Mean net R at double costs"], "0.15R")
        self.assertEqual(metrics["Model cumulative return"], "10.00%")
        self.assertEqual(metrics["Same-window ETF price return"], "5.00%")
        self.assertEqual(metrics["Actual cumulative TWR"], "—")
        self.assertEqual(metrics["Missing actual intervals"], "2")
        self.assertEqual(len(app.get("plotly_chart")), 2)
        self.assertTrue(any("no funded TA equity curve" in item.value for item in app.caption))
        self.assertTrue(any("performance is incomplete" in item.value for item in app.warning))
        app.radio(key="review_actual_mode").set_value("MOMENTUM").run()
        metrics = {item.label: item.value for item in app.metric}
        self.assertEqual(metrics["Actual cumulative TWR"], "2.00%")
        app.selectbox(key="review_actual_chart_MOMENTUM").set_value("Account value").run()
        self.assertEqual(len(app.exception), 0)

    def test_manual_refresh_setup_is_not_reported_as_a_queued_scan(self):
        service = FakeService()
        service.request_refresh = lambda: {"status": "manual_setup_required", "message": "Run the workflow manually.",
                                           "url": "https://github.com/example/project/actions/workflows/tracker-eod.yml"}
        app = self.app(service)
        app.button(key="overview_refresh").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Run the workflow manually" in item.value for item in app.info))
        self.assertFalse(any("refresh requested" in item.value for item in app.success))

    def test_overview_shows_storage_quota_and_background_health(self):
        service = FakeService()
        original = service.status()
        service.status = lambda: {**original, "storage": {"status": "quota_warning", "database_bytes": 1048576,
                                                           "tracked_input_archive_bytes": 2097152,
                                                           "archive_objects_without_size": 1},
                                  "health": {"status": "complete", "background_tasks": [{"key": "backup", "status": "failed"}]},
                                  "notifications": {"status": "not_configured"}}
        app = self.app(service)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("reference limit" in item.value for item in app.warning))
        metrics = {item.label: item.value for item in app.metric}
        self.assertEqual(metrics["Database size"], "1.00 MiB")
        self.assertEqual(metrics["Archives with unknown size"], "1")

    def test_actual_opening_balance_requires_explicit_date_and_passes_it_to_service(self):
        service = FakeService()
        app = self.app(service)
        app.radio(key="workspace_navigation").set_value("Actual journal").run()
        next(button for button in app.button if button.label == "Set opening balances").click().run()
        self.assertEqual(service.openings, [])
        app.checkbox(key="opening_ack_TA").check()
        next(button for button in app.button if button.label == "Set opening balances").click().run()
        self.assertEqual(service.openings, [])
        self.assertTrue(any("opening balances are valid" in item.value for item in app.error))
        app.date_input(key="opening_as_of_TA").set_value(date(2026, 11, 2))
        next(button for button in app.button if button.label == "Set opening balances").click().run()
        self.assertEqual(service.openings[0][1]["as_of"], "2026-11-02")

    def test_corporate_action_needs_verification_ratio_and_source_note(self):
        service = FakeService()
        service.corporate_issues = [{"issue_key": "split-1", "symbol": "SYNTH.NS", "session": "2026-11-03",
                                     "action": {"type": "Stock Splits", "value": 2}, "resolved": False}]
        app = self.app(service)
        app.radio(key="workspace_navigation").set_value("Settings").run()
        button = next(item for item in app.button if item.label == "Confirm corporate-action reconciliation")
        button.click().run()
        self.assertEqual(service.reconciliations, [])
        app.checkbox(key="corp_reviewed_split-1").check()
        next(item for item in app.button if item.label == "Confirm corporate-action reconciliation").click().run()
        self.assertEqual(service.reconciliations, [])
        app.number_input(key="corp_ratio_split-1").set_value(2.0)
        app.text_area(key="corp_note_split-1").set_value("Verified synthetic exchange action")
        app.checkbox(key="corp_actual_split-1").check()
        next(item for item in app.button if item.label == "Confirm corporate-action reconciliation").click().run()
        self.assertEqual(service.reconciliations, [("split-1", "SPLIT", 2.0, "Verified synthetic exchange action", True)])

    def test_unsupported_corporate_action_has_no_reconciliation_button(self):
        service = FakeService()
        service.corporate_issues = [{"issue_key": "action-1", "symbol": "SYNTH.NS", "session": "2026-11-03",
                                     "action": {"type": "Capital Gains", "value": 1}, "resolved": False}]
        app = self.app(service)
        app.radio(key="workspace_navigation").set_value("Settings").run()
        self.assertFalse(any(item.label == "Confirm corporate-action reconciliation" for item in app.button))
        self.assertTrue(any("stays blocked" in item.value for item in app.info))

    def test_access_denial_precedes_service_construction(self):
        security = types.ModuleType("scanner_tracker.security")
        security.require_app_access = lambda: False
        service_module = types.ModuleType("scanner_tracker.service")
        service_module.TrackerService = types.SimpleNamespace(from_env=lambda: self.fail("Private service opened before access"))
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with patch.dict(sys.modules, {"scanner_tracker.security": security, "scanner_tracker.service": service_module}):
            app = AppTest.from_file(str(app_path)).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.title), 0)

    def test_app_disposes_database_pool_after_render_and_handles_engine_free_fixture(self):
        from unittest.mock import Mock

        security = types.ModuleType("scanner_tracker.security")
        security.require_app_access = lambda: True
        service_module = types.ModuleType("scanner_tracker.service")
        service = FakeService()
        service.engine = types.SimpleNamespace(dispose=Mock())
        service_module.TrackerService = types.SimpleNamespace(from_env=lambda: service)
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with patch.dict(sys.modules, {"scanner_tracker.security": security, "scanner_tracker.service": service_module}):
            app = AppTest.from_file(str(app_path)).run()
        self.assertEqual(len(app.exception), 0)
        service.engine.dispose.assert_called_once()
        del service.engine
        with patch.dict(sys.modules, {"scanner_tracker.security": security, "scanner_tracker.service": service_module}):
            app = AppTest.from_file(str(app_path)).run()
        self.assertEqual(len(app.exception), 0)

    def test_real_service_contract_renders_all_pages_with_private_synthetic_records(self):
        from scanner_tracker.service import TrackerService
        with tempfile.TemporaryDirectory() as directory:
            database = (Path(directory) / "tracker.db").as_posix()
            service = TrackerService("sqlite:///" + database)
            candidate = {**FakeService().candidates()[0], "mode": "TA", "scopes": ["wide", "personal"],
                         "events": [], "current": {"levels": {"support": 99, "resistance": 125}}, "model_trade": None}
            service.repo.save_candidates([candidate])
            service.repo.save_document("latest_prices", "SYNTH.NS", {"bars": deepcopy(BARS)})
            service.repo.record_run("fixture-run", "2026-11-03", "complete",
                                    {"coverage_pct": 100, "diagnostics": {}, "published_at": "2026-11-03T11:00:00Z"})
            service.repo.save_document("momentum", "wide", {**FakeService().momentum_report(),
                                                              "scope": "wide", "regime": {"regime": "BULL"}})
            service.configure_ledger("TA", 1000, as_of="2026-11-02")
            service.record_fill("TA", {"execution_id": "fixture-fill", "executed_at": "2026-11-03",
                                        "symbol": "SYNTH.NS", "side": "BUY", "quantity": 1,
                                        "price_inr": "104", "fees_inr": "0", "signal_id": "setup-1"})
            service.set_watch("setup-1")
            service.save_note("setup-1", "Synthetic integration note")
            try:
                app = self.app(service)
                for page in PAGES:
                    app.radio(key="workspace_navigation").set_value(page).run()
                    self.assertEqual(len(app.exception), 0, f"Page {page}: {app.exception}")
                    self.assertEqual(len(app.error), 0, f"Page {page}: {app.error}")
            finally:
                service.engine.dispose()


if __name__ == "__main__":
    unittest.main()
