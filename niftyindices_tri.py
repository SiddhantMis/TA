"""Official NSE Indices NIFTY 500 Total Return Index history loader."""
import json
import time
from datetime import timedelta

import pandas as pd
import requests

# NSE changed the historical-data API route from /Backpage.aspx/ to /BackPage/.
URL = "https://www.niftyindices.com/BackPage/getTotalReturnIndexString"
LANDING_URL = "https://www.niftyindices.com/reports/historical-data"


def _warm_session(client):
    response = client.get(LANDING_URL, timeout=30)
    response.raise_for_status()


def _post_tri_request(client, body):
    last_error = None
    for attempt in range(3):
        response = None
        try:
            response = client.post(URL, json=body, timeout=60)
            response.raise_for_status()
            decoded = response.json()

            # Current NSE endpoint returns the array directly. Accept the older
            # {"d": "..."} envelope as a compatibility fallback.
            if isinstance(decoded, dict) and "d" in decoded:
                payload = decoded["d"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
            else:
                payload = decoded

            if not isinstance(payload, list):
                raise ValueError("NSE TRI response was not a JSON array")
            return payload
        except (ValueError, requests.exceptions.RequestException) as exc:
            last_error = exc
            if attempt == 2:
                content_type = response.headers.get("Content-Type", "unknown") if response is not None else "unknown"
                snippet = response.text[:240].replace("\\n", " ") if response is not None else ""
                raise RuntimeError(
                    "NSE Indices TRI request did not return valid JSON after 3 attempts "
                    f"(last error: {exc}; content-type: {content_type}; body: {snippet!r})"
                ) from exc
            _warm_session(client)
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"NSE Indices TRI request failed: {last_error}")


def load_nifty500_tri_history(start_date, end_date, session=None):
    start, end = pd.Timestamp(start_date).date(), pd.Timestamp(end_date).date()
    client = session or requests.Session()
    client.headers.update({
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://www.niftyindices.com",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": LANDING_URL,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/134.0.0.0 Safari/537.36",
    })
    _warm_session(client)
    rows, cursor = [], start
    while cursor <= end:
        last = min(end, cursor + timedelta(days=364))
        cinfo = (
            "{'name':'NIFTY 500','startDate':'"
            + cursor.strftime("%d-%b-%Y")
            + "','endDate':'"
            + last.strftime("%d-%b-%Y")
            + "','indexName':'NIFTY 500'}"
        )
        rows.extend(_post_tri_request(client, {"cinfo": cinfo}))
        cursor = last + timedelta(days=1)

    frame = pd.DataFrame(rows)
    if frame.empty or "Date" not in frame or "TotalReturnsIndex" not in frame:
        raise RuntimeError("NSE Indices returned no valid NIFTY 500 TRI data")
    frame["Date"] = pd.to_datetime(frame["Date"], format="%d %b %Y", errors="coerce")
    frame["Close"] = pd.to_numeric(frame["TotalReturnsIndex"], errors="coerce")
    frame = frame.dropna(subset=["Date", "Close"])
    frame = frame.loc[frame["Date"].dt.date.between(start, end), ["Date", "Close"]]
    frame = frame.drop_duplicates("Date", keep="last").set_index("Date").sort_index()
    if frame.empty or frame["Close"].le(0).any():
        raise RuntimeError("NIFTY 500 TRI contains invalid values")
    return frame
