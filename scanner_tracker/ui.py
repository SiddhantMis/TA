"""Private, EOD-only interface over TrackerService. Service injection enables offline UI checks."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import uuid

import streamlit as st

from scanner_tracker.charts import allocation_figure, candlestick_figure, equity_figure, number, plan_prices, trade_markers

LOG = logging.getLogger(__name__)
PAGES = ["Overview", "TA scanner", "Momentum basket", "Watch", "Actual journal", "Review", "Settings"]
MODES = ["TA", "MOMENTUM"]


def _error(exc, operation):
    reference = uuid.uuid4().hex[:8]
    LOG.error("%s failed: %s; reference=%s", operation, type(exc).__name__, reference)
    if isinstance(exc, (ValueError, KeyError, RuntimeError)):
        detail = str(exc).strip("'")[:350]
        if re.search(r"password|secret|token|api.?key|authorization|credential", detail, re.I):
            detail = "Check the supplied values and deployment configuration."
    else:
        detail = f"The service reported {type(exc).__name__}. Check the service log before retrying."
    st.error(f"{operation}: {detail} (reference {reference})")


def _action(operation, function, *args, **kwargs):
    try:
        value = function(*args, **kwargs)
    except Exception as exc:
        _error(exc, operation)
        return False, None
    st.success(f"{operation} completed.")
    return True, value


def _currency(value):
    parsed = number(value)
    return f"₹{parsed:,.2f}" if parsed is not None else "—"


def _text(value):
    return "—" if value is None or value == "" else str(value)


def _rows(value):
    if isinstance(value, list):
        return [item if isinstance(item, dict) else {"symbol": str(item)} for item in value]
    if isinstance(value, dict):
        for key in ("rows", "items", "holdings", "ranked", "ranks"):
            if key in value:
                return _rows(value[key])
        return [{"symbol": key, **(item if isinstance(item, dict) else {"value": item})}
                for key, item in value.items()]
    return []


def _table(rows, empty="No observations yet."):
    items = _rows(rows)
    if items:
        display = [{key: json.dumps(value, default=str) if isinstance(value, (dict, list, tuple)) else value
                    for key, value in item.items()} for item in items]
        st.dataframe(display, width="stretch", hide_index=True)
    else:
        st.info(empty)


def _id(candidate):
    return str(candidate.get("id", candidate.get("candidate_id", "")))


def _symbol(candidate):
    return str(candidate.get("symbol", candidate.get("ticker", "—")))


def _scopes(candidate):
    scopes = candidate.get("scopes")
    if isinstance(scopes, list):
        return [str(scope) for scope in scopes]
    scope = candidate.get("scope", candidate.get("universe"))
    return [item.strip() for item in str(scope).split(",") if item.strip()] if scope else []


def _candidate(item):
    return item.get("candidate", item) if isinstance(item, dict) else {}


def _summary_rows(candidates):
    rows = []
    for candidate in candidates:
        plan = candidate.get("original_plan") or {}
        entry, stop, targets = plan_prices(plan)
        entry_label = _currency(entry) if entry is not None else "Next session open" if plan.get("entry_type") == "next_session_open" else "Unavailable"
        stop_label = _currency(stop) if stop is not None else f"{plan['initial_stop_atr']} × ATR below fill" if plan.get("initial_stop_atr") else "Unavailable"
        target_label = ", ".join(f"{value:,.2f}" for value in targets) or ("Trailing / time exit" if plan.get("trailing_stop_atr") else "No fixed target")
        rows.append({"Symbol": _symbol(candidate), "Family": candidate.get("family"),
                     "Scope": ", ".join(_scopes(candidate)),
                     "Status": candidate.get("status"),
                     "Signal session": candidate.get("signal_session", candidate.get("signal_date")),
                     "Original entry": entry_label, "Original stop": stop_label,
                     "Original targets": target_label,
                     "ID": _id(candidate)})
    return rows


def _warning_list(values):
    if isinstance(values, str):
        values = [values]
    for value in values or []:
        st.warning(str(value))


def _coverage(coverage):
    if not isinstance(coverage, dict) or not coverage:
        st.caption("Coverage has not been reported yet.")
        return
    labels = {"requested": "Requested", "loaded": "Loaded", "scored": "Scored", "fresh": "Fresh",
              "failed": "Failed", "eligible": "Eligible", "coverage_pct": "Coverage (%)",
              "expected": "Expected", "available": "Available", "healthy": "Healthy"}
    rows = [{"Measure": labels.get(key, key.replace("_", " ").title()), "Value": str(value)}
            for key, value in coverage.items() if not isinstance(value, (dict, list))]
    _table(rows, "Coverage has not been reported yet.")


def _refresh(service, key):
    if st.button("Request EOD refresh", key=key, help="Requests a refresh through the private service. Prices are not live."):
        try:
            result = service.request_refresh()
        except Exception as exc:
            _error(exc, "Refresh request")
            return
        if isinstance(result, dict) and result.get("status") == "manual_setup_required":
            st.info(str(result.get("message", "Open the workflow to request a scan manually.")))
            if str(result.get("url", "")).startswith("https://github.com/"):
                st.link_button("Open EOD refresh workflow", result["url"])
        else:
            st.success("EOD refresh requested. The current published data remains visible until the worker completes.")
            if isinstance(result, dict):
                st.caption(str(result.get("message", result.get("status", "requested"))))


def _overview(service, status):
    st.subheader("The latest completed session")
    latest = status.get("latest_run") or {}
    if not latest:
        st.info("No scan has completed. Configure the private service and request the first EOD refresh.")
    else:
        st.caption(f"Session: {_text(latest.get('as_of', latest.get('session')))} · "
                   f"Run: {_text(latest.get('status'))} · "
                   f"Updated: {_text(latest.get('completed_at', latest.get('published_at', latest.get('created_at'))))}")
    counts = status.get("counts") or {}
    columns = st.columns(4)
    for column, (label, keys) in zip(columns, [("TA candidates", ("ta_candidates", "candidates", "total")),
                                               ("Watching", ("watch", "watched", "watch_items")),
                                               ("Open model trades", ("open_models", "model_trades")),
                                               ("Data issues", ("data_issues", "errors", "unknown"))]):
        value = next((counts[key] for key in keys if key in counts), None)
        column.metric(label, _text(value))
    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Universe coverage**")
        coverage = latest.get("coverage", status.get("coverage", {}))
        if not coverage and latest.get("coverage_pct") is not None:
            coverage = {"coverage_pct": latest["coverage_pct"]}
        if isinstance(coverage, dict) and any(isinstance(v, dict) for v in coverage.values()):
            for scope, item in coverage.items():
                if isinstance(item, dict):
                    with st.expander(str(scope), expanded=True):
                        _coverage(item)
        else:
            _coverage(coverage)
    with right:
        st.markdown("**Service health**")
        health = status.get("health")
        if isinstance(health, dict):
            for key, value in health.items():
                if not isinstance(value, (dict, list)):
                    st.write(f"{key.replace('_', ' ').title()}: {_text(value)}")
            if health.get("issues"):
                _table(health["issues"])
        elif health:
            st.write(str(health))
        else:
            st.caption("Health has not been reported yet.")
        _refresh(service, "overview_refresh")
    errors = status.get("last_errors", latest.get("diagnostics", latest.get("errors", status.get("errors", []))))
    if errors:
        st.markdown("**Latest scan issues**")
        if isinstance(errors, dict):
            _table([{"Symbol": key, "Issue": str(value)} for key, value in errors.items()])
        elif isinstance(errors, list) and errors and isinstance(errors[0], dict):
            _table(errors)
        else:
            _warning_list(errors)
    storage = status.get("storage") or {}
    if storage:
        st.markdown("**Private storage**")
        if storage.get("status") == "quota_warning":
            st.warning("Private storage is approaching the configured free-tier reference limit. Review provider usage and private backups before adding more history.")
        columns = st.columns(3)
        database = number(storage.get("database_bytes"))
        archive = number(storage.get("tracked_input_archive_bytes"))
        columns[0].metric("Database size", f"{database / 1024 ** 2:.2f} MiB" if database is not None else "—")
        columns[1].metric("Tracked input archives", f"{archive / 1024 ** 2:.2f} MiB" if archive is not None else "—")
        columns[2].metric("Archives with unknown size", _text(storage.get("archive_objects_without_size")))
        if storage.get("basis"):
            st.caption(str(storage["basis"]))
    background = (status.get("health") or {}).get("background_tasks", []) if isinstance(status.get("health"), dict) else []
    if background or status.get("notifications"):
        with st.expander("Background tasks and notification health"):
            _table(background, "No background task status has been reported.")
            if status.get("notifications"):
                st.markdown("**Notifications**")
                _table([status["notifications"]])
    st.info("TA tracks individual setups. Momentum tracks a separate monthly basket. Model fills and actual executions have separate records.")


def _plan(candidate):
    plan = candidate.get("original_plan") or {}
    entry, stop, targets = plan_prices(plan)
    cols = st.columns(3)
    cols[0].metric("Original entry reference", _currency(entry))
    cols[1].metric("Original stop reference", _currency(stop))
    cols[2].metric("Original first target", _currency(targets[0] if targets else None))
    if entry and stop and entry > stop and targets and targets[0] > entry:
        rr = (targets[0] - entry) / (entry - stop)
        potential = 100 * (targets[0] / entry - 1)
        st.caption(f"Hypothetical move to first target: {potential:.1f}% · planned reward/risk: {rr:.2f}R. "
                   "This is a price-distance calculation, not expected profit or an execution.")
    description = plan.get("entry_condition", plan.get("entry_rule", plan.get("description")))
    if description:
        st.write(str(description))
    elif plan.get("entry_type") == "next_session_open":
        st.write("Confirmed at the signal close; model entry uses the next exchange session's observed open, subject to the frozen entry conditions.")
        st.caption(f"Entry floor: {_currency(plan.get('entry_floor'))} · entry ceiling: {_currency(plan.get('entry_ceiling'))}. "
                   f"Initial stop: {plan.get('initial_stop_atr', '—')} × signal ATR below the fill; "
                   f"trail: {plan.get('trailing_stop_atr', '—')} × signal ATR. No fixed target is specified.")
    elif plan.get("confirmation_rule"):
        st.write("Await a later completed daily close strictly above the original trigger. Model entry is considered at the next session's open after confirmation.")
    reasons = candidate.get("reasons", plan.get("reasons"))
    if reasons:
        st.write("Decision reasons:", reasons)
    st.caption("The original plan stays fixed. Current levels provide context; they do not replace the original plan.")
    sizing = candidate.get("sizing") or {}
    if sizing.get("status") == "reference_only":
        st.info(f"Reference size: {sizing.get('quantity', '—')} shares · "
                f"risk budget {_currency(sizing.get('risk_budget_inr'))}. "
                "Uses EOD reference prices; cash is not reserved and no order is placed.")
    elif sizing:
        st.caption(f"Sizing unavailable: {sizing.get('reason', 'Configure capital and risk in Settings.')}")


def _candidate_detail(service, candidate):
    candidate_id = _id(candidate)
    st.divider()
    st.subheader(f"{_symbol(candidate)} · {_text(candidate.get('family'))}")
    st.caption(f"{_text(candidate.get('status'))} · signal session "
               f"{_text(candidate.get('signal_session', candidate.get('signal_date')))} · {candidate_id}")
    _plan(candidate)
    chart_tab, history_tab, model_tab = st.tabs(["Chart and context", "Decision history", "Model trade"])
    with chart_tab:
        try:
            figure = candlestick_figure(candidate.get("bars", []), candidate.get("original_plan"),
                                         candidate.get("current", candidate.get("current_plan", {})),
                                         trade_markers(candidate), _symbol(candidate))
            if figure is None:
                st.info("Observed EOD chart history is unavailable for this candidate.")
            else:
                st.plotly_chart(figure, width="stretch")
                st.caption("Observed daily candles only. Dotted lines show the original plan; dashed lines show current support and resistance.")
        except (ValueError, TypeError, KeyError) as exc:
            _error(exc, "Chart unavailable")
        current = candidate.get("current", candidate.get("current_plan"))
        if isinstance(current, dict):
            context = [{"Measure": key.replace("_", " ").title(), "Value": str(value)}
                       for key, value in current.items() if not isinstance(value, (dict, list))]
            if context:
                _table(context)
    with history_tab:
        _table(candidate.get("events", candidate.get("history", [])), "No later decisions have been recorded.")
    with model_tab:
        model_trade = candidate.get("model_trade")
        if isinstance(model_trade, dict) and model_trade:
            _table([model_trade])
        else:
            st.info("No modeled entry has been recorded. A candidate is not a filled trade.")
        st.caption("Daily-close confirmation becomes actionable from a subsequent exchange session. Actual fills belong in the actual journal.")
    notes = candidate.get("notes") or [{"text": event.get("details", {}).get("text"),
                                         "created_at": event.get("details", {}).get("recorded_at", event.get("session"))}
                                        for event in candidate.get("events", []) if event.get("type") == "note"]
    if notes:
        st.markdown("**Private notes**")
        if isinstance(notes, str):
            st.write(notes)
        else:
            for note in notes:
                if isinstance(note, dict):
                    st.caption(_text(note.get("created_at", note.get("timestamp"))))
                    st.write(str(note.get("text", note.get("note", ""))))
                else:
                    st.write(str(note))
    watched = {_id(_candidate(item)) for item in service.watch_items()}
    pin_label = "Remove from watch" if candidate_id in watched else "Add to watch"
    if st.button(pin_label, key=f"pin_{candidate_id}"):
        ok, _ = _action("Watch update", service.set_watch, candidate_id, watched=candidate_id not in watched)
        if ok:
            st.rerun()
    with st.form(f"note_{candidate_id}", clear_on_submit=True):
        note = st.text_area("Add a private note", key=f"note_text_{candidate_id}")
        if st.form_submit_button("Save note"):
            if note.strip():
                _action("Note saved", service.save_note, candidate_id, note.strip())
            else:
                st.error("Enter a note before saving.")


def _ta(service):
    st.subheader("Individual TA setups")
    st.caption("Patterns are research signals. A score is not a probability of success. Rejected, expired and data-blocked cases remain part of the record.")
    candidates = service.candidates(mode="TA")
    cols = st.columns(3)
    family = cols[0].selectbox("Family", ["All families"] + sorted({str(c.get("family")) for c in candidates if c.get("family")}))
    scope = cols[1].selectbox("Universe", ["All universes"] + sorted({scope for c in candidates for scope in _scopes(c)}))
    status = cols[2].selectbox("Status", ["All statuses"] + sorted({str(c.get("status")) for c in candidates if c.get("status")}))
    filtered = [c for c in candidates if (family == "All families" or str(c.get("family")) == family)
                and (scope == "All universes" or scope in _scopes(c))
                and (status == "All statuses" or str(c.get("status")) == status)]
    _table(_summary_rows(filtered), "No candidates match these filters.")
    ids = [_id(c) for c in filtered if _id(c)]
    if ids:
        labels = {_id(c): f"{_symbol(c)} · {c.get('family')} · {c.get('signal_session', c.get('signal_date'))} · {c.get('status')}" for c in filtered}
        selected = st.selectbox("Inspect a setup", ids, format_func=lambda value: labels[value], key="ta_selected")
        _candidate_detail(service, service.candidate(selected))


def _holdings(ledger):
    return _rows(ledger.get("holdings", {})) if isinstance(ledger, dict) else []


def _momentum(service):
    st.subheader("Independent momentum basket")
    st.caption("Top-20 basket research and monthly portfolio management. TA entry prices, targets and setup statuses do not drive this mode.")
    scope = st.selectbox("Basket universe", ["wide", "personal"], format_func=lambda value: "Wide universe" if value == "wide" else "Personal universe comparison")
    report = service.momentum_report(scope=scope) or {}
    model = report.get("model") or {}
    actual = service.ledger("MOMENTUM") or {}
    columns = st.columns(3)
    columns[0].metric("Basket status", _text(report.get("status", report.get("rebalance_status"))))
    regime = report.get("regime", report.get("market_regime"))
    columns[1].metric("Market regime", _text(regime.get("regime") if isinstance(regime, dict) else regime))
    columns[2].metric("Actual cash", _currency(actual.get("cash_balance_inr", actual.get("cash"))))
    st.caption(f"EOD session: {_text(report.get('as_of', report.get('signal_session')))}")
    _warning_list(report.get("warnings"))
    ranks_tab, model_tab, actual_tab, audit_tab = st.tabs(["Ranked stocks", "Model basket", "Actual and proposals", "Coverage and rebalance history"])
    with ranks_tab:
        ranks = _rows(report.get("ranks", report.get("ranked", report.get("rows", []))))
        _table([{"Symbol": _symbol(row), "Rank": row.get("leader_rank", row.get("rank")),
                 "EOD close (INR)": row.get("last_close", row.get("close")),
                 "12–1 relative strength (%)": row.get("relative_strength_12_1_pct"),
                 "Above 200-DMA": row.get("above_sma200", row.get("above_200dma")),
                 "126-session traded value": row.get("traded_value_126d"),
                 "Session": row.get("data_as_of", row.get("as_of", report.get("as_of")))} for row in ranks],
               "No healthy basket ranking is available yet.")
        if ranks:
            with st.expander("Full ranking inputs and data quality"):
                _table(ranks)
    with model_tab:
        st.markdown("**Model target holdings**")
        _table(model.get("target_holdings", report.get("target_holdings", [])))
        weights = model.get("target_weights", report.get("target_weights", {}))
        figure = allocation_figure(weights)
        if figure is not None:
            st.plotly_chart(figure, width="stretch")
        history = model.get("history", report.get("equity_history", []))
        figure = equity_figure(history)
        if figure is not None:
            st.plotly_chart(figure, width="stretch")
        else:
            st.info("No complete model equity history is available. Missing periods are not joined into a return series.")
        model_ledger = model.get("ledger") or {}
        st.caption(f"Model cash: {_currency(model_ledger.get('cash_balance_inr', model_ledger.get('cash')))}. "
                   "Model capital is an assumption and is separate from actual cash.")
        pending = model.get("pending_rebalance")
        if pending:
            st.markdown("**Pending model rebalance**")
            _table([pending] if isinstance(pending, dict) else pending)
    with actual_tab:
        if scope != "wide":
            st.info("Actual momentum allocation and proposals use the wide basket. The personal universe is a separate comparison and does not change that allocation.")
        st.markdown("**Actual executed holdings**")
        _table(_holdings(actual), "No actual momentum holdings have been entered.")
        target = report.get("actual_target") or {}
        if target:
            st.markdown("**Target based on actual holdings**")
            st.caption(f"Status: {_text(target.get('status'))}")
            _table(target.get("holdings", target.get("quantities", [])))
        st.markdown("**Proposed transactions**")
        _table(report.get("proposals", report.get("proposed_transactions", [])), "No proposed transactions.")
        st.caption("Proposals are not executions. Holdings change only after confirmed fills are recorded in the actual journal.")
    with audit_tab:
        _coverage(report.get("coverage"))
        _table(model.get("rebalance_history", []), "No rebalance decisions have been recorded.")


def _watch(service):
    st.subheader("Persistent watch")
    st.caption("Pins and notes survive later scans. Removing a pin does not erase the candidate or its history.")
    items = service.watch_items()
    candidates = [_candidate(item) for item in items]
    _table(_summary_rows(candidates), "No setups are pinned yet. Add a setup from the TA scanner.")
    ids = [_id(c) for c in candidates if _id(c)]
    if ids:
        labels = {_id(c): f"{_symbol(c)} · {c.get('family')} · {c.get('status')}" for c in candidates}
        selected = st.selectbox("Inspect a watched setup", ids, format_func=lambda value: labels[value])
        _candidate_detail(service, service.candidate(selected))


def _parse_positions(text):
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    required = {"symbol", "quantity", "average_cost_inr"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("Opening positions need CSV columns symbol,quantity,average_cost_inr.")
    positions = []
    for index, row in enumerate(reader, 2):
        symbol = (row.get("symbol") or "").strip().upper()
        quantity, cost = number(row.get("quantity")), number(row.get("average_cost_inr"))
        raw_cost = (row.get("average_cost_inr") or "").strip()
        if not symbol or quantity is None or quantity <= 0 or not quantity.is_integer() or (raw_cost and (cost is None or cost <= 0)):
            raise ValueError(f"Opening position row {index} needs a symbol, positive quantity and positive cost or blank unknown cost.")
        positions.append({"symbol": symbol, "quantity": quantity, "average_cost_inr": cost})
    return positions


def _journal(service):
    st.subheader("Actual execution journal")
    st.caption("Record confirmed executions and actual cash movements. Model trades remain separate. Dates and prices are supplied by you, not inferred from a daily candle.")
    mode = st.radio("Actual account", MODES, horizontal=True)
    ledger = service.ledger(mode) or {}
    st.metric("Actual cash balance", _currency(ledger.get("cash_balance_inr", ledger.get("cash"))))
    _table(_holdings(ledger), "No actual positions in this account.")
    fill_tab, import_tab, cash_tab, opening_tab, history_tab = st.tabs(["Record fill", "Import fills", "Cash and transfers", "Opening balances", "Journal history"])
    with fill_tab:
        with st.form(f"fill_{mode}", clear_on_submit=True):
            execution_id = st.text_input("Unique execution ID", key=f"execution_id_{mode}")
            executed_at = st.text_input("Execution timestamp (ISO 8601 with timezone)", placeholder="YYYY-MM-DDTHH:MM:SS+05:30", key=f"executed_at_{mode}")
            cols = st.columns(3)
            symbol = cols[0].text_input("Symbol", key=f"fill_symbol_{mode}")
            side = cols[1].selectbox("Side", ["BUY", "SELL"], key=f"fill_side_{mode}")
            quantity = cols[2].number_input("Executed quantity", min_value=0, step=1, key=f"fill_qty_{mode}")
            cols = st.columns(2)
            value = cols[0].number_input("Executed price (INR)", min_value=0.0, step=0.05, key=f"fill_price_{mode}")
            fees = cols[1].number_input("Actual fees (INR)", min_value=0.0, step=0.01, key=f"fill_fees_{mode}")
            signal_id = st.text_input("Related TA signal ID (optional)", key=f"fill_signal_{mode}") if mode == "TA" else ""
            if st.form_submit_button("Record confirmed fill"):
                if not execution_id.strip() or not executed_at.strip() or not symbol.strip() or quantity <= 0 or value <= 0:
                    st.error("Provide an execution ID, timestamp, symbol, positive quantity and price.")
                else:
                    _action("Fill recorded", service.record_fill, mode,
                            {"execution_id": execution_id.strip(), "mode": mode, "executed_at": executed_at.strip(),
                             "symbol": symbol.strip().upper(), "side": side, "quantity": quantity,
                             "price_inr": value, "fees_inr": fees, "signal_id": signal_id.strip() or None})
    with import_tab:
        text = st.text_area("Paste fill CSV", placeholder="execution_id,mode,executed_at,symbol,side,quantity,price_inr,fees_inr,signal_id", key=f"import_text_{mode}", height=150)
        digest = hashlib.sha256((mode + text).encode()).hexdigest()
        state_key = f"import_preview_{mode}"
        if st.button("Preview and validate CSV", key=f"preview_{mode}"):
            try:
                result = service.preview_import(mode, text)
                st.session_state[state_key] = {"digest": digest, "result": result}
            except Exception as exc:
                st.session_state.pop(state_key, None)
                _error(exc, "CSV preview")
        saved = st.session_state.get(state_key)
        result = saved["result"] if saved and saved["digest"] == digest else None
        if result is not None:
            _table(result.get("rows", []), "The CSV has no rows to import.")
            for error in result.get("errors", []):
                st.error(str(error))
            if not result.get("valid"):
                st.warning("Correct the CSV and preview it again before importing.")
        elif saved:
            st.info("The CSV changed. Preview the current text before importing.")
        confirmed = st.checkbox("I reviewed these executions and want to add them to the actual journal.", key=f"confirm_import_{mode}_{digest[:12]}")
        if st.button("Confirm import", disabled=not (result and result.get("valid") and confirmed), key=f"commit_{mode}"):
            ok, _ = _action("CSV import", service.commit_import, mode, text)
            if ok:
                st.session_state.pop(state_key, None)
    with cash_tab:
        with st.form(f"cash_{mode}", clear_on_submit=True):
            event_id = st.text_input("Cash event ID", key=f"cash_id_{mode}")
            executed_at = st.text_input("Cash movement timestamp", key=f"cash_time_{mode}")
            kind = st.selectbox("Movement", ["DEPOSIT", "WITHDRAWAL", "DIVIDEND"], key=f"cash_kind_{mode}")
            amount = st.number_input("Cash amount (INR)", min_value=0.0, key=f"cash_amount_{mode}")
            cash_symbol = st.text_input("Related symbol (optional, for dividends)", key=f"cash_symbol_{mode}")
            note = st.text_input("Cash note (optional)", key=f"cash_note_{mode}")
            if st.form_submit_button("Record cash movement"):
                if not event_id.strip() or not executed_at.strip() or amount <= 0:
                    st.error("Provide a cash event ID, timestamp and positive amount.")
                else:
                    _action("Cash movement recorded", service.cash_event, mode,
                            {"event_id": event_id.strip(), "executed_at": executed_at.strip(), "type": kind,
                             "amount_inr": amount, "note": note.strip(), "symbol": cash_symbol.strip().upper() or None})
        with st.form("transfer", clear_on_submit=True):
            st.markdown("**Transfer actual cash between accounts**")
            event_id = st.text_input("Transfer event ID")
            executed_at = st.text_input("Transfer timestamp")
            source = st.selectbox("Transfer from", MODES)
            destination = "MOMENTUM" if source == "TA" else "TA"
            st.caption(f"Transfer to: {destination}")
            amount = st.number_input("Transfer amount (INR)", min_value=0.0)
            if st.form_submit_button("Record transfer"):
                if not event_id.strip() or not executed_at.strip() or amount <= 0:
                    st.error("Provide a transfer ID, timestamp and positive amount.")
                else:
                    _action("Cash transfer recorded", service.transfer, amount, source, destination, event_id.strip(), executed_at.strip())
    with opening_tab:
        st.caption("Set actual opening cash and existing executed positions once. This does not set model capital and cannot reset an account with activity.")
        with st.form(f"opening_{mode}"):
            opening_as_of = st.date_input("Actual opening balance date", value=None, key=f"opening_as_of_{mode}",
                                         help="The date on which these cash and position balances are valid. They must not be projected into earlier historical sessions.")
            opening_cash = st.number_input("Actual opening cash (INR)", min_value=0.0, key=f"opening_cash_{mode}")
            positions = st.text_area("Actual opening positions (optional CSV)", placeholder="symbol,quantity,average_cost_inr", key=f"opening_positions_{mode}", help="Leave average_cost_inr blank when cost basis is unknown. Unknown cost is not zero profit.")
            acknowledge = st.checkbox("These are existing executed balances, not target holdings.", key=f"opening_ack_{mode}")
            if st.form_submit_button("Set opening balances"):
                if not acknowledge:
                    st.error("Confirm these are existing executed balances before recording them.")
                elif opening_as_of is None:
                    st.error("Choose the date on which the actual opening balances are valid.")
                else:
                    try:
                        parsed = _parse_positions(positions)
                    except ValueError as exc:
                        _error(exc, "Opening positions")
                    else:
                        _action("Opening balances", service.configure_ledger, mode, opening_cash, positions=parsed,
                                kind="actual", as_of=opening_as_of.isoformat())
    with history_tab:
        _table(ledger.get("execution_history", ledger.get("events", [])), "No actual journal events yet.")
        executions = ledger.get("execution_history", [])
        execution_ids = [item["execution_id"] for item in executions if item.get("execution_id")]
        if execution_ids:
            with st.expander("Correct an entered execution"):
                st.caption("Corrections append an explicit reversal and optional replacement. Original events stay in the audit record. A correction that breaks later cash or holdings is rejected.")
                correction_kind = st.selectbox("Correction action", ["Replace execution", "Reverse execution only"], key=f"correction_kind_{mode}")
                with st.form(f"correction_{mode}", clear_on_submit=True):
                    original_id = st.selectbox("Original execution ID", execution_ids, key=f"correction_original_{mode}")
                    correction_id = st.text_input("Unique correction ID", key=f"correction_id_{mode}")
                    replacement = None
                    if correction_kind == "Replace execution":
                        replacement_id = st.text_input("New replacement execution ID", key=f"replacement_id_{mode}")
                        replacement_time = st.text_input("Replacement execution timestamp", key=f"replacement_time_{mode}")
                        columns = st.columns(3)
                        replacement_symbol = columns[0].text_input("Replacement symbol", key=f"replacement_symbol_{mode}")
                        replacement_side = columns[1].selectbox("Replacement side", ["BUY", "SELL"], key=f"replacement_side_{mode}")
                        replacement_quantity = columns[2].number_input("Replacement quantity", min_value=0, step=1, key=f"replacement_quantity_{mode}")
                        columns = st.columns(2)
                        replacement_price = columns[0].number_input("Replacement price (INR)", min_value=0.0, key=f"replacement_price_{mode}")
                        replacement_fees = columns[1].number_input("Replacement fees (INR)", min_value=0.0, key=f"replacement_fees_{mode}")
                        replacement_signal = st.text_input("Replacement TA signal ID (optional)", key=f"replacement_signal_{mode}") if mode == "TA" else ""
                        replacement = {"execution_id": replacement_id.strip(), "mode": mode,
                                       "executed_at": replacement_time.strip(), "symbol": replacement_symbol.strip().upper(),
                                       "side": replacement_side, "quantity": replacement_quantity,
                                       "price_inr": replacement_price, "fees_inr": replacement_fees,
                                       "signal_id": replacement_signal.strip() or None}
                    confirmed = st.checkbox("I reviewed this correction to the actual journal.", key=f"correction_confirm_{mode}")
                    if st.form_submit_button("Record correction"):
                        if not confirmed:
                            st.error("Review and confirm the correction before recording it.")
                        elif not correction_id.strip():
                            st.error("Provide a unique correction ID.")
                        else:
                            _action("Execution correction", service.correct_fill, mode, original_id, correction_id.strip(), replacement=replacement)
        if ledger.get("events"):
            with st.expander("Full append-only account audit"):
                _table(ledger["events"])


def _fixed(value, suffix=""):
    parsed = number(value)
    return f"{parsed:,.2f}{suffix}" if parsed is not None else "—"


def _percentage(value, *, whole=False):
    parsed = number(value)
    return f"{parsed if whole else parsed * 100:,.2f}%" if parsed is not None else "—"


def _performance_status(report, label):
    status = str(report.get("status", "unavailable")).lower()
    total, valid, missing = (report.get(key, 0) for key in ("n_intervals", "valid_intervals", "missing_intervals"))
    st.caption(f"{label} status: {status} · {valid}/{total} valid intervals · {missing} missing intervals")
    if status == "incomplete":
        st.warning(f"{label} performance is incomplete. Cumulative return and drawdown are withheld; missing observations are not joined into a continuous record.")
    elif status != "complete":
        st.info(f"{label} is collecting observations. At least two valid EOD valuations are needed for an observed return interval.")
    if report.get("basis"):
        st.caption(str(report["basis"]))


def _performance_chart(report, label, key, *, benchmark=False):
    history = report.get("history") or []
    if not history:
        st.info(f"No observed {label.lower()} history is available yet.")
        return
    view = st.selectbox("Chart basis", ["Time-weighted return", "Account value"], key=key)
    returns = view == "Time-weighted return"
    series = {"cumulative_twr": f"{label} net TWR"} if returns else {"equity_inr": f"{label} value"}
    if benchmark and returns:
        series["benchmark_cumulative_return"] = "ETF price proxy"
    figure = equity_figure(history, series=series,
                           yaxis_title="Cumulative return" if returns else "Account value (INR)",
                           as_percentage=returns)
    if figure is None:
        st.info("This chart has no complete observed values. No missing return has been replaced with zero.")
    else:
        st.plotly_chart(figure, width="stretch", key=f"plot_{key}")
    st.caption("Gaps stay unknown. Account value includes funding changes; time-weighted return removes recorded deposits and withdrawals using the disclosed timing convention.")


def _ta_performance(report):
    st.caption("Independent unit-risk observations; no funded TA equity curve is implied.")
    families = report.get("families") or {}
    cohort = st.selectbox("TA performance cohort", ["All families"] + sorted(families), key="review_ta_cohort")
    row = report.get("overall", {}) if cohort == "All families" else families[cohort]
    columns = st.columns(4)
    for column, label, value in zip(columns,
                                    ["Closed observations", "Mean net R", "Median net R", "Win rate"],
                                    [_text(row.get("n_closed", row.get("closed"))), _fixed(row.get("mean_net_R"), "R"),
                                     _fixed(row.get("median_net_R"), "R"), _percentage(row.get("win_rate_pct"), whole=True)]):
        column.metric(label, value)
    columns = st.columns(4)
    for column, label, value in zip(columns,
                                    ["Profit factor", "Incomplete observations", "Open model trades", "Daily-bar ambiguities"],
                                    [_fixed(row.get("profit_factor")), _text(row.get("incomplete")),
                                     _text(row.get("model_open")), _text(row.get("ambiguities"))]):
        column.metric(label, value)
    if row.get("profit_factor_status") in {"no_losses", "no_trades"}:
        st.caption(f"Profit factor is undefined: {str(row['profit_factor_status']).replace('_', ' ')}. It is not displayed as infinity.")
    stress = row.get("double_cost_stress") or {}
    st.markdown("**Same fills with double transaction costs**")
    columns = st.columns(3)
    columns[0].metric("Mean net R at double costs", _fixed(stress.get("mean_net_R"), "R"))
    columns[1].metric("Median R at double costs", _fixed(stress.get("median_net_R"), "R"))
    columns[2].metric("Missing cost records", _text(stress.get("missing_cost_records")))
    if stress.get("status") == "incomplete":
        st.warning("Cost stress is incomplete. Results cover only observations with known costs.")
    if stress.get("basis"):
        st.caption(str(stress["basis"]))
    st.markdown("**Timing and excursions of completed observations**")
    _table([{"Mean favorable excursion (R)": row.get("mean_mfe_R"),
             "Mean adverse excursion (R)": row.get("mean_mae_R"),
             "Mean wait (sessions)": row.get("mean_wait_sessions"),
             "Mean hold (sessions)": row.get("mean_hold_sessions")}])
    if report.get("timing_basis"):
        st.caption(str(report["timing_basis"]))
    with st.expander("TA cohort counts, versions and excursion details"):
        st.json(row, expanded=False)
    for limitation in report.get("limitations") or []:
        st.caption(str(limitation))


def _review(service):
    st.subheader("Review evidence")
    st.caption("TA results use trade R and opportunity cohorts. Basket results use portfolio returns. Actual account outcomes are shown separately; candidate counts are not a performance claim.")
    reports = service.research_reports() or {}
    ta_tab, basket_tab, actual_tab, sources_tab = st.tabs(["TA model", "Momentum model", "Actual records", "Research and data limits"])
    with ta_tab:
        detailed = reports.get("ta_detailed")
        if detailed:
            _ta_performance(detailed)
        else:
            st.info("No complete TA model scorecard yet. No validated TA edge is established by candidate counts.")
            ta = reports.get("ta", reports.get("TA", {}))
            if isinstance(ta, dict) and ta:
                _table([{"Family": key, **value} for key, value in ta.items() if isinstance(value, dict)])
        st.caption("Repeated daily observations and overlapping setups are not independent portfolio trades. Candidate counts do not establish a profitable strategy.")
    with basket_tab:
        performance = reports.get("momentum_performance") or {}
        if performance:
            scope = st.selectbox("Performance universe", list(performance), key="review_momentum_scope")
            basket = performance[scope]
            _performance_status(basket, "Momentum model")
            columns = st.columns(4)
            columns[0].metric("Model cumulative return", _percentage(basket.get("cumulative_return", basket.get("cumulative_twr"))))
            columns[1].metric("Model maximum drawdown", _percentage(basket.get("max_drawdown")))
            columns[2].metric("Same-window ETF price return", _percentage(basket.get("benchmark_return")))
            columns[3].metric("Model excess over ETF price", _percentage(basket.get("excess_return")))
            turnover = basket.get("turnover") or {}
            columns = st.columns(4)
            columns[0].metric("Model transaction fees", _currency(basket.get("fees_inr")))
            columns[1].metric("L1 turnover (sum)", _fixed(turnover.get("weight_turnover"), "×"))
            columns[2].metric("Executed rebalances", _text(turnover.get("executed_rebalances")))
            columns[3].metric("Observed model cash", _percentage(basket.get("cash_pct"), whole=True))
            if turnover.get("status") == "incomplete":
                st.warning(f"Turnover is incomplete: {turnover.get('missing_rebalances', '—')} rebalances lack execution-weight records.")
            if turnover.get("basis"):
                st.caption(str(turnover["basis"]))
            comparison = basket.get("benchmark_comparison") or {}
            st.caption(f"Comparison window: {_text(comparison.get('start'))} to {_text(comparison.get('end'))}. "
                       f"{comparison.get('basis', 'Benchmark comparison basis has not been reported.')}")
            if comparison.get("status") != "complete":
                st.info("The same-window benchmark comparison is incomplete; missing benchmark returns and excess returns are withheld.")
            if not basket.get("capital_configured"):
                st.info("Model capital is not configured. No nominal starting balance or funded return is invented.")
            _performance_chart(basket, "Momentum model", f"review_momentum_chart_{scope}", benchmark=True)
            with st.expander("Momentum performance and missing-interval audit"):
                st.json(basket, expanded=False)
        else:
            st.info("No complete momentum model scorecard yet.")
        st.caption("Compare the same sessions and capital basis. Missing periods, current-constituent bias and unsupported corporate actions limit historical conclusions.")
    with actual_tab:
        mode = st.radio("Actual allocation performance", MODES, horizontal=True, key="review_actual_mode")
        ledger = service.ledger(mode) or {}
        actual = (reports.get("actual") or {}).get(mode) or {}
        if actual:
            _performance_status(actual, f"{mode} actual account")
            columns = st.columns(4)
            columns[0].metric("Actual cumulative TWR", _percentage(actual.get("cumulative_twr")))
            columns[1].metric("Actual maximum drawdown", _percentage(actual.get("max_drawdown")))
            columns[2].metric("Valid actual intervals", _text(actual.get("valid_intervals")))
            columns[3].metric("Missing actual intervals", _text(actual.get("missing_intervals")))
            if actual.get("timing_convention"):
                st.caption(str(actual["timing_convention"]))
            if actual.get("opening_date_known") is False:
                st.warning("The actual opening balance date is unknown; review the record before interpreting historical returns.")
            _performance_chart(actual, f"{mode} actual account", f"review_actual_chart_{mode}")
            with st.expander("Actual performance and cash-flow interval audit"):
                st.json(actual, expanded=False)
        else:
            st.info("No observed actual-account performance history yet.")
        st.caption(f"Actual cash: {_currency(ledger.get('cash_balance_inr', ledger.get('cash')))}")
        columns = st.columns(3)
        columns[0].metric("Known realized P&L", _currency(ledger.get("known_realized_pnl_inr")))
        columns[1].metric("Total realized P&L", _currency(ledger.get("realized_pnl_inr")))
        columns[2].metric("Sales with unknown cost", _text(ledger.get("unknown_cost_sales")))
        with st.expander("Actual executed fills"):
            _table(ledger.get("execution_history", []), "No confirmed executions yet.")
        st.caption("Deposits and withdrawals are cash flows, not trading profit. Model and actual records are not combined.")
    with sources_tab:
        for key in ("warnings", "limitations", "data_quality"):
            value = reports.get(key)
            if isinstance(value, dict):
                _table([value])
            elif value:
                _warning_list(value)
        if reports.get("interpretation"):
            st.write(str(reports["interpretation"]))
        comparisons = reports.get("comparisons")
        if comparisons:
            st.markdown("**Stored ranking comparisons**")
            items = comparisons if isinstance(comparisons, list) else [comparisons]
            index = st.selectbox("Stored research record", list(range(len(items))),
                                 format_func=lambda value: str(items[value].get("as_of", items[value].get("key", value))))
            with st.expander("Research definitions, ranks and exclusions"):
                st.json(items[index], expanded=False)
        documents = reports.get("reports", reports.get("documents", []))
        if isinstance(documents, dict):
            documents = [{"title": key, "content": value} for key, value in documents.items()]
        for item in documents or []:
            if isinstance(item, dict):
                with st.expander(str(item.get("title", item.get("name", "Research report")))):
                    st.text(str(item.get("content", item.get("text", item.get("status", "Report content unavailable.")))))
        st.info("Historical backtests remain diagnostic where point-in-time membership, former-constituent history or corporate-action coverage is incomplete.")


def _corporate_actions(service):
    st.markdown("**Corporate actions and data review**")
    notice = st.session_state.pop("corporate_action_notice", None)
    if notice:
        st.success(notice)
    issues = service.corporate_action_issues()
    if not issues:
        st.info("No corporate-action issues have been recorded.")
        return
    _table(issues)
    unresolved = [issue for issue in issues if not issue.get("resolved")]
    references = {str(issue.get("issue_key", issue.get("key", issue.get("id", "")))): issue
                  for issue in unresolved if issue.get("issue_key", issue.get("key", issue.get("id")))}
    if not references:
        st.caption("No unresolved corporate actions with a review reference.")
        return
    selected = st.selectbox("Corporate action to review", list(references),
                            format_func=lambda key: f"{references[key].get('symbol', '—')} · {references[key].get('session', '—')} · {key}",
                            key="corporate_action_selected")
    issue = references[selected]
    action = issue.get("action") or {}
    action_type = str(action.get("type", "") if isinstance(action, dict) else action).lower().replace(" ", "_")
    st.warning("Unresolved actions remain quarantined. Do not infer adjusted quantities, a dividend payment or a model return from a price jump.")
    if action_type not in {"stock_splits", "split", "bonus"}:
        st.info("This action is unsupported for automatic reconciliation and stays blocked pending manual review. "
                "Record a verified cash dividend in the actual journal as a dividend cash event; this form does not infer one.")
        return
    st.caption("Conservative first version: verified splits or bonuses adjust affected actual and model basket quantities and cost basis atomically. "
               "Affected TA reference outcomes become incomplete or invalidated; their original plans and history stay intact. "
               "A fresh data snapshot is required afterward. Fractional share results stay blocked for cash-in-lieu review.")
    with st.form(f"corporate_action_{selected}"):
        kind = st.selectbox("Verified action type", ["SPLIT", "BONUS"], key=f"corp_kind_{selected}")
        ratio = st.number_input("New shares divided by old shares", min_value=0.0, value=0.0, step=0.1,
                                format="%.8f", key=f"corp_ratio_{selected}",
                                help="Example: 2 new shares for each old share means 2.0; a 1-for-2 reverse split means 0.5. A 1-for-1 bonus also gives 2.0 total shares per old share.")
        note = st.text_area("Verified source and reconciliation explanation", key=f"corp_note_{selected}")
        reviewed = st.checkbox("I verified this event, effective date and share ratio.", key=f"corp_reviewed_{selected}")
        confirm_actual = st.checkbox("I confirmed affected actual holdings and authorize this actual-journal reconciliation.",
                                     key=f"corp_actual_{selected}")
        if st.form_submit_button("Confirm corporate-action reconciliation"):
            if not reviewed:
                st.error("Verify the event, effective date and ratio before confirming reconciliation.")
            elif ratio <= 0 or not note.strip():
                st.error("Provide a positive verified share ratio and an explanatory source note.")
            else:
                ok, _ = _action("Corporate-action reconciliation", service.reconcile_corporate_action,
                                selected, kind, ratio, note.strip(), confirm_actual=confirm_actual)
                if ok:
                    st.session_state["corporate_action_notice"] = "Reconciliation recorded. Original decisions remain in the audit; request a fresh EOD refresh before relying on updated marks."
                    st.rerun()


def _settings(service):
    st.subheader("Private settings")
    settings = service.settings() or {}
    st.caption("Capital values below are model assumptions, not actual cash balances. Actual opening cash and executed positions are entered in the journal.")
    with st.form("risk_settings"):
        cols = st.columns(2)
        ta_capital = cols[0].number_input("TA model capital (INR)", min_value=0.0, value=number(settings.get("ta_capital_inr")) or 0.0)
        basket_capital = cols[1].number_input("Momentum model capital (INR)", min_value=0.0, value=number(settings.get("momentum_capital_inr")) or 0.0)
        cols = st.columns(2)
        risk = cols[0].number_input("TA risk per trade (%)", min_value=0.0, max_value=100.0, value=number(settings.get("ta_risk_pct")) or 0.0, step=0.1)
        cap = cols[1].number_input("TA maximum position (%)", min_value=0.0, max_value=100.0, value=number(settings.get("ta_max_position_pct")) or 0.0, step=1.0)
        st.caption("Percent units: 0.5 means 0.5%. Sizing stays unavailable until the required capital, risk and position limit are configured. Changing model capital does not deposit actual cash.")
        if st.form_submit_button("Save risk and capital settings"):
            if min(ta_capital, basket_capital, risk, cap) <= 0:
                st.error("Set positive model capitals, TA risk and maximum position before enabling sizing.")
            else:
                _action("Settings saved", service.update_settings,
                        {"ta_capital_inr": ta_capital, "momentum_capital_inr": basket_capital,
                         "ta_risk_pct": risk, "ta_max_position_pct": cap})
    st.divider()
    st.markdown("**Personal universe**")
    st.caption("Use exchange symbols. Classification keeps commodity ETFs and unknown instruments out of equity-only momentum ranking.")
    with st.form("universe_settings"):
        symbols = st.text_area("Personal symbols, one per line", value="\n".join(settings.get("personal_symbols", [])))
        existing_types = settings.get("instrument_types") or {}
        classifications = st.text_area("Instrument classifications (CSV)",
                                       value="symbol,instrument_type\n" + "\n".join(f"{symbol},{kind}" for symbol, kind in sorted(existing_types.items())),
                                       help="Supported types: equity, equity_etf, commodity_etf, unknown.")
        if st.form_submit_button("Save personal universe"):
            try:
                parsed = csv.DictReader(io.StringIO(classifications))
                if not parsed.fieldnames or not {"symbol", "instrument_type"}.issubset(parsed.fieldnames):
                    raise ValueError("Classification CSV needs symbol,instrument_type columns.")
                types = {}
                for row in parsed:
                    symbol, kind = (row.get("symbol") or "").strip(), (row.get("instrument_type") or "").strip()
                    if not symbol or symbol in types or kind not in {"equity", "equity_etf", "commodity_etf", "unknown"}:
                        raise ValueError("Each classification needs a unique symbol and a supported instrument type.")
                    types[symbol] = kind
            except ValueError as exc:
                _error(exc, "Personal universe")
            else:
                _action("Personal universe saved", service.update_settings,
                        {"personal_symbols": [symbol.strip() for symbol in symbols.splitlines() if symbol.strip()],
                         "instrument_types": types})
    st.divider()
    _corporate_actions(service)
    st.divider()
    _refresh(service, "settings_refresh")
    st.markdown("**Export private records**")
    st.caption("The ZIP contains private journal and tracker data. Keep it in a private location.")
    if st.button("Prepare private export"):
        try:
            st.session_state["tracker_export"] = service.export_bundle()
        except Exception as exc:
            _error(exc, "Export preparation")
    if st.session_state.get("tracker_export") is not None:
        st.download_button("Download private records", st.session_state["tracker_export"],
                           file_name="scanner-tracker-private.zip", mime="application/zip")


def render_app(service):
    st.title("Scanner & Tracker")
    st.caption("Private workspace · End-of-day observations · Model decisions and confirmed executions")
    st.sidebar.markdown("### Scanner & Tracker")
    page = st.sidebar.radio("Workspace", PAGES, label_visibility="collapsed", key="workspace_navigation")
    st.sidebar.caption("EOD only. Prices are not live. No orders are placed by this interface.")
    try:
        status = service.status() or {}
        latest = status.get("latest_run") or {}
        st.sidebar.caption(f"Latest session: {_text(latest.get('as_of', latest.get('session')))}")
        if "shadow_mode" in status:
            st.sidebar.caption(f"Shadow observation flag: {'on' if status['shadow_mode'] else 'off'}")
        if page == "Overview":
            _overview(service, status)
        else:
            {"TA scanner": _ta, "Momentum basket": _momentum, "Watch": _watch,
             "Actual journal": _journal, "Review": _review, "Settings": _settings}[page](service)
    except Exception as exc:
        _error(exc, "Workspace unavailable")
