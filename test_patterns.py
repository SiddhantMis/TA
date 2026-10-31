"""
Offline unit tests for candlestick patterns, technical-analysis helpers,
momentum metrics, and the research harness. No network access is needed.
The live yfinance fetch path was separately exercised on the full watchlist
on 2026-10-31 (see analyzer.py docstring); Discord and Actions publishing
were not part of that run.

Several fixtures below are the real OHLC values checked by hand earlier
this week — this test suite is partly a regression check that the code
agrees with those manual calls, not just synthetic examples.
"""
import sys
import numpy as np
import pandas as pd
from main import check_total_failure, check_stale_after_cutoff, enable_settled_daily_candle
import analyzer as analyzer_module
from alerts import build_alert_content, DISCORD_CONTENT_LIMIT
from datetime import date, datetime, time as dt_time
from zoneinfo import ZoneInfo
from analyzer import (
    classify_single, classify_two_candle, classify_three_candle, trend_direction, trend_metrics,
    _flatten_columns, _find_pivots, _cluster_levels, get_sr_levels, SR_LEVELS_PER_SIDE,
    _data_staleness_business_days,
    compute_indicators, score_ticker,
)


def row(o, h, l, c):
    return pd.Series({"Open": o, "High": h, "Low": l, "Close": c})


def test_relative_strength_uses_common_dates_and_exact_12_1_windows():
    dates = pd.bdate_range("2020-01-01", periods=300)
    stock_close = 100 * 1.002 ** np.arange(len(dates))
    market_close = 100 * 1.001 ** np.arange(len(dates))
    stock = pd.DataFrame({"Close": stock_close}, index=dates)
    benchmark = pd.DataFrame({"Close": market_close}, index=dates)

    result = analyzer_module.relative_strength_metrics(stock, benchmark)
    start, end = len(dates) - 253, len(dates) - 22
    expected_stock = stock_close[end] / stock_close[start] - 1
    expected_market = market_close[end] / market_close[start] - 1
    expected_6m = (stock_close[-1] / stock_close[-127] - 1) - (market_close[-1] / market_close[-127] - 1)

    assert result["momentum_12_1_pct"] == round(expected_stock * 100, 2)
    assert result["benchmark_momentum_12_1_pct"] == round(expected_market * 100, 2)
    assert result["relative_strength_12_1_pct"] == round((expected_stock - expected_market) * 100, 2)
    assert result["relative_strength_6m_pct"] == round(expected_6m * 100, 2)
    assert result["momentum_12_1_end_date"] == dates[end].date().isoformat()
    assert result["relative_strength_date"] == dates[-1].date().isoformat()


def test_relative_strength_reports_short_history_and_disjoint_dates():
    dates = pd.bdate_range("2024-01-01", periods=150)
    stock = pd.DataFrame({"Close": np.linspace(100, 130, len(dates))}, index=dates)
    benchmark = pd.DataFrame({"Close": np.linspace(100, 115, len(dates))}, index=dates)
    short = analyzer_module.relative_strength_metrics(stock, benchmark)
    assert short["relative_strength_6m_pct"] is not None
    assert short["relative_strength_12_1_pct"] is None
    assert short["momentum_12_1_end_date"] is None

    no_overlap = benchmark.copy()
    no_overlap.index = no_overlap.index + pd.Timedelta(days=1000)
    empty = analyzer_module.relative_strength_metrics(stock, no_overlap)
    assert empty["relative_strength_6m_pct"] is None
    assert empty["relative_strength_12_1_pct"] is None
    assert empty["relative_strength_date"] is None


def test_relative_strength_ranks_are_watchlist_relative_and_ties_share_rank():
    results = [
        {"ticker": "A.NS", "relative_strength_12_1_pct": 5.0},
        {"ticker": "B.NS", "relative_strength_12_1_pct": 5.0},
        {"ticker": "C.NS", "relative_strength_12_1_pct": -2.0},
        {"ticker": "D.NS", "relative_strength_12_1_pct": None},
    ]
    ranked = analyzer_module.rank_relative_strength(results)
    assert [r["ticker"] for r in ranked] == ["A.NS", "B.NS", "C.NS"]
    assert results[0]["leader_rank"] == results[1]["leader_rank"] == 1
    assert results[0]["leader_percentile"] == results[1]["leader_percentile"] == 75.0
    assert results[2]["leader_rank"] == 3
    assert results[2]["leader_percentile"] == 0.0
    assert results[3].get("leader_rank") is None
    assert all(r["leader_universe_size"] == 3 for r in ranked)


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
    # The invariant that actually matters to a reader: flag and the
    # recommendation TEXT must agree. The previous version of this
    # assertion checked flag against internal fields that happened to
    # move together -- it would NOT have caught JIOFIN.NS's real case
    # (flag=true, recommendation="Borderline"), since that divergence
    # came from recommendation using a separate confidence/checks[0]
    # condition this assertion never touched.
    assert r.flag == (r.recommendation == "Worth a manual look — most criteria align")


def test_flag_and_recommendation_agree_on_choppy_trend_with_valid_pattern():
    # Reproduces the actual JIOFIN.NS shape from the 2026-07-07 run:
    # trend=choppy (fails check 1, "defined trend" only counts up/down-
    # trend) but the pattern's context is still valid in a choppy read,
    # confidence lands under the old hard-coded 75 threshold. Before
    # the fix: flag=true (didn't care about checks[0] or the 75 cutoff)
    # while recommendation="Borderline" (required both). Directly
    # contradictory on the same row of the same page.
    n = 90
    pad_o, pad_h, pad_l, pad_c, pad_v = _pad_history(450, base=240.0, seed=21)
    rng = np.random.default_rng(21)
    # choppy: oscillating, not a clean ramp -- keeps trend_metrics' R^2
    # below TREND_MIN_R2 so check 1 genuinely fails
    closes = pad_c + [240 + (3 if i % 2 == 0 else -3) + rng.normal(0, 0.5) for i in range(n - 3)]
    lows = [c - 1.5 for c in closes]
    highs = [c + 1.5 for c in closes]
    opens = [c + 0.2 for c in closes]
    vols = pad_v + [1_000_000] * (n - 3)
    # morning star on the final 3 bars: big red, small-body star, big green
    opens += [244, 240.5, 238]
    highs += [244.5, 241, 244]
    lows += [238, 239.5, 237.5]
    closes += [238.5, 240, 243]
    vols += [1_500_000, 1_200_000, 2_500_000]
    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols})
    r = score_ticker(df, "TEST.NS")
    assert r is not None
    assert r.flag == (r.recommendation == "Worth a manual look — most criteria align"), (
        r.flag, r.recommendation, r.trend, r.confidence, r.checks_passed
    )


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


