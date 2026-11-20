"""Charts of observed EOD data; no inferred fills or substituted prices."""
from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd
import plotly.graph_objects as go


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def price(value):
    if isinstance(value, Mapping):
        value = value.get("price", value.get("level", value.get("value")))
    result = number(value)
    return result if result is not None and result > 0 else None


def _levels(value):
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    return [p for item in values if (p := price(item)) is not None]


def plan_prices(plan):
    plan = plan or {}
    entry = price(plan.get("entry", plan.get("trigger", plan.get("entry_price", plan.get("reference_entry")))))
    stop = price(plan.get("stop", plan.get("stop_price", plan.get("initial_stop"))))
    targets = _levels(plan.get("targets", plan.get("target", plan.get("target_price"))))
    return entry, stop, targets


def trade_markers(candidate):
    """Use recorded fills or recorded model state; never infer a fill from candles."""
    fills = [dict(item) for item in candidate.get("fills", [])]
    trade = candidate.get("model_trade") or {}
    existing = {(str(item.get("kind", "")), item.get("executed_at", item.get("date")),
                 str(item.get("side", "")).upper()) for item in fills}
    for side, date_key, price_key in (("BUY", "entry_session", "entry_price"),
                                       ("SELL", "exit_session", "exit_price")):
        session, value = trade.get(date_key), price(trade.get(price_key))
        if session and value is not None and ("model", session, side) not in existing:
            fills.append({"executed_at": session, "price_inr": value, "side": side, "kind": "model"})
    return fills


def observed_bars(bars):
    frame = bars.copy() if isinstance(bars, pd.DataFrame) else pd.DataFrame(bars)
    if frame.empty:
        return frame
    frame.columns = [str(c).lower() for c in frame.columns]
    if "date" not in frame:
        for key in ("session", "timestamp", "datetime"):
            if key in frame:
                frame = frame.rename(columns={key: "date"})
                break
    required = {"date", "open", "high", "low", "close"}
    if not required.issubset(frame):
        raise ValueError("Chart history is missing an observed date or OHLC price.")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    if frame["date"].isna().any() or frame["date"].duplicated().any():
        raise ValueError("Chart history has invalid or duplicate sessions.")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].map(lambda x: not math.isfinite(x) or x <= 0).any():
            raise ValueError("Chart history has missing or non-positive OHLC prices.")
    if ((frame["high"] < frame[["open", "low", "close"]].max(axis=1)) |
            (frame["low"] > frame[["open", "high", "close"]].min(axis=1))).any():
        raise ValueError("Chart history has inconsistent OHLC ranges.")
    return frame.sort_values("date")


def candlestick_figure(bars, original_plan=None, current_levels=None, fills=None, ticker=""):
    frame = observed_bars(bars)
    if frame.empty:
        return None
    figure = go.Figure(go.Candlestick(
        x=frame["date"], open=frame["open"], high=frame["high"],
        low=frame["low"], close=frame["close"], name=f"{ticker} EOD",
        increasing_line_color="#16826d", decreasing_line_color="#c74b55",
    ))
    entry, stop, targets = plan_prices(original_plan)
    for label, level, color in [("Original entry", entry, "#3869c8"), ("Original stop", stop, "#c74b55")]:
        if level is not None:
            figure.add_hline(y=level, line_dash="dot", line_color=color, name=label, showlegend=True)
    for index, level in enumerate(targets, 1):
        figure.add_hline(y=level, line_dash="dot", line_color="#16826d", name=f"Original target {index}", showlegend=True)
    original_levels = (original_plan or {}).get("levels") or {}
    for key in ("support", "resistance"):
        level = price(original_levels.get(key))
        if level is not None:
            figure.add_hline(y=level, line_dash="dot", line_color="#b4b9c1", name=f"Original {key}", showlegend=True)
    current = current_levels or {}
    current = current.get("levels", current)
    for keys, label, color in [(("supports", "support", "support_ladder"), "Current support", "#9aa59f"),
                               (("resistances", "resistance", "resistance_ladder"), "Current resistance", "#bd9a60")]:
        values = next((current[k] for k in keys if current.get(k) is not None), None)
        for level in _levels(values):
            figure.add_hline(y=level, line_dash="dash", line_color=color, name=label, showlegend=True)
    for fill in fills or []:
        value = price(fill.get("price_inr", fill.get("price", fill.get("fill_price"))))
        date = fill.get("executed_at", fill.get("date", fill.get("session")))
        if value is None or date is None:
            continue
        side = str(fill.get("side", "fill")).upper()
        kind = str(fill.get("kind", "recorded")).replace("_", " ")
        figure.add_trace(go.Scatter(x=[date], y=[value], mode="markers", name=f"{kind} {side}",
                                   marker={"size": 12, "symbol": "triangle-up" if side == "BUY" else "triangle-down"},
                                   hovertemplate=f"{kind} {side}: %{{y:,.2f}}<br>%{{x}}<extra></extra>"))
    figure.update_layout(height=500, margin={"l": 16, "r": 24, "t": 18, "b": 70},
                         xaxis_rangeslider_visible=False, yaxis_title="Price (INR)",
                         legend={"orientation": "h"}, template="plotly_white")
    return figure


def equity_figure(rows, *, series=None, yaxis_title="Portfolio value (INR)", as_percentage=False):
    """Plot explicitly selected observed series without treating missing returns as zero."""
    frame = pd.DataFrame(rows)
    if frame.empty:
        return None
    date_key = next((key for key in ("date", "session", "as_of", "timestamp") if key in frame), None)
    if date_key is None:
        return None
    frame = frame.sort_values(date_key, kind="stable")
    figure = go.Figure()
    selections = ([((key,), label) for key, label in series.items()] if series is not None else
                  [(("model_equity", "equity", "equity_inr", "total_value"), "Model portfolio"),
                   (("actual_equity", "actual_equity_inr"), "Actual portfolio"),
                   (("benchmark_equity", "benchmark"), "Benchmark")])
    for keys, label in selections:
        key = next((k for k in keys if k in frame), None)
        if key is not None:
            values = [number(value) for value in frame[key]]
            if any(value is not None for value in values):
                hover = "%{x}<br>%{y:.2%}<extra>%{fullData.name}</extra>" if as_percentage else "%{x}<br>%{y:,.2f}<extra>%{fullData.name}</extra>"
                figure.add_trace(go.Scatter(x=frame[date_key], y=values, mode="lines", name=label,
                                           connectgaps=False, hovertemplate=hover))
    if not figure.data:
        return None
    figure.update_layout(height=320, margin={"l": 12, "r": 12, "t": 18, "b": 16},
                         yaxis_title=yaxis_title, yaxis_tickformat=".2%" if as_percentage else None,
                         xaxis_type="category",
                         legend={"orientation": "h"}, template="plotly_white")
    return figure


def allocation_figure(weights):
    if not isinstance(weights, Mapping):
        return None
    values = [(str(symbol), number(weight)) for symbol, weight in weights.items()]
    values = [(symbol, weight) for symbol, weight in values if weight is not None and weight >= 0]
    if not values:
        return None
    values.sort(key=lambda item: item[1], reverse=True)
    figure = go.Figure(go.Bar(x=[symbol for symbol, _ in values], y=[weight * 100 for _, weight in values],
                             marker_color="#16826d", hovertemplate="%{x}: %{y:.1f}%<extra></extra>"))
    figure.update_layout(height=280, margin={"l": 12, "r": 12, "t": 10, "b": 30},
                         yaxis_title="Target weight (%)", template="plotly_white")
    return figure
