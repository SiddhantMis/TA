"""Load one consistent NSE corporate-action-adjusted price history from TejHQ parquet.

The upstream parquet is derived from official NSE bhavcopy. OHLC is adjusted with
the cumulative factor; volume and turnover remain raw. Symbol/ISIN history is
used to preserve ticker continuity across a rename or short ISIN transition.
Raw price rows are never committed to this repository.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

REPO_ID = "tejhq/indian-markets"
HISTORY_FILE = "symbol_history/nse.parquet"
COLUMNS = [
    "date", "symbol", "series", "isin", "open", "high", "low", "close",
    "volume", "turnover", "adj_factor_cumulative", "adj_close",
]
HISTORY_COLUMNS = ["isin", "symbol", "valid_from", "valid_to"]
SERIES = {"EQ", "BE", "BZ"}


def get_dataset_revision() -> str:
    """Return the immutable Hugging Face dataset commit used for a reproducible run."""
    from huggingface_hub import HfApi

    revision = HfApi().dataset_info(REPO_ID, repo_type="dataset").sha
    if not revision:
        raise RuntimeError("Hugging Face did not return a TejHQ dataset revision")
    return str(revision)


def build_symbol_chains(history: pd.DataFrame) -> pd.DataFrame:
    """Build instrument chains from the published symbol/ISIN validity intervals.

    Same ISIN intervals are continuous. A new ISIN is joined only when the same
    symbol resumes within 30 calendar days, matching TejHQ's documented rule.
    """
    missing = set(HISTORY_COLUMNS) - set(history.columns)
    if missing:
        raise RuntimeError(f"TejHQ symbol_history missing columns: {sorted(missing)}")
    out = history.copy().reset_index(drop=True)
    out["isin"] = out["isin"].fillna("").astype(str).str.strip().str.upper()
    out["symbol"] = out["symbol"].fillna("").astype(str).str.strip().str.upper()
    out["valid_from"] = pd.to_datetime(out["valid_from"], errors="coerce").dt.normalize()
    out["valid_to"] = pd.to_datetime(out["valid_to"], errors="coerce").dt.normalize()
    if out["symbol"].eq("").any() or out["valid_from"].isna().any():
        raise RuntimeError("TejHQ symbol_history contains blank symbols or invalid valid_from")
    bad_range = out["valid_to"].notna() & out["valid_to"].lt(out["valid_from"])
    if bad_range.any():
        raise RuntimeError("TejHQ symbol_history contains reversed validity intervals")
    for symbol, group in out.groupby("symbol", sort=True):
        ordered = group.sort_values(["valid_from", "valid_to"], na_position="last")
        previous = None
        for row in ordered.itertuples():
            if previous is not None and previous.isin != row.isin:
                overlaps = pd.isna(previous.valid_to) or row.valid_from <= previous.valid_to
                if overlaps:
                    raise RuntimeError(
                        f"TejHQ symbol_history has overlapping ISIN intervals for {symbol}: "
                        f"{previous.isin} and {row.isin}"
                    )
            previous = row

    parent = list(range(len(out)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for _, group in out.loc[out["isin"].ne("")].groupby("isin", sort=True):
        positions = group.index.tolist()
        for pos in positions[1:]:
            union(positions[0], pos)

    for _, group in out.groupby("symbol", sort=True):
        rows = list(group.sort_values(["valid_from", "valid_to"], na_position="last").itertuples())
        for left, right in zip(rows, rows[1:]):
            if pd.isna(left.valid_to):
                continue
            gap_days = (right.valid_from - left.valid_to).days - 1
            if 0 <= gap_days <= 30:
                union(left.Index, right.Index)

    roots = [find(i) for i in range(len(out))]
    root_members: dict[int, list[int]] = {}
    for pos, root in enumerate(roots):
        root_members.setdefault(root, []).append(pos)
    names = {}
    for root, positions in root_members.items():
        isins = sorted(x for x in out.loc[positions, "isin"].unique() if x)
        symbols = sorted(x for x in out.loc[positions, "symbol"].unique() if x)
        names[root] = isins[0] if isins else f"SYMBOL:{symbols[0]}"
    out["chain_id"] = [names[root] for root in roots]
    return out


def map_symbol_chains(
    symbols: Iterable[str],
    history: pd.DataFrame,
    membership_df: pd.DataFrame | None = None,
) -> dict[str, set[str]]:
    """Map each PIT symbol to only the chains overlapping its membership intervals."""
    mapping: dict[str, set[str]] = {}
    hist = history.copy()
    for symbol in sorted({str(s).strip().upper().removesuffix(".NS") for s in symbols}):
        symbol_rows = hist.loc[hist["symbol"].eq(symbol)]
        if membership_df is None or symbol == "NIFTYBEES":
            mapping[symbol] = set(symbol_rows["chain_id"].astype(str))
            continue
        member = membership_df.copy()
        member["symbol"] = member["symbol"].astype(str).str.strip().str.upper()
        intervals = member.loc[member["symbol"].eq(symbol)]
        chains: set[str] = set()
        for row in intervals.itertuples(index=False):
            start = pd.Timestamp(row.valid_from).normalize()
            end = pd.Timestamp.max if pd.isna(row.valid_to) else pd.Timestamp(row.valid_to).normalize()
            overlaps = symbol_rows["valid_from"].lt(end) & (
                symbol_rows["valid_to"].isna() | symbol_rows["valid_to"].ge(start)
            )
            chains.update(symbol_rows.loc[overlaps, "chain_id"].astype(str))
        mapping[symbol] = chains
    return mapping


def load_adjusted_frames(
    tickers: Iterable[str],
    start_date: str,
    end_date: str,
    cache_dir: str = "data_cache/tejhq",
    refresh: bool = False,
    membership_df: pd.DataFrame | None = None,
    min_bars: int = 253,
    revision: str | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    """Return adjusted OHLCV frames keyed by Yahoo-style ticker (SYMBOL.NS).

    All prices come from one pinned TejHQ dataset revision. Short histories are
    retained but explicitly marked insufficient for a 253-session strategy lookback.
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
    revision = str(revision or get_dataset_revision())

    history_path = hf_hub_download(
        repo_id=REPO_ID, repo_type="dataset", filename=HISTORY_FILE,
        cache_dir=str(cache / "hf"), force_download=refresh, revision=revision,
    )
    history = build_symbol_chains(pd.read_parquet(history_path, columns=HISTORY_COLUMNS))
    chain_map = map_symbol_chains(symbols, history, membership_df)
    selected_chains = set().union(*(chain_map.get(symbol, set()) for symbol in symbols))
    selected_history = history.loc[history["chain_id"].isin(selected_chains)]
    isins = sorted(x for x in selected_history["isin"].unique() if x)
    if not isins:
        raise RuntimeError("No requested PIT symbols map to TejHQ NSE ISIN history")
    isin_to_chain = (
        selected_history.loc[selected_history["isin"].ne("")]
        .drop_duplicates("isin").set_index("isin")["chain_id"].to_dict()
    )

    parts = []
    row_count = 0
    for year in range(start.year, end.year + 1):
        filename = f"prices_adjusted/nse_{year}.parquet"
        try:
            path = hf_hub_download(
                repo_id=REPO_ID, repo_type="dataset", filename=filename,
                cache_dir=str(cache / "hf"), force_download=refresh, revision=revision,
            )
            table = pq.read_table(
                path,
                columns=COLUMNS,
                filters=[
                    ("isin", "in", isins),
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
        part["date"] = pd.to_datetime(part["date"], errors="coerce").dt.normalize()
        part["symbol"] = part["symbol"].astype(str).str.strip().str.upper()
        part["isin"] = part["isin"].astype(str).str.strip().str.upper()
        part["series"] = part["series"].astype(str).str.strip().str.upper()
        part = part.loc[
            part["date"].notna()
            & part["isin"].isin(isins)
            & part["series"].isin(SERIES)
            & part["date"].between(start, end)
        ].copy()
        if part.empty:
            continue

        duplicate_rows = part.loc[part.duplicated(["symbol", "date"], keep=False)]
        if not duplicate_rows.empty:
            conflicting = duplicate_rows.groupby(["symbol", "date"])["isin"].nunique().gt(1)
            if conflicting.any():
                sample_keys = conflicting.loc[conflicting].index.tolist()[:5]
                sample = duplicate_rows.set_index(["symbol", "date"]).loc[sample_keys].reset_index()
                raise RuntimeError(
                    f"{filename} has ambiguous same-symbol/session rows across ISINs: "
                    f"{sample[['symbol', 'date', 'isin']].to_dict('records')}"
                )
        part["_series_priority"] = part["series"].map({"EQ": 0, "BE": 1, "BZ": 2})
        part = part.sort_values(["symbol", "date", "_series_priority"])
        part = part.drop_duplicates(["symbol", "date"], keep="first").drop(columns="_series_priority")
        part["chain_id"] = part["isin"].map(isin_to_chain)
        if part["chain_id"].isna().any():
            sample = part.loc[part["chain_id"].isna(), ["symbol", "isin", "date"]].head(5)
            raise RuntimeError(f"{filename} has price rows without a symbol-history chain: {sample.to_dict('records')}")

        factor = pd.to_numeric(part["adj_factor_cumulative"], errors="coerce")
        raw_close = pd.to_numeric(part["close"], errors="coerce")
        adj_close = pd.to_numeric(part["adj_close"], errors="coerce")
        if factor.isna().any() or (factor <= 0).any():
            raise RuntimeError(f"{filename} contains missing/non-positive adjustment factors")
        if adj_close.isna().any() or (adj_close <= 0).any():
            raise RuntimeError(f"{filename} contains missing/non-positive adjusted closes")
        mismatch = ~np.isclose(raw_close.to_numpy(float) * factor.to_numpy(float),
                               adj_close.to_numpy(float), rtol=1e-6, atol=0.01)
        if mismatch.any():
            raise RuntimeError(
                f"{filename} has {int(mismatch.sum())} rows where adj_close != raw close * factor"
            )

        for col in ("open", "high", "low", "volume", "turnover"):
            part[col] = pd.to_numeric(part[col], errors="coerce")
        part["open"] *= factor
        part["high"] *= factor
        part["low"] *= factor
        part["close"] = adj_close
        part["adj_close"] = adj_close
        bad_ohlc = (
            part[["open", "high", "low", "close"]].isna().any(axis=1)
            | (part[["open", "high", "low", "close"]] <= 0).any(axis=1)
            | (part["high"] + 0.01 < part[["open", "low", "close"]].max(axis=1))
            | (part["low"] - 0.01 > part[["open", "high", "close"]].min(axis=1))
        )
        if bad_ohlc.any():
            raise RuntimeError(f"{filename} contains {int(bad_ohlc.sum())} invalid adjusted OHLC rows")
        if part[["volume", "turnover"]].isna().any().any() or (part[["volume", "turnover"]] < 0).any().any():
            raise RuntimeError(f"{filename} contains invalid raw volume/turnover")
        if part.duplicated(["chain_id", "date"]).any():
            sample = part.loc[part.duplicated(["chain_id", "date"], keep=False),
                              ["chain_id", "symbol", "isin", "date"]].head(8)
            raise RuntimeError(f"{filename} has multiple bars in one instrument chain/session: {sample.to_dict('records')}")
        row_count += len(part)
        parts.append(part[[
            "date", "symbol", "isin", "chain_id", "open", "high", "low",
            "close", "volume", "turnover",
        ]])

    if not parts:
        raise RuntimeError("No TejHQ adjusted price rows found for requested PIT symbols")
    prices = pd.concat(parts, ignore_index=True)
    frames: dict[str, pd.DataFrame] = {}
    diagnostics: dict[str, dict] = {}
    symbol_audit = []
    for symbol in symbols:
        chains = chain_map.get(symbol, set())
        selected = prices.loc[prices["chain_id"].isin(chains)].sort_values("date")
        if selected.empty:
            status, bars = "no_history", 0
            detail = "No TejHQ adjusted NSE rows in symbol/ISIN chains overlapping PIT membership"
        else:
            if selected["date"].duplicated().any():
                sample = selected.loc[selected["date"].duplicated(False), ["date", "symbol", "isin"]].head(8)
                raise RuntimeError(f"{symbol}: multiple price bars after symbol-chain mapping: {sample.to_dict('records')}")
            frame = pd.DataFrame({
                "Open": selected["open"].to_numpy(float),
                "High": selected["high"].to_numpy(float),
                "Low": selected["low"].to_numpy(float),
                "Close": selected["close"].to_numpy(float),
                "Volume": selected["volume"].to_numpy(float),
                "Turnover": selected["turnover"].to_numpy(float),
            }, index=pd.DatetimeIndex(selected["date"], name="Date")).sort_index()
            frames[f"{symbol}.NS"] = frame
            bars = int(len(frame))
            status = "loaded" if bars >= min_bars else "insufficient_history"
            aliases = sorted(selected["symbol"].unique().tolist())
            detail = (
                f"{len(chains)} chain(s), {selected['isin'].nunique()} ISIN(s), "
                f"aliases={aliases}; adjusted OHLC, raw volume/turnover"
            )
        diagnostics[f"{symbol}.NS"] = {"status": status, "bars": bars, "detail": detail}
        symbol_audit.append({
            "symbol": symbol,
            "chain_count": len(chains),
            "isin_count": int(selected["isin"].nunique()) if not selected.empty else 0,
            "aliases": ",".join(sorted(selected["symbol"].unique().tolist())) if not selected.empty else "",
            "bars": bars,
            "first_date": selected["date"].min().date().isoformat() if not selected.empty else "",
            "last_date": selected["date"].max().date().isoformat() if not selected.empty else "",
            "status": status,
        })

    diagnostics["_source"] = {
        "source": "TejHQ prices_adjusted NSE parquet",
        "dataset_id": REPO_ID,
        "dataset_revision": revision,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "series_scope": "EQ, BE, BZ (TejHQ published NSE coverage)",
        "adjustment_scope": "splits, bonuses and dividends; mergers, demergers, rights and buybacks are not scaled",
        "adjustment_validation": "passed: adj_close equals raw close multiplied by cumulative factor; adjusted OHLC checked",
        "liquidity_basis": "raw bhavcopy turnover; volume remains raw",
        "symbol_history_valid_to": "inclusive last trading day; PIT membership valid_to is exclusive",
        "instrument_chain_rule": "same ISIN is continuous; a new ISIN joins only when the same symbol resumes within 30 calendar days",
        "data_terms_url": "https://tejhq.dev/data-terms",
        "data_terms_as_of": "2026-10-30",
        "data_terms_summary": "personal research/backtesting permitted; TejHQ holds no NSE/BSE data licence; MIT covers code, not data; exchange terms still apply to commercial use and redistribution",
        "price_rows_loaded": int(row_count),
        "instrument_chains": int(len(selected_chains)),
        "isins_loaded": int(len(isins)),
    }
    diagnostics["_symbol_audit"] = symbol_audit
    return frames, diagnostics