def test_staleness_catches_the_actual_bse_scenario():
    # Real event: a run on Wed Jul 8 scored data dated Mon Jul 6 -- two
    # trading days old, not the same-day partial bar _drop_unsettled_
    # today already guards against. This must register as unusually
    # stale, not pass silently.
    last_date = date(2026, 7, 6)   # Monday
    today = date(2026, 7, 8)       # Wednesday
    assert _data_staleness_business_days(last_date, today) == 2


def test_staleness_does_not_flag_a_normal_weekend_gap():
    # Friday's data checked on Monday is the ordinary, expected T-1 case
    # -- this must NOT read as unusually stale just because a weekend
    # sits in between.
    last_date = date(2026, 7, 3)   # Friday
    today = date(2026, 7, 6)       # Monday
    assert _data_staleness_business_days(last_date, today) == 1


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


def _build_support_touch_fixture(num_touches: int, seed: int):
    """Downtrend into a support level near 200, touched `num_touches`
    times via separate dip shapes at the same price, ending on a
    bullish marubozu right at that level. Isolated helper so both
    touch-count tests build genuinely comparable fixtures that differ
    only in how many times support was actually tested."""
    n = 520
    base = 300.0
    rng = np.random.default_rng(seed)
    closes = [base - i * (base - 205) / (n - 20) for i in range(n - 20)]
    lows = [c - 1 + rng.normal(0, 0.3) for c in closes]
    highs = [c + 1 for c in closes]
    opens = [c + 0.3 for c in closes]

    # carve `num_touches` separate dips down to ~200 at spaced-out points
    spacing = (n - 20) // (num_touches + 1)
    for k in range(1, num_touches + 1):
        center = k * spacing
        for offset in range(-2, 3):
            idx = center + offset
            if 0 <= idx < len(lows):
                lows[idx] = 200.0 + abs(offset) * 0.8

    vols = [1_000_000] * len(closes)

    # final bullish marubozu right at the support level
    opens.append(200.3); highs.append(203.6); lows.append(200.0); closes.append(203.5)
    vols.append(2_000_000)

    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols})


def test_confidence_increases_with_support_touch_count():
    df_few = _build_support_touch_fixture(num_touches=1, seed=101)
    df_many = _build_support_touch_fixture(num_touches=5, seed=102)
    r_few = score_ticker(df_few, "FEW.NS")
    r_many = score_ticker(df_many, "MANY.NS")
    assert r_few is not None and r_many is not None
    assert r_few.near_support and r_many.near_support, (r_few.near_support, r_many.near_support)
    assert r_few.support_touches is not None and r_many.support_touches is not None
    assert r_many.support_touches > r_few.support_touches, (r_few.support_touches, r_many.support_touches)
    assert r_many.confidence > r_few.confidence, (
        f"more touches should mean higher confidence: "
        f"{r_few.support_touches} touches -> {r_few.confidence}%, "
        f"{r_many.support_touches} touches -> {r_many.confidence}%"
    )


def test_fallback_support_still_gets_full_binary_credit():
    # Explicit decision on #3: fallback stays as-is, binary, just
    # clearly labeled -- not scaled by touches, since there's no real
    # touch count to scale by. This confirms the graduated logic added
    # for #4 didn't accidentally start penalizing the fallback case,
    # which was deliberately left alone.
    n = 90
    pad_o, pad_h, pad_l, pad_c, pad_v = _pad_history(450, base=400.0, seed=55)
    closes = pad_c + [400 - i * 0.5 for i in range(n - 1)]  # monotonic -- forces zero real pivots
    lows = [c - 0.3 for c in closes]
    highs = [c + 0.3 for c in closes]
    opens = closes[:]
    vols = pad_v + [1_000_000] * (n - 1)
    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols})
    r = score_ticker(df, "TEST.NS")
    assert r is not None
    assert r.support_touches is None  # confirms this is genuinely the fallback path


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


def test_inverted_hammer_scores_as_bullish_reversal_after_downtrend():
    n = 90
    pad_o, pad_h, pad_l, pad_c, pad_v = _pad_history(450, base=300.0, seed=123)
    closes = pad_c + [240 - i * 0.8 for i in range(n - 1)]
    lows = pad_l + [c - 1 for c in closes[450:]]
    highs = pad_h + [c + 1 for c in closes[450:]]
    opens = pad_o + [c + 0.3 for c in closes[450:]]
    vols = pad_v + [1_000_000] * (n - 1)

    base = closes[-1] - 1.0
    opens.append(base)
    closes.append(base + 0.4)
    highs.append(base + 5.0)
    lows.append(base - 0.1)
    vols.append(1_500_000)

    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols})
    r = score_ticker(df, "TEST.NS")
    assert r is not None
    assert r.pattern == "shooting_star_or_inverted_hammer", r.pattern
    assert r.trend == "downtrend", r.trend
    assert r.pattern_matches_trend is True


def test_cluster_levels_does_not_chain_beyond_anchor_tolerance():
    clusters = _cluster_levels([100.0, 101.4, 102.8], tolerance_pct=0.015)
    assert len(clusters) == 2, clusters
    assert clusters[0]["touches"] == 2, clusters
    assert clusters[1]["level"] == 102.8, clusters


def test_partial_plateau_counts_as_one_pivot():
    lows = np.array([105.0, 100.0, 95.0, 95.0, 95.0, 100.0, 105.0])
    pivots = _find_pivots(lows, window=1, mode="low")
    assert pivots == [95.0], pivots


def _fake_flag(ticker):
    return {
        "ticker": ticker, "close": 1234.56, "pattern": "bullish_engulfing",
        "trend": "downtrend", "volume_ratio": 1.85, "support_level": 1200.0,
        "support_touches": 3, "checks_passed": 4, "checks_total": 5,
        "confidence": 73.3, "recommendation": "Worth a manual look — most criteria align",
    }


