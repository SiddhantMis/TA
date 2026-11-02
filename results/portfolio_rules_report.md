```
Benchmark data repairs: [('2019-12-19', '2019-12-20', 'x10')]; daily-return correlation NIFTYBEES vs ^NSEI after repair 0.972
Portfolio rules: 467 stocks, daily engine 2017-11-08 to 2026-10-30, IS/OOS split 2023-09-06, cost 0.3% round trip, cash 0%
Benchmark: NIFTYBEES auto-adjusted with yfinance repair=True; 2471 bars; max abs daily move 10.16%
Regime diagnostic: ^NSEI price index quality gate passed; 2466 bars; max abs daily move 12.98%
NIFTY50_price_index is a PRICE index (not a total-return index).
CAGR / vol / Sharpe(rf=0) / max drawdown (daily)

-- FULL --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    24.7%   20.9%    1.16   -21.0%
V3_live_nobuf                  23.4%   21.0%    1.11   -27.5%
V2_live                        20.4%   20.9%    1.00   -29.3%
V4a_stop20                     15.8%   19.0%    0.87   -33.2%
V4b_stop30                     19.1%   20.3%    0.96   -31.0%
V5_nofilter                    26.9%   25.0%    1.08   -40.3%
V6_half                        24.1%   21.8%    1.10   -30.7%
V7_nifty50_filter              12.8%   17.6%    0.78   -30.3%
NIFTYBEES_adjusted_buyhold     10.8%   15.1%    0.76   -36.3%
EW_universe_daily              15.1%   19.6%    0.82   -44.0%
NIFTY50_price_index             9.6%   16.8%    0.63   -38.4%

-- IS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    25.8%   19.6%    1.27   -21.0%
V3_live_nobuf                  23.1%   19.9%    1.15   -27.5%
V2_live                        19.6%   19.6%    1.01   -29.3%
V4a_stop20                     16.2%   17.9%    0.93   -33.2%
V4b_stop30                     18.4%   19.2%    0.98   -31.0%
V5_nofilter                    30.1%   23.4%    1.24   -40.3%
V6_half                        25.5%   20.4%    1.21   -28.3%
V7_nifty50_filter               8.0%   14.2%    0.62   -30.3%
NIFTYBEES_adjusted_buyhold     13.2%   16.5%    0.84   -36.3%
EW_universe_daily              15.6%   20.0%    0.83   -44.0%
NIFTY50_price_index            11.9%   18.4%    0.71   -38.4%

-- OOS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    22.7%   23.1%    1.00   -21.0%
V3_live_nobuf                  24.1%   22.9%    1.06   -22.9%
V2_live                        21.9%   23.0%    0.98   -25.5%
V4a_stop20                     15.2%   20.9%    0.78   -23.4%
V4b_stop30                     20.2%   22.2%    0.94   -25.4%
V5_nofilter                    21.2%   27.8%    0.83   -40.1%
V6_half                        21.6%   24.2%    0.93   -30.7%
V7_nifty50_filter              22.3%   22.6%    1.01   -25.5%
NIFTYBEES_adjusted_buyhold      6.6%   12.0%    0.59   -15.2%
EW_universe_daily              14.4%   18.8%    0.81   -22.7%
NIFTY50_price_index             5.4%   13.2%    0.46   -15.8%

-- activity --
                             rebalances  avg turnover stop-outs  days in cash
V1_baseline                         107          0.57         0           24%
V3_live_nobuf                       108          0.57         0           24%
V2_live                             108          0.46         0           24%
V4a_stop20                          108          0.47       227           24%
V4b_stop30                          108          0.45        64           24%
V5_nofilter                         108          0.47         0            1%
V6_half                             108          0.46         0            1%
V7_nifty50_filter                   108          0.33         0           56%

-- what the repaired NIFTYBEES filter sees: 525 BEAR days (24% of known-regime days), 1692 BULL days --
annualised adjusted ETF return on ETF-BEAR days: +18.6%; same-universe equal-weight: +26.6%
annualised adjusted ETF return on ETF-BULL days: +8.5%; same-universe equal-weight: +11.8%
^NSEI filter: 221 BEAR / 1004 BULL days; disagrees with repaired ETF regime on 18/1225 common days
annualised ^NSEI price-index return on ^NSEI-BEAR days: +53.2%; same-universe equal-weight: +39.6%

-- comparisons (rules fixed in advance) --
live rules vs old baseline                          DIFFERENT: IS CAGR differs by > 2 points; max drawdown > 3 points worse
28th trigger vs month-end (timing only)             DIFFERENT: IS CAGR differs by > 2 points; max drawdown > 3 points worse
buffer 30 vs none                                   turnover 0.46 vs 0.57 (+19% lower); CAGR -3.0 pts -> NOT SHOWN TO HELP
V4a_stop20 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points; IS CAGR falls by more than 2 points; OOS CAGR falls by more than 2 points
V4b_stop30 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points
V5_nofilter vs V2_live                              FULL CAGR +6.5 pts; FULL maxDD -11.1 pts; OOS CAGR -0.7 pts; OOS maxDD -14.6 pts
V6_half vs V2_live                                  FULL CAGR +3.7 pts; FULL maxDD -1.4 pts; OOS CAGR -0.4 pts; OOS maxDD -5.2 pts
V7_nifty50_filter vs V2_live                        FULL CAGR -7.6 pts; FULL maxDD -1.1 pts; OOS CAGR +0.4 pts; OOS maxDD -0.0 pts
```
