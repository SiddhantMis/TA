#!/usr/bin/env python3
"""Join dropped six-month basket positions to their in-hold corporate actions."""
from pathlib import Path
import pandas as pd

BASE = Path("results/pit_samples/n40_gap21_seed20261103_rev0303d8c/liquidity_first")
SAMPLES = BASE / "selected_stocks_and_outcomes.csv"
AUDIT = Path("results/corporate_action_audit.csv")
REPORT = BASE / "task4_diagnostics.md"
OUT = BASE / "dropped_basket_ca_events.csv"


def main() -> None:
    sample = pd.read_csv(SAMPLES, dtype=str, keep_default_na=False)
    audit = pd.read_csv(AUDIT, dtype=str, keep_default_na=False)
    audit["symbol"] = audit["symbol"].str.upper().str.strip()
    audit["type"] = audit["type"].str.lower().str.strip()
    audit["ex_date"] = pd.to_datetime(audit["ex_date"], errors="coerce")
    sample["signal_date_dt"] = pd.to_datetime(sample["signal_date"], errors="raise")
    sample["exit_date_dt"] = pd.to_datetime(sample["6M_exit_date"], errors="raise")
    dropped = sample.loc[
        sample["6M_return_status"].eq("unsupported_corporate_action_during_hold")
    ].copy()
    records = []
    for _, row in dropped.iterrows():
        events = audit.loc[
            audit["symbol"].eq(row["symbol"])
            & audit["ex_date"].gt(row["signal_date_dt"])
            & audit["ex_date"].le(row["exit_date_dt"])
        ].copy()
        if events.empty:
            raise RuntimeError(
                f"No corporate_action_audit.csv event for {row['sample_id']}/{row['symbol']} "
                f"inside {row['signal_date']}..{row['6M_exit_date']}"
            )
        for event in events.sort_values("ex_date").itertuples(index=False):
            action_type = str(event.type).lower()
            if action_type not in {"demerger", "buyback", "rights", "merger", "other"}:
                raise RuntimeError(f"Unexpected corporate-action type: {action_type}")
            records.append({
                "sample_id": row["sample_id"],
                "signal_date": row["signal_date"],
                "symbol": row["symbol"],
                "ex_date": event.ex_date.date().isoformat(),
                "corporate_action_type": action_type,
                "raw_subject": event.raw_subject,
                "source_file": event.source_file,
            })
    result = pd.DataFrame(records).drop_duplicates()
    positions = dropped[["sample_id", "symbol"]].drop_duplicates()
    joined = result[["sample_id", "symbol"]].drop_duplicates()
    if len(positions) != 12 or len(joined) != 12:
        raise RuntimeError(f"Expected 12 joined positions; got {len(positions)} dropped and {len(joined)} joined")
    result.to_csv(OUT, index=False)
    lines = [
        "| Sample | Signal date | Symbol | Exact ex-date | Corporate-action type |",
        "|---|---|---|---|---|",
    ]
    for r in result.sort_values(["sample_id", "symbol", "ex_date"]).itertuples(index=False):
        lines.append(f"| {r.sample_id} | {r.signal_date} | {r.symbol} | {r.ex_date} | {r.corporate_action_type} |")
    md = REPORT.read_text(encoding="utf-8")
    start_marker = "| Sample | Signal date | Unsupported holding(s) |"
    start = md.find(start_marker)
    if start < 0:
        raise RuntimeError("Could not find the six-month exclusion table in task4_diagnostics.md")
    end = md.find("\n\n", start)
    if end < 0:
        raise RuntimeError("Could not find end of six-month exclusion table")
    REPORT.write_text(md[:start] + "\n".join(lines) + md[end:], encoding="utf-8")
    print(f"Joined {len(result)} action rows across {len(joined)} dropped positions")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