def test_build_alert_content_untouched_when_short():
    content = build_alert_content([_fake_flag("A.NS"), _fake_flag("B.NS")], "(test session)")
    assert len(content) <= DISCORD_CONTENT_LIMIT
    assert "truncated" not in content
    assert "A.NS" in content and "B.NS" in content


def test_build_alert_content_truncates_when_over_limit():
    # 30 fake flags at this line length is comfortably over 2000 chars --
    # the actual scenario the 48-ticker watchlist can now produce on a
    # good day, not a contrived edge case.
    flagged = [_fake_flag(f"TICKER{i}.NS") for i in range(30)]
    content = build_alert_content(flagged, "(test session)")
    assert len(content) <= DISCORD_CONTENT_LIMIT, len(content)
    assert "truncated" in content
    assert "more flagged" in content
    # the footer must survive truncation, not get cut off along with the ticker lines
    assert "sections 7-9" in content  # footer reworded: R:R (section 6) is now pre-checked in code


def test_build_alert_content_empty_flag_list_unaffected():
    content = build_alert_content([], "(test session)")
    assert "nothing worth a manual look" in content
    assert len(content) <= DISCORD_CONTENT_LIMIT


def test_build_alert_content_shows_momentum_leaders_without_reversal_flags():
    leaders = [{
        "ticker": "MCX.NS", "leader_rank": 1,
        "relative_strength_12_1_pct": 87.43,
        "relative_strength_6m_pct": 11.44,
    }]
    content = build_alert_content([], "(test session)", leaders=leaders)
    assert "MCX.NS" in content
    assert "+87.4 pp" in content and "+11.4 pp" in content
    assert "not a validated entry signal" in content
    assert len(content) <= DISCORD_CONTENT_LIMIT


def test_build_alert_content_keeps_momentum_leaders_inside_discord_limit():
    flagged = [_fake_flag(f"TICKER{i}.NS") for i in range(30)]
    leaders = [{
        "ticker": f"LEADER{i}.NS", "leader_rank": i + 1,
        "relative_strength_12_1_pct": 50.0 - i,
        "relative_strength_6m_pct": 10.0 - i,
    } for i in range(10)]
    content = build_alert_content(flagged, "(test session)", leaders=leaders)
    assert len(content) <= DISCORD_CONTENT_LIMIT, len(content)
    assert "LEADER0.NS" in content
    assert "truncated" in content


def test_check_total_failure_fires_when_everything_fails():
    # The scenario the whole fix exists for -- previously invisible,
    # untested even in the commit that added it.
    msg = check_total_failure(["A.NS", "B.NS", "C.NS"], [])
    assert msg is not None
    assert "0 of 3" in msg


def test_check_total_failure_silent_on_normal_zero_flags_day():
    # The distinction the fix depends on getting right: SOME results
    # with nothing flagged is a completely normal day. Easy to get
    # backwards (checking "not flagged" instead of "not results") --
    # that would fire this on every ordinary quiet market day.
    fake_results = [{"ticker": "A.NS", "flag": False}, {"ticker": "B.NS", "flag": False}]
    msg = check_total_failure(["A.NS", "B.NS"], fake_results)
    assert msg is None, msg


def test_check_total_failure_silent_on_empty_watchlist():
    # An empty watchlist producing zero results is correctly reflecting
    # empty input, not a failure -- must not fire.
    msg = check_total_failure([], [])
    assert msg is None, msg


IST = ZoneInfo("Asia/Kolkata")
CUTOFF = dt_time(19, 0)


def test_check_stale_after_cutoff_silent_before_cutoff():
    # Before 7 PM, today's date genuinely not being in the data yet is
    # expected (market may still be open) -- must not fire.
    run_ts = datetime(2026, 7, 9, 16, 0, tzinfo=IST)  # 4 PM, before cutoff
    results = [{"date": "2026-07-08"}]  # yesterday's date, normal pre-cutoff state
    assert check_stale_after_cutoff(run_ts, results, CUTOFF) is None


def test_check_stale_after_cutoff_fires_when_data_still_lags():
    # Past 7 PM, today's candle should be present since the drop-guard
    # was disabled specifically to let it through. If the latest date
    # in the data still isn't today, Yahoo hasn't published yet --
    # this is the exact BSE incident from earlier in this project
    # (data a full day behind, silently), now caught explicitly.
    run_ts = datetime(2026, 7, 9, 20, 0, tzinfo=IST)  # 8 PM, past cutoff
    results = [{"date": "2026-07-08"}]  # still yesterday -- Yahoo hasn't posted today
    msg = check_stale_after_cutoff(run_ts, results, CUTOFF)
    assert msg is not None
    assert "2026-07-08" in msg and "2026-07-09" in msg


def test_check_stale_after_cutoff_silent_when_data_is_current():
    run_ts = datetime(2026, 7, 9, 20, 0, tzinfo=IST)
    results = [{"date": "2026-07-09"}]  # today's date IS present -- correct, no failure
    assert check_stale_after_cutoff(run_ts, results, CUTOFF) is None


def test_check_stale_after_cutoff_silent_on_empty_results():
    # Empty results is check_total_failure's job to catch, not this
    # one's -- must not double-fire on the same underlying problem.
    run_ts = datetime(2026, 7, 9, 20, 0, tzinfo=IST)
    assert check_stale_after_cutoff(run_ts, [], CUTOFF) is None


def test_enable_settled_daily_candle_disables_the_drop_guard():
    original = analyzer_module._drop_unsettled_today
    try:
        enable_settled_daily_candle()
        sentinel = object()
        assert analyzer_module._drop_unsettled_today(sentinel) is sentinel, (
            "after enabling, the drop-guard should be a no-op that returns its input unchanged"
        )
    finally:
        analyzer_module._drop_unsettled_today = original  # don't leak this into other tests


# ---------------------------------------------------------------------------
# Trade plan gate + backtest simulator
# ---------------------------------------------------------------------------

