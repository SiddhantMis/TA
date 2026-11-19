"""Predeclared ranking comparisons; operational rules never auto-promote a result."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .repository import clean

METHODS = ("baseline", "volatility_adjusted", "fip")


def compare_momentum_rankings(frames, benchmark, as_of):
    cutoff = pd.Timestamp(as_of)
    calendar = benchmark.loc[benchmark.index <= cutoff].index
    rows, excluded = [], {}
    method_exclusions = {method: {} for method in METHODS}
    for symbol, frame in frames.items():
        d = frame.loc[frame.index <= cutoff]
        if len(calendar) < 253 or d.empty or d.index[-1] != cutoff:
            excluded[symbol] = "Insufficient or stale history."
            continue
        close = pd.to_numeric(d["Adj Close"] if "Adj Close" in d else d.Close, errors="coerce").reindex(calendar)
        observed_close = pd.to_numeric(d["Adj Close"] if "Adj Close" in d else d.Close, errors="coerce")
        if observed_close.isna().any() or not np.isfinite(observed_close).all() or (observed_close <= 0).any():
            excluded[symbol] = "Adjusted source observations contain missing, non-finite or non-positive prices."
            continue
        raw = pd.to_numeric(d.Close, errors="coerce").reindex(calendar)
        volume = pd.to_numeric(d.Volume, errors="coerce").reindex(calendar)
        recent = close.iloc[-253:]
        if recent.notna().mean() < 0.95 or recent.iloc[[0, -22, -1]].isna().any():
            excluded[symbol] = "Insufficient observed formation coverage or missing return endpoints."
            continue
        returns = np.log(recent).diff().dropna()
        volatility = float(returns.std(ddof=1) * np.sqrt(252))
        formation = recent.iloc[-22] / recent.iloc[0] - 1
        path = recent.iloc[:-21].pct_change(fill_method=None).dropna()
        information_discreteness = float(np.sign(formation) * ((path < 0).mean() - (path > 0).mean()))
        rows.append({"symbol": symbol, "baseline_score": float(formation),
                     "above_sma200": bool(observed_close.iloc[-1] > observed_close.iloc[-200:].mean()),
                     "return_6m": float(close.iloc[-1] / close.iloc[-127] - 1),
                     "return_12m": float(close.iloc[-1] / close.iloc[-253] - 1),
                     "volatility": volatility, "information_discreteness": information_discreteness,
                     "liquidity_proxy": float((d.Close * d.Volume).rolling(126, min_periods=100).mean().iloc[-1])})
    rows = sorted(rows, key=lambda x: (-x["liquidity_proxy"], x["symbol"]))[:200]
    for row in rows:
        if not row["above_sma200"]:
            excluded[row["symbol"]] = "At or below the stock's 200-DMA after liquidity selection."
        if row["volatility"] <= 0:
            method_exclusions["volatility_adjusted"][row["symbol"]] = "No positive, finite return-volatility denominator."
    rows = [row for row in rows if row["above_sma200"]]
    panel = pd.DataFrame(rows)
    rankings = {method: [] for method in METHODS}
    if not panel.empty:
        for horizon in ("6m", "12m"):
            ratio = panel[f"return_{horizon}"] / panel.volatility.where(panel.volatility > 0)
            std = ratio.std(ddof=0)
            panel[f"z_{horizon}"] = (ratio - ratio.mean()) / std if std > 0 else ratio.where(ratio.isna(), 0)
        z = (panel.z_6m + panel.z_12m) / 2
        panel["volatility_adjusted_score"] = z.copy()
        panel.loc[z >= 0, "volatility_adjusted_score"] = 1 + z[z >= 0]
        panel.loc[z < 0, "volatility_adjusted_score"] = 1 / (1 - z[z < 0])
        for method in METHODS:
            selected = panel.loc[panel.information_discreteness < 0] if method == "fip" else panel
            score = "volatility_adjusted_score" if method == "volatility_adjusted" else "baseline_score"
            selected = selected.loc[selected[score].notna()].sort_values([score, "symbol"], ascending=[False, True])
            rankings[method] = [dict(symbol=row["symbol"], score=float(row[score]), rank=i + 1)
                                for i, row in enumerate(selected.to_dict("records"))]
    return clean({"as_of": str(as_of), "rankings": rankings, "factors": panel.to_dict("records"),
                  "excluded": excluded, "method_exclusions": method_exclusions,
                  "status": "diagnostic_only", "operational_method": "baseline",
                  "definitions": {
                      "baseline": "12-1 adjusted return, latest 21 sessions excluded.",
                      "volatility_adjusted": "Equal 6/12-month cross-sectional z-scores of return divided by annualized 252-session log-return volatility; ranking adaptation, not an NSE index replica.",
                      "fip": "Baseline ordering after ID=sign(formation return)*(negative-day share-positive-day share)<0; not a guarantee of path smoothness.",
                  }, "limitations": ["Current-constituent universe; not a survivorship-free historical reconstruction.",
                                       "No automatic strategy promotion; all three methods share basket execution assumptions in replay."]})


def compare_portfolios(frames, benchmark, start, end, capital):
    from .momentum import run_momentum
    states = {method: None for method in METHODS}
    reports = {method: [] for method in METHODS}
    sessions = benchmark.loc[(benchmark.index >= pd.Timestamp(start)) & (benchmark.index <= pd.Timestamp(end))].index
    for stamp in sessions:
        day = stamp.date().isoformat()
        for method in METHODS:
            report = run_momentum(frames, benchmark, day, previous_model=states[method],
                model_capital=capital, universe_size=len(frames), ranking_method=method)
            states[method] = report["model"]
            reports[method].append({"as_of": day, "status": report["status"], "model": report["model"]})
    return {"status": "diagnostic_only", "start": start, "end": end, "results": reports,
            "limitations": ["Membership is the supplied universe, not a validated historical constituent archive.",
                             "Use source-qualified, identical windows; inspected historical periods are not untouched holdouts."]}
