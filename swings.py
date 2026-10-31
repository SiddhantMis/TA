"""Causal ATR zigzag: swing highs/lows that are only 'known' after price reverses by mult*ATR.

Every swing carries `conf`, the first bar at which it can be known. Anything built on swings must
use only swings with conf <= the bar being decided; that is what keeps pattern detection free of
lookahead (tests/test_patterns.py checks it by truncating the data).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Swing:
    idx: int       # bar of the extreme
    price: float
    kind: int      # +1 swing high, -1 swing low
    conf: int      # first bar at which this swing is known


def atr_series(H, L, C, n: int = 14) -> np.ndarray:
    H, L, C = (np.asarray(x, float) for x in (H, L, C))
    pc = np.concatenate([[C[0]], C[:-1]])
    tr = np.maximum.reduce([H - L, np.abs(H - pc), np.abs(L - pc)])
    out = np.full(len(tr), np.nan)
    if len(tr) >= n:
        cs = np.cumsum(np.concatenate([[0.0], tr]))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def zigzag(H, L, atr, mult: float) -> list:
    H, L, atr = (np.asarray(x, float) for x in (H, L, atr))
    n = len(H)
    fin = np.isfinite(atr)
    if not fin.any():
        return []
    start = int(np.argmax(fin))
    if start >= n - 1:
        return []
    out, hi_i, lo_i = [], start, start
    hi, lo = H[start], L[start]
    dirn, ext_i, ext_p = 0, start, 0.0
    for t in range(start + 1, n):
        thr = mult * atr[t] if np.isfinite(atr[t]) else np.inf
        if dirn == 0:
            if H[t] > hi:
                hi, hi_i = H[t], t
            if L[t] < lo:
                lo, lo_i = L[t], t
            up, dn = H[t] - lo >= thr, hi - L[t] >= thr
            if up and (not dn or lo_i <= hi_i):          # a swing low was confirmed first
                out.append(Swing(lo_i, float(lo), -1, t))
                dirn = 1
                seg = H[lo_i:t + 1]                        # includes bar t itself (a very large first bar)
                j = int(np.argmax(seg)); ext_i, ext_p = lo_i + j, float(seg[j])
            elif dn:
                out.append(Swing(hi_i, float(hi), 1, t))
                dirn = -1
                seg = L[hi_i:t + 1]
                j = int(np.argmin(seg)); ext_i, ext_p = hi_i + j, float(seg[j])
        elif dirn == 1:
            if H[t] > ext_p:
                ext_i, ext_p = t, float(H[t])
            elif ext_p - L[t] >= thr:
                out.append(Swing(ext_i, ext_p, 1, t))
                dirn = -1
                seg = L[ext_i + 1:t + 1]
                j = int(np.argmin(seg)); ext_i, ext_p = ext_i + 1 + j, float(seg[j])
        else:
            if L[t] < ext_p:
                ext_i, ext_p = t, float(L[t])
            elif H[t] - ext_p >= thr:
                out.append(Swing(ext_i, ext_p, -1, t))
                dirn = 1
                seg = H[ext_i + 1:t + 1]
                j = int(np.argmax(seg)); ext_i, ext_p = ext_i + 1 + j, float(seg[j])
    return out
