"""Private tracker commands. All writes target explicit private storage."""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m scanner_tracker")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Apply additive database migrations.")
    commands.add_parser("password-hash", help="Create an owner password hash without echoing the password.")
    commands.add_parser("demo", help="Seed deterministic local-only synthetic data.")
    scan = commands.add_parser("scan")
    scan.add_argument("--as-of")
    scan.add_argument("--mode", choices=["both", "ta", "momentum"], default="both")
    scan.add_argument("--scope", choices=["all", "wide", "personal"], default="all")
    scan.add_argument("--request-id")
    scan.add_argument("--no-sleep", action="store_true", help="For deterministic fixtures only; not recommended for a live provider.")
    backup = commands.add_parser("backup")
    backup.add_argument("--output", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--input", required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--from", dest="start", required=True)
    replay.add_argument("--to", dest="end", required=True)
    replay.add_argument("--capital", type=float, required=True)
    args = parser.parse_args(argv)
    if args.command == "password-hash":
        from .security import hash_password
        password = getpass.getpass("New application password (12+ characters): ")
        if password != getpass.getpass("Confirm password: "):
            raise ValueError("Passwords did not match.")
        print(hash_password(password))
        return 0
    if args.command == "migrate":
        from .service import migrate_database
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise ValueError("DATABASE_URL is required.")
        migrate_database(url)
        print("Tracker schema is current.")
        return 0
    if args.command == "demo":
        if os.environ.get("TRACKER_ENV", "local") != "local":
            raise ValueError("Synthetic demo is local-only.")
        os.environ["TRACKER_DEMO"] = "1"
    from .service import TrackerService
    service = TrackerService.from_env()
    if args.command == "demo":
        from .demo import seed_demo
        seed_demo(service)
        print("Synthetic local demo ready. Run: python -m streamlit run app.py --server.address 127.0.0.1")
    elif args.command == "scan":
        from .worker import run_eod
        report = run_eod(service, as_of=args.as_of, mode=args.mode, scope=args.scope,
                         request_id=args.request_id, sleep=0 if args.no_sleep else 1.5)
        print(json.dumps({"id": report["id"], "as_of": report["as_of"], "status": report["status"],
                          "coverage_pct": report["coverage_pct"], "candidate_count": report["candidate_count"]}))
        return 0 if report["status"] == "complete" else 2
    elif args.command == "backup":
        output = Path(args.output).resolve()
        root = Path(__file__).resolve().parent.parent
        for public in (root / "docs", root / "results"):
            if output == public or public in output.parents:
                raise ValueError("Private backups cannot be written to a public artifact directory.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(service.export_bundle())
        print("Private backup written; store a copy outside this database/project.")
    elif args.command == "restore":
        print(json.dumps(service.restore_bundle(Path(args.input).read_bytes())))
    elif args.command == "replay":
        from .market import BENCHMARK, payload_frame
        from .research import compare_portfolios
        inputs = service.repo.documents("latest_prices")
        frames = {x["key"]: payload_frame(x) for x in inputs if x["key"] != BENCHMARK}
        benchmark = payload_frame(service.repo.prices(BENCHMARK))
        if benchmark.empty:
            raise ValueError("Replay requires stored, source-qualified market history.")
        result = compare_portfolios(frames, benchmark, args.start, args.end, args.capital)
        service.repo.save_document("research", f"replay:{args.start}:{args.end}", result)
        print(json.dumps({"status": "diagnostic_only", "methods": list(result["results"]), "actual_ledgers_changed": False}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.getLogger(__name__).error("Tracker command failed: %s", type(exc).__name__)
        if isinstance(exc, (ValueError, RuntimeError)):
            print(str(exc), file=sys.stderr)
        else:
            print("Operation failed. Check private service diagnostics; credentials are not printed.", file=sys.stderr)
        raise SystemExit(1)
