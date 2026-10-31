```
=== watchlist (48): 48 stocks, months 2017-12-01 to 2026-09-01 (106), IS/OOS split 2023-08-09, hold 20, cost 0.3% round trip ===
CAGR / vol / Sharpe(rf=0) / max drawdown (month-end) ; last column = rough after-tax CAGR (FULL only)

-- FULL (106 months) --
                          CAGR     vol  Sharpe    maxDD   after-tax
mom12_1                  24.7%   18.5%    1.30   -17.7%     22.1%
mom12_1+mkt              20.8%   16.0%    1.27   -28.2%     18.4%
mom6                     26.1%   20.1%    1.26   -22.6%     23.4%
mom6+mkt                 22.1%   17.9%    1.21   -32.0%     19.6%
nifty50                  10.5%   20.7%    0.59   -28.7%      9.6%
ew_universe              20.2%   22.8%    0.93   -34.8%

-- IS (69 months) --
                          CAGR     vol  Sharpe    maxDD
mom12_1                  27.3%   19.1%    1.37   -17.7%
mom12_1+mkt              19.6%   16.5%    1.17   -28.2%
mom6                     27.5%   21.5%    1.24   -22.6%
mom6+mkt                 19.9%   19.3%    1.04   -32.0%
nifty50                  13.1%   23.9%    0.64   -28.7%
ew_universe              22.9%   25.0%    0.96   -34.8%

-- OOS (37 months) --
                          CAGR     vol  Sharpe    maxDD
mom12_1                  20.1%   17.6%    1.13   -15.0%
mom12_1+mkt              23.0%   15.3%    1.44    -7.9%
mom6                     23.5%   17.5%    1.30   -11.6%
mom6+mkt                 26.2%   15.1%    1.63    -6.5%
nifty50                   5.9%   13.0%    0.50   -13.1%
ew_universe              15.4%   18.2%    0.88   -22.5%

-- avg names held / avg one-way turnover per rebalance (sum of |weight change|) --
mom12_1                 18.4    0.37
mom12_1+mkt             14.4    0.40
mom6                    18.4    0.40
mom6+mkt                14.4    0.44

-- excess return vs equal-weight universe, annualised, 95% interval (6-mo blocks) --
mom12_1               full   +2.8% [-4.4, +9.2]   OOS-only interval [-6.5, +12.1]
mom12_1+mkt           full   -0.9% [-11.6, +7.5]   OOS-only interval [-10.9, +16.7]
mom6                  full   +4.1% [-4.3, +12.2]   OOS-only interval [-5.3, +16.4]
mom6+mkt              full   +0.4% [-11.7, +10.2]   OOS-only interval [-9.6, +20.7]

-- calendar-year returns --
year         mom12_1   mom12_1+mkt          mom6      mom6+mkt       nifty50   ew_universe
2017            2.4%          2.4%          4.6%          4.6%          1.2%          2.9%
2018          -10.3%        -15.1%        -13.5%        -18.2%          5.2%         -3.5%
2019           18.5%          2.0%         14.8%         -1.1%         13.4%         10.2%
2020           37.8%         35.1%         38.2%         35.5%         23.8%         30.8%
2021           86.3%         86.3%         96.5%         96.5%         19.0%         60.4%
2022           18.4%         14.4%         18.5%         15.1%          5.8%         21.0%
2023           68.2%         52.3%         69.8%         53.8%         19.9%         51.7%
2024           23.4%         23.4%         30.7%         30.7%          9.7%         12.2%
2025            8.9%         13.6%          9.1%         13.9%         12.0%          6.9%
2026           -5.7%         -2.7%         -4.4%         -2.1%        -12.7%          0.6%

-- verdicts (rule fixed in advance) --
mom12_1       FAIL: full-period excess vs equal-weight universe interval includes 0
mom12_1+mkt   FAIL: IS CAGR <= ew_universe; full-period excess vs equal-weight universe interval includes 0
mom6          FAIL: full-period excess vs equal-weight universe interval includes 0
mom6+mkt      FAIL: IS CAGR <= ew_universe; full-period excess vs equal-weight universe interval includes 0

=== Nifty 200 (today's list): 191 stocks, months 2017-12-01 to 2026-09-01 (106), IS/OOS split 2023-08-09, hold 20, cost 0.3% round trip ===
CAGR / vol / Sharpe(rf=0) / max drawdown (month-end) ; last column = rough after-tax CAGR (FULL only)

-- FULL (106 months) --
                          CAGR     vol  Sharpe    maxDD   after-tax
mom12_1                  34.5%   24.3%    1.36   -29.6%     31.4%
mom12_1+mkt              30.2%   18.5%    1.53   -17.5%     27.3%
mom6                     33.1%   26.0%    1.24   -30.5%     30.0%
mom6+mkt                 28.8%   20.0%    1.37   -18.0%     26.0%
nifty50                  10.5%   20.7%    0.59   -28.7%      9.6%
ew_universe              22.3%   20.2%    1.11   -29.2%

-- IS (69 months) --
                          CAGR     vol  Sharpe    maxDD
mom12_1                  35.4%   24.2%    1.39   -29.6%
mom12_1+mkt              25.5%   17.4%    1.40   -17.5%
mom6                     35.8%   26.9%    1.29   -30.5%
mom6+mkt                 24.2%   20.2%    1.18   -18.0%
nifty50                  13.1%   23.9%    0.64   -28.7%
ew_universe              22.7%   21.8%    1.06   -29.2%

-- OOS (37 months) --
                          CAGR     vol  Sharpe    maxDD
mom12_1                  32.8%   24.8%    1.28   -24.3%
mom12_1+mkt              39.5%   20.5%    1.74    -7.1%
mom6                     28.1%   24.6%    1.13   -20.8%
mom6+mkt                 37.8%   19.8%    1.73    -8.4%
nifty50                   5.9%   13.0%    0.50   -13.1%
ew_universe              21.4%   17.0%    1.23   -19.7%

-- avg names held / avg one-way turnover per rebalance (sum of |weight change|) --
mom12_1                 19.9    0.57
mom12_1+mkt             14.7    0.53
mom6                    19.9    0.69
mom6+mkt                14.7    0.63

-- excess return vs equal-weight universe, annualised, 95% interval (6-mo blocks) --
mom12_1               full  +10.6% [+2.9, +20.0]   OOS-only interval [-4.1, +22.1]
mom12_1+mkt           full   +6.0% [-4.1, +16.5]   OOS-only interval [-3.5, +26.5]
mom6                  full  +10.0% [+2.2, +19.3]   OOS-only interval [-10.5, +18.5]
mom6+mkt              full   +5.1% [-5.7, +16.7]   OOS-only interval [-8.0, +26.9]

-- calendar-year returns --
year         mom12_1   mom12_1+mkt          mom6      mom6+mkt       nifty50   ew_universe
2017            4.5%          4.5%          4.7%          4.7%          1.2%          4.0%
2018            0.4%         -9.8%         -3.4%        -15.5%          5.2%         -6.1%
2019           16.6%          3.6%         22.0%          4.8%         13.4%          7.3%
2020           43.0%         48.6%         46.6%         42.1%         23.8%         35.3%
2021           68.6%         68.6%         81.4%         81.4%         19.0%         55.7%
2022           27.1%         11.8%         36.3%         26.1%          5.8%         17.2%
2023          111.1%         86.6%         89.7%         68.4%         19.9%         55.4%
2024           68.4%         68.4%         58.4%         58.4%          9.7%         32.1%
2025            6.3%         20.9%          2.8%         16.2%         12.0%         12.8%
2026           -3.2%         -0.8%         -9.8%         -0.0%        -12.7%         -1.4%

-- verdicts (rule fixed in advance) --
mom12_1       FAIL: OOS drawdown > 5 pts worse than Nifty 50
mom12_1+mkt   FAIL: full-period excess vs equal-weight universe interval includes 0
mom6          FAIL: OOS drawdown > 5 pts worse than Nifty 50
mom6+mkt      FAIL: full-period excess vs equal-weight universe interval includes 0
```
