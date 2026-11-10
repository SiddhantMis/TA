"""Pure, JSON-safe INR ledgers. Callers own authorization and atomic persistence.

Money is stored as decimal strings. Events are never removed: a correction records
an explicit reversal and optional replacement and rebuilds the effective ledger.
"""
from __future__ import annotations

from copy import deepcopy
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import re

CENT = Decimal("0.01")
ZERO = Decimal("0")
MODES = {"TA", "MOMENTUM"}
CSV_COLUMNS = (
    "execution_id", "mode", "executed_at", "symbol", "side", "quantity",
    "price_inr", "fees_inr",
)


def decimal(value, field="amount", *, positive=False):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        raise ValueError(f"{field} must be {'positive' if positive else 'non-negative'} and finite")
    return result


def money(value):
    return format(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP), "f")


def _quantity(value):
    result = decimal(value, "quantity", positive=True)
    if result != result.to_integral_value():
        raise ValueError("quantity must be a positive integer")
    return int(result)


def _mode(value):
    mode = str(value).strip().upper()
    if mode not in MODES:
        raise ValueError("mode must be TA or MOMENTUM")
    return mode


def _symbol(value):
    symbol = str(value or "").strip().upper()
    if not symbol or not re.fullmatch(r"[A-Z0-9&.^_-]+", symbol):
        raise ValueError("symbol is required and must be an exchange symbol")
    return symbol


def _timestamp(value):
    value = str(value or "").strip()
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if "T" not in value:
            raise ValueError("datetime requires T separator")
        return parsed.isoformat()
    except ValueError as exc:
        raise ValueError("executed_at must be an ISO date or datetime") from exc


def _time_key(value):
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _identifier(value, field):
    result = str(value or "").strip()
    if not result or len(result) > 200:
        raise ValueError(f"{field} is required (maximum 200 characters)")
    return result


def _opening_date(state):
    value = state.get("opening_as_of")
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ValueError("opening_as_of must be an ISO calendar date") from exc


def new_ledger(mode, opening_cash=0, kind="actual"):
    mode = _mode(mode)
    if kind not in {"actual", "paper", "model"}:
        raise ValueError("kind must be actual, paper or model")
    cash = money(decimal(opening_cash, "opening_cash"))
    return {
        "schema_version": 1, "mode": mode, "kind": kind,
        "opening_cash_inr": cash, "cash_balance_inr": cash,
        "opening_positions": {}, "holdings": {}, "events": [],
        "execution_history": [], "known_realized_pnl_inr": "0.00",
        "realized_pnl_inr": "0.00", "unknown_cost_sales": 0,
    }


def _check_state(state):
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError("unsupported ledger schema")
    _mode(state.get("mode"))
    if not isinstance(state.get("events"), list) or not isinstance(state.get("opening_positions"), dict):
        raise ValueError("invalid ledger event or opening-position collection")
    if state.get("read_only_projection"):
        raise ValueError("historical ledger projections cannot accept business events")
    decimal(state.get("opening_cash_inr"), "opening cash")
    _opening_date(state)


def _fill(fill, mode):
    if not isinstance(fill, dict):
        raise ValueError("fill must be an object")
    if _mode(fill.get("mode", mode)) != mode:
        raise ValueError("fill mode does not match this ledger")
    side = str(fill.get("side", "")).strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    return {
        "event_type": "FILL",
        "execution_id": _identifier(fill.get("execution_id"), "execution_id"),
        "mode": mode, "executed_at": _timestamp(fill.get("executed_at")),
        "symbol": _symbol(fill.get("symbol")), "side": side,
        "quantity": _quantity(fill.get("quantity")),
        "price_inr": format(decimal(fill.get("price_inr"), "price_inr", positive=True).normalize(), "f"),
        "fees_inr": money(decimal(fill.get("fees_inr", 0), "fees_inr")),
        "signal_id": str(fill["signal_id"]).strip() if fill.get("signal_id") else None,
    }


def _event_id(event):
    return event.get("execution_id") if event.get("event_type") == "FILL" else event.get("event_id")


def _all_ids(state):
    result = {}
    for event in state["events"]:
        result[_event_id(event)] = event
        if event.get("replacement"):
            result[event["replacement"]["execution_id"]] = event["replacement"]
    return result


