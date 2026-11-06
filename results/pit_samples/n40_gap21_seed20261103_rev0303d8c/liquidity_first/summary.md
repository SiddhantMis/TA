## Summary statistics

Benchmark: `nifty500_tri_return_pct` (signal-date close to exit close). Primary stock series: `raw_top20_close_to_close_net_return_pct` - measured over the SAME window as the benchmark (signal close to exit close), so the comparison is like for like. The as-traded next-open basket is shown separately with its overnight effect. Samples whose basket has any missing or corporate-action-invalidated stock return are EXCLUDED (never reweighted). Overlapping holding windows make neighbouring samples dependent: the effective number of independent samples is about n x min(1, min_gap / horizon), and the intervals use a circular block bootstrap.

### 1M (21 sessions): 40 samples, 40 complete, 0 incomplete; ~40.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 2.95 | 3.46 | 7.44 | -18.44 | 17.77 | 67.5 | 55.0 |
| market-filtered (close-to-close) | 2.54 | 0.74 | 5.66 | -7.86 | 12.82 | 55.0 | 57.5 |
| benchmark (TRI) | 2.03 | 1.66 | 4.99 | -5.81 | 20.55 | 70.0 |  |

As traded (buy at the next open): mean +2.52%, median +2.64%; the overnight execution effect vs the close-to-close basket averages -0.43 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +0.92 pts (median +1.17), 95% block-bootstrap interval [-0.54, +2.31]
Mean excess vs benchmark, market-filtered: +0.51 pts (median +1.17), 95% interval [-1.29, +2.28]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 32 | 3.18 | 3.46 | 3.18 | 1.39 | 62.5 | 62.5 |
| BEAR | 8 | 2.02 | 3.23 | 0.0 | 4.58 | 25.0 | 37.5 |

Stock-level return status counts at 1M: {'ok': 793}

### 3M (63 sessions): 40 samples, 37 complete, 3 incomplete; ~12.3 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 9.1 | 8.68 | 17.7 | -19.76 | 55.63 | 64.86 | 51.35 |
| market-filtered (close-to-close) | 6.59 | 0.0 | 16.64 | -18.98 | 55.63 | 48.65 | 43.24 |
| benchmark (TRI) | 5.85 | 4.9 | 10.0 | -11.92 | 33.53 | 72.97 |  |

As traded (buy at the next open): mean +8.69%, median +8.89%; the overnight execution effect vs the close-to-close basket averages -0.41 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +3.24 pts (median +0.59), 95% block-bootstrap interval [-1.18, +8.41]
Mean excess vs benchmark, market-filtered: +0.74 pts (median -1.29), 95% interval [-4.78, +7.13]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 30 | 8.13 | 4.53 | 8.13 | 4.08 | 50.0 | 50.0 |
| BEAR | 7 | 13.24 | 16.46 | 0.0 | 13.46 | 57.14 | 14.29 |

Stock-level return status counts at 3M: {'ok': 790, 'unsupported_corporate_action_during_hold': 3}

### 6M (126 sessions): 40 samples, 29 complete, 11 incomplete; ~4.8 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 17.91 | 14.25 | 25.92 | -25.45 | 60.86 | 72.41 | 72.41 |
| market-filtered (close-to-close) | 14.84 | 6.02 | 25.59 | -25.45 | 60.86 | 62.07 | 62.07 |
| benchmark (TRI) | 8.87 | 7.77 | 13.3 | -15.08 | 41.21 | 68.97 |  |

As traded (buy at the next open): mean +17.61%, median +13.44%; the overnight execution effect vs the close-to-close basket averages -0.30 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +9.04 pts (median +5.71), 95% block-bootstrap interval [+0.17, +19.32]
Mean excess vs benchmark, market-filtered: +5.97 pts (median +4.90), 95% interval [-3.53, +17.77]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 26 | 16.55 | 9.89 | 16.55 | 7.36 | 69.23 | 69.23 |
| BEAR | 3 | 29.68 | 23.26 | 0.0 | 21.98 | 100.0 | 0.0 |

Stock-level return status counts at 6M: {'ok': 781, 'unsupported_corporate_action_during_hold': 12}

