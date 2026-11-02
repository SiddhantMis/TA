```
NSE corporate-action adjustments: [{'ex_date': '2019-12-19', 'price_factor': 0.1, 'volume_factor': 10.0, 'source': 'https://archives.nseindia.com/content/circulars/CML42873.pdf'}]; daily-return correlation NSE NIFTYBEES vs ^NSEI 0.972
Portfolio rules: 946 loaded price histories for PIT Nifty 500, daily engine 2017-11-09 to 2026-10-13, IS/OOS split 2023-08-25, cost 0.3% round trip, cash 0%
PIT calendar: 1151 intervals / 970 symbols; source coverage through 2026-10-13; source categories {'press_release': 632, 'snapshot_floor': 516, 'merger': 2, 'snapshot': 1}
PIT active-member count during test: 498–507 (nominal index size 500; source documents historical count drift and a 499-name 2026 snapshot)
Price-history coverage across full calendar: 946/970 symbols loaded; 24 missing/unusable
Missing histories overlapping test window: 5/878 active-window symbols; 19 additional missing symbols have no overlap with this backtest window
Active-window missing load outcomes: {'no_history': 5}; first 20: ['BAGMANE:no_history(0 bars)', 'BIRET:no_history(0 bars)', 'EMBASSY:no_history(0 bars)', 'SGPC:no_history(0 bars)', 'SHTV:no_history(0 bars)']
Daily active-member bars covered: min 91.6%, p10 91.8%, median 95.2%; 0.0% of sessions below 90% coverage
Zero-coverage sessions: 0; dates: []
Worst coverage sessions (date: active bars/expected, coverage, all loaded-symbol bars): 2018-10-01: 460/502 (91.6%), all-symbol bars=668; 2018-10-03: 460/502 (91.6%), all-symbol bars=667; 2018-10-04: 460/502 (91.6%), all-symbol bars=667; 2018-10-05: 460/502 (91.6%), all-symbol bars=667; 2018-10-08: 460/502 (91.6%), all-symbol bars=670; 2018-10-09: 460/502 (91.6%), all-symbol bars=669; 2018-10-10: 460/502 (91.6%), all-symbol bars=670; 2018-10-11: 460/502 (91.6%), all-symbol bars=670
WARNING: missing/delisted-symbol history and source calendar gaps can still bias results; see universe/NIFTY500_PIT_DATA.md and the generated PIT audit CSVs.
Benchmark: official NSE NIFTYBEES traded closes, split-adjusted to current Rs 1 face-value units; 2448 bars; max abs daily move 10.16%
Regime diagnostic: ^NSEI price index quality gate passed; 2448 bars; max abs daily move 12.98%
NIFTY50_price_index is a PRICE index (not a total-return index).
CAGR / vol / Sharpe(rf=0) / max drawdown (daily)

-- FULL --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    16.1%   20.7%    0.83   -38.5%
V3_live_nobuf                  14.1%   20.7%    0.74   -37.1%
V2_live                        14.8%   20.6%    0.77   -34.9%
V4a_stop20                     12.2%   19.0%    0.70   -35.0%
V4b_stop30                     13.5%   20.0%    0.74   -36.2%
V5_nofilter                    20.2%   24.6%    0.87   -48.0%
V6_half                        17.5%   21.5%    0.86   -38.0%
V7_nifty50_filter              16.5%   15.3%    1.08   -31.1%
NIFTYBEES_adjusted_buyhold     10.8%   15.1%    0.75   -36.3%
EW_universe_daily              11.0%   19.8%    0.63   -55.1%
NIFTY50_price_index             9.5%   16.8%    0.63   -38.4%

-- IS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    11.3%   19.4%    0.65   -38.5%
V3_live_nobuf                   9.9%   19.6%    0.58   -37.1%
V2_live                        10.4%   19.3%    0.61   -34.9%
V4a_stop20                      8.9%   17.7%    0.57   -35.0%
V4b_stop30                      9.5%   18.8%    0.58   -36.2%
V5_nofilter                    19.2%   23.1%    0.88   -48.0%
V6_half                        14.5%   20.1%    0.77   -38.0%
V7_nifty50_filter              13.9%   16.1%    0.89   -31.1%
NIFTYBEES_adjusted_buyhold     13.1%   16.5%    0.83   -36.3%
EW_universe_daily               8.0%   20.4%    0.48   -55.1%
NIFTY50_price_index            11.7%   18.4%    0.69   -38.4%

-- OOS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    25.6%   22.9%    1.11   -19.7%
V3_live_nobuf                  22.3%   22.6%    1.01   -23.3%
V2_live                        23.4%   22.8%    1.04   -26.2%
V4a_stop20                     18.7%   21.1%    0.92   -23.9%
V4b_stop30                     21.4%   22.1%    0.99   -26.4%
V5_nofilter                    22.1%   27.1%    0.87   -40.8%
V6_half                        23.1%   24.0%    0.99   -31.3%
V7_nifty50_filter              21.6%   13.7%    1.49    -8.8%
NIFTYBEES_adjusted_buyhold      6.7%   12.0%    0.60   -15.2%
EW_universe_daily              16.8%   18.6%    0.93   -22.6%
NIFTY50_price_index             5.6%   13.2%    0.48   -15.8%

-- activity --
                             rebalances  avg turnover stop-outs  days in cash
V1_baseline                         107          0.59         0           22%
V3_live_nobuf                       107          0.59         0           23%
V2_live                             107          0.47         0           23%
V4a_stop20                          107          0.46       223           23%
V4b_stop30                          107          0.46        69           23%
V5_nofilter                         107          0.47         0            1%
V6_half                             107          0.46         0            1%
V7_nifty50_filter                   107          0.35         0           52%

-- what the NSE-sourced NIFTYBEES filter sees: 505 BEAR days (23% of known-regime days), 1689 BULL days --
annualised adjusted ETF return on ETF-BEAR days: +15.0%; same-universe equal-weight: +21.4%
annualised adjusted ETF return on ETF-BULL days: +9.6%; same-universe equal-weight: +8.0%
^NSEI filter: 464 BEAR / 1069 BULL days; disagrees with NSE-sourced ETF regime on 23/1533 common days
annualised ^NSEI price-index return on ^NSEI-BEAR days: +14.3%; same-universe equal-weight: +16.4%

-- comparisons (rules fixed in advance) --
live rules vs old baseline                          DIFFERENT: OOS CAGR differs by > 2 points
28th trigger vs month-end (timing only)             DIFFERENT: OOS CAGR differs by > 2 points
buffer 30 vs none                                   turnover 0.47 vs 0.59 (+20% lower); CAGR +0.7 pts -> BUFFER HELPS
V4a_stop20 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points; OOS CAGR falls by more than 2 points
V4b_stop30 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points
V5_nofilter vs V2_live                              FULL CAGR +5.4 pts; FULL maxDD -13.2 pts; OOS CAGR -1.3 pts; OOS maxDD -14.6 pts
V6_half vs V2_live                                  FULL CAGR +2.7 pts; FULL maxDD -3.1 pts; OOS CAGR -0.3 pts; OOS maxDD -5.2 pts
V7_nifty50_filter vs V2_live                        FULL CAGR +1.8 pts; FULL maxDD +3.8 pts; OOS CAGR -1.8 pts; OOS maxDD +17.4 pts
```
