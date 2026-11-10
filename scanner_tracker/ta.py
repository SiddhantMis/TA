"""Closed-session TA observations and a separate, deterministic model-trade journal.

Prices supplied to this module are execution prices, not retrospectively adjusted
closes. The caller supplies the exchange's expected session in ``as_of``. Scanning
never places an order or treats a model fill as an actual account holding.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
import hashlib
import math

import numpy as np
import pandas as pd

import analyzer as A
import research as R


STRATEGY_VERSION = "ta-v1"
COST_PER_SIDE = 0.0015
TERMINAL = {"closed", "expired", "invalidated", "skipped"}
FAMILIES = {"reversal", "breakout55", "pullback20"}


def _finite(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def _json(value):
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, np.generic):
        return _json(value.item())
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is pd.NA or value is pd.NaT:
        return None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Unsupported TA journal value: {type(value).__name__}")


def _session(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("A session must be a valid date")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_localize(None)
    return stamp.normalize()


def _frame(frame, cutoff, benchmark=False):
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["Close"] if benchmark else ["Open", "High", "Low", "Close", "Volume"],
                            index=pd.DatetimeIndex([]))
    result = frame.copy(deep=True)
    result.index = pd.DatetimeIndex([_session(item) for item in result.index])
    result = result.loc[result.index <= cutoff].sort_index()
    if result.index.has_duplicates:
        raise ValueError("TA input has duplicate session rows")
    required = ["Close"] if benchmark else ["Open", "High", "Low", "Close", "Volume"]
    missing = [key for key in required if key not in result]
    if missing:
        raise ValueError(f"TA {'benchmark' if benchmark else 'stock'} input lacks {missing}")
    for key in required:
        result[key] = pd.to_numeric(result[key], errors="coerce")
    return result


def _valid_row(frame, session, benchmark=False):
    if session not in frame.index:
        return False
    row = frame.loc[session]
    close = _finite(row.get("Close"))
    if close is None or close <= 0:
        return False
    if benchmark:
        return True
    values = {key: _finite(row.get(key)) for key in ("Open", "High", "Low", "Volume")}
    if any(value is None for value in values.values()):
        return False
    o, h, low, volume = (values[key] for key in ("Open", "High", "Low", "Volume"))
    return o > 0 and low > 0 and volume >= 0 and h >= max(o, close, low) and low <= min(o, close)


def _event(candidate, kind, session, **details):
    event = _json({"type": kind, "session": str(session), "details": details})
    if event not in candidate["events"]:
        candidate["events"].append(event)


def _pause(candidate, session, reason):
    current = candidate["current"]
    if candidate["status"] != "data_unavailable":
        current["resume_status"] = candidate["status"]
    candidate["status"] = "data_unavailable"
    current["data_status"] = "unavailable"
    current["reason"] = reason
    _event(candidate, "data_unavailable", session, reason=reason)


def _resume(candidate, session):
    if candidate["status"] == "data_unavailable":
        candidate["status"] = candidate["current"].pop("resume_status")
        _event(candidate, "data_resumed", session)
    candidate["current"]["data_status"] = "complete"


def _end(candidate, status, session, reason):
    candidate["status"] = status
    candidate["current"]["reason"] = reason
    _event(candidate, status, session, reason=reason)


def _levels(frame):
    if frame.empty:
        return {}
    sr = A.get_sr_levels(frame, len(frame) - 1)
    lows = frame["Low"].rolling(A.SR_WINDOW).min().iloc[-1]
    highs = frame["High"].rolling(A.SR_WINDOW).max().iloc[-1]
    support, resistance = sr["support"], sr["resistance"]
    return {
        "support": support if support is not None else _finite(lows),
        "resistance": resistance if resistance is not None else _finite(highs),
        "support_source": "pivot_cluster" if support is not None else "rolling_estimate",
        "resistance_source": "pivot_cluster" if resistance is not None else "rolling_estimate",
        "support_touches": sr["support_touches"],
        "resistance_touches": sr["resistance_touches"],
        "support_ladder": sr["support_ladder"],
        "resistance_ladder": sr["resistance_ladder"],
    }


def _rr_gate(entry, stop, target):
    if entry is None or stop is None or entry <= 0 or stop <= 0 or stop >= entry:
        return "invalid_entry_or_stop"
    if target is None or target <= entry:
        return "no_resistance_target_above_entry"
    if (entry - stop) / entry > 0.08:
        return "stop_risk_above_8pct"
    if (target - entry) / (entry - stop) < 2.0:
        return "reward_risk_below_2"
    return None


def _new(symbol, family, session, plan, evidence):
    session = session.date().isoformat()
    identity = "|".join((symbol, family, STRATEGY_VERSION, session))
    candidate = {
        "id": "ta_" + hashlib.sha256(identity.encode()).hexdigest()[:20],
        "mode": "TA", "symbol": symbol, "family": family,
        "strategy_version": STRATEGY_VERSION, "signal_session": session,
        "status": "detected", "original_plan": _json(plan),
        "current": {"last_processed_session": session, "data_status": "complete",
                    "confirmation_sessions": 0, "observations": 1},
        "events": [], "model_trade": None,
    }
    _event(candidate, "detected", session, evidence=evidence)
    if family == "reversal":
        rejection = _rr_gate(plan["trigger"], plan["stop"], plan["target"])
        if rejection:
            _end(candidate, "skipped", session, rejection)
            candidate["current"]["watch_reason"] = rejection
        else:
            candidate["status"] = "awaiting_confirmation"
            _event(candidate, "awaiting_confirmation", session, maximum_sessions=3)
    else:
        candidate["status"] = "awaiting_entry"
        candidate["current"]["confirmation_session"] = session
        _event(candidate, "confirmed", session, rule="signal_close")
    return candidate


def _detect(symbol, frame, benchmark, session):
    prefix = frame.loc[:session]
    benchmark = benchmark.loc[:session]
    row = prefix.iloc[-1]
    structure = _levels(prefix)
    found = []
    screen = A.score_ticker(prefix, symbol, benchmark)
    if screen is not None:
        screen = asdict(screen) if is_dataclass(screen) else dict(screen)
        if screen.get("flag"):
            trigger = float(row.High) * 1.001
            support = _finite(screen.get("support_level"))
            stop = min(float(row.Low), support if support is not None else float(row.Low)) * 0.995
            resistance = sorted(float(level["level"]) for level in screen.get("resistance_ladder", [])
                                if _finite(level.get("level")) is not None and float(level["level"]) > trigger)
            target = resistance[0] if resistance else None
            risk = trigger - stop
            plan = {
                "entry_type": "next_open_after_daily_close_confirmation",
                "signal_close": float(row.Close), "signal_high": float(row.High),
                "signal_low": float(row.Low), "trigger": trigger, "entry": trigger,
                "stop": stop, "target": target, "levels": structure,
                "risk_pct": risk / trigger,
                "rr": (target - trigger) / risk if target is not None and risk > 0 else None,
                "confirmation_rule": "later_close_strictly_above_trigger",
                "confirmation_limit_sessions": 3, "time_exit_sessions": 15,
                "cost_per_side": COST_PER_SIDE,
                "evidence": {key: screen.get(key) for key in (
                    "pattern", "trend", "trend_r2", "checks_passed", "confidence",
                    "volume_ratio", "rsi")},
            }
            found.append(_new(symbol, "reversal", session, plan, plan["evidence"]))
    prepared = R.prep(prefix, pd.Series(False, index=benchmark.index))
    prepared["rs"] = np.nan
    signals = R.signals(prepared)
    latest = prepared.iloc[-1]
    atr = _finite(latest.atr)
    if atr is not None and atr > 0:
        for family in ("breakout55", "pullback20"):
            if bool(signals[family].iloc[-1]):
                floor = float(latest.hh55 if family == "breakout55" else latest.ema20)
                plan = {
                    "entry_type": "next_session_open", "signal_close": float(row.Close),
                    "signal_high": float(row.High), "signal_low": float(row.Low),
                    "confirmation_close": float(row.Close), "entry_floor": floor,
                    "entry_ceiling": float(row.Close) + atr, "signal_atr": atr,
                    "initial_stop_atr": 2.0, "trailing_stop_atr": 3.0,
                    "time_exit_sessions": 60, "target": None, "levels": structure,
                    "cost_per_side": COST_PER_SIDE,
                    "evidence": {"close": float(latest.Close), "sma50": _finite(latest.sma50),
                                 "sma200": _finite(latest.sma200), "ema20": _finite(latest.ema20),
                                 "prior_high55": _finite(latest.hh55),
                                 "volume_ratio": _finite(latest.vol_ratio)},
                }
                found.append(_new(symbol, family, session, plan, plan["evidence"]))
    return found


def _enter(candidate, row, session):
    plan = candidate["original_plan"]
    entry = float(row.Open)
    if candidate["family"] == "reversal":
        if entry < plan["trigger"]:
            reason = "next_open_below_trigger"
        elif entry >= plan["target"]:
            reason = "next_open_at_or_above_target"
        else:
            reason = _rr_gate(entry, plan["stop"], plan["target"])
        stop = plan["stop"]
    else:
        reason = None
        if entry <= plan["entry_floor"]:
            reason = "next_open_not_above_signal_level"
        elif entry > plan["entry_ceiling"]:
            reason = "next_open_exceeds_one_signal_atr_gap"
        stop = entry - 2.0 * plan["signal_atr"]
        if stop <= 0:
            reason = "nonpositive_initial_stop"
    if reason:
        _end(candidate, "skipped", session, reason)
        return
    candidate["model_trade"] = {
        "status": "open", "entry_session": session, "entry_price": entry,
        "initial_stop": stop, "current_stop": stop, "initial_risk": entry - stop,
        "target": plan.get("target"), "entry_fee_per_share": entry * COST_PER_SIDE,
        "exit_fee_per_share": None, "cost_per_side": COST_PER_SIDE,
        "bars_after_entry": 0, "highest_close": entry,
        "mfe_pct": 0.0, "mae_pct": 0.0, "mfe_R": 0.0, "mae_R": 0.0,
        "max_favorable_price": entry, "min_adverse_price": entry,
        "ambiguities": [], "exit_session": None, "exit_price": None, "net_R": None,
    }
    candidate["status"] = "model_open"
    _event(candidate, "model_entered", session, price=entry, initial_stop=stop,
           cost_per_side=COST_PER_SIDE, actual_execution=False)
    _monitor(candidate, row, session, entry_bar=True)


def _excursions(trade, high, low):
    trade["max_favorable_price"] = max(trade["max_favorable_price"], high)
    trade["min_adverse_price"] = min(trade["min_adverse_price"], low)
    entry, risk = trade["entry_price"], trade["initial_risk"]
    trade["mfe_pct"] = (trade["max_favorable_price"] / entry - 1.0) * 100.0
    trade["mae_pct"] = (trade["min_adverse_price"] / entry - 1.0) * 100.0
    trade["mfe_R"] = (trade["max_favorable_price"] - entry) / risk
    trade["mae_R"] = (trade["min_adverse_price"] - entry) / risk


def _monitor(candidate, row, session, entry_bar=False):
    trade, plan = candidate["model_trade"], candidate["original_plan"]
    if not entry_bar:
        trade["bars_after_entry"] += 1
        if candidate["family"] != "reversal":
            trade["current_stop"] = max(trade["current_stop"],
                                         trade["highest_close"] - 3.0 * plan["signal_atr"])
    o, high, low, close = (float(row[key]) for key in ("Open", "High", "Low", "Close"))
    stop, target = trade["current_stop"], trade.get("target")
    stop_hit = low <= stop
    target_hit = target is not None and high >= target
    exit_price = exit_reason = None
    at_open = False
    if not entry_bar and o <= stop:
        exit_price, exit_reason, at_open = o, "gap_stop", True
    elif target is not None and o >= target:
        exit_price, exit_reason, at_open = o, "gap_target", True
    elif stop_hit:
        exit_price, exit_reason = stop, "stop"
    elif target_hit:
        exit_price, exit_reason = target, "target"
    elif trade["bars_after_entry"] >= plan["time_exit_sessions"]:
        exit_price, exit_reason = close, "time_exit"
    if stop_hit and target_hit and not at_open:
        ambiguity = {"session": session, "type": "stop_and_target_same_bar",
                     "resolution": "stop_first"}
        trade["ambiguities"].append(ambiguity)
        _event(candidate, "daily_bar_ambiguity", session,
               ambiguity=ambiguity["type"], resolution=ambiguity["resolution"])
    if exit_price is not None and exit_reason != "time_exit":
        # An exit-bar high/low may occur after the exit. Keep guaranteed
        # excursions and explicit bounds instead of inventing their sequence.
        _excursions(trade, max(o, exit_price), min(o, exit_price))
        trade["mfe_upper_pct"] = max(trade["mfe_pct"], (high / trade["entry_price"] - 1) * 100)
        trade["mae_lower_pct"] = min(trade["mae_pct"], (low / trade["entry_price"] - 1) * 100)
        trade["excursion_basis"] = "guaranteed_extremes_with_exit_bar_bounds" if not at_open else "through_exit_open"
        if at_open:
            trade["mfe_upper_pct"] = trade["mfe_pct"]
            trade["mae_lower_pct"] = trade["mae_pct"]
    else:
        _excursions(trade, high, low)
        trade["excursion_basis"] = "complete_held_bars"
    if exit_price is None:
        trade["highest_close"] = max(trade["highest_close"], close)
        trade["mark_session"], trade["mark_price"] = session, close
        trade["unrealized_gross_per_share"] = close - trade["entry_price"]
        return
    entry = trade["entry_price"]
    exit_fee = exit_price * COST_PER_SIDE
    fees = trade["entry_fee_per_share"] + exit_fee
    trade.update({
        "status": "closed", "exit_session": session, "exit_price": exit_price,
        "exit_reason": exit_reason, "exit_fee_per_share": exit_fee,
        "total_cost_per_share": fees, "gross_per_share": exit_price - entry,
        "net_per_share": exit_price - entry - fees,
        "net_return_pct": (exit_price - entry - fees) / entry * 100.0,
        "net_R": (exit_price - entry - fees) / trade["initial_risk"],
        "gross_R": (exit_price - entry) / trade["initial_risk"],
    })
    candidate["status"] = "closed"
    candidate["current"]["reason"] = exit_reason
    _event(candidate, "model_exited", session, price=exit_price, reason=exit_reason,
           net_R=trade["net_R"], actual_execution=False)


def _advance(candidate, row, session):
    status, plan, current = candidate["status"], candidate["original_plan"], candidate["current"]
    if status == "awaiting_confirmation":
        current["confirmation_sessions"] += 1
        if float(row.Low) <= plan["stop"]:
            _end(candidate, "invalidated", session, "stop_touched_before_confirmation")
        elif float(row.Close) > plan["trigger"]:
            current["confirmation_session"] = session
            candidate["status"] = "awaiting_entry"
            _event(candidate, "confirmed", session, close=float(row.Close), trigger=plan["trigger"])
        elif current["confirmation_sessions"] >= plan["confirmation_limit_sessions"]:
            _end(candidate, "expired", session, "confirmation_window_elapsed")
    elif status == "awaiting_entry":
        _enter(candidate, row, session)
    elif status == "model_open":
        _monitor(candidate, row, session)
    else:
        raise ValueError(f"Cannot advance TA lifecycle status {status!r}")
    current["last_processed_session"] = session


def scan_ta(symbol: str, frame: pd.DataFrame, benchmark_frame: pd.DataFrame | None,
            existing: list[dict] | None = None, as_of: str | None = None) -> list[dict]:
    """Update model lifecycles and detect the latest completed-session TA setups.

    ``frame.attrs['scan_start_session']`` optionally requests historical detection
    *after* a persisted successful scan session; otherwise only the latest session
    creates candidates. Existing lifecycles always replay unprocessed sessions.
    Missing rows pause at the first gap so later restored data can be replayed.
    """
    if not str(symbol).strip():
        raise ValueError("TA symbol must be nonempty")
    candidates = deepcopy(existing or [])
    last_dates = [item.index[-1] for item in (frame, benchmark_frame) if item is not None and not item.empty]
    if as_of is None and not last_dates:
        for candidate in candidates:
            if candidate.get("symbol") == symbol and candidate.get("status") not in TERMINAL:
                _pause(candidate, candidate["current"]["last_processed_session"], "no_stock_or_benchmark_data")
        return _json(candidates)
    cutoff = _session(as_of) if as_of is not None else max(_session(item) for item in last_dates)
    stock, benchmark = _frame(frame, cutoff), _frame(benchmark_frame, cutoff, benchmark=True)
    calendar = stock.index.union(benchmark.index).sort_values()
    own = [candidate for candidate in candidates if candidate.get("symbol") == symbol
           and candidate.get("mode") == "TA"]
    ids = [candidate["id"] for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("TA journal has duplicate candidate IDs")
    for candidate in own:
        if candidate["family"] not in FAMILIES:
            raise ValueError(f"Unknown TA setup family: {candidate['family']}")
    start = (frame.attrs.get("scan_start_session") if frame is not None else None)
    detection_sessions = set(calendar[calendar > _session(start)]) if start is not None else {cutoff}
    relevant_starts = [_session(candidate["current"]["last_processed_session"]) for candidate in own
                       if candidate["status"] not in TERMINAL]
    replay_start = min(relevant_starts + ([_session(start)] if start is not None else [cutoff]))
    sessions = calendar[calendar >= replay_start]
    blocked_ids = set()
    for day in sessions:
        session = day.date().isoformat()
        healthy = _valid_row(stock, day) and _valid_row(benchmark, day, benchmark=True)
        for candidate in own:
            if candidate["status"] in TERMINAL or candidate["id"] in blocked_ids:
                continue
            if day <= _session(candidate["current"]["last_processed_session"]):
                continue
            if not healthy:
                _pause(candidate, session, "missing_or_invalid_stock_or_benchmark_bar")
                blocked_ids.add(candidate["id"])
                continue
            _resume(candidate, session)
            _advance(candidate, stock.loc[day], session)
        if day not in detection_sessions or not healthy:
            continue
        # A gap inside a detection window makes that window untrustworthy.
        common_history = calendar[calendar <= day]
        if any(not _valid_row(stock, prior) or not _valid_row(benchmark, prior, benchmark=True)
               for prior in common_history[-253:]):
            continue
        for detected in _detect(symbol, stock.loc[:day], benchmark.loc[:day], day):
            if detected["id"] in ids:
                continue
            active = next((item for item in own if item["family"] == detected["family"]
                           and item["strategy_version"] == STRATEGY_VERSION and item["status"] not in TERMINAL), None)
            if active is not None:
                _event(active, "setup_observed_again", session,
                       observed_signal_session=detected["signal_session"])
                active["current"]["observations"] = 1 + sum(
                    event["type"] == "setup_observed_again" for event in active["events"])
                continue
            candidates.append(detected)
            own.append(detected)
            ids.append(detected["id"])
    latest_healthy = _valid_row(stock, cutoff) and _valid_row(benchmark, cutoff, benchmark=True)
    latest_levels = _levels(stock.loc[:cutoff]) if latest_healthy else None
    for candidate in own:
        if candidate["status"] in TERMINAL:
            continue
        current = candidate["current"]
        current["as_of"] = cutoff.date().isoformat()
        if not latest_healthy:
            _pause(candidate, cutoff.date().isoformat(), "expected_session_missing_or_stale")
        elif candidate["id"] not in blocked_ids:
            # A retry on the same now-restored session need not advance the state.
            _resume(candidate, cutoff.date().isoformat())
            current["close"] = float(stock.loc[cutoff, "Close"])
            current["levels"] = latest_levels
            current["data_session"] = cutoff.date().isoformat()
            current.pop("reason", None)
    return _json(candidates)
