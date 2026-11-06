"""Corporate-action audit and point-in-time post-event eligibility resets."""
from pathlib import Path
import pandas as pd

UNSUPPORTED = {"merger","demerger","rights","buyback","other"}

def action_quarantine_masks(sessions, frames):
    """Return eligibility and ex-session masks without deleting past prices.

    An action affects only its ex-date and later decisions. A complete 253-bar
    window must start on or after the latest action known on that signal date;
    prepare separately requires every observation in that window to be present.
    """
    idx = pd.DatetimeIndex(sessions)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    idx = idx.normalize()
    eligible = pd.DataFrame(True, index=idx, columns=list(frames))
    events = pd.DataFrame(False, index=idx, columns=list(frames))
    window_start = pd.Series(idx, index=idx).shift(252)
    for ticker, frame in frames.items():
        dates = pd.DatetimeIndex(pd.to_datetime(frame.attrs.get("unsupported_action_dates", []), errors="raise"))
        if dates.hasnans:
            raise ValueError(f"{ticker}: unsupported corporate action lacks an ex-date")
        if dates.tz is not None:
            dates = dates.tz_localize(None)
        for event in dates.normalize().unique().sort_values():
            affected = idx >= event
            eligible.loc[affected, ticker] = window_start.loc[affected].ge(event).to_numpy()
            pos = int(idx.searchsorted(event))
            if pos < len(idx):
                events.iloc[pos, events.columns.get_loc(ticker)] = True
    return eligible, events


def load_and_apply_action_quarantine(frames, start_date, end_date, cache_dir="data_cache/tejhq_actions", revision=None):
    """Attach reset dates while retaining pre-event bars for historical decisions.

    The quarantine table summarizes the final loaded window only and cannot
    decide whether the stock qualified at an earlier date.
    """
    from huggingface_hub import hf_hub_download
    start, end = pd.Timestamp(start_date).normalize(), pd.Timestamp(end_date).normalize()
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    parts = []
    for year in range(start.year,end.year+1):
        name = f"actions/nse_{year}.parquet"
        try:
            path = hf_hub_download(repo_id="tejhq/indian-markets",repo_type="dataset",
                filename=name,cache_dir=cache_dir,revision=revision)
        except Exception as exc:
            raise RuntimeError(f"Cannot audit {name}: {exc}") from exc
        data = pd.read_parquet(path)
        if not {"symbol","ex_date","type"}.issubset(data.columns):
            raise RuntimeError(f"{name} lacks required action fields")
        data["symbol"] = data["symbol"].astype(str).str.strip().str.upper()
        data["type"] = data["type"].astype(str).str.strip().str.lower()
        data["ex_date"] = pd.to_datetime(data["ex_date"],errors="coerce").dt.normalize()
        data = data.loc[data["ex_date"].between(start,end) & data["type"].isin(UNSUPPORTED)].copy()
        if not data.empty:
            data["source_file"] = name
            parts.append(data)
    audit = pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=["symbol","ex_date","type","source_file"])
    latest = audit.groupby("symbol")["ex_date"].max().to_dict() if not audit.empty else {}
    result, quarantine = {}, []
    for ticker, frame in frames.items():
        symbol = str(ticker).removesuffix(".NS").upper()
        event = latest.get(symbol)
        if event is None:
            result[ticker] = frame
            continue
        retained = frame.copy()
        symbol_events = audit.loc[audit["symbol"].eq(symbol), "ex_date"].drop_duplicates().sort_values()
        retained.attrs["unsupported_action_dates"] = symbol_events.dt.strftime("%Y-%m-%d").tolist()
        result[ticker] = retained
        post_event = frame.loc[pd.DatetimeIndex(frame.index).normalize() >= event]
        quarantine.append({"symbol":symbol,"reset_date":event.date().isoformat(),
            "bars_after_reset":len(post_event),"eligible_after_253_sessions":len(post_event)>=253})
    if not audit.empty:
        loaded = {str(t).removesuffix(".NS").upper() for t in frames}
        audit["loaded_symbol_series"] = audit["symbol"].isin(loaded)
    return result, audit, pd.DataFrame(quarantine)
