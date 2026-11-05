## Summary statistics

Benchmark: `nifty500_tri_entry_aligned_return_pct`. Samples whose basket has any missing or corporate-action-invalidated stock return are EXCLUDED (never reweighted). Overlapping holding windows make neighbouring samples dependent: the effective number of independent samples is about n x min(1, min_gap / horizon), and the intervals use a circular block bootstrap.

### 1M (21 sessions): 5 samples, 5 complete, 0 incomplete; ~5.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 | 5.24 | 6.31 | 11.23 | -9.04 | 19.32 | 60.0 | 40.0 |
| market-filtered | 3.18 | 0.0 | 5.83 | -2.3 | 11.91 | 40.0 | 60.0 |
| benchmark (TRI) | 3.8 | 0.47 | 10.04 | -5.54 | 20.55 | 60.0 |  |

Mean excess vs benchmark, raw: +1.45 pts (median -1.23), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -0.61 pts (median +5.54), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 5.31 | 6.31 | 5.31 | 1.32 | 66.67 | 66.67 |
| BEAR | 2 | 5.14 | 5.14 | 0.0 | 7.51 | 0.0 | 50.0 |

Stock-level return status counts at 1M: {'ok': 93}

### 3M (63 sessions): 5 samples, 5 complete, 0 incomplete; ~5.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 | 11.09 | 6.69 | 12.48 | 2.99 | 32.85 | 100.0 | 40.0 |
| market-filtered | 2.56 | 2.99 | 2.77 | 0.0 | 6.69 | 60.0 | 20.0 |
| benchmark (TRI) | 10.46 | 7.71 | 13.45 | -1.34 | 33.53 | 80.0 |  |

Mean excess vs benchmark, raw: +0.63 pts (median -0.69), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -7.90 pts (median -1.53), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 4.27 | 3.12 | 4.27 | 3.69 | 33.33 | 33.33 |
| BEAR | 2 | 21.33 | 21.33 | 0.0 | 20.62 | 50.0 | 0.0 |

Stock-level return status counts at 3M: {'ok': 93}

### 6M (126 sessions): 5 samples, 4 complete, 1 incomplete; ~4.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 | 11.99 | 0.88 | 28.2 | -7.64 | 53.83 | 50.0 | 50.0 |
| market-filtered | -1.47 | -0.22 | 4.27 | -7.64 | 2.19 | 25.0 | 25.0 |
| benchmark (TRI) | 9.95 | 2.09 | 21.19 | -5.61 | 41.21 | 75.0 |  |

Mean excess vs benchmark, raw: +2.04 pts (median +1.84), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -11.42 pts (median -6.13), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | -1.96 | -0.43 | -1.96 | -0.47 | 33.33 | 33.33 |
| BEAR | 1 | 53.83 | 53.83 | 0.0 | 41.21 | 100.0 | 0.0 |

Stock-level return status counts at 6M: {'ok': 92, 'unsupported_corporate_action_during_hold': 1}