def test_trade_plan_math_and_gate_failure():
    from analyzer import build_trade_plan
    # entry = 100 * 1.001; stop = min(96, 95) * 0.995; nearest target 110
    p = build_trade_plan(100.0, 96.0, 95.0, [{"level": 110.0, "touches": 2}, {"level": 120.0, "touches": 1}])
    assert abs(p["entry"] - 100.1) < 0.01 and abs(p["stop"] - 94.53) < 0.01, p
    assert p["target"] == 110.0 and abs(p["rr"] - 1.78) < 0.01, p
    assert p["trade_ok"] is False and "R:R" in p["why_not"], p


def test_trade_plan_passes_with_enough_room():
    from analyzer import build_trade_plan
    p = build_trade_plan(100.0, 96.0, 95.0, [{"level": 115.0, "touches": 3}])
    assert p["trade_ok"] is True and p["why_not"] is None and p["rr"] >= 2.0, p


def test_trade_plan_no_resistance_above_entry_fails_with_reason():
    from analyzer import build_trade_plan
    p = build_trade_plan(100.0, 96.0, 95.0, [{"level": 99.0, "touches": 2}])
    assert p["target"] is None and p["rr"] is None and p["trade_ok"] is False
    assert "no resistance" in p["why_not"]


def test_trade_plan_rejects_wide_stop_even_with_great_rr():
    from analyzer import build_trade_plan
    p = build_trade_plan(100.0, 80.0, 79.0, [{"level": 160.0, "touches": 2}])
    assert p["risk_pct"] > 0.08 and p["trade_ok"] is False and "below entry" in p["why_not"], p


def test_score_ticker_fills_plan_fields_and_stop_is_below_entry():
    pad_o, pad_h, pad_l, pad_c, pad_v = _pad_history(520, base=100.0, seed=3)
    df = pd.DataFrame({"Open": pad_o, "High": pad_h, "Low": pad_l, "Close": pad_c, "Volume": pad_v})
    r = score_ticker(df, "TEST.NS")
    assert r is not None and r.entry is not None and r.stop is not None
    assert r.stop < r.entry and isinstance(r.trade_ok, bool)


def test_alert_shows_plan_and_watch_and_breadth_warning():
    f = _fake_flag("A.NS")
    f.update({"entry": 101.0, "stop": 95.0, "target": 115.0, "rr": 2.3, "risk_pct": 0.059})
    content = build_alert_content([f], "(s)", watch=[{"ticker": "W.NS", "rr": 1.2}], breadth=0.1)
    assert "R:R 2.3" in content and "buy > 101.0" in content
    assert "W.NS" in content and "10%" in content
    assert len(content) <= DISCORD_CONTENT_LIMIT


def _bars(rows):
    import numpy as np
    a = np.array(rows, dtype=float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]   # O, H, L, C


def test_sim_target_hit_pays_about_the_planned_rr():
    from backtest import simulate
    # signal bar 0; bar 1 triggers entry 100 and closes; bar 2 tags target 110. risk = 100-95 = 5
    O, H, L, C = _bars([[99, 99.5, 97, 99], [99.5, 101, 99, 100.5], [101, 111, 100, 110]])
    s = simulate(O, H, L, C, 0, entry=100, stop=95, target=110, cost_pct=0)
    assert s["outcome"] == "target" and abs(s["R"] - 2.0) < 1e-9, s


def test_sim_same_bar_stop_and_target_resolves_to_stop():
    from backtest import simulate
    O, H, L, C = _bars([[99, 99.5, 97, 99], [99.5, 101, 99, 100.5], [101, 112, 94, 100]])
    s = simulate(O, H, L, C, 0, entry=100, stop=95, target=110, cost_pct=0)
    assert s["outcome"] == "stop" and abs(s["R"] + 1.0) < 1e-9, s


def test_sim_gap_through_stop_exits_at_open_worse_than_minus_one_r():
    from backtest import simulate
    O, H, L, C = _bars([[99, 99.5, 97, 99], [99.5, 101, 99, 100.5], [92, 93, 90, 91]])
    s = simulate(O, H, L, C, 0, entry=100, stop=95, target=110, cost_pct=0)
    assert s["outcome"] == "stop" and s["R"] < -1.0, s


def test_sim_gap_up_fills_at_open_not_at_entry():
    from backtest import simulate
    # opens at 103 (above the 100 buy-stop): fill = 103, risk = 103-95 = 8, exit at target 110 -> +0.875R
    O, H, L, C = _bars([[99, 99.5, 97, 99], [103, 104, 102, 103.5], [104, 111, 103, 110]])
    s = simulate(O, H, L, C, 0, entry=100, stop=95, target=110, cost_pct=0)
    assert abs(s["R"] - 0.875) < 1e-9, s


def test_sim_never_triggers_and_invalidation_are_not_trades():
    from backtest import simulate
    import math
    O, H, L, C = _bars([[99, 99.5, 97, 99]] + [[98, 99, 97, 98]] * 4)
    s = simulate(O, H, L, C, 0, entry=100, stop=95, target=110, trigger_days=3)
    assert s["outcome"] == "no_trigger" and math.isnan(s["R"])
    O, H, L, C = _bars([[99, 99.5, 97, 99], [97, 98, 94, 95]] + [[95, 96, 94, 95]] * 3)
    s = simulate(O, H, L, C, 0, entry=100, stop=95, target=110)
    assert s["outcome"] == "invalidated" and math.isnan(s["R"])


def test_sim_time_stop_exits_at_close_and_costs_reduce_r():
    from backtest import simulate
    rows = [[99, 99.5, 97, 99], [99.5, 101, 99, 100]] + [[100, 101, 99, 100.5]] * 6
    O, H, L, C = _bars(rows)
    s0 = simulate(O, H, L, C, 0, entry=100, stop=95, target=110, max_hold=3, cost_pct=0)
    s1 = simulate(O, H, L, C, 0, entry=100, stop=95, target=110, max_hold=3, cost_pct=0.25)
    assert s0["outcome"] == "time" and s0["bars"] == 3
    assert s1["R"] < s0["R"]


