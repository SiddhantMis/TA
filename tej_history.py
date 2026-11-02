"""Load TejHQ's public, corporate-action-adjusted NSE parquet history.

The raw market data is never written into the repository. Only reproducible code
and metadata/coverage audits are emitted by the research workflow.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from huggingface_hub import HfApi, hf_hub_download

DATASET_ID = "tejhq/indian-markets"
ADJUSTED_PREFIX = "prices_adjusted"
HISTORY_FILE = "symbol_history/nse.parquet"
SERIES = {"EQ", "BE", "BZ"}
ADJUSTED_COLUMNS = [
    "date", "symbol", "series", "isin", "open", "high", "low", "close",
    "volume", "turnover", "adj_factor_cumulative", "adj_close",
]


class TejHistoryError(RuntimeError):
    """Raised when adjusted source data cannot safely be used."""


def _naive_date(value):
    value = pd.Timestamp(value)
    return value.tz_localize(None).normalize() if value.tz is not None else value.normalize()


def build_symbol_chains(history: pd.DataFrame) -> pd.DataFrame:
    """Attach a stable chain id across same-ISIN renames and short same-symbol ISIN changes.

    This mirrors TejHQ's documented chain rule: same ISIN is continuous; a new
    ISIN is joined when the same symbol resumes within 30 calendar days.
    """
    required = {"isin", "symbol", "valid_from", "valid_to"}
    missing = required - set(history.columns)
    if missing:
        raise TejHistoryError(f"symbol_history missing columns: {sorted(missing)}")
    out = history.copy().reset_index(drop=True)
    out["isin"] = out["isin"].fillna("").astype(str).str.strip().str.upper()
    out["symbol"] = out["symbol"].fillna("").astype(str).str.strip().str.upper()
    out["valid_from"] = pd.to_datetime(out["valid_from"], errors="coerce")
    out["valid_to"] = pd.to_datetime(out["valid_to"], errors="coerce")
    if out[["symbol", "valid_from"]].isna().any().any() or out["symbol"].eq("").any():
        raise TejHistoryError("symbol_history contains blank symbols or invalid valid_from")

    parent = list(range(len(out)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for _, group in out[out["isin"].ne("")].groupby("isin", sort=True):
        positions = group.index.tolist()
        for p in positions[1:]:
            union(positions[0], p)

    for _, group in out.groupby("symbol", sort=True):
        group = group.sort_values(["valid_from", "valid_to"], na_position="last")
        rows = list(group.itertuples())
        for left, right in zip(rows, rows[1:]):
            if pd.isna(left.valid_to):
                continue
            gap = (right.valid_from - left.valid_to).days
            if 0 <= gap <= 30:
                union(left.Index, right.Index)

    roots = [find(i) for i in range(len(out))]
    members = {}
    for i, root in enumerate(roots):
        members.setdefault(root, []).append(i)
    chain_names = {}
    for root, positions in members.items():
        isins = sorted(x for x in out.loc[positions, "isin"].unique() if x)
        symbols = sorted(x for x in out.loc[positions, "symbol"].unique() if x)
        chain_names[root] = isins[0] if isins else f"SYMBOL:{symbols[0]}"
    out["chain_id"] = [chain_names[root] for root in roots]
    return out


def map_membership_chains(
    membership: pd.DataFrame,
    history: pd.DataFrame,
    extra_symbols: tuple[str, ...] = ("NIFTYBEES",),
) -> dict[str, set[str]]:
    """Map each point-in-time membership symbol to the Tej instrument chains it overlaps."""
    required = {"symbol", "valid_from", "valid_to"}
    missing = required - set(membership.columns)
    if missing:
        raise TejHistoryError(f"membership calendar missing columns: {sorted(missing)}")
    mapping: dict[str, set[str]] = {}
    for symbol, group in membership.groupby(membership["symbol"].astype(str).str.upper()):
        sh = history.loc[history["symbol"].eq(symbol)]
        chains: set[str] = set()
        for row in group.itertuples(index=False):
            start = _naive_date(row.valid_from)
            end = pd.Timestamp.max if pd.isna(row.valid_to) else _naive_date(row.valid_to)
            overlaps = sh["valid_from"].le(end) & (
                sh["valid_to"].isna() | sh["valid_to"].ge(start)
            )
            chains.update(sh.loc[overlaps, "chain_id"].astype(str))
        mapping[symbol] = chains

    for raw in extra_symbols:
        symbol = str(raw).strip().upper()
        mapping[symbol] = set(history.loc[history["symbol"].eq(symbol), "chain_id"].astype(str))
    return mapping


def _validate_adjusted_rows(rows: pd.DataFrame, source: str) -> pd.DataFrame:
    if rows.empty:
        return rows
    required = set(ADJUSTED_COLUMNS)
    missing = required - set(rows.columns)
    if missing:
        raise TejHistoryError(f"{source} missing adjusted columns: {sorted(missing)}")

    out = rows.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    for col in ("open", "high", "low", "close", "volume", "turnover",
                "adj_factor_cumulative", "adj_close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if out["date"].isna().any():
        raise TejHistoryError(f"{source} contains invalid dates")
    if out["adj_factor_cumulative"].isna().any() or (out["adj_factor_cumulative"] <= 0).any():
        raise TejHistoryError(f"{source} contains missing or non-positive adjustment factors")
    expected = out["close"] * out["adj_factor_cumulative"]
    mismatch = ~np.isclose(out["adj_close"], expected, rtol=1e-6, atol=0.01)
    if mismatch.any():
        sample = out.loc[mismatch, ["symbol", "date", "close", "adj_factor_cumulative", "adj_close"]].head(5)
        raise TejHistoryError(
            f"{source} adj_close != close * cumulative factor for {int(mismatch.sum())} rows: "
            f"{sample.to_dict('records')}"
        )
    prices = out[["open", "high", "low", "close", "adj_close"]]
    if prices.isna().any().any() or (prices <= 0).any().any():
        raise TejHistoryError(f"{source} contains missing or non-positive prices")
    if (out["high"] + 0.01 < out[["open", "low", "close"]].max(axis=1)).any():
        raise TejHistoryError(f"{source} contains high below another OHLC value")
    if (out["low"] - 0.01 > out[["open", "high", "close"]].min(axis=1)).any():
        raise TejHistoryError(f"{source} contains low above another OHLC value")
    if out["volume"].isna().any() or (out["volume"] < 0).any():
        raise TejHistoryError(f"{source} contains invalid raw volume")
    if out["turnover"].isna().any() or (out["turnover"] < 0).any():
        raise TejHistoryError(f"{source} contains invalid raw turnover")
    return out


def _frame_for_symbol(rows: pd.DataFrame, symbol: str) -> pd.DataFrame:
    selected = rows.loc[rows["chain_id"].isin(rows.attrs.get("chain_ids", set()))].copy()
    if selected.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume", "Turnover"])
    selected = selected.sort_values(["date", "symbol", "isin"])
    if selected["date"].duplicated().any():
        duplicates = selected.loc[selected["date"].duplicated(False), ["date", "symbol", "isin"]].head(8)
        raise TejHistoryError(
            f"{symbol}: multiple bars in the same instrument chain on one session: "
            f"{duplicates.to_dict('records')}"
        )
    factor = selected["adj_factor_cumulative"]
    frame = pd.DataFrame({
        "Open": selected["open"].to_numpy(float) * factor.to_numpy(float),
        "High": selected["high"].to_numpy(float) * factor.to_numpy(float),
        "Low": selected["low"].to_numpy(float) * factor.to_numpy(float),
        "Close": selected["adj_close"].to_numpy(float),
        "Volume": selected["volume"].to_numpy(float),
        # Turnover is an as-traded rupee value and must not be scaled by the
        # back-adjustment factor used for price history.
        "Turnover": selected["turnover"].to_numpy(float),
    }, index=pd.DatetimeIndex(selected["date"], name="Date"))
    return frame.sort_index()


def load_adjusted_frames(
    tickers: list[str],
    membership: pd.DataFrame,
    years: int = 10,
    end_date: str | pd.Timestamp = "2026-10-13",
    cache_dir: str = "data_cache/tejhq",
    refresh: bool = False,
    extra_symbols: tuple[str, ...] = ("NIFTYBEES",),
    min_bars: int = 253,
):
    """Load adjusted NSE bars for membership symbols plus the NIFTYBEES benchmark.

    Returns (frames, diagnostics, metadata, symbol_audit). The dataset revision
    is pinned for every parquet download in this run and recorded in metadata.
    """
    if years < 1:
        raise ValueError("years must be at least 1")
    end = _naive_date(end_date)
    first_year = max(2010, end.year - years - 1)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    revision = api.dataset_info(DATASET_ID, repo_type="dataset").sha
    if not revision:
        raise TejHistoryError("Hugging Face did not return a dataset revision")

    history_path = hf_hub_download(
        repo_id=DATASET_ID, filename=HISTORY_FILE, repo_type="dataset",
        revision=revision, cache_dir=str(cache), force_download=refresh,
    )
    raw_history = pd.read_parquet(history_path)
    history = build_symbol_chains(raw_history)
    mapping = map_membership_chains(membership, history, extra_symbols=extra_symbols)

    requested = {str(t).strip().upper().removesuffix(".NS") for t in tickers}
    requested.update(str(s).strip().upper() for s in extra_symbols)
    missing_map = sorted(s for s in requested if not mapping.get(s))
    selected_chains = set().union(*(mapping.get(s, set()) for s in requested))
    if not selected_chains:
        raise TejHistoryError("No requested PIT symbols mapped to TejHQ instrument chains")
    selected_history = history.loc[history["chain_id"].isin(selected_chains)]
    isins = sorted(x for x in selected_history["isin"].unique() if x)
    if not isins:
        raise TejHistoryError("Mapped TejHQ instrument chains contain no ISINs")

    parts = []
    downloaded = []
    for year in range(first_year, end.year + 1):
        filename = f"{ADJUSTED_PREFIX}/nse_{year}.parquet"
        path = hf_hub_download(
            repo_id=DATASET_ID, filename=filename, repo_type="dataset",
            revision=revision, cache_dir=str(cache), force_download=refresh,
        )
        frame = pd.read_parquet(path, columns=ADJUSTED_COLUMNS, filters=[("isin", "in", isins)])
        if not frame.empty:
            frame = frame.loc[
                frame["isin"].astype(str).isin(isins)
                & pd.to_datetime(frame["date"]).le(end)
                & frame["series"].astype(str).str.upper().isin(SERIES)
            ].copy()
            if not frame.empty:
                parts.append(frame)
        downloaded.append(year)
        print(f"[tejhq] {year}: {len(frame):,} selected adjusted rows", file=sys.stderr)

    if not parts:
        raise TejHistoryError("No adjusted price rows found for the requested NSE instrument chains")
    prices = _validate_adjusted_rows(pd.concat(parts, ignore_index=True), "TejHQ adjusted NSE history")
    isin_to_chain = (
        selected_history.loc[selected_history["isin"].ne("")]
        .drop_duplicates("isin").set_index("isin")["chain_id"].to_dict()
    )
    prices["chain_id"] = prices["isin"].astype(str).map(isin_to_chain)
    unmapped_rows = int(prices["chain_id"].isna().sum())
    prices = prices.loc[prices["chain_id"].notna()].copy()
    prices["chain_id"] = prices["chain_id"].astype(str)

    frames: dict[str, pd.DataFrame] = {}
    diagnostics: dict[str, dict] = {}
    symbol_audit = []
    for ticker in tickers + [f"{s}.NS" for s in extra_symbols if f"{s}.NS" not in tickers]:
        symbol = str(ticker).strip().upper().removesuffix(".NS")
        chains = mapping.get(symbol, set())
        selected = prices.loc[prices["chain_id"].isin(chains)].copy()
        if selected.empty:
            diagnostics[ticker] = {"status": "no_history", "bars": 0, "detail": "no adjusted rows in mapped TejHQ chains"}
            symbol_audit.append({
                "symbol": symbol, "chain_count": len(chains), "isin_count": 0,
                "bars": 0, "first_date": "", "last_date": "", "status": "no_history",
            })
            continue
        selected.attrs["chain_ids"] = chains
        frame = _frame_for_symbol(selected, ticker)
        frames[ticker] = frame
        status = "loaded" if len(frame) >= min_bars else "insufficient_history"
        chain_isins = selected["isin"].nunique()
        diagnostics[ticker] = {
            "status": status, "bars": int(len(frame)),
            "detail": f"{len(chains)} instrument chain(s), {chain_isins} ISIN(s); TejHQ adjusted",
        }
        symbol_audit.append({
            "symbol": symbol, "chain_count": len(chains), "isin_count": int(chain_isins),
            "bars": int(len(frame)),
            "first_date": frame.index.min().date().isoformat(),
            "last_date": frame.index.max().date().isoformat(),
            "status": status,
        })

    metadata = {
        "source": "TejHQ prices_adjusted (NSE)",
        "dataset_id": DATASET_ID,
        "dataset_revision": revision,
        "first_year": first_year,
        "last_year": end.year,
        "rows_loaded": int(len(prices)),
        "chains_loaded": int(len(selected_chains)),
        "isins_loaded": int(len(isins)),
        "symbols_requested": int(len(requested)),
        "symbols_without_symbol_history": missing_map,
        "price_rows_without_chain_mapping": unmapped_rows,
        "adjustment_check": "passed: adj_close == raw close * cumulative factor; adjusted OHLC validated",
        "liquidity_basis": "raw bhavcopy turnover (not adjusted close * raw volume)",
    }
    return frames, diagnostics, metadata, pd.DataFrame(symbol_audit)
