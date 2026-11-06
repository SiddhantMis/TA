## Summary statistics

Benchmark: `nifty500_tri_return_pct` (signal-date close to exit close). Primary stock series: `raw_top20_close_to_close_net_return_pct` - measured over the SAME window as the benchmark (signal close to exit close), so the comparison is like for like. The as-traded next-open basket is shown separately with its overnight effect. Samples whose basket has any missing or corporate-action-invalidated stock return are EXCLUDED (never reweighted). Overlapping holding windows make neighbouring samples dependent: the effective number of independent samples is about n x min(1, min_gap / horizon), and the intervals use a circular block bootstrap.

### 1M (21 sessions): 5 samples, 5 complete, 0 incomplete; ~5.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 5.89 | 7.12 | 14.37 | -12.42 | 25.68 | 60.0 | 60.0 |
| market-filtered (close-to-close) | 3.24 | 0.0 | 5.76 | -2.3 | 11.38 | 40.0 | 60.0 |
| benchmark (TRI) | 4.65 | 3.82 | 9.66 | -4.8 | 20.55 | 60.0 |  |

As traded (buy at the next open): mean +6.26%, median +6.89%; the overnight execution effect vs the close-to-close basket averages +0.36 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +1.24 pts (median +3.30), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -1.41 pts (median +3.30), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 5.4 | 7.12 | 5.4 | 2.5 | 66.67 | 66.67 |
| BEAR | 2 | 6.63 | 6.63 | 0.0 | 7.88 | 50.0 | 50.0 |

Stock-level return status counts at 1M: {'ok': 100}

### 3M (63 sessions): 5 samples, 5 complete, 0 incomplete; ~5.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 11.61 | 5.49 | 16.71 | -0.1 | 40.54 | 80.0 | 40.0 |
| market-filtered (close-to-close) | 3.52 | 1.35 | 4.62 | 0.0 | 10.74 | 60.0 | 20.0 |
| benchmark (TRI) | 11.33 | 8.23 | 12.72 | 1.96 | 33.53 | 100.0 |  |

As traded (buy at the next open): mean +12.06%, median +4.77%; the overnight execution effect vs the close-to-close basket averages +0.46 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +0.28 pts (median -2.74), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -7.81 pts (median -3.01), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 5.86 | 5.49 | 5.86 | 4.85 | 33.33 | 33.33 |
| BEAR | 2 | 20.22 | 20.22 | 0.0 | 21.04 | 50.0 | 0.0 |

Stock-level return status counts at 3M: {'ok': 100}

### 6M (126 sessions): 5 samples, 5 complete, 0 incomplete; ~5.0 effectively independent
| series | mean % | median % | std % | worst % | best % | win rate % (>0) | beats benchmark % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw top-20 (close-to-close) | 15.39 | 3.49 | 30.72 | -8.22 | 68.87 | 80.0 | 40.0 |
| market-filtered (close-to-close) | 0.92 | 0.0 | 7.06 | -8.22 | 11.6 | 40.0 | 20.0 |
| benchmark (TRI) | 11.44 | 3.7 | 17.76 | -2.46 | 41.21 | 80.0 |  |

As traded (buy at the next open): mean +15.94%, median +3.69%; the overnight execution effect vs the close-to-close basket averages +0.56 pts (the TRI includes the signal-close-to-open interval, as does the close-to-close basket).

Mean excess vs benchmark, raw: +3.94 pts (median -2.50), 95% block-bootstrap interval [+nan, +nan]
Mean excess vs benchmark, market-filtered: -10.53 pts (median -8.88), 95% interval [+nan, +nan]

| regime | n | raw mean % | raw median % | filtered mean % | benchmark mean % | raw beats % | filtered beats % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BULL | 3 | 1.53 | 1.2 | 1.53 | 0.64 | 33.33 | 33.33 |
| BEAR | 2 | 36.18 | 36.18 | 0.0 | 27.65 | 50.0 | 0.0 |

Stock-level return status counts at 6M: {'ok': 100}

