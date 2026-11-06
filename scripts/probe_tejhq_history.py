#!/usr/bin/env python3
"""Probe missing PIT Nifty 500 histories against TejHQ's NSE bhavcopy-backed API.

This is a coverage-only diagnostic. It deliberately does not save OHLCV rows or
feed raw, as-traded prices into the adjusted-price backtest.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from tej import Client


def read_missing(path: Path, end_date: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [
        row for row in rows
        if row.get("overlaps_test_window", "").strip().lower() == "true"
        and row.get("load_status") in {"no_history", "insufficient_history"}
        and row.get("membership_first", "") <= end_date
    ]


def probe(rows: list[dict[str, str]], start_date: str, end_date: str,
          client: Client, pause: float = 0.55) -> list[dict[str, object]]:
    results = []
    for position, row in enumerate(rows, start=1):
        symbol = row["symbol"].strip().upper()
        outcome: dict[str, object] = {
            "symbol": symbol,
            "loader_status": row.get("load_status", ""),
            "loader_bars": int(row.get("history_bars") or 0),
            "membership_first": row.get("membership_first", ""),
            "membership_last": row.get("membership_last", ""),
            "tej_status": "error",
            "tej_bars": 0,
            "tej_first_date": "",
            "tej_last_date": "",
            "detail": "",
        }
        try:
            bars = client.ohlcv(symbol, "nse", start_date, end_date)
            dates = sorted(str(bar["date"]) for bar in bars if bar.get("date"))
            outcome.update({
                "tej_status": "available" if dates else "no_history",
                "tej_bars": len(dates),
                "tej_first_date": dates[0] if dates else "",
                "tej_last_date": dates[-1] if dates else "",
            })
        except Exception as exc:  # provider-specific errors are captured per symbol
            outcome["detail"] = f"{type(exc).__name__}: {exc}"[:300]
        results.append(outcome)
        print(f"[{position}/{len(rows)}] {symbol}: {outcome['tej_status']} "
              f"({outcome['tej_bars']} bars)", file=sys.stderr)
        if position < len(rows) and pause > 0:
            time.sleep(pause)
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="results/pit_price_history_audit.csv")
    parser.add_argument("--output", default="results/pit_tejhq_coverage_audit.csv")
    parser.add_argument("--from-date", default="2016-10-13")
    parser.add_argument("--to-date", default="2026-10-13")
    parser.add_argument("--pause", type=float, default=0.55)
    args = parser.parse_args(argv)

    source = Path(args.input)
    if not source.exists():
        parser.error(f"missing input audit: {source}")
    missing = read_missing(source, args.to_date)
    if not missing:
        print("No overlapping missing-history symbols to probe.")
        return 0

    results = probe(missing, args.from_date, args.to_date, Client(), args.pause)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(results[0])
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    available = sum(row["tej_status"] == "available" for row in results)
    total_bars = sum(int(row["tej_bars"]) for row in results)
    print(f"TejHQ coverage probe: {available}/{len(results)} symbols returned history "
          f"({total_bars} total bars).")
    print(f"Coverage-only output written to {output}; no price rows were retained.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