def _append(state, event):
    _check_state(state)
    existing = _all_ids(state).get(_event_id(event))
    if existing is not None:
        if existing != event:
            raise ValueError("event ID already exists with a different payload")
        return _rebuild(deepcopy(state))
    result = deepcopy(state)
    result["events"].append(event)
    return _rebuild(result)


def _effective_events(state):
    corrections = {e["reverses_execution_id"]: e for e in state["events"] if e["event_type"] == "REVERSAL"}
    effective = []
    for ordinal, event in enumerate(state["events"]):
        if event["event_type"] == "REVERSAL":
            continue
        while event is not None and event.get("execution_id") in corrections:
            event = corrections[event["execution_id"]].get("replacement")
        if event is not None:
            effective.append((ordinal, event))
    effective.sort(key=lambda item: (_time_key(item[1]["executed_at"]), item[1]["event_type"] != "CORPORATE_ACTION", item[0]))
    return effective


def _rebuild(state):
    cash = decimal(state["opening_cash_inr"])
    positions = deepcopy(state["opening_positions"])
    effective = _effective_events(state)
    opening_date = _opening_date(state)
    known_realized, unknown_sales, executions = ZERO, 0, []
    for _, event in effective:
        if opening_date and event["executed_at"][:10] < opening_date:
            raise ValueError("effective event executed_at precedes opening_as_of; opening balances are unavailable before that date")
        if event["event_type"] == "CORPORATE_ACTION":
            symbol = event["symbol"]
            position = positions.get(symbol)
            if position is None:
                raise ValueError(f"no holding exists for corporate action on {symbol}")
            adjusted_quantity = position["quantity"] * decimal(event["ratio"], "ratio", positive=True)
            if adjusted_quantity != adjusted_quantity.to_integral_value():
                raise ValueError("fractional corporate-action entitlement requires cash/quantity reconciliation")
            position["quantity"] = int(adjusted_quantity)
            basis = position["cost_basis_inr"]
            position["average_cost_inr"] = format((Decimal(basis) / position["quantity"]).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP), "f") if basis is not None else None
            continue
        if event["event_type"] == "CASH":
            amount = decimal(event["amount_inr"])
            cash += -amount if event["cash_type"] == "WITHDRAWAL" else amount
            if cash < 0:
                raise ValueError("cash event would overdraw the ledger")
            continue
        symbol, quantity = event["symbol"], event["quantity"]
        price, fees = decimal(event["price_inr"]), decimal(event["fees_inr"])
        gross = Decimal(money(price * quantity))
        if gross <= 0:
            raise ValueError("fill gross value must be at least one paisa")
        position = positions.get(symbol)
        old_quantity = position["quantity"] if position else 0
        old_basis = Decimal(position["cost_basis_inr"]) if position and position["cost_basis_inr"] is not None else (ZERO if not position else None)
        realized = ZERO
        if event["side"] == "BUY":
            cost = gross + fees
            if cost > cash:
                raise ValueError(f"insufficient cash for {symbol}")
            cash -= cost
            basis = old_basis + cost if old_basis is not None else None
            quantity_after = old_quantity + quantity
        else:
            if old_quantity < quantity:
                raise ValueError(f"cannot oversell {symbol}")
            cash += gross - fees
            if cash < 0:
                raise ValueError("sale fees would overdraw the ledger")
            allocated_basis = Decimal(money(old_basis * quantity / old_quantity)) if old_basis is not None else None
            realized = gross - fees - allocated_basis if allocated_basis is not None else None
            basis = old_basis - allocated_basis if old_basis is not None else None
            quantity_after = old_quantity - quantity
            if realized is None:
                unknown_sales += 1
            else:
                known_realized += realized
        if quantity_after:
            positions[symbol] = {
                "symbol": symbol, "quantity": quantity_after,
                "cost_basis_inr": money(basis) if basis is not None else None,
                "average_cost_inr": format((basis / quantity_after).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP), "f") if basis is not None else None,
            }
        else:
            positions.pop(symbol, None)
        executions.append({**event, "realized_pnl_inr": money(realized) if realized is not None else None})
    state.update({
        "cash_balance_inr": money(cash), "holdings": positions,
        "execution_history": executions, "known_realized_pnl_inr": money(known_realized),
        "realized_pnl_inr": None if unknown_sales else money(known_realized),
        "unknown_cost_sales": unknown_sales,
    })
    return state


