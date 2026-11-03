"""Corporate-action audit and conservative post-event lookback reset."""
from pathlib import Path
import pandas as pd

UNSUPPORTED = {"merger","demerger","rights","buyback","other"}

def load_and_apply_action_quarantine(frames, start_date, end_date, cache_dir="data_cache/tejhq_actions", revision=None):
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
        clipped = frame.loc[pd.DatetimeIndex(frame.index).normalize() >= event].copy()
        result[ticker] = clipped
        quarantine.append({"symbol":symbol,"reset_date":event.date().isoformat(),
            "bars_after_reset":len(clipped),"eligible_after_253_sessions":len(clipped)>=253})
    if not audit.empty:
        loaded = {str(t).removesuffix(".NS").upper() for t in frames}
        audit["loaded_symbol_series"] = audit["symbol"].isin(loaded)
    return result, audit, pd.DataFrame(quarantine)
