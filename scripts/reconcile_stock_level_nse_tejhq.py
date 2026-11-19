#!/usr/bin/env python3
"""Compare a deterministic stock sample's raw TejHQ OHLC with official NSE history."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

from nifty500_pit import MEMBERSHIP_COVERAGE_THROUGH, load_membership_calendar
from tejhq_data import get_dataset_revision, load_adjusted_frames

PIN = "0303d8c95b4519765a9d5556fd9c2d430f8f81d8"
BASE = Path("results/pit_samples/n40_gap21_seed20261103_rev0303d8c/liquidity_first")
SAMPLES = BASE / "selected_stocks_and_outcomes.csv"
DETAIL = BASE / "stock_level_nse_tejhq_reconciliation.csv"
REPORT = BASE / "stock_level_nse_tejhq_reconciliation.md"
FLAGGED = {"NESTLEIND", "AJANTPHARM", "AARTIDRUGS", "BSOFT", "SUZLON", "VEDL"}
CLEAN = ("ADANIGREEN", "NAVINFLUOR", "DIXON", "DMART")
OHLC = {
    "Open": ("CH_OPENING_PRICE", "mOPEN"),
    "High": ("CH_TRADE_HIGH_PRICE", "mHIGH"),
    "Low": ("CH_TRADE_LOW_PRICE", "mLOW"),
    "Close": ("CH_CLOSING_PRICE", "mCLOSE"),
}


def nse_history(session: requests.Session, symbol: str, start: pd.Timestamp, end: pd.Timestamp):
    url = "https://www.nseindia.com/api/historical/cm/equity"
    params = {
        "symbol": symbol,
        "series": '["EQ"]',
        "from": start.strftime("%d-%m-%Y"),
        "to": end.strftime("%d-%m-%Y"),
    }
    response = session.get(url, params=params, timeout=25)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected NSE payload for {symbol}: no data list")
    rows = []
    for item in data:
        date_value = item.get("CH_TIMESTAMP") or item.get("mTIMESTAMP") or item.get("TIMESTAMP")
        if not date_value:
            continue
        row = {"Date": pd.Timestamp(date_value).normalize()}
        for field, keys in OHLC.items():
            value = next((item[k] for k in keys if k in item and item[k] not in (None, "")), None)
            if value is None:
                row[field] = float("nan")
            else:
                row[field] = float(str(value).replace(",", ""))
        rows.append(row)
    if not rows:
        raise RuntimeError(f"NSE returned no historical EQ rows for {symbol}")
    return pd.DataFrame(rows).drop_duplicates("Date").set_index("Date").sort_index()


def main() -> None:
    if get_dataset_revision() != PIN:
        raise RuntimeError("Stock-level reconciliation must use the pinned TejHQ revision")
    samples = pd.read_csv(SAMPLES, dtype=str, keep_default_na=False)
    signals = {}
    for symbol in sorted(FLAGGED):
        match = samples.loc[samples["symbol"].eq(symbol)]
        if match.empty:
            raise RuntimeError(f"Flagged stock {symbol} is absent from the sample")
        signals[symbol] = pd.Timestamp(match.iloc[0]["signal_date"]).normalize()
    for symbol in CLEAN:
        match = samples.loc[samples["symbol"].eq(symbol)]
        if match.empty:
            raise RuntimeError(f"Clean control {symbol} is absent from the sample")
        signals[symbol] = pd.Timestamp(match.iloc[0]["signal_date"]).normalize()

    start = min(signals.values()) - pd.Timedelta(days=30)
    end = max(signals.values()) + pd.Timedelta(days=30)
    membership = load_membership_calendar()
    frames, _ = load_adjusted_frames(
        [f"{s}.NS" for s in signals], start.date().isoformat(), end.date().isoformat(),
        cache_dir="data_cache/tejhq_parquet", membership_df=membership,
        min_bars=1, revision=PIN, include_raw=True,
    )
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    })
    homepage_error = ""
    try:
        home = session.get("https://www.nseindia.com/", timeout=20)
        home.raise_for_status()
    except Exception as exc:
        homepage_error = f"{type(exc).__name__}: {exc}"

    details = []
    symbol_summaries = []
    for symbol, signal in signals.items():
        begin, finish = signal - pd.Timedelta(days=20), signal + pd.Timedelta(days=20)
        try:
            nse = nse_history(session, symbol, begin, finish)
            tej_frame = frames.get(f"{symbol}.NS")
            if tej_frame is None or tej_frame.empty:
                raise RuntimeError("No pinned TejHQ raw price frame")
            tej = tej_frame.rename(columns={
                "RawOpen": "Open", "RawHigh": "High", "RawLow": "Low", "RawClose": "Close"
            })[["Open", "High", "Low", "Close"]].copy()
            tej.index = pd.DatetimeIndex(pd.to_datetime(tej.index)).normalize()
            tej = tej.loc[(tej.index >= begin) & (tej.index <= finish)]
            common = nse.index.intersection(tej.index)
            if common.empty:
                raise RuntimeError("NSE and TejHQ returned no common sessions in sample window")
            diffs = (tej.loc[common] - nse.loc[common]).abs()
            for day in common:
                row = {
                    "symbol": symbol, "sample_signal_date": signal.date().isoformat(),
                    "date": day.date().isoformat(), "status": "MATCHED",
                }
                for field in ("Open", "High", "Low", "Close"):
                    row[f"tejhq_{field.lower()}"] = float(tej.at[day, field])
                    row[f"nse_{field.lower()}"] = float(nse.at[day, field])
                    row[f"abs_diff_{field.lower()}"] = float(diffs.at[day, field])
                details.append(row)
            symbol_summaries.append({
                "symbol": symbol, "sample_type": "flagged_CA" if symbol in FLAGGED else "clean_control",
                "signal_date": signal.date().isoformat(), "status": "MATCHED",
                "common_sessions": len(common),
                "max_abs_open_diff": float(diffs["Open"].max()),
                "max_abs_high_diff": float(diffs["High"].max()),
                "max_abs_low_diff": float(diffs["Low"].max()),
                "max_abs_close_diff": float(diffs["Close"].max()),
                "nse_sessions": len(nse), "tejhq_sessions": len(tej),
                "error": "",
            })
        except Exception as exc:
            symbol_summaries.append({
                "symbol": symbol, "sample_type": "flagged_CA" if symbol in FLAGGED else "clean_control",
                "signal_date": signal.date().isoformat(), "status": "UNVERIFIED",
                "common_sessions": 0, "max_abs_open_diff": "", "max_abs_high_diff": "",
                "max_abs_low_diff": "", "max_abs_close_diff": "", "nse_sessions": 0,
                "tejhq_sessions": len(frames.get(f"{symbol}.NS", [])),
                "error": f"{type(exc).__name__}: {exc}",
            })

    pd.DataFrame(details).to_csv(DETAIL, index=False, float_format="%.8f")
    summary = pd.DataFrame(symbol_summaries)
    summary_path = BASE / "stock_level_nse_tejhq_reconciliation_summary.csv"
    summary.to_csv(summary_path, index=False)
    all_verified = len(summary) == 10 and summary["status"].eq("MATCHED").all()
    lines = [
        "# Stock-level official NSE vs TejHQ raw OHLC reconciliation",
        "",
        f"TejHQ dataset revision: `{PIN}`",
        f"Overall status: **{'VERIFIED' if all_verified else 'UNVERIFIED'}**",
        "Deterministic sample: six corporate-action-flagged equities (NESTLEIND, AJANTPHARM, AARTIDRUGS, "
        "BSOFT, SUZLON, VEDL) plus four clean controls (ADANIGREEN, NAVINFLUOR, DIXON, DMART). "
        "For each stock, the comparison window is 20 calendar days either side of its first sample signal date.",
        "Comparison is raw NSE EQ OHLC against TejHQ raw_open/raw_high/raw_low/raw_close, not adjusted prices.",
        "",
        "| Symbol | Sample | Signal date | Status | Common sessions | Max abs open diff | high diff | low diff | close diff |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in summary.itertuples(index=False):
        lines.append(
            f"| {r.symbol} | {r.sample_type} | {r.signal_date} | {r.status} | {r.common_sessions} | "
            f"{r.max_abs_open_diff} | {r.max_abs_high_diff} | {r.max_abs_low_diff} | {r.max_abs_close_diff} |"
        )
    if not all_verified:
        errors = [f"{r.symbol}: {r.error}" for r in summary.itertuples(index=False) if r.status != "MATCHED"]
        lines.extend([
            "",
            "NSE official equity-history endpoint could not provide a complete verifiable sample from this GitHub Actions run. "
            "Stock-level reconciliation is therefore **UNVERIFIED**; the NIFTYBEES benchmark comparison is not a substitute.",
            f"Homepage bootstrap error: {homepage_error or 'none'}",
            *[f"- {error}" for error in errors],
        ])
    lines.extend([
        "",
        f"Per-session exact OHLC values and absolute differences: `{DETAIL.name}`.",
        f"Per-symbol summary: `{summary_path.name}`.",
    ])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
