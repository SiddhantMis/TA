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
import pandas as pd
from analyzer import classify_single, classify_two_candle, trend_direction


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
