```
NSE corporate-action adjustments: [{'ex_date': '2019-12-19', 'price_factor': 0.1, 'volume_factor': 10.0, 'source': 'https://archives.nseindia.com/content/circulars/CML42873.pdf'}]; daily-return correlation NSE NIFTYBEES vs ^NSEI 0.971
Portfolio rules: 467 stocks, daily engine 2017-11-08 to 2026-11-02, IS/OOS split 2023-09-08, cost 0.3% round trip, cash 0%
Benchmark: official NSE NIFTYBEES traded closes, split-adjusted to current Rs 1 face-value units; 2474 bars; max abs daily move 10.16%
Regime diagnostic: ^NSEI price index quality gate passed; 2466 bars; max abs daily move 12.98%
NIFTY50_price_index is a PRICE index (not a total-return index).
CAGR / vol / Sharpe(rf=0) / max drawdown (daily)

-- FULL --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    11.9%   15.9%    0.79   -24.2%
V3_live_nobuf                  10.2%   16.1%    0.68   -32.9%
V2_live                         9.2%   16.0%    0.63   -30.3%
V4a_stop20                      7.1%   14.6%    0.54   -33.7%
V4b_stop30                      8.5%   15.6%    0.60   -32.1%
V5_nofilter                    14.0%   17.2%    0.85   -31.5%
V6_half                        11.5%   16.3%    0.75   -26.2%
V7_nifty50_filter               4.8%   12.4%    0.44   -31.6%
NIFTYBEES_adjusted_buyhold     11.0%   15.0%    0.77   -36.3%
EW_universe_daily               9.1%   12.9%    0.74   -21.9%
NIFTY50_price_index             9.6%   16.8%    0.63   -38.4%

-- IS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    15.9%   17.6%    0.93   -24.2%
V3_live_nobuf                  12.9%   17.9%    0.77   -32.9%
V2_live                        11.3%   17.8%    0.69   -30.3%
V4a_stop20                      8.5%   16.1%    0.59   -33.7%
V4b_stop30                     10.4%   17.3%    0.66   -32.1%
V5_nofilter                    18.2%   19.1%    0.97   -31.5%
V6_half                        14.7%   18.1%    0.85   -26.2%
V7_nifty50_filter               4.5%   12.6%    0.41   -31.6%
NIFTYBEES_adjusted_buyhold     13.4%   16.4%    0.85   -36.3%
EW_universe_daily              10.6%   14.4%    0.77   -21.9%
NIFTY50_price_index            12.2%   18.4%    0.72   -38.4%

-- OOS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                     4.8%   12.2%    0.45   -12.3%
V3_live_nobuf                   5.3%   12.1%    0.49   -10.3%
V2_live                         5.3%   11.9%    0.49   -10.9%
V4a_stop20                      4.5%   11.5%    0.44   -11.8%
V4b_stop30                      5.2%   11.9%    0.49   -10.8%
V5_nofilter                     6.6%   12.9%    0.56   -10.9%
V6_half                         6.0%   12.2%    0.54   -10.9%
V7_nifty50_filter               5.3%   11.9%    0.49   -10.9%
NIFTYBEES_adjusted_buyhold      6.6%   12.0%    0.59   -15.2%
EW_universe_daily               6.4%    9.6%    0.70    -8.0%
NIFTY50_price_index             5.1%   13.3%    0.44   -15.8%

-- activity --
                             rebalances  avg turnover stop-outs  days in cash
V1_baseline                         108          0.41         0           49%
V3_live_nobuf                       108          0.42         0           49%
V2_live                             108          0.34         0           49%
V4a_stop20                          108          0.35       158           49%
V4b_stop30                          108          0.34        40           49%
V5_nofilter                         108          0.32         0           41%
V6_half                             108          0.33         0           41%
V7_nifty50_filter                   108          0.26         0           70%

-- what the NSE-sourced NIFTYBEES filter sees: 524 BEAR days (24% of known-regime days), 1696 BULL days --
annualised adjusted ETF return on ETF-BEAR days: +18.9%; same-universe equal-weight: +94.8%
annualised adjusted ETF return on ETF-BULL days: +8.6%; same-universe equal-weight: +7.1%
^NSEI filter: 166 BEAR / 680 BULL days; disagrees with NSE-sourced ETF regime on 12/846 common days
annualised ^NSEI price-index return on ^NSEI-BEAR days: +84.4%; same-universe equal-weight: +91.6%

-- comparisons (rules fixed in advance) --
live rules vs old baseline                          DIFFERENT: IS CAGR differs by > 2 points; max drawdown > 3 points worse
28th trigger vs month-end (timing only)             DIFFERENT: IS CAGR differs by > 2 points; max drawdown > 3 points worse
buffer 30 vs none                                   turnover 0.34 vs 0.42 (+17% lower); CAGR -1.0 pts -> NOT SHOWN TO HELP
V4a_stop20 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points; IS CAGR falls by more than 2 points
V4b_stop30 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points
V5_nofilter vs V2_live                              FULL CAGR +4.9 pts; FULL maxDD -1.1 pts; OOS CAGR +1.3 pts; OOS maxDD +0.0 pts
V6_half vs V2_live                                  FULL CAGR +2.4 pts; FULL maxDD +4.1 pts; OOS CAGR +0.6 pts; OOS maxDD +0.0 pts
V7_nifty50_filter vs V2_live                        FULL CAGR -4.4 pts; FULL maxDD -1.2 pts; OOS CAGR +0.0 pts; OOS maxDD -0.0 pts
```
