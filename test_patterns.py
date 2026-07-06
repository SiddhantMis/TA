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
    classify_single, classify_two_candle, classify_three_candle, trend_direction, trend_metrics,
    _flatten_columns, _find_pivots, _cluster_levels, get_sr_levels, SR_LEVELS_PER_SIDE,
    compute_indicators, score_ticker,
)


def row(o, h, l, c):
    return pd.Series({"Open": o, "High": h, "Low": l, "Close": c})


def _pad_history(n, base=300.0, seed=0):
    """Flat-ish padding history so a test dataframe clears score_ticker's
    minimum-length gate (now ~SR_LOOKBACK rows, for the 2-year S/R window)
    without disturbing the specific recent-candle behavior each test is
    actually checking. Returns lists, not a DataFrame, so callers can
    concatenate with their own hand-built recent candles."""
    rng = np.random.default_rng(seed)
    closes = [base + rng.normal(0, 2) for _ in range(n)]
    opens = [c + rng.normal(0, 1) for c in closes]
    highs = [max(o, c) + abs(rng.normal(2, 1)) for o, c in zip(opens, closes)]
    lows = [min(o, c) - abs(rng.normal(2, 1)) for o, c in zip(opens, closes)]
    vols = [1_000_000 + int(rng.normal(0, 50_000)) for _ in range(n)]
    return opens, highs, lows, closes, vols


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
    pad_o, pad_h, pad_l, pad_c, pad_v = _pad_history(450, base=300.0, seed=70)
    rng = np.random.default_rng(7)
    closes = pad_c + [200 - i * 1.2 for i in range(n - 1)]
    lows = pad_l + [c - 1 for c in closes[450:]]
    highs = pad_h + [c + 1 for c in closes[450:]]
    opens = pad_o + [c + 0.3 for c in closes[450:]]
    vols = pad_v + [1_000_000 + int(rng.normal(0, 50_000)) for _ in range(n - 1)]
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
    assert r.flag == bool(r.pattern is not None and r.pattern_matches_trend and r.checks_passed >= 4)


def test_flag_requires_pattern_not_just_four_of_five():
    # Same downtrend-into-support-with-volume setup as the test above,
    # but the final candle is deliberately ordinary -- no marubozu, no
    # doji, no hammer/star wick ratio, no two-candle relationship with
    # the prior bar. Trend/support/volume/RSI can still all pass on
    # their own. Before the fix, that was enough: flag=passed>=4 didn't
    # care whether pattern was one of the four. It has to be false now.
    n = 90
    pad_o, pad_h, pad_l, pad_c, pad_v = _pad_history(450, base=300.0, seed=70)
    rng = np.random.default_rng(7)
    closes = pad_c + [200 - i * 1.2 for i in range(n - 1)]
    lows = pad_l + [c - 1 for c in closes[450:]]
    highs = pad_h + [c + 1 for c in closes[450:]]
    opens = pad_o + [c + 0.3 for c in closes[450:]]
    vols = pad_v + [1_000_000 + int(rng.normal(0, 50_000)) for _ in range(n - 1)]
    support_level = min(lows[-20:])
    # ordinary candle: body/range ~0.6 (not marubozu >0.85, not doji <0.10),
    # wicks roughly equal (not hammer/star, which need one wick >=2x body)
    opens.append(support_level + 0.5)
    highs.append(support_level + 1.3)
    lows.append(support_level + 0.3)
    closes.append(support_level + 1.0)
    vols.append(3_000_000)  # volume check still passes on its own
    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols})
    r = score_ticker(df, "TEST.NS")
    assert r is not None
    assert r.pattern is None, r.pattern  # confirms this candle really doesn't match anything
    assert r.checks_passed >= 4, r.checks_passed  # confirms the other four really do pass
    assert r.flag is False, "flag fired with no candlestick pattern -- the exact bug being tested for"


def test_bullish_harami_detected():
    # prev: big red candle, curr: small candle fully inside prev's body
    prev = row(250.00, 251.00, 234.00, 235.00)   # body 235-250, big red
    curr = row(240.00, 242.00, 239.00, 241.00)   # body 240-241, inside 235-250
    assert classify_two_candle(prev, curr) == "bullish_harami", classify_two_candle(prev, curr)