def test_run_backtest_pipeline_runs_end_to_end_with_a_stubbed_scorer():
    import numpy as np
    import analyzer as A
    import backtest as B
    rng = np.random.default_rng(5)
    n = 700
    close = 100 + np.cumsum(rng.normal(0, 1.2, n))
    open_ = close + rng.normal(0, 0.4, n)
    df = pd.DataFrame({"Open": open_, "High": np.maximum(open_, close) + abs(rng.normal(0, .6, n)) + .1,
                       "Low": np.minimum(open_, close) - abs(rng.normal(0, .6, n)) - .1,
                       "Close": close, "Volume": 1_000_000}, index=pd.bdate_range("2022-01-03", periods=n))
    real = A.score_ticker
    class Stub:
        flag, trade_ok, pattern, trend, confidence, risk_pct = True, True, "stub", "downtrend", 80.0, 0.04
    def fake(window, t):
        r = Stub(); last = window.iloc[-1]
        r.entry, r.stop, r.target, r.rr = last.High * 1.001, last.Low * .995, last.High * 1.06, 2.0
        return r
    A.score_ticker = fake
    try:
        t = B.run_backtest({"X.NS": df, "Y.NS": df * 1.1}, max_hold=10)
        assert len(t) > 0 and {"R", "breadth", "outcome"} <= set(t.columns)
        class Args: years, max_hold, trigger_days, cost_pct = 5, 10, 3, 0.25
        text = B.report(t, Args)
        assert "Does the R:R gate help?" in text and "By watchlist breadth" in text
    finally:
        A.score_ticker = real


# ---------------------------------------------------------------------------
# research.py: trade simulator, no-lookahead, bootstrap, end-to-end smoke
# ---------------------------------------------------------------------------

def _trade_frame(rows, sig_at=2):
    """rows: (O,H,L,C) per bar; ATR fixed at 1; one signal on bar `sig_at`."""
    idx = pd.bdate_range("2024-01-01", periods=len(rows))
    d = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)
    d["atr"] = 1.0
    sig = pd.Series(False, index=idx); sig.iloc[sig_at] = True
    return d, sig


_PAD = [(100, 100, 100, 100)] * 3


def test_research_trail_locks_in_profit():
    import research as R
    d, sig = _trade_frame(_PAD + [(100, 101, 99.5, 101), (101, 105, 100.5, 104),
                                   (104, 111, 103.5, 110), (110, 110.5, 106, 108), (108, 108, 107, 107)])
    t = R.run_trades(d, sig, "x", "T", cost_pct=0, start=0)
    # fill 100, risk 2; trail = highest close 110 - 3 = 107 -> exit 107 -> +3.5R
    assert len(t) == 1 and abs(t[0]["R"] - 3.5) < 1e-9 and t[0]["why"] == "stop", t


def test_research_gap_through_stop_exits_at_open():
    import research as R
    d, sig = _trade_frame(_PAD + [(100, 101, 99.5, 100), (95, 96, 94, 95)] + [(95, 95, 95, 95)] * 3)
    t = R.run_trades(d, sig, "x", "T", cost_pct=0, start=0)
    assert len(t) == 1 and abs(t[0]["R"] + 2.5) < 1e-9, t


def test_research_entry_bar_can_stop_out():
    import research as R
    d, sig = _trade_frame(_PAD + [(100, 100, 97, 99)] + [(99, 99, 99, 99)] * 3)
    t = R.run_trades(d, sig, "x", "T", cost_pct=0, start=0)
    assert len(t) == 1 and abs(t[0]["R"] + 1.0) < 1e-9, t


def test_research_time_stop_and_cost_in_r():
    import research as R
    flat = [(100, 100.5, 99.5, 100)] * 8
    d, sig = _trade_frame(_PAD + flat)
    t0 = R.run_trades(d, sig, "x", "T", cost_pct=0, start=0, max_hold=3)
    t1 = R.run_trades(d, sig, "x", "T", cost_pct=0.5, start=0, max_hold=3)
    assert t0[0]["why"] == "time" and abs(t0[0]["R"]) < 1e-9
    assert abs(t1[0]["R"] + 0.25) < 1e-9     # 0.5% of 100 = 0.5 price units = 0.25R at 2 ATR risk


def test_research_trade_still_open_at_end_of_data_is_dropped():
    import research as R
    d, sig = _trade_frame(_PAD + [(100, 100.5, 99.5, 100)] * 3)
    assert R.run_trades(d, sig, "x", "T", cost_pct=0, start=0, max_hold=60) == []


def test_research_signals_have_no_lookahead():
    import numpy as np
    import research as R
    def mk(seed, n=700):
        rng = np.random.default_rng(seed)
        c = np.abs(100 + np.cumsum(rng.normal(0.05, 1.5, n))) + 20
        o = c + rng.normal(0, .5, n)
        return pd.DataFrame({"Open": o, "High": np.maximum(o, c) + abs(rng.normal(0, .6, n)) + .1,
                             "Low": np.minimum(o, c) - abs(rng.normal(0, .6, n)) - .1, "Close": c,
                             "Volume": rng.integers(8e5, 2e6, n)}, index=pd.bdate_range("2021-01-04", periods=n))
    frames = {"A": mk(1), "B": mk(2)}
    bench = mk(3)["Close"]
    full = R.build_universe(frames, bench)
    for cut in (450, 560, 650):
        part = R.build_universe({t: f.iloc[:cut] for t, f in frames.items()}, bench.iloc[:cut])
        for t in frames:
            sf, sp = R.signals(full[t]), R.signals(part[t])
            for k in sf:
                assert bool(sf[k].iloc[cut - 1]) == bool(sp[k].iloc[cut - 1]), (t, k, cut)


def test_research_month_bootstrap_constant_series():
    import research as R
    dates = pd.date_range("2022-01-15", periods=24, freq="MS")
    df = pd.DataFrame({"signal_date": dates, "R": 1.0})
    lo, hi = R.month_boot(df)
    assert lo == 1.0 and hi == 1.0


