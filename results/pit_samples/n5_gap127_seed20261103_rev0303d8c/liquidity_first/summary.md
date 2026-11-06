## Summary statistics

Benchmark: `nifty500_tri_return_pct` (signal-date close to exit close). Primary stock series: `raw_top20_close_to_close_net_return_pct` - measured over the SAME window as the benchmark (signal close to exit close), so the comparison is like for like. The as-traded next-open basket is shown separately with its overnight effect. Samples whose basket has any missing or corporate-action-invalidated stock return are EXCLUDED (never reweighted). Overlapping holding windows make neighbouring samples dependent: the effective number of independent samples is about n x min(1, min_gap / horizon), and the intervals use a circular block bootstrap.

### 1M (21 sessions): 5 samples, 5 complete, 0 incomplete; ~5.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 5.03 | 6.5 | 10.97 | -9.03 | 17.77 | 60.0 | 40.0 |
| market-filtered (close-to-close) | 3.28 | 0.0 | 6.26 | -2.77 | 12.68 | 40.0 | 60.0 |
| benchmark (TRI) | 4.65 | 3.82 | 9.66 | -4.8 | 20.55 | 60.0 |  |

As traded (buy at the next open): mean +5.24%, median +6.31%; the overnight execution effect vs the close-to-close basket averages +0.21 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +0.39 pts (median -1.88), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -1.36 pts (median +2.68), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 5.47 | 6.5 | 5.47 | 2.5 | 66.67 | 66.67 |
| BEAR | 2 | 4.37 | 4.37 | 0.0 | 7.88 | 0.0 | 50.0 |

Stock-level return status counts at 1M: {'ok': 93}

### 3M (63 sessions): 5 samples, 5 complete, 0 incomplete; ~5.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 10.8 | 7.42 | 11.64 | 2.49 | 30.92 | 100.0 | 40.0 |
| market-filtered (close-to-close) | 2.65 | 2.49 | 3.05 | 0.0 | 7.42 | 60.0 | 20.0 |
| benchmark (TRI) | 11.33 | 8.23 | 12.72 | 1.96 | 33.53 | 100.0 |  |

As traded (buy at the next open): mean +11.09%, median +6.69%; the overnight execution effect vs the close-to-close basket averages +0.30 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: -0.53 pts (median -0.82), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -8.68 pts (median -1.87), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 4.41 | 3.34 | 4.41 | 4.85 | 33.33 | 33.33 |
| BEAR | 2 | 20.38 | 20.38 | 0.0 | 21.04 | 50.0 | 0.0 |

Stock-level return status counts at 3M: {'ok': 93}

### 6M (126 sessions): 5 samples, 4 complete, 1 incomplete; ~4.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 11.54 | 1.35 | 27.04 | -8.05 | 51.53 | 75.0 | 50.0 |
| market-filtered (close-to-close) | -1.34 | 0.13 | 4.61 | -8.05 | 2.44 | 50.0 | 25.0 |
| benchmark (TRI) | 10.78 | 2.18 | 20.44 | -2.46 | 41.21 | 75.0 |  |

As traded (buy at the next open): mean +11.99%, median +0.88%; the overnight execution effect vs the close-to-close basket averages +0.44 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +0.77 pts (median +0.73), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -12.12 pts (median -6.08), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | -1.78 | 0.26 | -1.78 | 0.64 | 33.33 | 33.33 |
| BEAR | 1 | 51.53 | 51.53 | 0.0 | 41.21 | 100.0 | 0.0 |

Stock-level return status counts at 6M: {'ok': 92, 'unsupported_corporate_action_during_hold': 1}