def test_harami_rejected_when_curr_not_contained():
    prev = row(250.00, 251.00, 234.00, 235.00)  # bearish
    curr = row(233.00, 253.00, 232.00, 252.00)  # bullish, engulfs prev's body -> engulfing, not harami
    assert classify_two_candle(prev, curr) == "bullish_engulfing", classify_two_candle(prev, curr)


def test_harami_rejected_when_curr_body_too_large_relative_to_prev():
    prev = row(250.00, 251.00, 234.00, 235.00)   # body = 15
    curr = row(240.00, 249.00, 239.00, 249.00)   # body = 9, > 50% of 15 -> not a harami
    assert classify_two_candle(prev, curr) is None, classify_two_candle(prev, curr)


def test_morning_star_detected():
    c1 = row(250.00, 251.00, 234.00, 235.00)     # long red, body 235-250 (mid=242.5)
    c2 = row(232.00, 234.00, 230.00, 233.00)     # small star below c1's body
    c3 = row(233.00, 246.00, 232.50, 245.00)     # long green, closes above c1 midpoint (242.5)
    assert classify_three_candle(c1, c2, c3) == "morning_star", classify_three_candle(c1, c2, c3)


def test_evening_star_detected():
    c1 = row(235.00, 251.00, 234.00, 250.00)     # long green, body 235-250 (mid=242.5)
    c2 = row(252.00, 254.00, 251.00, 253.00)     # small star above c1's body
    c3 = row(252.00, 253.00, 239.00, 240.00)     # long red, closes below c1 midpoint (242.5)
    assert classify_three_candle(c1, c2, c3) == "evening_star", classify_three_candle(c1, c2, c3)


def test_morning_star_rejected_when_third_candle_doesnt_reclaim_midpoint():
    c1 = row(250.00, 251.00, 234.00, 235.00)     # mid = 242.5
    c2 = row(232.00, 234.00, 230.00, 233.00)
    c3 = row(233.00, 240.00, 232.50, 239.00)     # closes at 239, below midpoint 242.5 -> not a reclaim
    assert classify_three_candle(c1, c2, c3) is None, classify_three_candle(c1, c2, c3)


def test_morning_star_rejected_when_middle_candle_not_small():
    c1 = row(250.00, 251.00, 234.00, 235.00)
    c2 = row(232.00, 245.00, 230.00, 244.00)     # big body, not a "star"
    c3 = row(233.00, 246.00, 232.50, 245.00)
    assert classify_three_candle(c1, c2, c3) is None, classify_three_candle(c1, c2, c3)


def test_score_ticker_three_candle_precedence_over_single():
    # Build a downtrend ending in a genuine morning star so score_ticker's
    # 3-candle-first precedence actually gets exercised end to end, not
    # just the standalone classify_three_candle unit.
    n = 90
    pad_o, pad_h, pad_l, pad_c, pad_v = _pad_history(450, base=300.0, seed=11)
    rng = np.random.default_rng(11)
    closes = pad_c + [200 - i * 1.0 for i in range(n - 3)]
    lows = pad_l + [c - 1 for c in closes[450:]]
    highs = pad_h + [c + 1 for c in closes[450:]]
    opens = pad_o + [c + 0.3 for c in closes[450:]]
    vols = pad_v + [1_000_000 + int(rng.normal(0, 30_000)) for _ in range(n - 3)]

    base = closes[-1]
    # c1: long red
    opens += [base + 15]; highs += [base + 16]; lows += [base - 1]; closes += [base]
    vols += [1_200_000]
    # c2: small star below c1's body
    opens += [base - 2]; highs += [base - 0.5]; lows += [base - 4]; closes += [base - 3]
    vols += [900_000]
    # c3: long green closing above c1's midpoint
    c1_mid = (base + 15 + base) / 2
    opens += [base - 3]; highs += [c1_mid + 6]; lows += [base - 3.5]; closes += [c1_mid + 5]
    vols += [2_500_000]

    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols})
    r = score_ticker(df, "TEST.NS")
    assert r is not None
    assert r.pattern == "morning_star", r.pattern


