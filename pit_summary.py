"""Summary statistics for the point-in-time momentum samples.

Reports the distribution, not just the mean: dispersion, win rates, the Bull/Bear split, the market filter against the
raw basket and the benchmark, exclusion counts, and a block-bootstrap interval that respects overlapping windows.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

RAW = "raw_top20_equal_weight_net_return_pct"
FILTERED = "market_filter_portfolio_net_return_pct"


def block_bootstrap_ci(values, block, reps=2000, seed=11, level=95.0):
    """Circular block bootstrap of the mean. Block length >= the number of consecutive samples whose holding windows
    overlap, so neighbouring (dependent) samples are resampled together."""
    x = np.asarray(values, float)
    n = len(x)
    if n < 6:
        return (float("nan"), float("nan"))
    block = int(max(1, min(block, n)))
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(n / block))
    starts = rng.integers(0, n, size=(reps, nb))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(reps, -1)[:, :n]
    means = x[idx].mean(1)
    q = (100 - level) / 2
    return (float(np.percentile(means, q)), float(np.percentile(means, 100 - q)))


def json_safe(obj):
    """NaN / inf -> None and tuples -> lists, so summary.json is strict JSON."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(x) for x in obj]
    if isinstance(obj, (float, np.floating)):
        return float(obj) if math.isfinite(float(obj)) else None
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _dist(v):
    v = np.asarray(v, float)
    return {"mean": float(v.mean()), "median": float(np.median(v)), "std": float(v.std(ddof=1)) if len(v) > 1 else float("nan"),
            "min": float(v.min()), "max": float(v.max()), "win_rate_pct": float((v > 0).mean() * 100)}


def _md(frame):
    cols = list(frame.columns)
    rows = frame.astype("object").where(pd.notna(frame), "").astype(str).values.tolist()
    return "\n".join(["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |",
                      *["| " + " | ".join(r) + " |" for r in rows]])


