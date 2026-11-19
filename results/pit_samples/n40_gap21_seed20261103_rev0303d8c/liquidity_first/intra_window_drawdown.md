# Intra-window drawdown study

Dataset revision: `0303d8c95b4519765a9d5556fd9c2d430f8f81d8`
Method: equal-weight buy-and-hold basket from adjusted next-session entry open; daily adjusted close marks; missing daily closes are carried forward only for held-position valuation. No incomplete horizon basket is reweighted.

| Horizon | Complete baskets | Mean max DD | Median max DD | Worst max DD |
|---|---:|---:|---:|---:|
| 1M | 40 | -6.08% | -4.51% | -20.85% |
| 3M | 37 | -10.93% | -9.01% | -30.73% |
| 6M | 29 | -14.73% | -13.61% | -30.14% |

Per-sample peak/trough dates and drawdowns are in `intra_window_drawdown.csv`.
