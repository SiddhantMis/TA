## Summary statistics

Benchmark: `nifty500_tri_entry_aligned_return_pct`. Samples whose basket has any missing or corporate-action-invalidated stock return are EXCLUDED (never reweighted). Overlapping holding windows make neighbouring samples dependent: the effective number of independent samples is about n x min(1, min_gap / horizon), and the intervals use a circular block bootstrap.

### 1M (21 sessions): 5 samples, 5 complete, 0 incomplete; ~5.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 | 6.26 | 6.89 | 15.01 | -12.27 | 27.97 | 60.0 | 60.0 |
| market-filtered | 3.12 | 0.0 | 5.36 | -1.91 | 10.59 | 40.0 | 60.0 |
| benchmark (TRI) | 3.8 | 0.47 | 10.04 | -5.54 | 20.55 | 60.0 |  |

Mean excess vs benchmark, raw: +2.46 pts (median +6.05), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -0.68 pts (median +5.54), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 5.19 | 6.89 | 5.19 | 1.32 | 66.67 | 66.67 |
| BEAR | 2 | 7.85 | 7.85 | 0.0 | 7.51 | 50.0 | 50.0 |

Stock-level return status counts at 1M: {'ok': 100}

### 3M (63 sessions): 5 samples, 5 complete, 0 incomplete; ~5.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 | 12.06 | 4.77 | 17.87 | 0.1 | 43.23 | 100.0 | 40.0 |
| market-filtered | 3.4 | 1.76 | 4.41 | 0.0 | 10.47 | 60.0 | 20.0 |
| benchmark (TRI) | 10.46 | 7.71 | 13.45 | -1.34 | 33.53 | 80.0 |  |

Mean excess vs benchmark, raw: +1.60 pts (median -2.43), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -7.06 pts (median -3.45), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 5.66 | 4.77 | 5.66 | 3.69 | 33.33 | 33.33 |
| BEAR | 2 | 21.66 | 21.66 | 0.0 | 20.62 | 50.0 | 0.0 |

Stock-level return status counts at 3M: {'ok': 100}

### 6M (126 sessions): 5 samples, 5 complete, 0 incomplete; ~5.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 | 15.94 | 3.69 | 32.16 | -7.91 | 72.14 | 80.0 | 40.0 |
| market-filtered | 0.78 | 0.0 | 6.85 | -7.91 | 11.3 | 40.0 | 20.0 |
| benchmark (TRI) | 10.6 | 3.69 | 18.41 | -5.61 | 41.21 | 80.0 |  |

Mean excess vs benchmark, raw: +5.34 pts (median -3.20), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -9.82 pts (median -8.40), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 1.3 | 0.5 | 1.3 | -0.47 | 33.33 | 33.33 |
| BEAR | 2 | 37.91 | 37.91 | 0.0 | 27.21 | 50.0 | 0.0 |

Stock-level return status counts at 6M: {'ok': 100}

