```
NSE corporate-action adjustments: [{'ex_date': '2019-12-19', 'price_factor': 0.1, 'volume_factor': 10.0, 'source': 'https://archives.nseindia.com/content/circulars/CML42873.pdf'}]; daily-return correlation NSE NIFTYBEES vs ^NSEI 0.971
Portfolio rules: 806 loaded price histories for PIT Nifty 500, daily engine 2017-11-08 to 2026-10-13, IS/OOS split 2023-08-28, cost 0.3% round trip, cash 0%
PIT calendar: 1151 intervals / 970 symbols; source coverage through 2026-10-13; source categories {'press_release': 632, 'snapshot_floor': 516, 'merger': 2, 'snapshot': 1}
PIT active-member count during test: 498–507 (nominal index size 500; source documents historical count drift and a 499-name 2026 snapshot)
Price-history coverage across full calendar: 806/970 symbols loaded; 164 missing/unusable
Missing histories overlapping test window: 105/878 active-window symbols; 59 additional missing symbols have no overlap with this backtest window
Active-window missing load outcomes: {'no_history': 85, 'insufficient_history': 20}; first 20: ['AKZOINDIA:no_history(0 bars)', 'ALBK:no_history(0 bars)', 'ANDHRABANK:no_history(0 bars)', 'ANGELBRKG:no_history(0 bars)', 'BAGMANE:no_history(0 bars)', 'BALLARPUR:no_history(0 bars)', 'BHARATCOAL:insufficient_history(193 bars)', 'BHARATFIN:no_history(0 bars)', 'BHUSANSTL:no_history(0 bars)', 'BRFL:no_history(0 bars)', 'CAPF:no_history(0 bars)', 'CENTURYTEX:no_history(0 bars)', 'CLEANMAX:insufficient_history(164 bars)', 'CMPDI:insufficient_history(146 bars)', 'CORPBANK:no_history(0 bars)', 'COX&KINGS:no_history(0 bars)', 'DENABANK:no_history(0 bars)', 'DHANI:no_history(0 bars)', 'DHFL:no_history(0 bars)', 'EMMVEE:insufficient_history(236 bars)']
Daily active-member bars covered: min 0.0%, p10 87.7%, median 95.8%; 18.6% of sessions below 90% coverage
Zero-coverage sessions: 8; dates: ['2019-02-13', '2019-03-29', '2020-02-01', '2023-11-12', '2024-01-20', '2024-03-02', '2024-05-18', '2026-02-01']
Worst coverage sessions (date: active bars/expected, coverage, all loaded-symbol bars): 2019-02-13: 0/502 (0.0%), all-symbol bars=0; 2019-03-29: 0/503 (0.0%), all-symbol bars=0; 2020-02-01: 0/504 (0.0%), all-symbol bars=0; 2023-11-12: 0/501 (0.0%), all-symbol bars=0; 2024-01-20: 0/501 (0.0%), all-symbol bars=0; 2024-03-02: 0/501 (0.0%), all-symbol bars=0; 2024-05-18: 0/500 (0.0%), all-symbol bars=0; 2026-02-01: 0/499 (0.0%), all-symbol bars=0
WARNING: missing/delisted-symbol history and source calendar gaps can still bias results; see universe/NIFTY500_PIT_DATA.md and the generated PIT audit CSVs.
Benchmark: official NSE NIFTYBEES traded closes, split-adjusted to current Rs 1 face-value units; 2461 bars; max abs daily move 10.16%
Regime diagnostic: ^NSEI price index quality gate passed; 2454 bars; max abs daily move 12.98%
NIFTY50_price_index is a PRICE index (not a total-return index).
CAGR / vol / Sharpe(rf=0) / max drawdown (daily)

-- FULL --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                     7.8%   16.1%    0.54   -38.0%
V3_live_nobuf                   7.1%   16.2%    0.50   -38.0%
V2_live                         6.2%   15.9%    0.46   -37.7%
V4a_stop20                      5.9%   14.5%    0.47   -34.2%
V4b_stop30                      5.9%   15.5%    0.45   -37.7%
V5_nofilter                    11.2%   17.1%    0.70   -35.8%
V6_half                         8.7%   16.2%    0.60   -36.8%
V7_nifty50_filter               5.0%   12.3%    0.46   -30.2%
NIFTYBEES_adjusted_buyhold     10.7%   15.1%    0.75   -36.3%
EW_universe_daily               7.3%   13.2%    0.60   -27.6%
NIFTY50_price_index             9.5%   16.8%    0.63   -38.4%

-- IS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                     7.4%   17.8%    0.49   -38.0%
V3_live_nobuf                   5.8%   18.0%    0.40   -38.0%
V2_live                         4.5%   17.7%    0.34   -37.7%
V4a_stop20                      4.3%   16.0%    0.34   -34.2%
V4b_stop30                      4.1%   17.2%    0.32   -37.7%
V5_nofilter                    11.3%   19.1%    0.66   -35.8%
V6_half                         8.0%   18.1%    0.52   -36.8%
V7_nifty50_filter               2.6%   12.6%    0.27   -30.2%
NIFTYBEES_adjusted_buyhold     13.0%   16.5%    0.82   -36.3%
EW_universe_daily               6.9%   14.8%    0.53   -27.6%
NIFTY50_price_index            11.7%   18.4%    0.70   -38.4%

-- OOS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                     8.4%   12.3%    0.72   -11.4%
V3_live_nobuf                   9.4%   12.0%    0.81   -10.6%
V2_live                         9.5%   11.7%    0.83    -8.9%
V4a_stop20                      8.9%   11.4%    0.80    -8.5%
V4b_stop30                      9.2%   11.6%    0.81    -8.9%
V5_nofilter                    10.8%   12.7%    0.87    -8.9%
V6_half                        10.2%   11.9%    0.87    -8.9%
V7_nifty50_filter               9.5%   11.7%    0.83    -8.9%
NIFTYBEES_adjusted_buyhold      6.6%   12.0%    0.60   -15.2%
EW_universe_daily               8.1%    9.6%    0.86    -7.8%
NIFTY50_price_index             5.5%   13.2%    0.47   -15.8%

-- activity --
                             rebalances  avg turnover stop-outs  days in cash
V1_baseline                         107          0.43         0           48%
V3_live_nobuf                       107          0.43         0           49%
V2_live                             107          0.35         0           49%
V4a_stop20                          107          0.34       154           49%
V4b_stop30                          107          0.35        47           49%
V5_nofilter                         107          0.34         0           41%
V6_half                             107          0.35         0           41%
V7_nifty50_filter                   107          0.26         0           70%

-- what the NSE-sourced NIFTYBEES filter sees: 511 BEAR days (23% of known-regime days), 1696 BULL days --
annualised adjusted ETF return on ETF-BEAR days: +17.9%; same-universe equal-weight: +91.6%
annualised adjusted ETF return on ETF-BULL days: +8.6%; same-universe equal-weight: +3.9%
^NSEI filter: 166 BEAR / 680 BULL days; disagrees with NSE-sourced ETF regime on 12/846 common days
annualised ^NSEI price-index return on ^NSEI-BEAR days: +84.4%; same-universe equal-weight: +90.2%

-- comparisons (rules fixed in advance) --
live rules vs old baseline                          DIFFERENT: IS CAGR differs by > 2 points
28th trigger vs month-end (timing only)             ~ SAME as baseline
buffer 30 vs none                                   turnover 0.35 vs 0.43 (+17% lower); CAGR -0.8 pts -> NOT SHOWN TO HELP
V4a_stop20 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points
V4b_stop30 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points
V5_nofilter vs V2_live                              FULL CAGR +4.9 pts; FULL maxDD +2.0 pts; OOS CAGR +1.3 pts; OOS maxDD +0.0 pts
V6_half vs V2_live                                  FULL CAGR +2.5 pts; FULL maxDD +1.0 pts; OOS CAGR +0.7 pts; OOS maxDD -0.0 pts
V7_nifty50_filter vs V2_live                        FULL CAGR -1.3 pts; FULL maxDD +7.6 pts; OOS CAGR -0.0 pts; OOS maxDD +0.0 pts
```
