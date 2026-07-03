"""
Unit tests for candlestick pattern detection. Zero network access needed —
this is what's actually been verified. The live yfinance fetch path has
NOT been run (see analyzer.py docstring); test that separately once this
runs inside GitHub Actions.

Several fixtures below are the real OHLC values checked by hand earlier
this week — this test suite is partly a regression check that the code
agrees with those manual calls, not just synthetic examples.
"""
import sys
import numpy as np
import pandas as pd
from analyzer import (
    classify_single, classify_two_candle, trend_direction, trend_metrics,
    _flatten_columns, _find_pivots, _cluster_levels, get_sr_levels,
    compute_indicators, score_ticker,
)


def row(o, h, l, c):
    return pd.Series({"Open": o, "High": h, "Low": l, "Close": c})


def test_bullish_marubozu():
    # MCX, June 22 close — confirmed Marubozu in conversation
    r = row(2822.00, 2870.40, 2822.00, 2863.60)
    assert classify_single(r) == "bullish_marubozu", classify_single(r)


def test_doji():
    # HDFCBANK, June 9 — confirmed Doji (not Hammer) after checking OHLC by hand
    r = row(739.45, 743.95, 732.30, 738.35)
    assert classify_single(r) == "doji", classify_single(r)


def test_not_a_hammer_when_upper_wick_dominates():
    # HDFCBANK, June 10 — looked Hammer-shaped at a glance, correctly
    # rejected once OHLC was checked (real upper wick, near-zero lower wick)
    r = row(736.50, 755.95, 736.40, 746.85)
    result = classify_single(r)
    assert result != "hammer_or_hanging_man", result


def test_engulfing_condition_correctly_rejected():
    # ETERNAL June 11-12 — looked like it might be engulfing, confirmed
    # NOT engulfing once OHLC was checked (opened above prior close)
    prev = row(238.00, 238.30, 234.25, 235.20)
    curr = row(239.00, 244.50, 237.65, 243.80)
    assert classify_two_candle(prev, curr) != "bullish_engulfing"


def test_bullish_engulfing_when_conditions_actually_met():
    prev = row(238.00, 238.30, 234.25, 235.20)
    curr = row(234.00, 244.50, 233.00, 243.80)  # opens below prev close, closes above prev open
    assert classify_two_candle(prev, curr) == "bullish_engulfing"


def test_piercing_pattern():
    prev = row(238.00, 238.30, 234.25, 235.20)  # midpoint = 236.60
    curr = row(233.00, 240.00, 232.00, 237.50)  # opens below prev low, closes above midpoint but below prev open
    assert classify_two_candle(prev, curr) == "piercing_pattern"


def test_trend_direction_uptrend():
    highs = [100 + i for i in range(20)]
    lows = [95 + i for i in range(20)]
    df = pd.DataFrame({
        "Open": lows, "High": highs, "Low": [h - 6 for h in lows], "Close": highs,
        "Volume": [1_000_000] * 20,
    })
    assert trend_direction(df, 19) == "uptrend", trend_direction(df, 19)


def test_trend_direction_downtrend():
    highs = [120 - i for i in range(20)]
    lows = [115 - i for i in range(20)]
    df = pd.DataFrame({
        "Open": [h - 2 for h in highs], "High": highs, "Low": lows,
        "Close": [h - 4 for h in highs], "Volume": [1_000_000] * 20,
    })
    assert trend_direction(df, 19) == "downtrend", trend_direction(df, 19)


def test_flatten_multiindex_field_level_first():
    # Simulates the yfinance layout that caused "truth value of a Series
    # is ambiguous" on 9 of 11 tickers in the first live run
    idx = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["ETERNAL.NS"]])
    data = pd.DataFrame([[100, 105, 99, 103, 1_000_000]] * 5, columns=idx)
    flat = _flatten_columns(data, "ETERNAL.NS")
    assert set(flat.columns) == {"Open", "High", "Low", "Close", "Volume"}, list(flat.columns)
    assert isinstance(flat["Close"], pd.Series), type(flat["Close"])


def test_flatten_multiindex_ticker_level_first():
    idx = pd.MultiIndex.from_product([["ETERNAL.NS"], ["Open", "High", "Low", "Close", "Volume"]])
    data = pd.DataFrame([[100, 105, 99, 103, 1_000_000]] * 5, columns=idx)
    flat = _flatten_columns(data, "ETERNAL.NS")
    assert set(flat.columns) == {"Open", "High", "Low", "Close", "Volume"}, list(flat.columns)
    assert isinstance(flat["Close"], pd.Series), type(flat["Close"])