def summarize_returns(returns: pd.DataFrame, stocks: pd.DataFrame, min_gap: int, horizons: dict, seed: int = 11, reps: int = 2000):
    comp = "nifty500_tri_return_pct"
    cc = "raw_top20_close_to_close_net_return_pct" in returns and returns["raw_top20_close_to_close_net_return_pct"].notna().any()
    raw_col = "raw_top20_close_to_close_net_return_pct" if cc else RAW
    fil_col = "market_filter_close_to_close_net_return_pct" if cc else FILTERED
    out = {"benchmark_column": comp, "primary_basket_column": raw_col, "min_gap_sessions": min_gap, "horizons": {}}
    lines = ["## Summary statistics", "",
             f"Benchmark: `{comp}` (signal-date close to exit close). Primary stock series: `{raw_col}` - "
             + ("measured over the SAME window as the benchmark (signal close to exit close), so the comparison is like for like. "
                "The as-traded next-open basket is shown separately with its overnight effect. " if cc else "next-open entry (no like-for-like series available). ")
             + "Samples whose basket has any missing or corporate-action-invalidated stock return are EXCLUDED (never reweighted). "
             "Overlapping holding windows make neighbouring samples dependent: the effective number of independent samples is about "
             "n x min(1, min_gap / horizon), and the intervals use a circular block bootstrap.", ""]
    for label, h in horizons.items():
        d = returns[returns["horizon"] == label].sort_values("signal_date")
        ok = d[d["complete_stock_prices"].astype(bool) & d[comp].notna() & d[raw_col].notna() & d[fil_col].notna()]
        block = max(1, int(math.ceil(h / max(1, min_gap))))
        info = {"samples": int(len(d)), "complete_samples": int(len(ok)), "incomplete_samples": int(len(d) - len(ok)),
                "effective_independent_samples": float(len(ok) * min(1.0, min_gap / h)), "bootstrap_block": block}
        excl = {}
        status_col = f"{label}_return_status"
        if stocks is not None and status_col in stocks:
            excl = {str(k): int(v) for k, v in stocks[status_col].value_counts().items()}
        info["stock_return_status_counts"] = excl
        lines.append(f"### {label} ({h} sessions): {len(d)} samples, {len(ok)} complete, {len(d) - len(ok)} incomplete; "
                     f"~{info['effective_independent_samples']:.1f} effectively independent")
        if len(ok) == 0:
            out["horizons"][label] = info
            lines += ["_No complete samples._", ""]
            continue
        raw, fil, tri = ok[raw_col].astype(float), ok[fil_col].astype(float), ok[comp].astype(float)
        if cc:
            traded = ok[RAW].astype(float)
            info["as_traded_next_open"] = {**_dist(traded), "overnight_execution_effect_mean": float((traded - raw).mean()),
                                           "beats_benchmark_pct": float((traded > tri).mean() * 100)}
        info.update({"raw": _dist(raw), "market_filter": _dist(fil), "benchmark": _dist(tri),
                     "raw_beats_benchmark_pct": float((raw > tri).mean() * 100),
                     "filter_beats_benchmark_pct": float((fil > tri).mean() * 100),
                     "mean_excess_raw": float((raw - tri).mean()), "mean_excess_filter": float((fil - tri).mean()),
                     "median_excess_raw": float((raw - tri).median()), "median_excess_filter": float((fil - tri).median()),
                     "ci95_mean_excess_raw": block_bootstrap_ci((raw - tri).to_numpy(), block, reps, seed),
                     "ci95_mean_excess_filter": block_bootstrap_ci((fil - tri).to_numpy(), block, reps, seed)})
        table = pd.DataFrame({
            "series": ["raw top-20" + (" (close-to-close)" if cc else ""), "market-filtered" + (" (close-to-close)" if cc else ""), "benchmark (TRI)"],
            "mean %": [info[k]["mean"] for k in ("raw", "market_filter", "benchmark")],
            "median %": [info[k]["median"] for k in ("raw", "market_filter", "benchmark")],
            "std %": [info[k]["std"] for k in ("raw", "market_filter", "benchmark")],
            "worst %": [info[k]["min"] for k in ("raw", "market_filter", "benchmark")],
            "best %": [info[k]["max"] for k in ("raw", "market_filter", "benchmark")],
            "win rate % (>0)": [info[k]["win_rate_pct"] for k in ("raw", "market_filter", "benchmark")],
            "beats benchmark %": [info["raw_beats_benchmark_pct"], info["filter_beats_benchmark_pct"], float("nan")],
        }).round(2)
        lines += [_md(table), ""]
        lo, hi = info["ci95_mean_excess_raw"]
        flo, fhi = info["ci95_mean_excess_filter"]
        if cc:
            a = info["as_traded_next_open"]
            lines += [f"As traded (buy at the next open): mean {a['mean']:+.2f}%, median {a['median']:+.2f}%; the overnight execution effect vs the close-to-close basket "
                      f"averages {a['overnight_execution_effect_mean']:+.2f} pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).", ""]
        lines += [f"Mean excess vs benchmark, raw: {info['mean_excess_raw']:+.2f} pts (median {info['median_excess_raw']:+.2f}), "
                  f"95% block-bootstrap interval [{lo:+.2f}, {hi:+.2f}]",
                  f"Mean excess vs benchmark, market-filtered: {info['mean_excess_filter']:+.2f} pts (median {info['median_excess_filter']:+.2f}), "
                  f"95% interval [{flo:+.2f}, {fhi:+.2f}]", ""]
        reg_rows, info["by_regime"] = [], {}
        for reg in ("BULL", "BEAR"):
            sub = ok[ok["market_regime"] == reg]
            if len(sub):
                r, f, t = sub[raw_col].astype(float), sub[fil_col].astype(float), sub[comp].astype(float)
                info["by_regime"][reg] = {"n": int(len(sub)), "raw_mean": float(r.mean()), "raw_median": float(r.median()),
                                          "filter_mean": float(f.mean()), "benchmark_mean": float(t.mean()),
                                          "raw_beats_pct": float((r > t).mean() * 100), "filter_beats_pct": float((f > t).mean() * 100)}
                reg_rows.append({"regime": reg, "n": len(sub), "raw mean %": r.mean(), "raw median %": r.median(), "filtered mean %": f.mean(),
                                 "benchmark mean %": t.mean(), "raw beats %": (r > t).mean() * 100, "filtered beats %": (f > t).mean() * 100})
        if reg_rows:
            lines += [_md(pd.DataFrame(reg_rows).round(2)), ""]
        lines += [f"Stock-level return status counts at {label}: {excl}", ""]
        out["horizons"][label] = info
    return "\n".join(lines), out
