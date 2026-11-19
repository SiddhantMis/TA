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

    def test_unsupported_action_while_held_exits_at_prior_close_after_cost_and_holds_cash(self):
        idx, frame, bench, membership = self._world()
        frame.attrs["unsupported_action_dates"] = [idx[500].date().isoformat()]
        prepared = prepare({"AAA.NS": frame}, bench, membership_df=membership)
        result = simulate(prepared, {252, 550}, size=1, regime="off", cost_pct=0.30)

        self.assertTrue(np.isfinite(result["equity"][499]))
        self.assertEqual(result["forced_exit_count"], 1)
        event = result["forced_exit_events"][0]
        prior_close = float(prepared["C_raw"][499, 0])
        expected_cost = float(result["equity"][499]) * (0.30 / 200.0)
        self.assertEqual(event["symbol"], "AAA.NS")
        self.assertEqual(event["session"], idx[500].date().isoformat())
        self.assertEqual(event["prior_close_session"], idx[499].date().isoformat())
        self.assertAlmostEqual(event["prior_close_used"], prior_close)
        self.assertAlmostEqual(event["cost"], expected_cost, places=10)
        self.assertEqual(event["reason"], "unsupported_corporate_action")
        self.assertAlmostEqual(result["equity"][500], result["equity"][499] - expected_cost, places=10)
        # The next rebalance is at index 551; the quarantined symbol is still ineligible,
        # so the position remains cash rather than being silently re-entered.
        self.assertAlmostEqual(result["equity"][551], result["equity"][500], places=10)
        np.testing.assert_allclose(result["equity"][500:], result["equity"][500], rtol=0, atol=1e-10)

    def test_signal_before_action_cannot_fill_on_the_unsupported_action_session(self):
        idx, frame, bench, membership = self._world()
        frame.attrs["unsupported_action_dates"] = [idx[500].date().isoformat()]
        prepared = prepare({"AAA.NS": frame}, bench, membership_df=membership)
        result = simulate(prepared, {499}, size=1, regime="off", cost_pct=0)
        self.assertTrue(np.all(result["equity"][500:] == 1.0))
        self.assertEqual(result["action_blocked_entries"], [{"symbol": "AAA.NS",
            "session": idx[500].date().isoformat(), "reason": "unsupported_corporate_action_on_execution_session"}])

    def test_equal_weight_control_exits_at_prior_close_cost_without_reweighting_survivors(self):
        idx, frame, bench, _ = self._world()
        frame.attrs["unsupported_action_dates"] = [idx[254].date().isoformat()]
        other = frame.copy()
        other.attrs = {}
        factor = np.ones(len(idx))
        factor[254:] = 1.10
        for column in ("Open", "High", "Low", "Close"):
            other[column] = other[column].to_numpy() * factor
        membership = pd.DataFrame([
            {"symbol": symbol, "valid_from": idx[0], "valid_to": pd.NaT,
             "source": "fixture", "source_url": "fixture", "notes": ""}
            for symbol in ("AAA", "BBB")
        ])

        series, report = run_rules(
            {"AAA.NS": frame, "BBB.NS": other}, bench, cost_pct=0.30,
            membership_df=membership,
        )
        side = 0.30 / 200.0
        survivor_return = float(other["Close"].iloc[254] / other["Close"].iloc[253] - 1.0)
        expected_event_return = (survivor_return - side) / 2.0
        self.assertAlmostEqual(series["EW_universe_daily"][254], 1.0 + expected_event_return, places=10)
        self.assertIn("Equal-weight control forced-exit events: 1", report)
        self.assertIn(f"AAA.NS {idx[254].date().isoformat()}", report)
        self.assertIn(f"prior close {float(frame['Close'].iloc[253]):.6f}", report)
        self.assertIn(f"cost {side / 2.0:.8f}", report)
        self.assertIn("reason=unsupported_corporate_action", report)


if __name__=="__main__": unittest.main()