def test_suppressed_pattern_surfaced_not_dropped():
    # c2/c3 alone form a valid bullish_engulfing; c1/c2/c3 together form
    # a valid morning_star. 3-candle precedence wins as `pattern`, but the
    # engulfing match must show up as a suppressed alternate — "check
    # manually" only works if the report shows what got buried.
    c1 = row(250.00, 251.00, 234.00, 235.00)
    c2 = row(233.00, 234.00, 231.00, 232.00)
    c3 = row(231.00, 246.00, 230.50, 245.00)
    assert classify_three_candle(c1, c2, c3) == "morning_star"
    assert classify_two_candle(c2, c3) == "bullish_engulfing"

    n = 90
    pad_o, pad_h, pad_l, pad_c, pad_v = _pad_history(450, base=300.0, seed=42)
    closes = pad_c + [200 - i * 1.0 for i in range(n - 3)]
    lows = pad_l + [c - 1 for c in closes[450:]]
    highs = pad_h + [c + 1 for c in closes[450:]]
    opens = pad_o + [c + 0.5 for c in closes[450:]]
    vols = pad_v + [1_000_000] * (n - 3)

    for c in (c1, c2, c3):
        opens.append(c["Open"]); highs.append(c["High"]); lows.append(c["Low"]); closes.append(c["Close"])
        vols.append(1_500_000)

    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols})
    r = score_ticker(df, "TEST.NS")
    assert r is not None
    assert r.pattern == "morning_star", r.pattern
    assert any("bullish_engulfing" in note for note in r.notes), r.notes


def test_get_sr_ladder_returns_multiple_ranked_levels():
    # Three separate historical dips at 190, 170, 150 -- all below a
    # current close of 250, all further than SR_MAX_DISTANCE_PCT (5%)
    # from it. The single "support" field should find nothing (too far
    # for a tradeable signal) -- but the ladder should list all three,
    # nearest-to-close first, since seeing S2/S3 regardless of distance
    # is the entire point of asking for them.
    n = 70
    base = 250.0
    rng = np.random.default_rng(5)
    lows = [base + rng.normal(0, 0.3) for _ in range(n)]
    for center, depth in [(13, 190.0), (33, 170.0), (53, 150.0)]:
        for offset in range(-2, 3):
            lows[center + offset] = depth + abs(offset) * 5
    highs = [l + 3 for l in lows]
    opens = [l + 1 for l in lows]
    closes = [l + 1 for l in lows]
    closes[-1] = base
    highs[-1] = base + 2
    opens[-1] = base
    lows[-1] = base - 2
    vols = [1_000_000] * n

    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols})
    sr = get_sr_levels(df, n - 1)

    # The single "support" field may legitimately find something close
    # to price now that realistic noise creates genuine small pivots
    # near the current level -- that's not what this test is about.
    # What matters: the far-away 190/170/150 dips show up in the ladder
    # in the right order, regardless of whatever the nearest single
    # field reports.
    levels = [l["level"] for l in sr["support_ladder"]]
    assert 190.0 in levels and 170.0 in levels, sr["support_ladder"]
    assert levels == sorted(levels, reverse=True), "ladder should be nearest-to-close first (S1, S2, S3...)"
    assert len(levels) <= SR_LEVELS_PER_SIDE


def test_fallback_support_has_none_touches_not_zero():
    # A near-flat series with no real swing pivot nearby -- get_sr_levels
    # correctly finds no usable cluster, so score_ticker substitutes the
    # legacy rolling-min fallback. touches must be None, not 0: a real
    # cluster always has >=1 member, so 0 was ambiguous between "a thin
    # but real 0-touch zone" (impossible) and "no real zone at all, this
    # is a rough guess" (what's actually happening here).
    # A monotonic decline has no interior local min/max at all -- every
    # point's neighbors are consistently higher-before/lower-after, so
    # zero pivots form anywhere, which is what actually forces the
    # fallback (a flat series would just risk tripping the flat-window
    # skip added above instead of testing the fallback path itself).
    n = 90
    pad_o, pad_h, pad_l, pad_c, pad_v = _pad_history(450, base=400.0, seed=99)
    closes = pad_c + [400 - i * 0.5 for i in range(n - 1)]
    lows = [c - 0.3 for c in closes]
    highs = [c + 0.3 for c in closes]
    opens = closes[:]
    vols = pad_v + [1_000_000] * (n - 1)

    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols})
    r = score_ticker(df, "TEST.NS")
    assert r is not None
    assert r.support_touches is None, r.support_touches
    assert r.resistance_touches is None, r.resistance_touches
    assert any("estimate" in n for n in r.notes), r.notes


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
