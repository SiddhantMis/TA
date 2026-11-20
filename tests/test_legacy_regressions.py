"""Previously observed failures in freshness, notifications and empty reports."""
from datetime import datetime, time
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

import pandas as pd

from alerts import build_alert_content, DISCORD_CONTENT_LIMIT
from backtest import report
from main import check_stale_after_cutoff


class LegacyRegressionTests(unittest.TestCase):
    def test_current_row_cannot_hide_a_stale_flag_candidate(self):
        rows = [{"ticker": "FRESH.NS", "date": "2026-11-06"},
                {"ticker": "STALE.NS", "date": "2026-10-20", "flag": True}]
        run = datetime(2026, 11, 6, 20, tzinfo=ZoneInfo("Asia/Kolkata"))
        failure = check_stale_after_cutoff(run, rows, time(19), "2026-11-06")
        self.assertIn("STALE.NS=2026-10-20", failure)
        self.assertIn("2026-11-06", failure)

    def test_weekend_uses_last_completed_exchange_session_not_calendar_today(self):
        run = datetime(2026, 11, 8, 20, tzinfo=ZoneInfo("Asia/Kolkata"))
        rows = [{"ticker": "TEST.NS", "date": "2026-11-06"}]
        self.assertIsNone(check_stale_after_cutoff(run, rows, time(19), "2026-11-06"))

    def test_explicit_session_is_checked_before_cutoff_and_bad_dates_fail_closed(self):
        run = datetime(2026, 11, 6, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
        rows = [{"ticker": "OLD.NS", "date": "2026-11-04"}, {"ticker": "BAD.NS", "date": None}]
        failure = check_stale_after_cutoff(run, rows, time(19), "2026-11-05")
        self.assertIn("OLD.NS", failure)
        self.assertIn("BAD.NS=missing date", failure)

    def test_wide_board_and_warnings_cannot_make_flagged_alert_exceed_limit(self):
        flag = {"ticker": "FLAG.NS", "close": 100, "pattern": "hammer", "trend": "downtrend",
                "volume_ratio": 1.1, "support_level": 96, "support_touches": 3,
                "checks_passed": 4, "checks_total": 5, "confidence": 80,
                "recommendation": "Worth a manual look"}
        plan = {"fired": ["breakout55"], "stop_if_filled_at_ref": 410.0,
                "risk_pct": 6.1, "shares_per_1000_risk": 16,
                "triggers": {"breakout55_close_above": 480.0}}
        leaders = [{"leader_rank": i, "ticker": f"LONGTICKER{i}.NS",
                    "relative_strength_12_1_pct": 80.0-i, "relative_strength_6m_pct": 20.0,
                    "pct_below_52w_high": 3.2, "plan": plan,
                    "structure": {"support_level": 410.0, "support_touches": 3,
                                  "resistance_ladder": [{"level": 470.0}]}} for i in range(1, 21)]
        wide = {"counts": {"liquid": 200, "above_200dma": 80}, "leaders": leaders,
                "setup_record": "x" * 230, "scorecard_text": "y" * 200}
        text = build_alert_content([flag], "(last COMPLETE session as of 2026-11-06 19:00 IST)",
            wide_leaders=wide, watch=[{"ticker": f"WATCH{i}.NS", "rr": 0.1} for i in range(10)],
            breadth=0.1, scan_coverage={"scored": 30, "requested": 48,
            "missing_tickers": [f"MISSING{i}.NS" for i in range(18)]})
        self.assertLessEqual(len(text), DISCORD_CONTENT_LIMIT)
        self.assertIn("truncated", text)
        self.assertIn("sections 7-9", text)
        giant = build_alert_content([flag], "x" * 10000,
            watch=[{"ticker": "y" * 10000, "rr": 0.1}])
        self.assertLessEqual(len(giant), DISCORD_CONTENT_LIMIT)
        self.assertIn("sections 7-9", giant)

    def test_report_handles_empty_dataframe_without_a_ticker_column(self):
        args = SimpleNamespace(years=5, max_hold=15, trigger_days=3, cost_pct=0.25)
        text = report(pd.DataFrame(), args)
        self.assertIn("0 tickers", text)
        self.assertIn("No flags in the period", text)
        self.assertIn("0.25% round trip", text)


if __name__ == "__main__":
    unittest.main()
