#!/usr/bin/env python3
"""Validate the published paper scorecard without modifying repository data."""
from __future__ import annotations

import json
import math
from pathlib import Path

SCORECARD = Path("docs/scorecard.json")


def finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def main() -> int:
    if not SCORECARD.exists():
        print("No published paper scorecard yet; audit is clean (collecting).")
        return 0

    with SCORECARD.open(encoding="utf-8") as handle:
        data = json.load(
            handle,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON constant: {value}")),
        )

    errors = []
    if data.get("schema_version") != 2:
        errors.append(f"unsupported schema_version: {data.get('schema_version')!r}")

    rows = data.get("monthly", [])
    if not isinstance(rows, list):
        errors.append("monthly must be a list")
        rows = []

    for row in rows:
        if row.get("status") == "closed":
            for key in ("top20_net", "same_universe_equal_weight", "nifty50", "turnover_l1"):
                if not finite(row.get(key)):
                    errors.append(f"{row.get('signal_date')}: closed row has invalid {key}")
            if row.get("data_status") != "complete":
                errors.append(f"{row.get('signal_date')}: closed row is not marked complete")
        if row.get("status") == "incomplete_data" and row.get("data_status") == "complete":
            errors.append(f"{row.get('signal_date')}: contradictory completeness status")

    cumulative = data.get("cumulative", {})
    if cumulative.get("status") == "complete":
        for key in ("top20_net", "same_universe_equal_weight", "nifty50"):
            if not finite(cumulative.get(key)):
                errors.append(f"cumulative marked complete but {key} is not finite")
        if data.get("missing_month_ends"):
            errors.append("cumulative marked complete despite missing month-end snapshots")
        if data.get("snapshots_outside_price_window"):
            errors.append("cumulative marked complete despite snapshots outside price history")

    if errors:
        print("PAPER SCORECARD AUDIT: FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PAPER SCORECARD AUDIT: PASSED")
    print(f"Status: {data.get('status')}")
    print(f"Snapshots: {data.get('snapshots', 0)}")
    print(f"Confirmed month-end snapshots: {data.get('month_end_snapshots', 0)}")
    print(f"Missing month-end snapshots: {len(data.get('missing_month_ends', []))}")
    print(f"Snapshots outside price history: {len(data.get('snapshots_outside_price_window', []))}")
    print(data.get("summary", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
