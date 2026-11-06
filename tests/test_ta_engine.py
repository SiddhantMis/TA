"""Synthetic execution contracts; these tests never request market data."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scanner_tracker.ta import scan_ta, STRATEGY_VERSION


def prices(count=510):
    dates = pd.bdate_range("2023-01-02", periods=count)
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 1000.0}, index=dates)


def candidate(frame, signal_position=-4, family="reversal"):
    day = frame.index[signal_position].date().isoformat()
    plan = {"trigger": 100.1, "entry": 100.1, "stop": 96.0, "target": 112.0,
            "confirmation_limit_sessions": 3, "time_exit_sessions": 15,
            "signal_close": 100.0, "cost_per_side": 0.0015}
    if family != "reversal":
        plan = {"entry_floor": 100.0, "entry_ceiling": 105.0, "signal_atr": 2.0,
                "target": None, "time_exit_sessions": 60, "cost_per_side": 0.0015}
    return {"id": "existing-idea", "mode": "TA", "symbol": "TEST.NS", "family": family,
            "strategy_version": STRATEGY_VERSION, "signal_session": day,
            "status": "awaiting_confirmation" if family == "reversal" else "awaiting_entry",
            "original_plan": plan,
            "current": {"last_processed_session": day, "confirmation_sessions": 0,
                        "observations": 1, "data_status": "complete"},
            "events": [], "model_trade": None}


def find(items, identity="existing-idea"):
    return next(item for item in items if item["id"] == identity)


def row(frame, position, o, high, low, close):
    frame.loc[frame.index[position], ["Open", "High", "Low", "Close"]] = [o, high, low, close]


class TAEngineTests(unittest.TestCase):
    def test_confirmation_needs_later_close_and_cannot_fill_on_confirmation_bar(self):
        frame = prices()
        idea = candidate(frame)
        row(frame, -3, 100.0, 105.0, 98.0, 101.0)
        day = frame.index[-3].date().isoformat()
        updated = find(scan_ta("TEST.NS", frame, prices(), [idea], day))
        self.assertEqual(updated["status"], "awaiting_entry")
        self.assertIsNone(updated["model_trade"])
        self.assertEqual(updated["current"]["confirmation_session"], day)
        row(frame, -2, 100.5, 102.0, 99.0, 101.0)
        entered = find(scan_ta("TEST.NS", frame, prices(), [updated], frame.index[-2].date().isoformat()))
        self.assertEqual(entered["status"], "model_open")
        self.assertEqual(entered["model_trade"]["entry_price"], 100.5)
        self.assertEqual(idea["events"], [], "pure scan must not mutate caller state")

    def test_confirmation_requires_close_not_high_and_expires_after_three_sessions(self):
        frame, benchmark = prices(), prices()
        idea = candidate(frame)
        row(frame, -3, 100.0, 106.0, 99.0, 100.0)
        row(frame, -2, 100.0, 106.0, 99.0, 100.0)
        before = find(scan_ta("TEST.NS", frame, benchmark, [idea], frame.index[-2].date().isoformat()))
        self.assertEqual(before["status"], "awaiting_confirmation")
        self.assertEqual(before["current"]["confirmation_sessions"], 2)
        final = find(scan_ta("TEST.NS", frame, benchmark, [before]))
        self.assertEqual(final["status"], "expired")
        self.assertIsNone(final["model_trade"])

    def test_stop_touch_before_confirmation_invalidates_even_if_close_recovers(self):
        frame = prices()
        row(frame, -3, 100.0, 104.0, 95.0, 103.0)
        updated = find(scan_ta("TEST.NS", frame, prices(), [candidate(frame)]))
        self.assertEqual(updated["status"], "invalidated")
        self.assertEqual(updated["current"]["reason"], "stop_touched_before_confirmation")

    def test_reversal_gap_rechecks_rr_and_never_delays_a_failed_fill(self):
        frame = prices()
        row(frame, -3, 100.0, 103.0, 99.0, 102.0)
        row(frame, -2, 104.0, 105.0, 102.0, 103.0)
        row(frame, -1, 101.0, 102.0, 99.0, 100.0)
        updated = find(scan_ta("TEST.NS", frame, prices(), [candidate(frame)]))
        self.assertEqual(updated["status"], "skipped")
        self.assertEqual(updated["current"]["reason"], "reward_risk_below_2")
        self.assertIsNone(updated["model_trade"])

    def test_same_bar_stop_and_target_resolves_to_stop_with_explicit_ambiguity(self):
        frame = prices()
        row(frame, -3, 100.0, 103.0, 99.0, 102.0)
        row(frame, -2, 101.0, 114.0, 95.0, 110.0)
        updated = find(scan_ta("TEST.NS", frame, prices(), [candidate(frame)]))
        trade = updated["model_trade"]
        self.assertEqual(updated["status"], "closed")
        self.assertEqual(trade["exit_price"], 96.0)
        self.assertEqual(trade["ambiguities"][0]["resolution"], "stop_first")
        self.assertAlmostEqual(trade["total_cost_per_share"], (101.0 + 96.0) * 0.0015)
        self.assertAlmostEqual(trade["net_R"], (-5.0 - (101.0 + 96.0) * 0.0015) / 5.0)
        self.assertLess(trade["mfe_pct"], trade["mfe_upper_pct"], "exit-bar high is not a known held excursion")

    def test_gap_stop_exits_at_open_instead_of_the_original_stop(self):
        frame = prices()
        row(frame, -3, 100.0, 103.0, 99.0, 102.0)
        row(frame, -2, 101.0, 103.0, 99.0, 102.0)
        row(frame, -1, 93.0, 95.0, 90.0, 94.0)
        trade = find(scan_ta("TEST.NS", frame, prices(), [candidate(frame)]))["model_trade"]
        self.assertEqual((trade["exit_reason"], trade["exit_price"]), ("gap_stop", 93.0))
        self.assertEqual(trade["excursion_basis"], "through_exit_open")

    def test_missing_entry_bar_pauses_and_restoration_replays_original_next_open(self):
        frame, benchmark = prices(), prices()
        row(frame, -3, 100.0, 103.0, 99.0, 102.0)
        row(frame, -2, 101.0, 103.0, 99.0, 102.0)
        idea = candidate(frame)
        missing = frame.drop(frame.index[-2])
        paused = find(scan_ta("TEST.NS", missing, benchmark, [idea]))
        self.assertEqual(paused["status"], "data_unavailable")
        self.assertEqual(paused["current"]["resume_status"], "awaiting_entry")
        self.assertIsNone(paused["model_trade"])
        resumed = find(scan_ta("TEST.NS", frame, benchmark, [paused]))
        self.assertEqual(resumed["model_trade"]["entry_session"], frame.index[-2].date().isoformat())
        self.assertEqual(resumed["model_trade"]["entry_price"], 101.0)

    def test_missing_benchmark_and_stale_expected_session_cannot_create_fills(self):
        frame = prices()
        idea = candidate(frame)
        no_benchmark = find(scan_ta("TEST.NS", frame, None, [idea]))
        self.assertEqual(no_benchmark["status"], "data_unavailable")
        self.assertIsNone(no_benchmark["model_trade"])
        expected = (frame.index[-1] + pd.offsets.BDay()).date().isoformat()
        stale = find(scan_ta("TEST.NS", frame.iloc[:-3], prices().iloc[:-3], [idea], expected))
        self.assertEqual(stale["status"], "data_unavailable")
        self.assertEqual(stale["current"]["confirmation_sessions"], 0)

    def test_retries_and_future_bars_preserve_exact_original_and_events(self):
        frame = prices()
        row(frame, -3, 100.0, 103.0, 99.0, 102.0)
        row(frame, -2, 101.0, 103.0, 99.0, 102.0)
        as_of = frame.index[-2].date().isoformat()
        original = candidate(frame)
        result = scan_ta("TEST.NS", frame, prices(), [original], as_of)
        retry = scan_ta("TEST.NS", frame, prices(), result, as_of)
        self.assertEqual(result, retry)
        future = frame.copy()
        row(future, -1, 300.0, 500.0, 1.0, 400.0)
        self.assertEqual(result, scan_ta("TEST.NS", future, prices(), [original], as_of))
        self.assertEqual(find(result)["original_plan"], original["original_plan"])
        json.dumps(result, allow_nan=False)

    def test_continuation_trailing_stop_uses_prior_completed_close(self):
        frame = prices()
        idea = candidate(frame, family="breakout55")
        row(frame, -3, 102.0, 104.0, 100.0, 103.0)
        row(frame, -2, 103.0, 111.0, 99.0, 110.0)
        day_two = find(scan_ta("TEST.NS", frame, prices(), [idea], frame.index[-2].date().isoformat()))
        self.assertEqual(day_two["status"], "model_open")
        self.assertEqual(day_two["model_trade"]["current_stop"], 98.0)
        row(frame, -1, 105.0, 106.0, 103.0, 104.5)
        closed = find(scan_ta("TEST.NS", frame, prices(), [day_two]))
        self.assertEqual(closed["model_trade"]["exit_price"], 104.0)
        self.assertEqual(closed["model_trade"]["exit_reason"], "stop")
        self.assertIsNone(closed["model_trade"]["target"])

    def test_continuation_rejects_open_gap_and_does_not_fill_later(self):
        frame = prices()
        row(frame, -3, 106.0, 108.0, 104.0, 107.0)
        idea = candidate(frame, family="pullback20")
        result = find(scan_ta("TEST.NS", frame, prices(), [idea]))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["current"]["reason"], "next_open_exceeds_one_signal_atr_gap")
        self.assertIsNone(result["model_trade"])

    def test_real_breakout_detection_confirms_on_signal_close_without_invented_target(self):
        frame = prices()
        close = 100.0 + np.arange(len(frame)) * 0.02
        frame["Close"], frame["Open"] = close, close - 0.1
        frame["High"], frame["Low"] = close + 0.2, close - 0.2
        row(frame, -1, close[-1], close[-1] + 1.2, close[-1] - 0.1, close[-1] + 1.0)
        found = scan_ta("TEST.NS", frame, prices())
        breakout = next(item for item in found if item["family"] == "breakout55")
        self.assertEqual(breakout["status"], "awaiting_entry")
        self.assertIsNone(breakout["original_plan"]["target"])
        self.assertIsNone(breakout["model_trade"])
        self.assertEqual(found, scan_ta("TEST.NS", frame, prices(), found))

    def test_failed_reversal_rr_is_retained_as_rejected_watch_evidence(self):
        frame = prices()
        screen = {"flag": True, "pattern": "hammer", "support_level": 96.0,
                  "resistance_ladder": [{"level": 103.0, "touches": 2}]}
        with patch("scanner_tracker.ta.A.score_ticker", return_value=screen):
            result = scan_ta("TEST.NS", frame, prices())
        reversal = next(item for item in result if item["family"] == "reversal")
        self.assertEqual(reversal["status"], "skipped")
        self.assertEqual(reversal["current"]["watch_reason"], "reward_risk_below_2")
        self.assertEqual(reversal["original_plan"]["evidence"]["pattern"], "hammer")

    def test_pending_observations_do_not_move_the_frozen_plan_or_restart_window(self):
        frame = prices()
        idea = candidate(frame, signal_position=-2)
        original = deepcopy(idea["original_plan"])
        screen = {"flag": True, "pattern": "engulfing", "support_level": 95.0,
                  "resistance_ladder": [{"level": 140.0}]}
        with patch("scanner_tracker.ta.A.score_ticker", return_value=screen):
            result = scan_ta("TEST.NS", frame, prices(), [idea])
        current = find(result)
        self.assertEqual(current["original_plan"], original)
        self.assertEqual(current["current"]["confirmation_sessions"], 1)
        self.assertEqual(current["current"]["observations"], 2)
        self.assertEqual(len([item for item in result if item["family"] == "reversal"]), 1)

    def test_time_stop_counts_sessions_after_fill_and_terminal_records_are_immutable(self):
        frame, benchmark = prices(530), prices(530)
        idea = candidate(frame, signal_position=-18)
        row(frame, -17, 100.0, 103.0, 99.0, 102.0)
        row(frame, -16, 101.0, 103.0, 99.0, 102.0)
        result = find(scan_ta("TEST.NS", frame, benchmark, [idea]))
        self.assertEqual(result["status"], "closed")
        self.assertEqual(result["model_trade"]["bars_after_entry"], 15)
        self.assertEqual(result["model_trade"]["exit_reason"], "time_exit")
        self.assertEqual(result, find(scan_ta("TEST.NS", frame, benchmark, [result])))


if __name__ == "__main__":
    unittest.main()