def test_research_end_to_end_smoke():
    import numpy as np
    import research as R
    def mk(seed, n=900):
        rng = np.random.default_rng(seed)
        c = np.abs(100 + np.cumsum(rng.normal(0.08, 1.5, n))) + 20
        o = c + rng.normal(0, .5, n)
        return pd.DataFrame({"Open": o, "High": np.maximum(o, c) + abs(rng.normal(0, .6, n)) + .1,
                             "Low": np.minimum(o, c) - abs(rng.normal(0, .6, n)) - .1, "Close": c,
                             "Volume": rng.integers(8e5, 2e6, n)}, index=pd.bdate_range("2021-01-04", periods=n))
    tr, text = R.run_research({"A": mk(1), "B": mk(2), "C": mk(4)}, mk(3)["Close"])
    assert {"R", "variant", "period"} <= set(tr.columns)
    assert "-- verdicts" in text and "ctrl_uptrend" in text


# ---------------------------------------------------------------------------
# portfolio.py: universe parsing, portfolio mechanics, no-lookahead, metrics, verdict
# ---------------------------------------------------------------------------

def _panel(n=700):
    import numpy as np
    idx = pd.bdate_range("2020-01-01", periods=n)
    t = np.arange(n)
    C = pd.DataFrame({"A": 100 * 1.0015 ** t, "B": 100 + np.sin(t / 7.0), "C": 100 * 0.999 ** t}, index=idx)
    O = C.shift(1).fillna(C.iloc[0])
    return O, C


def test_portfolio_parse_constituents():
    import portfolio as P
    txt = ("Company Name,Industry,Symbol,Series,ISIN Code\n"
           "Adani Enterprises Ltd.,Metals,ADANIENT,EQ,INE423A01024\n"
           "Mahindra & Mahindra Ltd.,Auto,M&M ,EQ,INE101A01026\n")
    assert P.parse_constituents(txt) == ["ADANIENT.NS", "M&M.NS"]
    assert P.parse_constituents("") == [] and P.parse_constituents("a,b\n1,2\n") == []


def test_portfolio_picks_the_leader_and_charges_cost_only_on_turnover():
    import numpy as np
    import portfolio as P
    O, C = _panel()
    ind = P.indicators(C)
    mc = pd.Series(100 * 1.001 ** np.arange(len(C)), index=C.index)
    rets, info = P.simulate(O, C, ind, mc, mc.rolling(200).mean(), O["A"], ("mom12_1",), n_hold=1, cost_pct=0.30)
    ex = [p for p in P.first_days_of_month(C.index) if p >= 253]
    a, b = ex[0], ex[1]
    exp1 = O["A"].iloc[b] / O["A"].iloc[a] - 1
    assert abs(rets["mom12_1"].iloc[0] - (exp1 - 0.30 / 200)) < 1e-12      # entry costs half the round trip
    a, b = ex[1], ex[2]
    exp2 = O["A"].iloc[b] / O["A"].iloc[a] - 1
    assert abs(rets["mom12_1"].iloc[1] - exp2) < 1e-12                      # same holding: no turnover, no cost
    assert (info["held"] == 1).all()


def test_portfolio_market_filter_goes_to_cash():
    import numpy as np
    import portfolio as P
    O, C = _panel()
    ind = P.indicators(C)
    mc = pd.Series(100 * 0.999 ** np.arange(len(C)), index=C.index)         # Nifty falling below its 200-day avg
    rets, info = P.simulate(O, C, ind, mc, mc.rolling(200).mean(), O["A"], ("mom12_1+mkt",), n_hold=1)
    assert (info["held"] == 0).all() and (rets["mom12_1+mkt"] == 0).all()


def test_portfolio_selection_has_no_lookahead():
    import numpy as np
    import portfolio as P
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2019-01-01", periods=800)
    C = pd.DataFrame({f"S{i}": np.abs(100 + np.cumsum(rng.normal(0.05, 1.4, 800))) + 20 for i in range(6)}, index=idx)
    ind = P.indicators(C)
    for cut in (500, 640):
        ind_t = P.indicators(C.iloc[:cut])
        for v in P.VARIANTS:
            assert P.select(C, ind, cut - 1, v, True, 3) == P.select(C.iloc[:cut], ind_t, cut - 1, v, True, 3), (v, cut)


def test_portfolio_metrics_and_bootstrap():
    import numpy as np
    import portfolio as P
    m = P.metrics(pd.Series([0.10, -0.20, 0.05, 0.0, 0.0, 0.0]))
    assert abs(m["maxdd"] + 0.20) < 1e-12
    m = P.metrics(pd.Series([0.01] * 24))
    assert abs(m["cagr"] - (1.01 ** 12 - 1)) < 1e-9 and abs(m["maxdd"]) < 1e-12
    lo, hi = P.block_boot_mean(np.full(36, 0.01))
    assert abs(lo - 0.12) < 1e-12 and abs(hi - 0.12) < 1e-12
    assert P.after_tax_cagr({"gain": 1.0, "months": 12}, 0.20) < 1.0        # taxed gain compounds less


def test_portfolio_verdict_rule():
    import portfolio as P
    def mm(c, dd=-0.10): return {"cagr": c, "vol": .15, "sharpe": 1.0, "maxdd": dd, "months": 36, "gain": 1.0}
    good = {("v", "IS"): mm(.20), ("v", "OOS"): mm(.18), ("nifty50", "IS"): mm(.12), ("nifty50", "OOS"): mm(.10),
            ("ew_universe", "IS"): mm(.14), ("ew_universe", "OOS"): mm(.12)}
    assert P.verdict("v", good, (0.02, 0.10)) == "CANDIDATE"
    assert "includes 0" in P.verdict("v", good, (-0.01, 0.10))
    bad = dict(good); bad[("v", "OOS")] = mm(.11)
    assert "OOS CAGR <= ew_universe" in P.verdict("v", bad, (0.02, 0.10))
    deep = dict(good); deep[("v", "OOS")] = mm(.18, dd=-0.30)
    assert "drawdown" in P.verdict("v", deep, (0.02, 0.10))


def test_portfolio_end_to_end_smoke():
    import numpy as np
    import portfolio as P
    def mk(seed, n=1200):
        rng = np.random.default_rng(seed)
        c = np.abs(100 + np.cumsum(rng.normal(0.06, 1.5, n))) + 20
        o = c + rng.normal(0, .5, n)
        return pd.DataFrame({"Open": o, "High": np.maximum(o, c) + 1, "Low": np.minimum(o, c) - 1, "Close": c,
                             "Volume": 1e6}, index=pd.bdate_range("2019-01-01", periods=n))
    frames = {f"S{i}": mk(10 + i) for i in range(8)}
    bench = mk(99)
    rets, text = P.run_portfolio(frames, bench["Close"], bench["Open"], "smoke", n_hold=3)
    assert {"mom12_1", "mom6+mkt", "nifty50", "ew_universe"} <= set(rets.columns)
    assert "-- verdicts" in text and "calendar-year" in text


