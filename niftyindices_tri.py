"""Official NSE Indices NIFTY 500 Total Return Index history loader."""
import json
from datetime import timedelta
import pandas as pd
import requests

URL = "https://www.niftyindices.com/Backpage.aspx/getTotalReturnIndexString"

def load_nifty500_tri_history(start_date, end_date, session=None):
    start, end = pd.Timestamp(start_date).date(), pd.Timestamp(end_date).date()
    client = session or requests.Session()
    client.headers.update({"Content-Type":"application/json; charset=UTF-8",
        "X-Requested-With":"XMLHttpRequest",
        "Referer":"https://www.niftyindices.com/reports/historical-data",
        "User-Agent":"Mozilla/5.0 (compatible; TAResearch/1.0)"})
    rows, cursor = [], start
    while cursor <= end:
        last = min(end, cursor + timedelta(days=364))
        cinfo = "{'name':'NIFTY 500','startDate':'" + cursor.strftime("%d-%b-%Y") + "','endDate':'" + last.strftime("%d-%b-%Y") + "','indexName':'NIFTY 500'}"
        response = client.post(URL, json={"cinfo":cinfo}, timeout=60)
        response.raise_for_status()
        payload = response.json().get("d")
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected NSE Indices TRI response")
        rows.extend(payload)
        cursor = last + timedelta(days=1)
    frame = pd.DataFrame(rows)
    if frame.empty or "Date" not in frame or "TotalReturnsIndex" not in frame:
        raise RuntimeError("NSE Indices returned no valid NIFTY 500 TRI data")
    frame["Date"] = pd.to_datetime(frame["Date"], format="%d %b %Y", errors="coerce")
    frame["Close"] = pd.to_numeric(frame["TotalReturnsIndex"], errors="coerce")
    frame = frame.dropna(subset=["Date","Close"])
    frame = frame.loc[frame["Date"].dt.date.between(start,end),["Date","Close"]]
    frame = frame.drop_duplicates("Date",keep="last").set_index("Date").sort_index()
    if frame.empty or frame["Close"].le(0).any():
        raise RuntimeError("NIFTY 500 TRI contains invalid values")
    return frame