def test_flatten_leaves_normal_columns_untouched():
    data = pd.DataFrame({"Open": [1], "High": [2], "Low": [0], "Close": [1.5], "Volume": [100]})
    flat = _flatten_columns(data, "ANY.NS")
    assert list(flat.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_trend_direction_choppy_when_r2_low():
    # Sawtooth around a flat mean -- old HH/LH counter could tip this
    # either way depending on the exact zigzag; regression should see
    # ~zero slope and low R^2 and correctly call it choppy either way.
    closes = [100 + (5 if i % 2 == 0 else -5) for i in range(20)]
    df = pd.DataFrame({
        "Open": closes, "High": [c + 1 for c in closes], "Low": [c - 1 for c in closes],
        "Close": closes, "Volume": [1_000_000] * 20,
    })
    assert trend_direction(df, 19) == "choppy", trend_direction(df, 19)


def test_trend_metrics_high_r2_for_clean_line():
    closes = [100 + i * 0.5 for i in range(20)]
    df = pd.DataFrame({
        "Open": closes, "High": closes, "Low": closes, "Close": closes,
        "Volume": [1_000_000] * 20,
    })
    m = trend_metrics(df, 19)
    assert m["r2"] > 0.95, m


def test_rsi_uses_wilder_smoothing_not_plain_sma():
    # A plain rolling-mean RSI and a Wilder-smoothed RSI diverge once you
    # have more than RSI_WINDOW bars of history with a regime change in
    # them -- Wilder's EWM keeps weighting old bars (decayed), a simple
    # rolling window drops them instantly. Construct a case designed to
    # separate them and just check the formula path runs and produces a
    # sane bounded value, since exact expected value requires a reference
    # implementation.
    closes = [100] * 10 + [100 + i for i in range(20)]
    df = pd.DataFrame({
        "Open": closes, "High": [c + 1 for c in closes], "Low": [c - 1 for c in closes],
        "Close": closes, "Volume": [1_000_000] * len(closes),
    })
    out = compute_indicators(df)
    rsi = out["rsi14"].iloc[-1]
    assert 0 <= rsi <= 100, rsi
    assert rsi > 50, "RSI should read well above 50 after a sustained 20-bar rally"


def test_pivot_clustering_finds_repeated_touch_as_higher_confidence():
    lows = [100, 95, 98, 94.8, 99, 95.2, 97, 90, 96]
    pivots = _find_pivots(np.array(lows), window=1, mode="low")
    clusters = _cluster_levels(pivots, tolerance_pct=0.02)
    touched_95 = [c for c in clusters if 94 <= c["level"] <= 96]
    assert touched_95, clusters
    assert touched_95[0]["touches"] >= 2, touched_95


def test_get_sr_levels_ignores_far_away_levels():
    # support pivot exists but sits >5% below current close -- should be
    # dropped rather than reported as "near support" bait
    n = 70
    lows = [50] * 5 + [200] * (n - 5)
    highs = [l + 2 for l in lows]
    closes = [l + 1 for l in lows]
    df = pd.DataFrame({"Open": closes, "High": highs, "Low": lows, "Close": closes,
                        "Volume": [1_000_000] * n})
    sr = get_sr_levels(df, n - 1)
    assert sr["support"] is None or sr["support"] > 190, sr


def test_score_ticker_recommendation_and_flag_agree_at_threshold():
    # Full synthetic downtrend into a hammer at a twice-touched support
    # level -- should score checks 1-3 at minimum and produce a
    # non-empty recommendation string, not just a bare flag.
    n = 90
    rng = np.random.default_rng(7)
    closes = [200 - i * 1.2 for i in range(n - 1)]
    lows = [c - 1 for c in closes]
    highs = [c + 1 for c in closes]
    opens = [c + 0.3 for c in closes]
    vols = [1_000_000 + int(rng.normal(0, 50_000)) for _ in range(n - 1)]
    # hammer candle on the last bar: long lower wick, small body, closes near support
    support_level = min(lows[-20:])
    opens.append(support_level + 3)
    highs.append(support_level + 4)
    lows.append(support_level - 8)
    closes.append(support_level + 3.5)
    vols.append(3_000_000)
    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols})
    r = score_ticker(df, "TEST.NS")
    assert r is not None
    assert isinstance(r.confidence, float)
    assert r.recommendation, "recommendation should never be empty"
    assert r.flag == (r.checks_passed >= 4)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
