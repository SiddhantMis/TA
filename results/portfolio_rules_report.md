```
Portfolio rules: 467 stocks, daily engine 2017-11-08 to 2026-10-30, IS/OOS split 2023-09-05, cost 0.3% round trip, cash 0%
CAGR / vol / Sharpe(rf=0) / max drawdown (daily)

-- FULL --
                      CAGR     vol  Sharpe    maxDD
V1_baseline          24.7%   20.9%    1.16   -21.0%
V3_live_nobuf        22.5%   21.3%    1.06   -27.5%
V2_live              19.2%   21.2%    0.94   -29.3%
V4a_stop20           14.8%   19.2%    0.82   -33.2%
V4b_stop30           17.7%   20.5%    0.90   -31.0%
V5_nofilter          26.7%   25.0%    1.07   -40.3%
V6_half              23.4%   22.0%    1.06   -30.7%
Nifty50_buyhold      10.8%  304.3%    0.34   -89.9%
EW_universe_daily    15.1%   19.6%    0.82   -44.0%

-- IS --
                      CAGR     vol  Sharpe    maxDD
V1_baseline          26.0%   19.6%    1.28   -21.0%
V3_live_nobuf        23.2%   19.9%    1.15   -27.5%
V2_live              19.4%   19.6%    1.00   -29.3%
V4a_stop20           15.8%   17.9%    0.91   -33.2%
V4b_stop30           17.9%   19.1%    0.96   -31.0%
V5_nofilter          29.8%   23.4%    1.23   -40.3%
V6_half              25.2%   20.4%    1.20   -28.3%
Nifty50_buyhold      13.2%  377.4%    0.41   -89.9%
EW_universe_daily    15.6%   20.0%    0.82   -44.0%

-- OOS --
                      CAGR     vol  Sharpe    maxDD
V1_baseline          22.2%   23.0%    0.99   -21.0%
V3_live_nobuf        21.3%   23.7%    0.93   -22.9%
V2_live              18.8%   23.8%    0.85   -25.5%
V4a_stop20           13.1%   21.5%    0.68   -23.4%
V4b_stop30           17.4%   22.9%    0.82   -25.4%
V5_nofilter          21.3%   27.8%    0.83   -40.1%
V6_half              20.0%   24.8%    0.86   -30.7%
Nifty50_buyhold       6.6%   12.0%    0.59   -15.2%
EW_universe_daily    14.4%   18.8%    0.81   -22.7%

-- activity --
                   rebalances  avg turnover stop-outs  days in cash
V1_baseline               107          0.57         0           24%
V3_live_nobuf             105          0.58         0           24%
V2_live                   105          0.47         0           24%
V4a_stop20                105          0.47       233           24%
V4b_stop30                105          0.46        65           24%
V5_nofilter               105          0.48         0            1%
V6_half                   105          0.47         0            1%

-- what the market filter sees: 522 BEAR days (24% of the period), 1694 BULL days --
annualised return on BEAR days:  Nifty50 +265.4%   same-universe equal-weight +28.5%
annualised return on BULL days:  Nifty50 -23.2%   same-universe equal-weight +11.3%

-- comparisons (rules fixed in advance) --
live rules vs old baseline                  DIFFERENT: IS CAGR differs by > 2 points; OOS CAGR differs by > 2 points; max drawdown > 3 points worse
28th trigger vs month-end (timing only)     DIFFERENT: IS CAGR differs by > 2 points; max drawdown > 3 points worse
buffer 30 vs none                           turnover 0.47 vs 0.58 (+18% lower); CAGR -3.4 pts -> NOT SHOWN TO HELP
V4a_stop20 vs V2_live                       NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points; IS CAGR falls by more than 2 points; OOS CAGR falls by more than 2 points
V4b_stop30 vs V2_live                       NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points
V5_nofilter vs V2_live                      CAGR +7.6 pts, max drawdown -11.1 pts (full period)
V6_half vs V2_live                          CAGR +4.2 pts, max drawdown -1.4 pts (full period)
```
