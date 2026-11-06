## Summary statistics

Benchmark: `nifty500_tri_return_pct` (signal-date close to exit close). Primary stock series: `raw_top20_close_to_close_net_return_pct` - measured over the SAME window as the benchmark (signal close to exit close), so the comparison is like for like. The as-traded next-open basket is shown separately with its overnight effect. Samples whose basket has any missing or corporate-action-invalidated stock return are EXCLUDED (never reweighted). Overlapping holding windows make neighbouring samples dependent: the effective number of independent samples is about n x min(1, min_gap / horizon), and the intervals use a circular block bootstrap.

### 1M (21 sessions): 5 samples, 4 complete, 1 incomplete; ~4.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 3.89 | 0.12 | 10.43 | -3.52 | 18.83 | 50.0 | 25.0 |
| market-filtered (close-to-close) | 3.06 | -1.52 | 10.62 | -3.52 | 18.83 | 25.0 | 25.0 |
| benchmark (TRI) | 1.51 | 0.7 | 4.1 | -2.47 | 7.1 | 50.0 |  |

As traded (buy at the next open): mean +3.29%, median -0.47%; the overnight execution effect vs the close-to-close basket averages -0.60 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +2.38 pts (median -1.88), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: +1.56 pts (median -1.88), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 4.09 | -3.05 | 4.09 | -0.36 | 33.33 | 33.33 |
| BEAR | 1 | 3.28 | 3.28 | 0.0 | 7.1 | 0.0 | 0.0 |

Stock-level return status counts at 1M: {'ok': 99, 'unsupported_corporate_action_during_hold': 1}

### 3M (63 sessions): 5 samples, 4 complete, 1 incomplete; ~4.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 7.52 | 5.55 | 13.21 | -3.94 | 22.92 | 50.0 | 75.0 |
| market-filtered (close-to-close) | 1.79 | -1.52 | 8.4 | -3.94 | 14.13 | 25.0 | 50.0 |
| benchmark (TRI) | 3.28 | 2.2 | 9.28 | -6.31 | 15.02 | 50.0 |  |

As traded (buy at the next open): mean +6.83%, median +4.95%; the overnight execution effect vs the close-to-close basket averages -0.69 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +4.24 pts (median +5.59), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -1.49 pts (median +0.38), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 2.39 | -3.03 | 2.39 | -0.64 | 66.67 | 66.67 |
| BEAR | 1 | 22.92 | 22.92 | 0.0 | 15.02 | 100.0 | 0.0 |

Stock-level return status counts at 3M: {'ok': 99, 'unsupported_corporate_action_during_hold': 1}

### 6M (126 sessions): 5 samples, 3 complete, 2 incomplete; ~3.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 14.9 | 8.75 | 36.94 | -18.57 | 54.53 | 66.67 | 66.67 |
| market-filtered (close-to-close) | 14.9 | 8.75 | 36.94 | -18.57 | 54.53 | 66.67 | 66.67 |
| benchmark (TRI) | 1.25 | -4.05 | 15.13 | -10.52 | 18.32 | 33.33 |  |

As traded (buy at the next open): mean +14.40%, median +8.54%; the overnight execution effect vs the close-to-close basket averages -0.51 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +13.65 pts (median +12.80), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: +13.65 pts (median +12.80), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 14.9 | 8.75 | 14.9 | 1.25 | 66.67 | 66.67 |

Stock-level return status counts at 6M: {'ok': 98, 'unsupported_corporate_action_during_hold': 2}