def ledger_as_of(state, as_of):
    """Read-only corrected economic history through an inclusive calendar date.

    Corrections restate the original effective execution rather than treating a
    later correction-recording timestamp as a real cash movement. The complete
    audit remains in the source ledger, which is never mutated by projection.
    """
    _check_state(state)
    cutoff = date.fromisoformat(str(as_of)[:10]).isoformat()
    result = deepcopy(state)
    opening = state.get("opening_as_of")
    if opening and cutoff < str(opening)[:10]:
        result.update(opening_cash_inr="0.00", opening_positions={}, events=[])
        _rebuild(result)
        result["projection_status"] = "BEFORE_OPENING"
    else:
        result["events"] = [deepcopy(event) for _, event in _effective_events(state)
                            if event["executed_at"][:10] <= cutoff]
        _rebuild(result)
        result["projection_status"] = "COMPLETE"
    result.update(read_only_projection=True, projected_as_of=cutoff,
                  projection_basis="corrected economic execution dates; inclusive end-of-day",
                  opening_date_known=bool(opening))
    return result


def record_fill(state, fill):
    """Return a new ledger; replaying an identical execution ID is a no-op."""
    _check_state(state)
    return _append(state, _fill(fill, state["mode"]))


def record_cash_event(state, event):
    """Record a deposit, withdrawal or dividend without inventing a stock fill."""
    _check_state(state)
    if _mode(event.get("mode", state["mode"])) != state["mode"]:
        raise ValueError("cash-event mode does not match this ledger")
    cash_type = str(event.get("cash_type", event.get("type", ""))).upper()
    if cash_type not in {"DEPOSIT", "WITHDRAWAL", "DIVIDEND"}:
        raise ValueError("cash_type must be DEPOSIT, WITHDRAWAL or DIVIDEND")
    normalized = {
        "event_type": "CASH", "event_id": _identifier(event.get("event_id"), "event_id"),
        "mode": state["mode"], "executed_at": _timestamp(event.get("executed_at")),
        "cash_type": cash_type, "amount_inr": money(decimal(event.get("amount_inr"), "amount_inr", positive=True)),
        "symbol": _symbol(event["symbol"]) if event.get("symbol") else None,
    }
    if Decimal(normalized["amount_inr"]) <= 0:
        raise ValueError("cash amount must be at least one paisa")
    return _append(state, normalized)


def record_corporate_action(state, event):
    """Apply a confirmed split/bonus share multiplier, conserving total cost basis.

    ``ratio`` is new shares / old shares (2 for a 2-for-1 split or 1:1 bonus).
    Fractional entitlements require explicit reconciliation rather than rounding.
    """
    _check_state(state)
    if _mode(event.get("mode", state["mode"])) != state["mode"]:
        raise ValueError("corporate-action mode does not match this ledger")
    action_type = str(event.get("action_type", "SPLIT")).upper()
    if action_type not in {"SPLIT", "BONUS"}:
        raise ValueError("only confirmed SPLIT and BONUS adjustments are supported")
    normalized = {
        "event_type": "CORPORATE_ACTION", "event_id": _identifier(event.get("event_id"), "event_id"),
        "mode": state["mode"], "executed_at": _timestamp(event.get("executed_at")),
        "symbol": _symbol(event.get("symbol")), "action_type": action_type,
        "ratio": format(decimal(event.get("ratio"), "ratio", positive=True).normalize(), "f"),
    }
    return _append(state, normalized)


