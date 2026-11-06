import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import numpy as np
from corporate_action_audit import load_and_apply_action_quarantine
from portfolio_rules import prepare, run_rules, simulate

class TestActionQuarantine(unittest.TestCase):
    def test_resets_lookback(self):
        idx=pd.bdate_range("2024-01-01",periods=300)
        frame=pd.DataFrame({"Close":range(300)},index=idx)
        data=pd.DataFrame([{"symbol":"AAA","ex_date":idx[270],"type":"demerger"}])
        with tempfile.TemporaryDirectory() as tmp:
            with patch("huggingface_hub.hf_hub_download",return_value=str(Path(tmp)/"actions.parquet")):
                empty = pd.DataFrame(columns=["symbol","ex_date","type"])
                with patch("pandas.read_parquet",side_effect=[data,empty]):
                    out,audit,quarantine=load_and_apply_action_quarantine({"AAA.NS":frame},idx[0],idx[-1],tmp,"fixture")
        self.assertEqual(len(out["AAA.NS"]),300)
        self.assertEqual(out["AAA.NS"].attrs["unsupported_action_dates"], [idx[270].date().isoformat()])
        self.assertEqual(frame.attrs, {}, "audit must not mutate caller history metadata")
        self.assertFalse(bool(quarantine.iloc[0]["eligible_after_253_sessions"]))
        self.assertEqual(len(audit),1)

    def _world(self, length=800):
        idx = pd.bdate_range("2018-01-01", periods=length)
        close = np.linspace(100.0, 300.0, length)
        frame = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                              "Close": close, "Volume": 10000.0, "Turnover": close * 10000.0}, index=idx)
        bench = pd.DataFrame({"Close": np.linspace(100.0, 150.0, length)}, index=idx)
        membership = pd.DataFrame([{"symbol": "AAA", "valid_from": idx[0], "valid_to": pd.NaT,
                                    "source": "fixture", "source_url": "fixture", "notes": ""}])
        return idx, frame, bench, membership

    def test_future_action_never_removes_earlier_history_or_changes_earlier_eligibility(self):
        idx, frame, bench, membership = self._world()
        baseline = prepare({"AAA.NS": frame}, bench, membership_df=membership)
        frame.attrs["unsupported_action_dates"] = [idx[500].date().isoformat()]
        with_action = prepare({"AAA.NS": frame}, bench, membership_df=membership)
        np.testing.assert_equal(baseline["C_raw"], with_action["C_raw"])
        np.testing.assert_equal(baseline["rank"][:500], with_action["rank"][:500])
        np.testing.assert_equal(baseline["univ"][:500], with_action["univ"][:500])
        prefix = prepare({"AAA.NS": frame.iloc[:500]}, bench.iloc[:500], membership_df=membership)
        np.testing.assert_equal(prefix["rank"], with_action["rank"][:500])
        self.assertTrue(np.isnan(with_action["rank"][500, 0]))
        self.assertTrue(np.isnan(with_action["rank"][751, 0]))
        self.assertTrue(np.isfinite(with_action["rank"][752, 0]))

    def test_latest_known_action_restarts_the_window_without_changing_earlier_eligibility(self):
        idx, frame, bench, membership = self._world(1000)
        frame.attrs["unsupported_action_dates"] = [idx[400].date().isoformat()]
        first = prepare({"AAA.NS": frame}, bench, membership_df=membership)
        frame.attrs["unsupported_action_dates"].append(idx[700].date().isoformat())
        second = prepare({"AAA.NS": frame}, bench, membership_df=membership)
        np.testing.assert_equal(first["rank"][:700], second["rank"][:700])
        self.assertTrue(np.isfinite(second["rank"][699, 0]))
        self.assertTrue(np.isnan(second["rank"][700, 0]))
        self.assertTrue(np.isnan(second["rank"][951, 0]))
        self.assertTrue(np.isfinite(second["rank"][952, 0]))

    def test_missing_post_action_bar_requires_a_new_consecutive_observed_window(self):
        idx, frame, bench, membership = self._world(900)
        frame.attrs["unsupported_action_dates"] = [idx[400].date().isoformat()]
        frame = frame.drop(idx[500])
        prepared = prepare({"AAA.NS": frame}, bench, membership_df=membership)
        self.assertTrue(np.isnan(prepared["rank"][752, 0]))
        self.assertTrue(np.isfinite(prepared["rank"][753, 0]))

    def test_unsupported_action_while_held_fails_closed_at_event_not_before(self):
        idx, frame, bench, membership = self._world()
        frame.attrs["unsupported_action_dates"] = [idx[500].date().isoformat()]
        prefix = prepare({"AAA.NS": frame.iloc[:500]}, bench.iloc[:500], membership_df=membership)
        ordinary = simulate(prefix, {252}, size=1, regime="off", cost_pct=0)
        self.assertTrue(np.isfinite(ordinary["equity"][499]))
        prepared = prepare({"AAA.NS": frame}, bench, membership_df=membership)
        with self.assertRaisesRegex(RuntimeError, "held position.*AAA.NS.*valuation and execution quarantined"):
            simulate(prepared, {252}, size=1, regime="off", cost_pct=0)

    def test_signal_before_action_cannot_fill_on_the_unsupported_action_session(self):
        idx, frame, bench, membership = self._world()
        frame.attrs["unsupported_action_dates"] = [idx[500].date().isoformat()]
        prepared = prepare({"AAA.NS": frame}, bench, membership_df=membership)
        result = simulate(prepared, {499}, size=1, regime="off", cost_pct=0)
        self.assertTrue(np.all(result["equity"][500:] == 1.0))
        self.assertEqual(result["action_blocked_entries"], [{"symbol": "AAA.NS",
            "session": idx[500].date().isoformat(), "reason": "unsupported_corporate_action_on_execution_session"}])

    def test_equal_weight_control_cannot_silently_drop_an_affected_constituent(self):
        idx, frame, bench, membership = self._world()
        # The action precedes the first eligible monthly rebalance; strategies
        # still hold cash, but yesterday's equal-weight control owns the stock.
        frame.attrs["unsupported_action_dates"] = [idx[254].date().isoformat()]
        with self.assertRaisesRegex(RuntimeError, "equal-weight control exposure.*AAA.NS"):
            run_rules({"AAA.NS": frame}, bench, membership_df=membership)


if __name__=="__main__": unittest.main()