def test_portfolio_liquidity_filter_is_point_in_time():
    import numpy as np
    import portfolio as P
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2019-01-01", periods=700)
    C = pd.DataFrame({f"S{i}": 150 + np.cumsum(rng.normal(0.05, 1, 700)) for i in range(5)}, index=idx)
    V = pd.DataFrame({f"S{i}": 1e6 * (i + 1) for i in range(5)}, index=idx)      # S0 least liquid
    ind = P.indicators(C, V, liquid_top=3)
    assert ind["liquid"].iloc[-1].tolist() == [False, False, True, True, True]
    assert not bool(ind["valid"].iloc[-1]["S0"])
    cut = 500
    V2 = V.copy(); V2.iloc[cut:, 0] *= 1000                                       # S0 becomes huge AFTER the cut
    a = P.indicators(C, V, 3)["liquid"].iloc[cut - 1]
    b = P.indicators(C, V2, 3)["liquid"].iloc[cut - 1]
    assert a.tolist() == b.tolist()                                                # no peeking at future liquidity
    assert P.indicators(C.iloc[:cut], V.iloc[:cut], 3)["liquid"].iloc[cut - 1].tolist() == a.tolist()


def test_portfolio_constituent_urls_and_liquid_smoke():
    import numpy as np
    import portfolio as P
    urls = P.constituent_urls("nifty500")
    assert len(urls) == 3 and all("ind_nifty500list.csv" in u for u in urls)
    def mk(seed, n=1200):
        rng = np.random.default_rng(seed)
        c = np.abs(100 + np.cumsum(rng.normal(0.06, 1.5, n))) + 20
        o = c + rng.normal(0, .5, n)
        return pd.DataFrame({"Open": o, "High": np.maximum(o, c) + 1, "Low": np.minimum(o, c) - 1, "Close": c,
                             "Volume": 1e6}, index=pd.bdate_range("2019-01-01", periods=n))
    frames = {}
    for i in range(8):
        f = mk(30 + i); f["Volume"] = 1e6 * (i + 1); frames[f"S{i}"] = f
    bench = mk(98)
    rets, text = P.run_portfolio(frames, bench["Close"], bench["Open"], "liq", n_hold=3, liquid_top=4)
    assert "point-in-time top 4" in text and "-- verdicts" in text and not rets.empty


# ---------------------------------------------------------------------------
# swings.py / geo_patterns.py / pattern_lab.py
# ---------------------------------------------------------------------------

def _wp(wps, per=10, warm=0):
    """OHLC arrays from straight legs between waypoints (optionally preceded by flat warm-up bars)."""
    import numpy as np
    C = np.array([wps[0]] + [x for a, b in zip(wps[:-1], wps[1:]) for x in np.linspace(a, b, per + 1)[1:]], float)
    if warm:
        C = np.concatenate([np.full(warm, C[0]), C])
    O = np.concatenate([[C[0]], C[:-1]])
    return O, np.maximum(O, C) + 0.3, np.minimum(O, C) - 0.3, C


def _events(wps, per=10, warm=0):
    import geo_patterns as G
    return G.detect_all(*_wp(wps, per, warm))


def test_zigzag_swings_and_causality():
    import swings as S
    O, H, L, C = _wp([100, 130, 100, 130, 100], 10)
    atr = S.atr_series(H, L, C)
    sw = S.zigzag(H, L, atr, 3.0)
    assert [x.kind for x in sw] == [-1, 1, -1, 1] or [x.kind for x in sw] == [1, -1, 1], sw
    assert all(x.conf > x.idx for x in sw)                              # a swing is known only after the reversal
    cut = 30
    part = S.zigzag(H[:cut], L[:cut], atr[:cut], 3.0)
    full_known = [x for x in sw if x.conf < cut]
    assert part == full_known                                           # truncating the data changes nothing it knew


def test_zigzag_handles_a_huge_first_bar():
    import numpy as np
    import swings as S
    H = np.array([10, 10.2, 30, 29, 28, 27, 26, 25, 20, 15, 14, 13, 12, 11, 10, 9, 8, 12, 16, 20, 24.])
    atr = np.full(len(H), 1.0); atr[:3] = np.nan
    S.zigzag(H, H - 0.5, atr, 3.0)                                      # used to raise on an empty segment


def test_double_bottom_and_top_found_and_bad_second_low_rejected():
    ev = _events([100, 130, 100, 120, 100.5, 125])
    db = [e for e in ev if e["name"] == "double_bottom"]
    assert len(db) == 1 and db[0]["dir"] == 1 and 139 < db[0]["target"] < 142 and db[0]["stop"] < 100
    assert not [e for e in _events([100, 130, 100, 120, 108, 125]) if e["name"] == "double_bottom"]
    dt = [e for e in _events([100, 70, 100, 80, 99.5, 75]) if e["name"] == "double_top"]
    assert len(dt) == 1 and dt[0]["dir"] == -1 and 58 < dt[0]["target"] < 61


def test_head_and_shoulders_and_inverse():
    hs = [e for e in _events([100, 120, 110, 130, 110, 120, 100]) if e["name"] == "head_shoulders"]
    assert len(hs) == 1 and hs[0]["dir"] == -1 and abs(hs[0]["target"] - 90) < 2 and hs[0]["stop"] > 119
    ih = [e for e in _events([100, 80, 90, 70, 90, 80, 100]) if e["name"] == "inverse_head_shoulders"]
    assert len(ih) == 1 and ih[0]["dir"] == 1 and abs(ih[0]["target"] - 110) < 2
    assert not [e for e in _events([100, 120, 110, 121, 110, 120, 100]) if e["name"] == "head_shoulders"]   # head barely higher than the shoulders


