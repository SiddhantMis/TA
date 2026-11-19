# All-eligible cross-sectional factor rank-IC

TejHQ dataset revision: `0303d8c95b4519765a9d5556fd9c2d430f8f81d8`
Eligibility on each signal date: point-in-time NIFTY 500 membership, at least 253 observed sessions, top 200 by 126-session average raw traded value, adjusted close above its 200-DMA, and corporate-action quarantine eligibility. Factors are measured on the signal close. Forward returns use next-session adjusted open to the sample's fixed horizon exit close; a stock is omitted for a horizon if an unsupported corporate action occurs between signal and exit. This avoids outcome contamination without changing the signal-date universe.

| Horizon | Factor | Sample dates | Mean eligible N | Mean valid-return N | Mean Spearman IC | Median Spearman IC |
|---|---|---:|---:|---:|---:|---:|
| 1M | 12–1 momentum | 40 | 125.7 | 125.2 | +0.0360 | +0.0541 |
| 1M | Distance above 200-DMA | 40 | 125.7 | 125.2 | -0.0014 | +0.0114 |
| 1M | Distance from 52-week high | 40 | 125.7 | 125.2 | +0.0111 | -0.0008 |
| 1M | 126-day traded value | 40 | 125.7 | 125.2 | +0.0155 | +0.0174 |
| 3M | 12–1 momentum | 40 | 125.7 | 124.4 | +0.0339 | +0.0347 |
| 3M | Distance above 200-DMA | 40 | 125.7 | 124.4 | +0.0104 | -0.0180 |
| 3M | Distance from 52-week high | 40 | 125.7 | 124.4 | +0.0101 | +0.0550 |
| 3M | 126-day traded value | 40 | 125.7 | 124.4 | -0.0079 | -0.0016 |
| 6M | 12–1 momentum | 40 | 125.7 | 123.2 | +0.0241 | +0.0053 |
| 6M | Distance above 200-DMA | 40 | 125.7 | 123.2 | +0.0272 | +0.0330 |
| 6M | Distance from 52-week high | 40 | 125.7 | 123.2 | +0.0194 | +0.0518 |
| 6M | 126-day traded value | 40 | 125.7 | 123.2 | -0.0313 | -0.0360 |

IC is computed cross-sectionally across all eligible stocks on each sample date, not only the selected top-20. The 40 signal dates are overlapping observations and are descriptive, not independent statistical trials.

Per-date results: `all_eligible_factor_rank_ic.csv`; summary: `all_eligible_factor_rank_ic_summary.csv`.
