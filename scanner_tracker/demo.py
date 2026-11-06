"""Deterministic synthetic preview. This never downloads real market data."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .market import BENCHMARK


def synthetic_frames(as_of="2026-10-30"):
    dates = pd.bdate_range(end=as_of, periods=620)
    x = np.arange(len(dates))
    frames = {}
    for i, symbol in enumerate(("DEMOA.NS", "DEMOB.NS", "DEMOC.NS", BENCHMARK)):
        close = (70 + i * 15) * np.exp((0.001 + i * 0.00005) * x) + np.sin(x / 7) * 0.5
        frame = pd.DataFrame({"Open": close * 0.998, "High": close * 1.006,
                              "Low": close * 0.994, "Close": close, "Adj Close": close,
                              "Volume": np.full(len(x), 100_000 + i * 10_000)}, index=dates)
        if symbol == "DEMOA.NS":
            frame.loc[dates[-2], "Close"] = frame.loc[dates[-3], "High"] * 1.025
            frame.loc[dates[-2], "High"] = frame.loc[dates[-2], "Close"] * 1.003
            frame.loc[dates[-2], "Volume"] = 300_000
            for col in ("Open", "High", "Low", "Close", "Adj Close"):
                frame.loc[dates[-1], col] *= 1.025
            frame.loc[dates[-2], "Adj Close"] = frame.loc[dates[-2], "Close"]
        frames[symbol] = frame
    benchmark = frames.pop(BENCHMARK)
    return frames, benchmark


def seed_demo(service):
    if service.repo.runs(1):
        return service.status()
    frames, benchmark = synthetic_frames()
    service.update_settings({"personal_symbols": ["DEMOA.NS", "DEMOB.NS"], "momentum_capital_inr": 200_000,
                             "instrument_types": {"DEMOA.NS": "equity", "DEMOB.NS": "equity", "DEMOC.NS": "equity"},
                             "ta_capital_inr": 100_000, "ta_risk_pct": 0.5, "ta_max_position_pct": 10})
    service.configure_ledger("TA", 100_000, as_of="2026-10-29")
    service.configure_ledger("MOMENTUM", 200_000, as_of="2026-10-29")
    scope = {"wide": list(frames), "personal": ["DEMOA.NS", "DEMOB.NS"]}
    first = benchmark.index[-2].date().isoformat()
    service.scan_frames({s: f.loc[:first] for s, f in frames.items()}, benchmark.loc[:first], first,
                        scopes=scope, source="SYNTHETIC LOCAL DEMO")
    service.scan_frames(frames, benchmark, "2026-10-30", scopes=scope, source="SYNTHETIC LOCAL DEMO")
    candidates = service.repo.candidates()
    if candidates:
        service.set_watch(candidates[0]["id"], note="Synthetic demonstration — not a real security or trading result.")
    return service.status()
