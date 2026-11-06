## Summary statistics

Benchmark: `nifty500_tri_return_pct` (signal-date close to exit close). Primary stock series: `raw_top20_close_to_close_net_return_pct` - measured over the SAME window as the benchmark (signal close to exit close), so the comparison is like for like. The as-traded next-open basket is shown separately with its overnight effect. Samples whose basket has any missing or corporate-action-invalidated stock return are EXCLUDED (never reweighted). Overlapping holding windows make neighbouring samples dependent: the effective number of independent samples is about n x min(1, min_gap / horizon), and the intervals use a circular block bootstrap.

### 1M (21 sessions): 5 samples, 4 complete, 1 incomplete; ~4.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 4.24 | 0.75 | 9.98 | -2.89 | 18.36 | 50.0 | 25.0 |
| market-filtered (close-to-close) | 3.19 | -1.36 | 10.2 | -2.89 | 18.36 | 25.0 | 25.0 |
| benchmark (TRI) | 1.51 | 0.7 | 4.1 | -2.47 | 7.1 | 50.0 |  |

As traded (buy at the next open): mean +3.65%, median +0.06%; the overnight execution effect vs the close-to-close basket averages -0.59 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +2.73 pts (median -1.40), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: +1.68 pts (median -1.40), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 4.25 | -2.71 | 4.25 | -0.36 | 33.33 | 33.33 |
| BEAR | 1 | 4.2 | 4.2 | 0.0 | 7.1 | 0.0 | 0.0 |

Stock-level return status counts at 1M: {'ok': 99, 'unsupported_corporate_action_during_hold': 1}

### 3M (63 sessions): 5 samples, 4 complete, 1 incomplete; ~4.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 6.69 | 4.54 | 12.92 | -4.13 | 21.82 | 50.0 | 75.0 |
| market-filtered (close-to-close) | 1.24 | -1.99 | 8.12 | -4.13 | 13.07 | 25.0 | 50.0 |
| benchmark (TRI) | 3.28 | 2.2 | 9.28 | -6.31 | 15.02 | 50.0 |  |

As traded (buy at the next open): mean +6.01%, median +4.11%; the overnight execution effect vs the close-to-close basket averages -0.68 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +3.42 pts (median +4.49), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -2.04 pts (median -0.19), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 1.65 | -3.99 | 1.65 | -0.64 | 66.67 | 66.67 |
| BEAR | 1 | 21.82 | 21.82 | 0.0 | 15.02 | 100.0 | 0.0 |

Stock-level return status counts at 3M: {'ok': 99, 'unsupported_corporate_action_during_hold': 1}

### 6M (126 sessions): 5 samples, 3 complete, 2 incomplete; ~3.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 12.94 | 6.92 | 35.38 | -19.05 | 50.93 | 66.67 | 66.67 |
| market-filtered (close-to-close) | 12.94 | 6.92 | 35.38 | -19.05 | 50.93 | 66.67 | 66.67 |
| benchmark (TRI) | 1.25 | -4.05 | 15.13 | -10.52 | 18.32 | 33.33 |  |

As traded (buy at the next open): mean +12.44%, median +6.71%; the overnight execution effect vs the close-to-close basket averages -0.50 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +11.68 pts (median +10.97), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: +11.68 pts (median +10.97), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 12.94 | 6.92 | 12.94 | 1.25 | 66.67 | 66.67 |

Stock-level return status counts at 6M: {'ok': 97, 'unsupported_corporate_action_during_hold': 3}