def configure_opening_positions(state, positions, as_of=None):
    """Set reconciled opening positions once; omitted cost basis stays unknown.

    Opening cash is the cash beside these positions, not their purchase budget.
    Positions may be a symbol-keyed mapping or a list of position objects.
    """
    _check_state(state)
    if state["events"] or state["opening_positions"]:
        raise ValueError("opening positions can only be configured on an unused ledger")
    result = deepcopy(state)
    source = [{**row, "symbol": symbol} for symbol, row in positions.items()] if isinstance(positions, dict) else positions
    normalized = {}
    for row in source:
        symbol, quantity = _symbol(row.get("symbol")), _quantity(row.get("quantity"))
        if symbol in normalized:
            raise ValueError(f"duplicate opening position {symbol}")
        cost = row.get("average_cost_inr", row.get("average_cost"))
        basis = decimal(row["cost_basis_inr"], "cost_basis_inr") if row.get("cost_basis_inr") is not None else (decimal(cost, "average_cost_inr") * quantity if cost is not None else None)
        normalized[symbol] = {
            "symbol": symbol, "quantity": quantity,
            "cost_basis_inr": money(basis) if basis is not None else None,
            "average_cost_inr": format((basis / quantity).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP), "f") if basis is not None else None,
        }
    result["opening_positions"] = normalized
    result["opening_as_of"] = _timestamp(as_of) if as_of else None
    return _rebuild(result)


def correct_fill(state, execution_id, correction_id, replacement=None, corrected_at=None):
    """Append an explicit reversal/replacement; reject corrections breaking later fills."""
    _check_state(state)
    execution_id = _identifier(execution_id, "execution_id")
    original = _all_ids(state).get(execution_id)
    if original is None or original.get("event_type") != "FILL":
        raise ValueError("original execution does not exist")
    corrected = _fill(replacement, state["mode"]) if replacement is not None else None
    event = {
        "event_type": "REVERSAL", "event_id": _identifier(correction_id, "correction_id"),
        "executed_at": _timestamp(corrected_at or original["executed_at"]),
        "reverses_execution_id": execution_id, "replacement": corrected,
    }
    existing = _all_ids(state).get(event["event_id"])
    if existing is not None:
        if existing != event:
            raise ValueError("correction ID already exists with a different payload")
        return _rebuild(deepcopy(state))
    if any(e.get("reverses_execution_id") == execution_id for e in state["events"]):
        raise ValueError("execution already reversed; correct its replacement instead")
    if corrected is not None and (corrected["execution_id"] in _all_ids(state) or corrected["execution_id"] == event["event_id"]):
        raise ValueError("replacement requires a new execution ID")
    return _append(state, event)


def import_fills_csv(state, text, commit=False):
    """Validate a whole file against a copy; callers persist only a valid result.

    Preview and commit perform the same simulation. No caller-owned object is
    mutated and an invalid file returns the original state, never partial fills.
    """
    _check_state(state)
    reader = csv.DictReader(io.StringIO(str(text).lstrip("\ufeff")), strict=True)
    errors, rows, trial = [], [], deepcopy(state)
    headers = reader.fieldnames or []
    missing = [name for name in CSV_COLUMNS if name not in headers]
    if missing or len(headers) != len(set(headers)):
        return {"state": deepcopy(state), "rows": [], "errors": [{"row": 1, "error": "missing/duplicate CSV columns: " + ", ".join(missing)}], "valid": False, "committed": False}
    try:
        raw_rows = list(reader)
    except csv.Error as exc:
        return {"state": deepcopy(state), "rows": [], "errors": [{"row": reader.line_num, "error": str(exc)}], "valid": False, "committed": False}
    normalized_rows = []
    for line, raw in enumerate(raw_rows, 2):
        try:
            if None in raw:
                raise ValueError("too many CSV fields")
            normalized = _fill(raw, state["mode"])
            normalized_rows.append((line, normalized))
        except (ValueError, TypeError, InvalidOperation) as exc:
            errors.append({"row": line, "error": str(exc)})
    for line, normalized in sorted(normalized_rows, key=lambda row: (_time_key(row[1]["executed_at"]), row[0])):
        try:
            trial = record_fill(trial, normalized)
            rows.append(normalized)
        except (ValueError, TypeError, InvalidOperation) as exc:
            errors.append({"row": line, "error": str(exc)})
    if not rows and not errors:
        errors.append({"row": 2, "error": "CSV has no fills"})
    return {"state": deepcopy(state) if errors else trial, "rows": rows, "errors": errors, "valid": not errors, "committed": bool(commit and not errors)}
