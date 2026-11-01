"""Geometric chart-pattern detectors built on causal ATR swings.

Each detector emits an event at the BREAKOUT bar t (the close that confirms the pattern):
    {name, dir (+1 bullish / -1 bearish), t, key (broken level), stop, target, start}
Nothing here looks past bar t. Parameters are fixed constants, chosen before any backtest and
NOT tuned; the pattern lab (pattern_lab.py) is what tells us whether a detector is worth trusting.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from swings import atr_series, zigzag

SCALE_MAJOR = 3.0      # swing size (x ATR14) for double tops/bottoms and head & shoulders
SCALE_MINOR = 2.0      # for triangles, rectangles, wedges
W_BREAK = 20           # bars after the last swing is confirmed in which a breakout still counts
TOUCH_TOL = 0.6        # a swing must sit within this many ATR of its trendline
POLE_BARS = 20


def _add(ev, e):
    ev.setdefault((e["name"], e["t"], e["dir"]), e)


def _double(sw, H, L, C, atr, ev):
    n = len(C)
    for i in range(2, len(sw)):
        s2, s1, s0 = sw[i], sw[i - 1], sw[i - 2]
        a = atr[s2.conf]
        if not np.isfinite(a) or a <= 0 or not (10 <= s2.idx - s0.idx <= 120):
            continue
        if abs(s2.price - s0.price) > 1.0 * a:
            continue
        if s2.kind == -1 and s1.kind == 1 and s0.kind == -1:            # double bottom
            lo = min(s0.price, s2.price)
            height = s1.price - lo
            if height < 3 * a:
                continue
            for t in range(s2.conf, min(s2.conf + W_BREAK, n - 1) + 1):
                if L[t] < lo - 0.25 * a:
                    break
                if C[t] > s1.price:
                    _add(ev, dict(name="double_bottom", dir=1, t=t, key=s1.price, stop=lo - 0.5 * a,
                                  target=s1.price + height, start=s0.idx))
                    break
        elif s2.kind == 1 and s1.kind == -1 and s0.kind == 1:           # double top
            hi = max(s0.price, s2.price)
            height = hi - s1.price
            if height < 3 * a:
                continue
            for t in range(s2.conf, min(s2.conf + W_BREAK, n - 1) + 1):
                if H[t] > hi + 0.25 * a:
                    break
                if C[t] < s1.price:
                    _add(ev, dict(name="double_top", dir=-1, t=t, key=s1.price, stop=hi + 0.5 * a,
                                  target=s1.price - height, start=s0.idx))
                    break


def _head_shoulders(sw, H, L, C, atr, ev):
    n = len(C)
    for i in range(4, len(sw)):
        s = sw[i - 4:i + 1]
        kinds = [x.kind for x in s]
        if kinds not in ([1, -1, 1, -1, 1], [-1, 1, -1, 1, -1]):
            continue
        sgn = 1 if kinds[0] == 1 else -1            # +1: bearish head & shoulders, -1: inverse (bullish)
        LS, N1, HD, N2, RS = s
        a = atr[RS.conf]
        if not np.isfinite(a) or a <= 0:
            continue
        p = lambda x: sgn * x.price                 # flip so the head is always the highest point
        if not (p(HD) > p(LS) + 1.0 * a and p(HD) > p(RS) + 1.0 * a):
            continue
        neck_mean = (N1.price + N2.price) / 2
        head_h = sgn * (HD.price - neck_mean)
        if head_h < 3 * a or abs(LS.price - RS.price) > 0.35 * head_h:
            continue
        d1, d2 = HD.idx - LS.idx, RS.idx - HD.idx
        if d2 <= 0 or not (0.4 <= d1 / d2 <= 2.5):
            continue
        slope = (N2.price - N1.price) / (N2.idx - N1.idx)
        neck = lambda x, N1=N1, slope=slope: N1.price + slope * (x - N1.idx)
        height = sgn * (HD.price - neck(HD.idx))
        if height <= 0 or abs(slope) * (N2.idx - N1.idx) > 0.6 * head_h:
            continue
        for t in range(RS.conf, min(RS.conf + W_BREAK, n - 1) + 1):
            if sgn * H[t] > sgn * HD.price if sgn == 1 else L[t] < HD.price:
                break
            if sgn == 1 and C[t] < neck(t) - 0.1 * a:
                _add(ev, dict(name="head_shoulders", dir=-1, t=t, key=neck(t), stop=RS.price + 0.25 * a,
                              target=neck(t) - height, start=LS.idx))
                break
            if sgn == -1 and C[t] > neck(t) + 0.1 * a:
                _add(ev, dict(name="inverse_head_shoulders", dir=1, t=t, key=neck(t), stop=RS.price - 0.25 * a,
                              target=neck(t) + height, start=LS.idx))
                break


def _lines(sw, H, L, C, atr, ev):
    n = len(C)
    for i in range(4, len(sw)):
        s = sw[i - 4:i + 1]
        hi = [x for x in s if x.kind == 1]
        lo = [x for x in s if x.kind == -1]
        span = s[-1].idx - s[0].idx
        a = atr[s[-1].conf]
        if len(hi) < 2 or len(lo) < 2 or not (15 <= span <= 120) or not np.isfinite(a) or a <= 0:
            continue
        fh = np.polyfit([x.idx for x in hi], [x.price for x in hi], 1)
        fl = np.polyfit([x.idx for x in lo], [x.price for x in lo], 1)
        up = lambda x, fh=fh: fh[0] * x + fh[1]
        dn = lambda x, fl=fl: fl[0] * x + fl[1]
        if any(abs(x.price - up(x.idx)) > TOUCH_TOL * a for x in hi) or \
           any(abs(x.price - dn(x.idx)) > TOUCH_TOL * a for x in lo):
            continue
        w0, w1 = up(s[0].idx) - dn(s[0].idx), up(s[-1].idx) - dn(s[-1].idx)
        if min(w0, w1) <= 0.5 * a:
            continue
        mh, ml, ratio = fh[0] * span, fl[0] * span, w1 / w0
        flat = lambda m: abs(m) <= 1.0 * a
        rise = lambda m: m >= 1.5 * a
        fall = lambda m: m <= -1.5 * a
        if flat(mh) and rise(ml) and ratio <= 0.75:
            name, allowed = "ascending_triangle", (1,)
        elif flat(ml) and fall(mh) and ratio <= 0.75:
            name, allowed = "descending_triangle", (-1,)
        elif fall(mh) and rise(ml) and ratio <= 0.75:
            name, allowed = "symmetrical_triangle", (1, -1)
        elif flat(mh) and flat(ml) and 0.7 <= ratio <= 1.3 and min(w0, w1) >= 2 * a:
            name, allowed = "rectangle", (1, -1)
        elif rise(mh) and rise(ml) and ratio <= 0.75:
            name, allowed = "rising_wedge", (-1,)
        elif fall(mh) and fall(ml) and ratio <= 0.75:
            name, allowed = "falling_wedge", (1,)
        else:
            continue
        for t in range(s[-1].conf, min(s[-1].conf + 15, n - 1) + 1):
            u, l = up(t), dn(t)
            if u - l <= 0:
                break
            if C[t] > u + 0.1 * a:
                if 1 in allowed:
                    _add(ev, dict(name=name, dir=1, t=t, key=u, stop=l - 0.25 * a, target=u + w0, start=s[0].idx))
                break
            if C[t] < l - 0.1 * a:
                if -1 in allowed:
                    _add(ev, dict(name=name, dir=-1, t=t, key=l, stop=u + 0.25 * a, target=l - w0, start=s[0].idx))
                break


def _flags(O, H, L, C, atr, ev):
    Hs, Ls, Cs = pd.Series(H), pd.Series(L), pd.Series(C)
    A = pd.Series(atr)
    pole_hi = Hs.rolling(POLE_BARS).max()
    pole_lo = Ls.rolling(POLE_BARS).min()
    for m in range(5, 21):
        k = max(2, -(-m // 3))
        fh = Hs.rolling(m).max().shift(1)
        fl = Ls.rolling(m).min().shift(1)
        rng = fh - fl
        first_max = Hs.rolling(k).max().shift(m - k + 1)       # highest high in the first third of the flag
        first_min = Ls.rolling(k).min().shift(m - k + 1)
        pre_lo, pre_hi = pole_lo.shift(m + 1), pole_hi.shift(m + 1)     # the pole: POLE_BARS before the flag
        gain_u = fh - pre_lo
        gain_d = pre_hi - fl
        # the flag must START at the pole's end: no higher high (bull) / lower low (bear) just before it
        bull = ((Cs > fh) & (gain_u >= 4 * A) & (rng <= 0.5 * gain_u) & (rng >= 0.75 * A)
                & (first_max >= fh - 1e-9) & (pre_hi <= fh + 0.5 * A))
        bear = ((Cs < fl) & (gain_d >= 4 * A) & (rng <= 0.5 * gain_d) & (rng >= 0.75 * A)
                & (first_min <= fl + 1e-9) & (pre_lo >= fl - 0.5 * A))
        for t in np.flatnonzero(bull.fillna(False).to_numpy()):
            _add(ev, dict(name="bull_flag", dir=1, t=int(t), key=float(fh[t]), stop=float(fl[t] - 0.25 * atr[t]),
                          target=float(fh[t] + gain_u[t]), start=int(t - m)))
        for t in np.flatnonzero(bear.fillna(False).to_numpy()):
            _add(ev, dict(name="bear_flag", dir=-1, t=int(t), key=float(fl[t]), stop=float(fh[t] + 0.25 * atr[t]),
                          target=float(fl[t] - gain_d[t]), start=int(t - m)))


def detect_all(O, H, L, C) -> list:
    """All pattern events for one stock, sorted by breakout bar."""
    O, H, L, C = (np.asarray(x, float) for x in (O, H, L, C))
    atr = atr_series(H, L, C)
    ev = {}
    major = zigzag(H, L, atr, SCALE_MAJOR)
    minor = zigzag(H, L, atr, SCALE_MINOR)
    _double(major, H, L, C, atr, ev)
    _head_shoulders(major, H, L, C, atr, ev)
    _lines(minor, H, L, C, atr, ev)
    _flags(O, H, L, C, atr, ev)
    return sorted(ev.values(), key=lambda e: (e["t"], e["name"]))