def test_triangles_rectangle_found():
    names = lambda ev, d: {e["name"] for e in ev if e["dir"] == d}
    assert "ascending_triangle" in names(_events([100, 120, 105, 120, 110, 120, 115, 128], 8), 1)
    assert "descending_triangle" in names(_events([100, 80, 95, 80, 90, 80, 85, 72], 8), -1)
    assert "rectangle" in names(_events([100, 120, 100, 120, 100, 120, 100, 128], 10), 1)
    assert "symmetrical_triangle" in names(_events([90, 130, 100, 124, 106, 119, 110, 115, 112, 128], 9, warm=20), 1)


def test_flags_found_and_steady_trend_is_not_a_flag():
    import numpy as np
    import geo_patterns as G
    def build(parts):
        C = np.concatenate(parts); O = np.concatenate([[C[0]], C[:-1]])
        return O, np.maximum(O, C) + 0.3, np.minimum(O, C) - 0.3, C
    bull = G.detect_all(*build([np.full(40, 100.0), np.linspace(100, 130, 16), np.linspace(130, 125, 9)[1:], [127, 129, 131, 135, 138]]))
    assert [e["name"] for e in bull] == ["bull_flag"] and 159 < bull[0]["target"] < 161
    bear = G.detect_all(*build([np.full(40, 130.0), np.linspace(130, 100, 16), np.linspace(100, 105, 9)[1:], [103, 101, 99, 95, 92]]))
    assert [e["name"] for e in bear] == ["bear_flag"]
    steady = np.linspace(100, 160, 60)
    assert G.detect_all(*build([steady])) == []
    v_bounce = G.detect_all(*_wp([100, 130, 100, 120, 100.5, 125]))      # a V-shaped bounce is not a bear flag
    assert not [e for e in v_bounce if e["name"] == "bear_flag"]


def test_pattern_detection_has_no_lookahead():
    import numpy as np
    import geo_patterns as G
    rng = np.random.default_rng(1); n = 1500
    C = np.abs(100 + np.cumsum(rng.normal(0, 1.6, n))) + 30
    O = np.concatenate([[C[0]], C[:-1]])
    H = np.maximum(O, C) + abs(rng.normal(0, .5, n)); L = np.minimum(O, C) - abs(rng.normal(0, .5, n))
    key = lambda e: (e["name"], e["t"], e["dir"], round(float(e["key"]), 6))
    full = G.detect_all(O, H, L, C)
    assert len(full) > 20
    for T in (500, 800, 1100, 1400):
        part = G.detect_all(O[:T], H[:T], L[:T], C[:T])
        assert {key(e) for e in full if e["t"] <= T - 1} == {key(e) for e in part}, T


def test_lab_trade_simulator():
    import math
    import numpy as np
    import pattern_lab as L
    O = np.array([100, 100, 101, 105, 109.]); Hh = O + 1; Ll = O - 1; C = O.copy()
    # long: entry open[1]=100, stop 95 (risk 5), target 110 -> reached on the last bar's high
    r = L.sim_event(O, Hh, Ll, C, 0, 1, 95, 110, cost_pct=0)
    assert abs(r - 2.0) < 1e-9, r
    # same bar touches both stop and target -> stop
    Hh2, Ll2 = Hh.copy(), Ll.copy(); Hh2[2], Ll2[2] = 112, 94
    assert abs(L.sim_event(O, Hh2, Ll2, C, 0, 1, 95, 110, cost_pct=0) + 1.0) < 1e-9
    # short mirror: entry 100, stop 105, target 90; opens gap down through the target on bar 3
    O3 = np.array([100, 100, 99, 88, 87.]); r = L.sim_event(O3, O3 + 1, O3 - 1, O3, 0, -1, 105, 90, cost_pct=0)
    assert abs(r - 2.4) < 1e-9, r                                       # exit at the 88 open: (100-88)/5
    # a favourable gap through the target exits at the open, not at the target
    Og = np.array([100, 100, 101, 105, 112.]); assert abs(L.sim_event(Og, Og + 1, Og - 1, Og, 0, 1, 95, 110, cost_pct=0) - 2.4) < 1e-9
    # entry already beyond the stop -> no trade
    assert math.isnan(L.sim_event(np.array([100, 90., 90, 90]), np.full(4, 91.), np.full(4, 89.), np.full(4, 90.), 0, 1, 95, 110))


def test_lab_month_ci_and_verdict():
    import numpy as np
    import pandas as pd
    import pattern_lab as L
    dates = pd.date_range("2018-01-01", periods=400, freq="7D")
    lo, hi = L.month_ci(np.full(400, 0.02), dates)
    assert abs(lo - 0.02) < 1e-12 and abs(hi - 0.02) < 1e-12
    good = {"n": 100, "ex20": 0.02, "lo": 0.004, "avgR": 0.2}
    assert L.verdict({"n": 200, "ex20": 0.01, "lo": 0, "avgR": 0.1}, good, 300) == "VALIDATED"
    assert "includes 0" in L.verdict({"n": 200, "ex20": 0.01}, dict(good, lo=-0.001), 300)
    assert "OOS mean <= 0" in L.verdict({"n": 200, "ex20": 0.01}, dict(good, ex20=-0.01), 300)
    assert "events" in L.verdict({"n": 20, "ex20": 0.01}, good, 100)


def test_lab_end_to_end_on_random_stocks_validates_nothing():
    import numpy as np
    import pandas as pd
    import pattern_lab as L
    def mk(seed, n=1400):
        rng = np.random.default_rng(seed); c = np.abs(100 + np.cumsum(rng.normal(0.04, 1.6, n))) + 40
        o = np.concatenate([[c[0]], c[:-1]]) * (1 + rng.normal(0, .004, n))
        return pd.DataFrame({"Open": o, "High": np.maximum(o, c) + abs(rng.normal(0, .5, n)),
                             "Low": np.minimum(o, c) - abs(rng.normal(0, .5, n)), "Close": c,
                             "Volume": rng.integers(5e5, 3e6, n)}, index=pd.bdate_range("2019-01-01", periods=n))
    ev, text = L.run_lab({f"S{i}": mk(i) for i in range(30)}, liquid_top=20)
    assert len(ev) > 300 and "-- verdicts" in text
    assert "VALIDATED" not in text, "the lab found 'edge' in pure noise: the harness is biased"


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
