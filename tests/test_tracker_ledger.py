"""Accounting regressions: caller state stays immutable and every event is auditable."""
from copy import deepcopy
from decimal import Decimal
import json
import unittest

from scanner_tracker.ledger import (
    configure_opening_positions, correct_fill, import_fills_csv, new_ledger,
    ledger_as_of, record_cash_event, record_corporate_action, record_fill,
)


def fill(identifier="buy", **changes):
    return {"execution_id": identifier, "mode": "TA", "executed_at": "2026-11-02",
            "symbol": "ABC.NS", "side": "BUY", "quantity": 10, "price_inr": "100.10", "fees_inr": "1.50", **changes}


class LedgerTests(unittest.TestCase):
    def test_fill_cost_basis_cash_pnl_and_input_immutability(self):
        original = new_ledger("TA", "10000")
        bought = record_fill(original, fill())
        self.assertEqual(original["holdings"], {})
        self.assertEqual(bought["cash_balance_inr"], "8997.50")
        self.assertEqual(bought["holdings"]["ABC.NS"]["average_cost_inr"], "100.25000000")
        sold = record_fill(bought, fill("sell", side="SELL", quantity=4, price_inr="110", fees_inr="2", executed_at="2026-11-03"))
        self.assertEqual(sold["cash_balance_inr"], "9435.50")
        self.assertEqual(sold["realized_pnl_inr"], "37.00")
        self.assertEqual(sold["holdings"]["ABC.NS"]["cost_basis_inr"], "601.50")
        json.dumps(sold, allow_nan=False)

    def test_identical_ids_are_idempotent_different_payload_conflicts(self):
        state = record_fill(new_ledger("TA", 2000), fill())
        self.assertEqual(record_fill(state, fill(price_inr=Decimal("100.100"))), state)
        with self.assertRaisesRegex(ValueError, "different payload"):
            record_fill(state, fill(quantity=9))

    def test_validation_and_failure_do_not_mutate(self):
        state = new_ledger("TA", 100)
        for changes in ({"quantity": 0}, {"quantity": 1.5}, {"quantity": True}, {"price_inr": "NaN"}, {"fees_inr": -1}, {"mode": "MOMENTUM"}, {"executed_at": "yesterday"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                record_fill(state, fill(**changes))
        with self.assertRaisesRegex(ValueError, "insufficient cash"):
            record_fill(state, fill())
        with self.assertRaisesRegex(ValueError, "oversell"):
            record_fill(state, fill(side="SELL"))
        self.assertEqual(state, new_ledger("TA", 100))

    def test_cash_events_and_mode_budgets_stay_separate(self):
        ta, momentum = new_ledger("TA"), new_ledger("MOMENTUM", 500)
        ta = record_cash_event(ta, {"event_id": "deposit", "executed_at": "2026-11-01", "cash_type": "DEPOSIT", "amount_inr": "100.50"})
        ta = record_cash_event(ta, {"event_id": "dividend", "executed_at": "2026-11-02", "cash_type": "DIVIDEND", "symbol": "ABC.NS", "amount_inr": "3.50"})
        self.assertEqual(ta["cash_balance_inr"], "104.00")
        with self.assertRaisesRegex(ValueError, "overdraw"):
            record_cash_event(ta, {"event_id": "withdraw", "executed_at": "2026-11-03", "cash_type": "WITHDRAWAL", "amount_inr": 105})
        self.assertEqual(momentum["cash_balance_inr"], "500.00")

    def test_unknown_opening_cost_is_never_fabricated(self):
        state = configure_opening_positions(new_ledger("TA", 10), [{"symbol": "ABC.NS", "quantity": 10}])
        state = record_fill(state, fill("sell", side="SELL", quantity=4))
        self.assertIsNone(state["holdings"]["ABC.NS"]["average_cost_inr"])
        self.assertIsNone(state["realized_pnl_inr"])
        self.assertEqual(state["unknown_cost_sales"], 1)

    def test_correction_preserves_audit_and_rebuilds_later_sales(self):
        state = record_fill(new_ledger("TA", 10000), fill())
        state = record_fill(state, fill("sell", side="SELL", quantity=2, price_inr=120, executed_at="2026-11-03"))
        prior = deepcopy(state)
        corrected = correct_fill(state, "buy", "correction-1", fill("replacement", price_inr=90), "2026-11-04")
        self.assertEqual(state, prior)
        self.assertEqual(len(corrected["events"]), 3)
        self.assertEqual(corrected["events"][0], state["events"][0])
        self.assertEqual(corrected["execution_history"][0]["execution_id"], "replacement")
        self.assertGreater(Decimal(corrected["realized_pnl_inr"]), Decimal(state["realized_pnl_inr"]))
        self.assertEqual(correct_fill(corrected, "buy", "correction-1", fill("replacement", price_inr=90), "2026-11-04"), corrected)
        with self.assertRaisesRegex(ValueError, "oversell"):
            correct_fill(state, "buy", "bad-reversal")

    def test_backdated_events_replay_in_chronological_order(self):
        state = record_cash_event(new_ledger("TA"), {"event_id": "future", "executed_at": "2026-11-03", "cash_type": "DEPOSIT", "amount_inr": 2000})
        with self.assertRaisesRegex(ValueError, "insufficient cash"):
            record_fill(state, fill(executed_at="2026-11-02"))

    def test_confirmed_split_preserves_basis_and_is_idempotent(self):
        state = record_fill(new_ledger("TA", 2000), fill())
        action = {"event_id": "split", "executed_at": "2026-11-03", "symbol": "ABC.NS", "ratio": "2", "action_type": "SPLIT"}
        split = record_corporate_action(state, action)
        self.assertEqual(split["holdings"]["ABC.NS"]["quantity"], 20)
        self.assertEqual(split["holdings"]["ABC.NS"]["cost_basis_inr"], state["holdings"]["ABC.NS"]["cost_basis_inr"])
        self.assertEqual(split["holdings"]["ABC.NS"]["average_cost_inr"], "50.12500000")
        self.assertEqual(record_corporate_action(split, action), split)
        with self.assertRaisesRegex(ValueError, "different payload"):
            record_corporate_action(split, {**action, "ratio": "3"})
        with self.assertRaisesRegex(ValueError, "fractional"):
            record_corporate_action(state, {**action, "ratio": "0.33"})

    def test_csv_preview_atomic_commit_duplicate_and_conflict(self):
        state = new_ledger("TA", 2000)
        header = "execution_id,mode,executed_at,symbol,side,quantity,price_inr,fees_inr,signal_id\n"
        valid = header + "buy,TA,2026-11-02,ABC.NS,BUY,10,100,1,signal-1\n"
        preview = import_fills_csv(state, valid)
        self.assertTrue(preview["valid"])
        self.assertFalse(preview["committed"])
        self.assertEqual(state["holdings"], {})
        committed = import_fills_csv(state, valid, commit=True)
        self.assertEqual(preview["state"], committed["state"])
        self.assertTrue(committed["committed"])
        self.assertEqual(import_fills_csv(committed["state"], valid, commit=True)["state"], committed["state"])
        bad = valid + "sell,TA,2026-11-03,ABC.NS,SELL,11,110,0,\n"
        result = import_fills_csv(state, bad, commit=True)
        self.assertFalse(result["valid"])
        self.assertFalse(result["committed"])
        self.assertEqual(result["state"], state)
        conflict = import_fills_csv(committed["state"], valid.replace(",10,100,", ",9,100,"), commit=True)
        self.assertFalse(conflict["valid"])

    def test_csv_descending_tradebook_is_replayed_by_execution_time(self):
        text = "execution_id,mode,executed_at,symbol,side,quantity,price_inr,fees_inr\n" + (
            "sell,TA,2026-11-03,ABC.NS,SELL,10,110,1\n"
            "buy,TA,2026-11-02,ABC.NS,BUY,10,100,1\n"
        )
        result = import_fills_csv(new_ledger("TA", 1001), text, commit=True)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["state"]["cash_balance_inr"], "1099.00")
        self.assertEqual(result["state"]["realized_pnl_inr"], "98.00")

    def test_malformed_csv_returns_errors_without_partial_state(self):
        state = new_ledger("TA", 2000)
        text = "execution_id,mode,executed_at,symbol,side,quantity,price_inr,fees_inr\n\"unclosed"
        result = import_fills_csv(state, text, commit=True)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], state)

    def test_fills_cannot_spend_future_opening_cash(self):
        state = new_ledger("TA", 2000)
        state["opening_as_of"] = "2026-11-03"
        saved = deepcopy(state)
        with self.assertRaisesRegex(ValueError, "precedes opening_as_of"):
            record_fill(state, fill(executed_at="2026-11-02"))
        self.assertEqual(state, saved)
        boundary = record_fill(state, fill(executed_at="2026-11-03"))
        self.assertEqual(boundary["cash_balance_inr"], "997.50")

    def test_all_cash_events_before_opening_are_rejected(self):
        state = new_ledger("TA", 2000)
        state["opening_as_of"] = "2026-11-03"
        saved = deepcopy(state)
        for kind in ("DEPOSIT", "WITHDRAWAL", "DIVIDEND"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "precedes opening_as_of"):
                record_cash_event(state, {"event_id": kind, "cash_type": kind, "amount_inr": 100,
                                          "executed_at": "2026-11-02"})
        self.assertEqual(state, saved)

    def test_preopening_corporate_actions_and_replacement_fills_are_rejected(self):
        state = configure_opening_positions(new_ledger("TA", 2000),
            [{"symbol": "ABC.NS", "quantity": 10, "average_cost_inr": 100}], "2026-11-03")
        with self.assertRaisesRegex(ValueError, "precedes opening_as_of"):
            record_corporate_action(state, {"event_id": "early-split", "executed_at": "2026-11-02",
                                          "symbol": "ABC.NS", "ratio": 2})
        bought = record_fill(state, fill(executed_at="2026-11-04"))
        saved = deepcopy(bought)
        with self.assertRaisesRegex(ValueError, "precedes opening_as_of"):
            correct_fill(bought, "buy", "bad-date", fill("replacement", executed_at="2026-11-02"), "2026-11-05")
        self.assertEqual(bought, saved)

    def test_rebuild_rejects_inconsistent_explicit_opening_date_but_legacy_is_flagged(self):
        state = record_fill(new_ledger("TA", 2000), fill(executed_at="2026-11-02"))
        self.assertFalse(ledger_as_of(state, "2026-11-02")["opening_date_known"])
        invalid = deepcopy(state)
        invalid["opening_as_of"] = "2026-11-03"
        with self.assertRaisesRegex(ValueError, "precedes opening_as_of"):
            ledger_as_of(invalid, "2026-11-04")
        with self.assertRaisesRegex(ValueError, "precedes opening_as_of"):
            record_fill(invalid, fill(executed_at="2026-11-02"))

    def test_csv_with_preopening_fill_cannot_partially_commit(self):
        state = new_ledger("TA", 2000)
        state["opening_as_of"] = "2026-11-03"
        content = "execution_id,mode,executed_at,symbol,side,quantity,price_inr,fees_inr\n" + (
            "too-early,TA,2026-11-02,ABC.NS,BUY,1,100,0\n"
            "valid-date,TA,2026-11-03,ABC.NS,BUY,1,100,0\n"
        )
        result = import_fills_csv(state, content, commit=True)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], state)


if __name__ == "__main__":
    unittest.main()
