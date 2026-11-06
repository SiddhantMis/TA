"""Application boundary shared by the private UI, worker and replay commands."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import csv
import io
import json
import logging
import os
from pathlib import Path
import uuid
import zipfile

import pandas as pd
import requests
from sqlalchemy import DateTime, func, select

from .db import Base, assert_ready, make_engine, transaction
from . import models
from .models import Account, BasketSnapshot, Candidate, Document, LedgerEvent, PriceSnapshot, Run, WatchItem
from .repository import TrackerRepository, clean, digest
from .security import secret_value
from .storage import InputArchive
from .market import BENCHMARK, adjustment_status, frame_payload, normalize_frame, payload_frame, symbol_name

LOG = logging.getLogger(__name__)
DEFAULT_SETTINGS = {
    "ta_capital_inr": 0, "ta_risk_pct": 0, "ta_max_position_pct": 0,
    "momentum_capital_inr": 0, "cost_per_side": 0.0015,
    "personal_symbols": [], "instrument_types": {}, "shadow_mode": True,
}


def migrate_database(url):
    from alembic.config import Config
    from alembic import command
    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")


def _mode(value):
    value = str(value).upper()
    if value not in ("TA", "MOMENTUM"):
        raise ValueError("Mode must be TA or MOMENTUM.")
    return value


class TrackerService:
    def __init__(self, database_url, *, initialize=None, archive=None):
        self.database_url = database_url
        self.engine = make_engine(database_url)
        if initialize is True or (initialize is None and self.engine.dialect.name == "sqlite"):
            migrate_database(database_url)
        assert_ready(self.engine)
        self.repo = TrackerRepository(self.engine)
        if archive is None:
            directory = None
            if self.engine.dialect.name == "sqlite":
                dbpath = self.engine.url.database
                directory = Path(dbpath).parent / "inputs" if dbpath and dbpath != ":memory:" else Path(".local/test-inputs")
            archive = InputArchive.from_env(local_directory=directory)
        self.archive = archive

    @classmethod
    def from_env(cls):
        if os.environ.get("TRACKER_DEMO") == "1":
            if secret_value("TRACKER_ENV", "local") != "local" or secret_value("DATABASE_URL"):
                raise ValueError("Demo mode cannot use configured account storage. Unset DATABASE_URL and use the synthetic local database.")
            return cls("sqlite:///.local/demo.db")
        url = secret_value("DATABASE_URL")
        if not url:
            if os.environ.get("TRACKER_DEMO") == "1" and secret_value("TRACKER_ENV", "local") == "local":
                url = "sqlite:///.local/demo.db"
            else:
                raise ValueError("DATABASE_URL is not configured. Add private server secrets before using account data.")
        if secret_value("TRACKER_ENV", "local") == "production" and str(url).startswith("sqlite"):
            raise ValueError("Production requires durable PostgreSQL storage, not an application-local SQLite file.")
        return cls(url)

    def settings(self):
        import analyzer as A
        values = deepcopy(DEFAULT_SETTINGS)
        values["personal_symbols"] = list(A.WATCHLIST)
        values["instrument_types"] = dict(A.INSTRUMENT_TYPE_BY_TICKER)
        values.update(self.repo.document("settings", "owner", {}))
        values["shadow_mode"] = secret_value("TRACKER_SHADOW_MODE", "true").lower() != "false"
        return values

    def update_settings(self, changes):
        allowed = {"ta_capital_inr", "ta_risk_pct", "ta_max_position_pct", "momentum_capital_inr", "personal_symbols", "instrument_types"}
        if set(changes) - allowed:
            raise ValueError("Settings contain unsupported or strategy-changing fields.")
        values = self.settings()
        for key, value in changes.items():
            if key in {"personal_symbols", "instrument_types"}:
                continue
            from .ledger import decimal
            number = decimal(value, key)
            if key.endswith("_pct") and number > 100:
                raise ValueError("Risk and allocation percentages cannot exceed 100%.")
            if key == "momentum_capital_inr" and values[key] != float(number):
                for scope in ("wide", "personal"):
                    report = self.momentum_report(scope)
                    model = report.get("model") or {}
                    if model.get("capital_configured") or (model.get("ledger") or {}).get("execution_history"):
                        raise ValueError("A running model's starting capital is fixed. Export it and create a new model version to restart.")
            values[key] = float(number)
        if "personal_symbols" in changes:
            values["personal_symbols"] = list(dict.fromkeys(symbol_name(x) for x in changes["personal_symbols"]))
        if "instrument_types" in changes:
            types = {symbol_name(k): v for k, v in changes["instrument_types"].items()}
            if any(v not in {"equity", "commodity_etf", "equity_etf", "unknown"} for v in types.values()):
                raise ValueError("Unsupported instrument classification.")
            values["instrument_types"] = types
        import analyzer as A
        import leaders
        known = set(A.WATCHLIST) | set(leaders.load_universe())
        for symbol in values["personal_symbols"]:
            if symbol not in known and values["instrument_types"].get(symbol, "unknown") == "unknown":
                raise ValueError(f"Classify {symbol} as an equity or ETF before adding it to the scan universe.")
        self.repo.save_document("settings", "owner", values)
        return values

    def status(self):
        runs = self.repo.runs()
        complete = next((x for x in runs if x["status"] == "complete"), None)
        candidates = self.repo.candidates()
        return {"latest_run": runs[0] if runs else None, "latest_success": complete,
                "counts": {"candidates": len(candidates), "watched": len(self.repo.watch_items()),
                           "open_models": sum(x["status"] == "model_open" for x in candidates)},
                "health": {"status": "not_run" if not runs else runs[0]["status"],
                           "issues": self.repo.documents("data_issues"), "background_tasks": self.repo.documents("health")},
                "shadow_mode": self.settings()["shadow_mode"], "storage": self.storage_usage(),
                "notifications": self.repo.document("health", "notifications", {"status": "not_configured"})}

    def storage_usage(self):
        with self.engine.connect() as connection:
            if self.engine.dialect.name == "postgresql":
                from sqlalchemy import text
                database_bytes = int(connection.execute(text("SELECT pg_database_size(current_database())")).scalar())
            else:
                path = Path(self.engine.url.database or "")
                database_bytes = path.stat().st_size if path.is_file() else 0
            key = PriceSnapshot.payload["archive_key"].as_string()
            size = PriceSnapshot.payload["archive_bytes"].as_integer()
            objects = list(connection.execute(select(key, size).distinct()))
        tracked = sum(size for key, size in objects if key and size is not None)
        unknown = sum(1 for key, size in objects if key and size is None)
        fraction = database_bytes / (500 * 1024 ** 2)
        return {"database_bytes": database_bytes, "tracked_input_archive_bytes": tracked,
                "archive_objects_without_size": unknown, "free_database_reference_bytes": 500 * 1024 ** 2,
                "free_storage_reference_bytes": 1024 ** 3,
                "status": "quota_warning" if fraction >= 0.8 or tracked >= 0.8 * 1024 ** 3 else "within_reference_limits",
                "basis": "Tracked objects only; Supabase dashboard is authoritative for quotas, orphaned uploads and other project usage."}

    def candidates(self, mode="TA", scope=None, status=None):
        return [self._candidate_view(x, include_bars=False) for x in self.repo.candidates(_mode(mode), status=status, scope=scope)]

    def _candidate_view(self, candidate, include_bars=True):
        value = deepcopy(candidate)
        value.update(ticker=value["symbol"], signal_date=value["signal_session"], scope=", ".join(value.get("scopes", [])))
        value["history"] = value.get("events", [])
        value["current_plan"] = value.get("current", {})
        watched = next((x for x in self.repo.watch_items() if x["id"] == value["id"]), None)
        value["watched"], value["note"] = bool(watched), watched.get("note", "") if watched else ""
        if include_bars:
            bars = self.repo.prices(value["symbol"]).get("bars", [])
            value["bars"] = [{"date": x["date"], **{k.lower(): v for k, v in x.items() if k != "date"}} for x in bars]
            account = self.repo.account("TA") or {}
            value["fills"] = [x for x in account.get("execution_history", []) if x.get("signal_id") == value["id"]]
        value["sizing"] = self._sizing(value)
        return value

    def candidate(self, candidate_id):
        candidate = self.repo.candidate(candidate_id)
        if not candidate:
            raise ValueError("Unknown candidate.")
        return self._candidate_view(candidate)

    def _sizing(self, candidate):
        values = self.settings()
        capital, risk_pct, cap_pct = (float(values.get(x) or 0) for x in ("ta_capital_inr", "ta_risk_pct", "ta_max_position_pct"))
        if min(capital, risk_pct, cap_pct) <= 0:
            return {"status": "unconfigured", "reason": "Configure allocated capital, per-trade risk and maximum position percentage."}
        if candidate.get("current", {}).get("data_status") != "complete":
            return {"status": "unavailable", "reason": "Current setup data is unavailable; no position quantity is proposed."}
        plan = candidate.get("original_plan", {})
        entry = (candidate.get("model_trade") or {}).get("entry_price") or candidate.get("current", {}).get("close") or plan.get("entry")
        stop = (candidate.get("model_trade") or {}).get("initial_stop") or plan.get("stop")
        if stop is None and entry and plan.get("signal_atr"):
            stop = float(entry) - 2 * float(plan["signal_atr"])
        if not entry or not stop or not float(entry) > float(stop) > 0:
            return {"status": "unavailable", "reason": "No valid entry/stop pair."}
        ledger = self.repo.account("TA")
        available = float(ledger["cash_balance_inr"]) if ledger else capital
        held = (ledger or {}).get("holdings", {}).get(candidate["symbol"], {}).get("quantity", 0)
        headroom = max(0, capital * cap_pct / 100 - int(held) * float(entry))
        risk_with_costs = float(entry) - float(stop) + (float(entry) + float(stop)) * 0.0015
        quantity = int(min(capital * risk_pct / 100 / risk_with_costs,
                           headroom / float(entry), available / (float(entry) * 1.0015)))
        return {"status": "reference_only", "quantity": max(0, quantity), "reference_entry": entry,
                "risk_budget_inr": capital * risk_pct / 100, "existing_quantity": held,
                "reason": "Uses EOD prices, estimated costs and remaining symbol allocation; gaps can exceed the stop scenario. No cash reservation or order placement."}

    def watch_items(self):
        return [self._candidate_view(x, include_bars=False) for x in self.repo.watch_items()]

    def set_watch(self, candidate_id, watched=True, note=None):
        if note is not None and len(str(note)) > 5000:
            raise ValueError("Notes are limited to 5,000 characters.")
        self.repo.set_watch(candidate_id, watched, note)
        if note:
            self.save_note(candidate_id, note)

    def save_note(self, candidate_id, text):
        value = str(text).strip()
        if not value or len(value) > 5000:
            raise ValueError("Enter a note of 1–5,000 characters.")
        with transaction(self.engine) as session:
            record = session.scalar(select(Candidate).where(Candidate.id == candidate_id).with_for_update())
            if not record:
                raise ValueError("Unknown candidate.")
            candidate = deepcopy(record.payload)
            candidate.setdefault("events", []).append({"type": "note", "session": datetime.now(timezone.utc).date().isoformat(),
                "details": {"text": value, "recorded_at": datetime.now(timezone.utc).isoformat()}})
            self.repo.put_candidate(session, candidate)

    def momentum_report(self, scope="wide"):
        report = self.repo.document("momentum", scope, {})
        actual = self.repo.account("MOMENTUM") if scope == "wide" else None
        if report and actual:
            from .momentum import reconcile_actual_proposals
            inputs = self.repo.documents("latest_prices")
            frames = {item["key"]: payload_frame(item).loc[:report["as_of"]] for item in inputs if item.get("bars")}
            reconciled = reconcile_actual_proposals(actual, report.get("actual_target"), frames, report["as_of"])
            report["proposals"] = reconciled["proposals"]
            report["proposal_status"] = reconciled["status"]
            report["proposal_funding"] = reconciled
            report["proposal_basis"] = "Frozen target, current confirmed holdings and latest stored EOD reference prices; no order placement."
        return report

    def ledger(self, mode):
        from .ledger import new_ledger
        mode = _mode(mode)
        return self.repo.account(mode) or dict(new_ledger(mode, 0), configured=False)

    def configure_ledger(self, mode, opening_cash, positions=None, kind="actual", as_of=None):
        from .ledger import new_ledger, configure_opening_positions
        mode = _mode(mode)
        if kind != "actual":
            raise ValueError("Configure actual accounts here; model capital has a separate setting.")
        def operation(old):
            if old is not None:
                raise ValueError("Opening balances are immutable. Record a deposit, withdrawal or correction instead.")
            state = new_ledger(mode, opening_cash)
            from .market import IST
            state["opening_as_of"] = pd.Timestamp(as_of).date().isoformat() if as_of else datetime.now(IST).date().isoformat()
            if state["opening_as_of"] > datetime.now(IST).date().isoformat():
                raise ValueError("Actual opening balances cannot be dated in the future.")
            if positions:
                prepared = {symbol_name(k): v for k, v in positions.items()} if isinstance(positions, dict) else positions
                state = configure_opening_positions(state, prepared, as_of=state["opening_as_of"])
            state["configured"] = True
            return state
        return self.repo.change_account(mode, operation, create=True)

    def record_fill(self, mode, fill):
        from .ledger import record_fill
        mode = _mode(mode)
        value = dict(fill)
        value["mode"] = mode
        value["symbol"] = symbol_name(value.get("symbol") or value.get("ticker") or "")
        self._validate_actual_time(value.get("executed_at"))
        for canonical, alias in (("execution_id", "event_id"), ("price_inr", "price"), ("fees_inr", "fees")):
            if canonical not in value and alias in value:
                value[canonical] = value.pop(alias)
        if value.get("signal_id"):
            candidate = self.repo.candidate(value["signal_id"])
            if not candidate or candidate["symbol"] != value["symbol"] or mode != "TA":
                raise ValueError("The linked idea must be a TA setup for this exact symbol.")
        result = self.repo.change_account(mode, lambda state: record_fill(state, value))
        result["valuation_refresh"] = self._refresh_cached_valuations()
        return result

    def correct_fill(self, mode, execution_id, correction_id, replacement=None):
        from .ledger import correct_fill
        mode = _mode(mode)
        if replacement:
            replacement = dict(replacement)
            replacement["mode"] = mode
            replacement["symbol"] = symbol_name(replacement.get("symbol", ""))
            self._validate_actual_time(replacement.get("executed_at"))
            self._validate_signal_link(mode, replacement)
        result = self.repo.change_account(mode, lambda state: correct_fill(state, execution_id, correction_id, replacement))
        result["valuation_refresh"] = self._refresh_cached_valuations()
        return result

    def _validate_signal_link(self, mode, value):
        if value.get("signal_id"):
            candidate = self.repo.candidate(value["signal_id"])
            if not candidate or candidate["symbol"] != value["symbol"] or mode != "TA":
                raise ValueError("The linked idea must be a TA setup for this exact symbol.")

    @staticmethod
    def _validate_actual_time(value):
        from .market import IST
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise ValueError("Actual executions and cash movements require a valid date.")
        stamp = stamp.tz_localize(IST) if stamp.tzinfo is None else stamp.tz_convert(IST)
        if stamp > pd.Timestamp(datetime.now(IST)):
            raise ValueError("A future event cannot be recorded as an already-confirmed actual execution or cash movement.")

    def _canonical_csv(self, mode, text):
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        if not reader.fieldnames:
            raise ValueError("CSV requires a header.")
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            if str(row.get("mode", "")).upper() != mode:
                raise ValueError("Every imported execution must match the selected mode.")
            row["symbol"] = symbol_name(row.get("symbol", ""))
            self._validate_actual_time(row.get("executed_at"))
            self._validate_signal_link(mode, row)
            writer.writerow(row)
        return output.getvalue()

    def preview_import(self, mode, text):
        from .ledger import import_fills_csv
        mode = _mode(mode)
        state = self.repo.account(mode)
        if state is None:
            return {"valid": False, "rows": [], "errors": ["Configure opening balances first."]}
        try:
            return clean(import_fills_csv(state, self._canonical_csv(mode, text), commit=False))
        except ValueError as exc:
            return {"valid": False, "rows": [], "errors": [str(exc)]}

    def commit_import(self, mode, text):
        from .ledger import import_fills_csv
        mode = _mode(mode)
        text = self._canonical_csv(mode, text)
        result = {}
        def operation(state):
            result.update(import_fills_csv(state, text, commit=True))
            if not result.get("valid"):
                raise ValueError("CSV validation failed: " + "; ".join(str(x) for x in result.get("errors", [])))
            return result["state"]
        self.repo.change_account(mode, operation)
        result["valuation_refresh"] = self._refresh_cached_valuations()
        return clean(result)

    def cash_event(self, mode, event):
        from .ledger import record_cash_event
        value = dict(event)
        self._validate_actual_time(value.get("executed_at"))
        if value.get("symbol"):
            value["symbol"] = symbol_name(value["symbol"])
        if "cash_type" not in value:
            value["cash_type"] = value.pop("type", "")
        if "amount_inr" not in value:
            value["amount_inr"] = value.pop("amount", None)
        result = self.repo.change_account(_mode(mode), lambda state: record_cash_event(state, value))
        result["valuation_refresh"] = self._refresh_cached_valuations()
        return result

    def transfer(self, amount, from_mode, to_mode, event_id, executed_at):
        from .ledger import decimal, record_cash_event
        first, second = _mode(from_mode), _mode(to_mode)
        self._validate_actual_time(executed_at)
        if first == second:
            raise ValueError("A transfer requires two different allocations.")
        amount = str(decimal(amount, "transfer", positive=True))
        with transaction(self.engine) as session:
            accounts = {x.mode: x for x in session.scalars(select(Account).where(Account.kind == "actual").order_by(Account.id).with_for_update())}
            if first not in accounts or second not in accounts:
                raise ValueError("Configure both allocations before transferring cash.")
            for mode, kind in ((first, "WITHDRAWAL"), (second, "DEPOSIT")):
                accounts[mode].payload = record_cash_event(accounts[mode].payload,
                    {"event_id": f"transfer:{event_id}:{mode}", "cash_type": kind, "amount_inr": amount,
                     "executed_at": executed_at, "note": f"Transfer {first} -> {second}"})
                accounts[mode].revision += 1
                item = accounts[mode].payload["events"][-1]
                external_id = item.get("event_id") or digest(item)
                saved_id = digest([accounts[mode].id, external_id])
                if session.get(LedgerEvent, saved_id) is None:
                    session.add(LedgerEvent(id=saved_id, account_id=accounts[mode].id, external_id=external_id, payload=item))
            return {"status": "recorded", "amount_inr": amount, "from_mode": first, "to_mode": second}

    def request_refresh(self):
        token = secret_value("GITHUB_DISPATCH_TOKEN")
        repository = secret_value("GITHUB_REPOSITORY", "SiddhantMis/TA")
        if not token:
            return {"status": "manual_setup_required", "url": f"https://github.com/{repository}/actions/workflows/tracker-eod.yml",
                    "message": "Run the tracker workflow manually, or configure a server-side Actions dispatch token."}
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid GitHub repository configuration.")
        request_id = uuid.uuid4().hex
        try:
            response = requests.post(f"https://api.github.com/repos/{repository}/actions/workflows/tracker-eod.yml/dispatches",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                json={"ref": "main", "inputs": {"request_id": request_id,
                      "environment": secret_value("TRACKER_ENV", "staging")}}, timeout=20)
        except requests.RequestException as exc:
            raise RuntimeError("The scan request could not reach GitHub. No account state changed.") from exc
        if response.status_code != 204:
            raise RuntimeError(f"GitHub rejected the scan request (HTTP {response.status_code}). Check Actions permissions.")
        self.repo.save_document("job_requests", request_id, {"status": "queued", "requested_at": datetime.now(timezone.utc).isoformat()})
        return {"status": "queued", "request_id": request_id}

    def research_reports(self):
        from .performance import summarize_ta, account_performance, summarize_momentum
        candidates = self.repo.candidates("TA")
        closed = [x for x in candidates if (x.get("model_trade") or {}).get("net_R") is not None]
        groups = {}
        for family in ("reversal", "breakout55", "pullback20"):
            cohort = [x for x in candidates if x["family"] == family]
            outcomes = [float(x["model_trade"]["net_R"]) for x in closed if x["family"] == family]
            groups[family] = {"candidates": len(cohort), "closed": len(outcomes),
                "mean_net_R": sum(outcomes) / len(outcomes) if outcomes else None,
                "win_rate_pct": 100 * sum(x > 0 for x in outcomes) / len(outcomes) if outcomes else None,
                "statuses": {state: sum(x["status"] == state for x in cohort) for state in sorted({x["status"] for x in cohort})}}
        valuations = self.repo.documents("valuations")
        actual = {mode: account_performance([x for x in valuations if x["mode"] == mode], self.ledger(mode))
                  for mode in ("TA", "MOMENTUM")}
        return {"ta": groups, "ta_detailed": summarize_ta(candidates),
                "momentum": self.repo.documents("momentum"),
                "momentum_performance": {scope: summarize_momentum(self.momentum_report(scope)) for scope in ("wide", "personal")},
                "actual": actual,
                "comparisons": self.repo.documents("research"),
                "interpretation": "TA outcomes are independent unit-risk observations, not a funded portfolio. Historical current-constituent comparisons are diagnostic, not decision-grade."}

    def scan_frames(self, frames, benchmark_frame, as_of, *, scopes=None, diagnostics=None, source="provided", request_id=None, mode="both"):
        from .ta import scan_ta
        from .momentum import run_momentum
        from .research import compare_momentum_rankings
        as_of = pd.Timestamp(as_of).date().isoformat()
        if mode not in {"both", "ta", "momentum"}:
            raise ValueError("Scan mode must be both, ta or momentum.")
        newer = [x for x in self.repo.runs() if x["status"] in {"complete", "partial"} and x["as_of"] > as_of]
        if newer:
            raise ValueError("An operational scan cannot move persisted state backward. Use the isolated replay command for historical research.")
        scopes = scopes or {"wide": list(frames)}
        scopes = {key: sorted(set(value)) for key, value in scopes.items()}
        diagnostics = deepcopy(diagnostics or {})
        benchmark = normalize_frame(benchmark_frame, as_of)
        input_refs, usable = {}, {}
        if benchmark.empty or benchmark.index[-1] != pd.Timestamp(as_of):
            raise ValueError("Benchmark lacks the exact requested completed session; refusing stale publication.")
        for symbol, frame in {BENCHMARK: benchmark, **frames}.items():
            try:
                data = normalize_frame(frame, as_of)
                payload = frame_payload(data, source)
                key = self.archive.put(payload)
                payload.update(archive_key=key, archive_bytes=self.archive.last_put_bytes, as_of=as_of)
                input_refs[symbol] = self.repo.save_snapshot(symbol, as_of, payload)
                if data.empty or data.index[-1] != pd.Timestamp(as_of):
                    raise ValueError("The exact requested stock session is missing.")
                if symbol != BENCHMARK:
                    usable[symbol] = data
            except ValueError as exc:
                diagnostics[symbol] = str(exc)
        settings = self.settings()
        import analyzer as A
        import leaders
        known_equities = set(leaders.load_universe()) | (set(A.WATCHLIST) - set(A.INSTRUMENT_TYPE_BY_TICKER))
        known_equities.update(scopes.get("wide", []))
        def is_equity(symbol):
            classification = settings["instrument_types"].get(symbol)
            return classification == "equity" or (classification is None and symbol in known_equities)
        last_run = next((x for x in self.repo.runs() if x["status"] == "complete" and x["as_of"] < as_of), None)
        all_existing = self.repo.candidates("TA")
        for symbol, data in list(usable.items()):
            since = last_run["as_of"] if last_run else as_of
            pending = [x for x in all_existing if x["symbol"] == symbol and x["status"] not in {"closed", "expired", "invalidated", "skipped"}]
            if pending:
                since = min(since, min(x["signal_session"] for x in pending))
            actions = adjustment_status(data, since)
            unresolved = [x for x in self.repo.documents("data_issues") if x.get("symbol") == symbol and not x.get("resolved")]
            for session, action in actions.items():
                issue_key = digest([symbol, session, action])
                old = self.repo.document("data_issues", issue_key)
                if old is None:
                    self.repo.save_document("data_issues", issue_key,
                        {"symbol": symbol, "session": session, "action": action, "resolved": False,
                         "reason": "Corporate action requires explicit quantity/level reconciliation."})
                    unresolved.append({"session": session})
            if unresolved:
                diagnostics[symbol] = "Corporate action unresolved; plans and account marks are quarantined."
                del usable[symbol]
        candidates = []
        ta_runs = [run for run in self.repo.runs(1000) if run["status"] in {"complete", "partial"}
                   and run.get("mode") in {"both", "ta"} and run["as_of"] < as_of]
        symbols = sorted(set().union(*map(set, scopes.values()), {x["symbol"] for x in all_existing}))
        for symbol in symbols if mode != "momentum" else []:
            existing = [x for x in all_existing if x["symbol"] == symbol and (x["status"] not in {"closed", "expired", "invalidated", "skipped"} or x["signal_session"] == as_of)]
            frame = usable.get(symbol, pd.DataFrame())
            checkpoint = self.repo.document("ta_checkpoints", symbol)
            if checkpoint is None:
                eligible_runs = [run for run in ta_runs if symbol not in run.get("diagnostics", {})
                                 and any(symbol in members for members in run.get("scopes", {}).values())]
                if eligible_runs:
                    checkpoint = max(eligible_runs, key=lambda run: run["as_of"])
            if checkpoint and checkpoint["as_of"] < as_of and not frame.empty:
                frame.attrs["scan_start_session"] = checkpoint["as_of"]
            generated = scan_ta(symbol, frame, benchmark, existing, as_of)
            for item in generated:
                item["scopes"] = sorted(scope for scope, members in scopes.items() if symbol in members)
                item.setdefault("input_refs", {key: input_refs[key] for key in (symbol, BENCHMARK) if key in input_refs})
                item.setdefault("decision_timestamp", datetime.now(timezone.utc).isoformat())
                item.setdefault("reconstructed", item["signal_session"] != as_of)
            candidates.extend(generated)
        reports = {}
        actual = self.repo.account("MOMENTUM")
        if actual is not None:
            from .ledger import ledger_as_of
            actual = ledger_as_of(actual, as_of)
            if actual.get("projection_status") == "BEFORE_OPENING":
                actual = None
        for scope, members in scopes.items() if mode != "ta" else []:
            market_frames = dict(usable)
            equity_universe = [symbol for symbol in members if is_equity(symbol)]
            expected = len(equity_universe)
            old = self.momentum_report(scope)
            reports[scope] = clean(run_momentum(market_frames, benchmark, as_of, previous_model=old.get("model"),
                actual_ledger=actual if scope == "wide" else None,
                model_capital=settings.get("momentum_capital_inr") or None, universe_size=expected, universe_symbols=equity_universe))
            reports[scope]["scope"] = scope
        run_id = digest([as_of, mode, scopes, input_refs, "tracker-v1"])
        requested = set().union(*map(set, scopes.values()))
        coverage = 100 * len(requested.intersection(usable)) / len(requested) if requested else 0
        status = "complete" if coverage >= 95 else "partial"
        payload = {"source": source, "mode": mode, "input_refs": input_refs, "scopes": scopes, "coverage_pct": coverage,
                   "diagnostics": diagnostics, "candidate_count": len(candidates), "request_id": request_id,
                   "rule_version": "tracker-v1", "code_revision": os.environ.get("GITHUB_SHA", "local-working-tree"),
                   "calendar": "NSE completed-session calendar", "published_at": datetime.now(timezone.utc).isoformat()}
        research_scope = scopes.get("wide", scopes.get("personal", []))
        comparison = compare_momentum_rankings({s: usable[s] for s in research_scope if s in usable and is_equity(s)}, benchmark, as_of)
        valuations = self._record_actual_valuations(usable, as_of, persist=False)
        with transaction(self.engine) as session:
            if self.engine.dialect.name == "postgresql":
                from sqlalchemy import text
                session.execute(text("SELECT pg_advisory_xact_lock(739211)"))
            for item in candidates:
                self.repo.put_candidate(session, item)
            if mode != "momentum":
                for symbol in symbols:
                    if symbol in usable:
                        self.repo.put_document(session, "ta_checkpoints", symbol, {"as_of": as_of, "run_id": run_id})
            for scope, report in reports.items():
                self.repo.put_document(session, "momentum", scope, report)
                basket_id = digest([scope, report])
                if session.get(BasketSnapshot, basket_id) is None:
                    session.add(BasketSnapshot(id=basket_id, scope=scope, as_of=as_of, payload=report))
            if session.get(Run, run_id) is None:
                session.add(Run(id=run_id, as_of=as_of, status=status, payload=clean(payload)))
            self.repo.put_document(session, "research", as_of, comparison)
            for mark in valuations:
                self._save_valuation(session, mark)
            if request_id:
                self.repo.put_document(session, "job_requests", request_id, {"status": status, "run_id": run_id, "as_of": as_of})
        return dict(payload, id=run_id, as_of=as_of, status=status)

    def _record_actual_valuations(self, frames, as_of, persist=True):
        from .ledger import ledger_as_of
        from .market import expected_sessions
        results = []
        for mode in ("TA", "MOMENTUM"):
            source = self.repo.account(mode)
            if source is None:
                continue
            start = min(source.get("opening_as_of") or as_of, as_of)
            dates = list(expected_sessions(start, as_of))
            if pd.Timestamp(as_of) not in dates:
                dates.append(pd.Timestamp(as_of))
            for stamp in sorted(dates):
                day = stamp.date().isoformat()
                state = ledger_as_of(source, day)
                if state.get("projection_status") in {"unavailable", "BEFORE_OPENING"}:
                    mark = {"mode": mode, "as_of": day, "complete": False, "equity_inr": None,
                            "reason": "Opening balances are not known for this session."}
                else:
                    missing = [symbol for symbol in state.get("holdings", {}) if symbol not in frames or stamp not in frames[symbol].index]
                    value = Decimal(state["cash_balance_inr"])
                    if not missing:
                        for symbol, holding in state.get("holdings", {}).items():
                            value += Decimal(str(frames[symbol].loc[stamp, "Close"])) * int(holding["quantity"])
                    mark = {"mode": mode, "as_of": day, "complete": not missing,
                            "equity_inr": str(value) if not missing else None, "missing_symbols": missing,
                            "cash_balance_inr": state["cash_balance_inr"],
                            "valuation_basis": "reported EOD observations and executions effective by this date"}
                results.append(mark)
                if persist:
                    with transaction(self.engine) as session:
                        self._save_valuation(session, mark)
        return results

    def _save_valuation(self, session, mark):
        key = f"{mark['mode']}:{mark['as_of']}"
        previous = session.scalar(select(Document).where(Document.namespace == "valuations", Document.key == key).with_for_update())
        if previous and previous.payload != mark:
            self.repo.put_document(session, "valuation_revisions", digest([key, previous.payload]),
                {"mode": mark["mode"], "as_of": mark["as_of"], "original": previous.payload,
                 "reason": "Recorded executions, cash movements or qualified input history changed.",
                 "revised_at": datetime.now(timezone.utc).isoformat()})
        self.repo.put_document(session, "valuations", key, mark)

    def _refresh_cached_valuations(self):
        try:
            benchmark = self.repo.prices(BENCHMARK)
            if not benchmark.get("bars"):
                return {"status": "awaiting_market_data"}
            day = benchmark["bars"][-1]["date"]
            blocked = {x["symbol"] for x in self.repo.documents("data_issues") if not x.get("resolved")}
            frames = {x["key"]: payload_frame(x) for x in self.repo.documents("latest_prices") if x.get("bars") and x["key"] not in blocked}
            self._record_actual_valuations(frames, day)
            result = {"status": "complete", "as_of": day}
            self.repo.save_document("health", "valuations", result)
            return result
        except Exception as exc:
            LOG.error("Private valuation refresh failed (%s); confirmed ledger entries are preserved.", type(exc).__name__)
            result = {"status": "failed", "error": type(exc).__name__, "message": "Execution saved; valuation recalculation needs review."}
            try:
                self.repo.save_document("health", "valuations", result)
            except Exception as persistence_error:
                LOG.error("Could not persist valuation health status (%s).", type(persistence_error).__name__)
            return result

    def corporate_action_issues(self):
        return self.repo.documents("data_issues")

    def reconcile_corporate_action(self, issue_key, action_type, ratio, note, confirm_actual=False):
        from .ledger import record_corporate_action, decimal
        action_type = str(action_type).upper()
        if action_type not in {"SPLIT", "BONUS"}:
            raise ValueError("Only a confirmed split or bonus ratio can be reconciled here. Other actions remain blocked.")
        ratio = str(decimal(ratio, "new shares / old shares", positive=True))
        if len(str(note).strip()) < 5:
            raise ValueError("Record the source and reason for the corporate-action confirmation.")
        with transaction(self.engine) as session:
            issue = session.scalar(select(Document).where(Document.namespace == "data_issues", Document.key == issue_key).with_for_update())
            if issue is None:
                raise ValueError("Unknown corporate-action review item.")
            if issue.payload.get("resolved"):
                return {"status": "already_reconciled"}
            symbol, when = issue.payload["symbol"], issue.payload["session"]
            action = issue.payload.get("action") or {}
            if action.get("type") not in {"Stock Splits", "split", "bonus", "SPLIT", "BONUS"}:
                raise ValueError("This source action is unsupported and cannot be relabelled as a split or bonus.")
            accounts = list(session.scalars(select(Account).where(Account.kind == "actual").order_by(Account.id).with_for_update()))
            if not confirm_actual and any(symbol in x.payload.get("holdings", {}) for x in accounts):
                raise ValueError("Explicitly confirm the adjustment to recorded actual positions.")
            event = {"event_id": f"corporate:{issue_key}", "executed_at": when, "symbol": symbol,
                     "action_type": action_type, "ratio": ratio, "note": str(note).strip()}
            for account in accounts:
                if symbol in account.payload.get("holdings", {}):
                    account.payload = record_corporate_action(account.payload, event)
                    account.revision += 1
                    event_id = digest([account.id, event["event_id"]])
                    if session.get(LedgerEvent, event_id) is None:
                        session.add(LedgerEvent(id=event_id, account_id=account.id, external_id=event["event_id"], payload=event))
            for document in session.scalars(select(Document).where(Document.namespace == "momentum").with_for_update()):
                report = deepcopy(document.payload)
                model = report.get("model") or {}
                if symbol in (model.get("ledger") or {}).get("holdings", {}):
                    model["ledger"] = record_corporate_action(model["ledger"], event)
                    model["pending_rebalance"] = None
                    model.setdefault("history", []).append({"as_of": when, "equity_inr": None, "complete": False,
                        "status": "CORPORATE_ACTION_RECONCILIATION", "reason": str(note).strip()})
                    report["model"] = model
                    document.payload = report
            for record in session.scalars(select(Candidate).where(Candidate.symbol == symbol).with_for_update()):
                if record.status not in {"closed", "expired", "invalidated", "skipped"}:
                    candidate = deepcopy(record.payload)
                    candidate["status"] = "invalidated"
                    candidate.setdefault("events", []).append({"type": "corporate_action_reconciled", "session": when,
                        "details": {"note": note, "reference_outcome": "incomplete; no inferred entitlement or exit fill"}})
                    if candidate.get("model_trade"):
                        candidate["model_trade"].update(net_R=None, exit_reason="corporate_action_incomplete", incomplete=True)
                    self.repo.put_candidate(session, candidate)
            issue.payload = dict(issue.payload, resolved=True, resolution=event,
                                 resolved_at=datetime.now(timezone.utc).isoformat())
            cached = session.scalar(select(Document).where(Document.namespace == "latest_prices", Document.key == symbol))
            if cached:
                cached.payload = dict(cached.payload, bars=[], cache_invalidated="corporate_action_reconciliation")
            return {"status": "reconciled", "symbol": symbol, "ratio": ratio}

    def export_bundle(self):
        records, keys = {}, set()
        with transaction(self.engine, isolation="REPEATABLE READ") as session:
            for table in Base.metadata.sorted_tables:
                rows = [clean(dict(row)) for row in session.execute(select(table)).mappings()]
                records[table.name] = rows
                for row in rows:
                    payload = row.get("payload") or {}
                    if isinstance(payload, dict) and payload.get("archive_key"):
                        keys.add(payload["archive_key"])
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("tracker.json", json.dumps({"schema_version": 1, "exported_at": datetime.now(timezone.utc).isoformat(), "records": records}, allow_nan=False))
            for key in sorted(keys):
                bundle.writestr("inputs/" + key, self.archive.get_bytes(key))
        return output.getvalue()

    def restore_bundle(self, data):
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            if sum(info.file_size for info in bundle.infolist()) > 250_000_000:
                raise ValueError("Backup exceeds the safe import size limit.")
            manifest = json.loads(bundle.read("tracker.json"))
            if manifest.get("schema_version") != 1 or set(manifest.get("records", {})) != set(Base.metadata.tables):
                raise ValueError("Unsupported backup schema.")
            names = bundle.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Backup contains duplicate archive members.")
            required_inputs = set()
            for rows in manifest["records"].values():
                for row in rows:
                    payload = row.get("payload") or {}
                    if isinstance(payload, dict) and payload.get("archive_key"):
                        required_inputs.add(payload["archive_key"])
            available_inputs = {name[len("inputs/"):] for name in names if name.startswith("inputs/")}
            if required_inputs - available_inputs:
                raise ValueError("Backup is incomplete: one or more referenced market-input archives are missing.")
            import gzip
            import hashlib
            for key in available_inputs:
                self.archive._validate(key)
                if hashlib.sha256(gzip.decompress(bundle.read("inputs/" + key))).hexdigest() != key[:64]:
                    raise ValueError("Backup input checksum mismatch.")
            for row in manifest["records"]["tracker_accounts"]:
                from .ledger import _check_state, _rebuild
                state = deepcopy(row["payload"])
                _check_state(state)
                _rebuild(state)
                if state["cash_balance_inr"] != row["payload"]["cash_balance_inr"] or state["holdings"] != row["payload"]["holdings"]:
                    raise ValueError("Backup ledger projection does not match its recorded events.")
            with transaction(self.engine) as session:
                for table in Base.metadata.sorted_tables:
                    if session.scalar(select(func.count()).select_from(table)):
                        raise ValueError("Restore requires an empty tracker database; no existing records were changed.")
                for name in bundle.namelist():
                    if name.startswith("inputs/"):
                        self.archive.put_bytes(name[len("inputs/"):], bundle.read(name))
                for table in Base.metadata.sorted_tables:
                    rows = manifest["records"][table.name]
                    for row in rows:
                        for column in table.columns:
                            if isinstance(column.type, DateTime) and row.get(column.name):
                                row[column.name] = datetime.fromisoformat(row[column.name])
                    if rows:
                        session.execute(table.insert(), rows)
                if self.engine.dialect.name == "postgresql":
                    from sqlalchemy import text
                    for table in Base.metadata.sorted_tables:
                        for column in table.primary_key.columns:
                            if column.name == "id" and str(column.type) == "INTEGER":
                                sequence = session.execute(text("SELECT pg_get_serial_sequence(:table, :column)"),
                                    {"table": table.name, "column": column.name}).scalar()
                                if sequence:
                                    maximum = session.scalar(select(func.max(column))) or 1
                                    session.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, true)"),
                                                    {"sequence": sequence, "value": maximum})
        return {"status": "restored", "tables": len(manifest["records"])}
