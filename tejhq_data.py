"""Load one consistent NSE corporate-action-adjusted price history from TejHQ parquet.

The upstream parquet is derived from official NSE bhavcopy. OHLC is adjusted with
the cumulative factor; volume and turnover remain raw. Raw price rows are never
committed to this repository.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

REPO_ID = "tejhq/indian-markets"
COLUMNS = [
    "date", "symbol", "series", "open", "high", "low", "close",
    "volume", "turnover", "adj_factor_cumulative", "adj_close",
]


def load_adjusted_frames(
    tickers: Iterable[str],
    start_date: str,
    end_date: str,
    cache_dir: str = "data_cache/tejhq",
    refresh: bool = False,
) -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    """Return adjusted OHLCV frames keyed by Yahoo-style ticker (SYMBOL.NS).

    Files are downloaded per year and cached outside git. All requested symbols
    are loaded from the same source and adjustment convention. New listings are
    retained even when they have fewer than 253 bars; strategy lookback masks
    decide when they become eligible.
    """
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    symbols = sorted({str(t).strip().upper().removesuffix(".NS") for t in tickers})
    if not symbols:
        return {}, {}
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    pieces: dict[str, list[pd.DataFrame]] = {s: [] for s in symbols}
    errors: dict[str, str] = {}

    for year in range(start.year, end.year + 1):
        filename = f"prices_adjusted/nse_{year}.parquet"
        try:
            path = hf_hub_download(
                repo_id=REPO_ID,
                repo_type="dataset",
                filename=filename,
                cache_dir=str(cache / "hf"),
                force_download=refresh,
            )
            table = pq.read_table(
                path,
                columns=COLUMNS,
                filters=[
                    ("symbol", "in", symbols),
                    ("date", ">=", start.date()),
                    ("date", "<=", end.date()),
                ],
            )
            part = table.to_pandas()
        except Exception as exc:
            raise RuntimeError(
                f"Could not load TejHQ adjusted partition {filename}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if part.empty:
            continue
        part["date"] = pd.to_datetime(part["date"], errors="coerce")
        part = part.dropna(subset=["date", "symbol"])
        part["symbol"] = part["symbol"].astype(str).str.strip().str.upper()
        part = part[part["symbol"].isin(symbols)]
        part = part[part["series"].isin(["EQ", "BE", "BZ"])].copy()
        part["_series_priority"] = part["series"].map({"EQ": 0, "BE": 1, "BZ": 2})
        part = part.sort_values(["symbol", "date", "_series_priority"])
        part = part.drop_duplicates(["symbol", "date"], keep="first").drop(columns="_series_priority")

        factor = pd.to_numeric(part["adj_factor_cumulative"], errors="coerce")
        for col in ("open", "high", "low", "close"):
            part[col] = pd.to_numeric(part[col], errors="coerce") * factor
        part["adj_close"] = pd.to_numeric(part["adj_close"], errors="coerce")
        part["volume"] = pd.to_numeric(part["volume"], errors="coerce")
        part["turnover"] = pd.to_numeric(part["turnover"], errors="coerce")

        # The provider publishes adj_close = raw close * cumulative factor.
        # Reject corrupt adjustment rows rather than silently mixing price bases.
        expected = pd.to_numeric(part["close"], errors="coerce")
        if not factor.notna().all() or (factor <= 0).any():
            raise RuntimeError(f"{filename} contains missing/non-positive adjustment factors")
        if not part["adj_close"].notna().all() or (part["adj_close"] <= 0).any():
            raise RuntimeError(f"{filename} contains missing/non-positive adjusted closes")
        # Close was adjusted above; check it agrees with the provider's adj_close.
        mismatch = (expected - part["adj_close"]).abs() / part["adj_close"]
        if (mismatch > 1e-6).any():
            raise RuntimeError(
                f"{filename} has {int((mismatch > 1e-6).sum())} rows where "
                "adjusted close does not match raw close * adjustment factor"
            )

        for symbol, group in part.groupby("symbol", sort=False):
            frame = group.set_index("date").sort_index()
            frame = frame.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "adj_close": "Close", "volume": "Volume", "turnover": "Turnover",
            })
            # Keep only the columns consumed by the strategy and data-quality checks.
            frame = frame[["Open", "High", "Low", "Close", "Volume", "Turnover"]]
            frame.index.name = "Date"
            pieces[symbol].append(frame)

    frames: dict[str, pd.DataFrame] = {}
    diagnostics: dict[str, dict] = {}
    for symbol in symbols:
        if pieces[symbol]:
            frame = pd.concat(pieces[symbol]).sort_index()
            frame = frame[~frame.index.duplicated(keep="last")]
            frame = frame.loc[(frame.index >= start) & (frame.index <= end)]
            frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
            if not frame.empty:
                frames[f"{symbol}.NS"] = frame
                diagnostics[f"{symbol}.NS"] = {
                    "status": "loaded", "bars": int(len(frame)),
                    "detail": "TejHQ NSE bhavcopy; split/bonus/dividend-adjusted OHLC; raw volume/turnover",
                }
                continue
        diagnostics[f"{symbol}.NS"] = {
            "status": "no_history", "bars": 0,
            "detail": "No TejHQ adjusted NSE rows in requested date range",
        }
    return frames, diagnostics
