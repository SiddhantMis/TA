```
=== Nifty 500 list, point-in-time top 200 by traded value: 467 stocks, months 2017-12-01 to 2026-09-01 (106), IS/OOS split 2023-08-09, hold 20, cost 0.3% round trip ===
CAGR / vol / Sharpe(rf=0) / max drawdown (month-end) ; last column = rough after-tax CAGR (FULL only)
eligible names per rebalance (avg): 197 -- point-in-time top 200 by trailing 126-day traded value

-- FULL (106 months) --
                          CAGR     vol  Sharpe    maxDD   after-tax
mom12_1                  28.3%   25.6%    1.11   -33.6%     25.5%
mom12_1+mkt              21.8%   20.1%    1.09   -21.0%     19.4%
mom6                     24.2%   26.9%    0.95   -31.2%     21.6%
mom6+mkt                 19.6%   21.3%    0.95   -24.6%     17.2%
nifty50                  10.5%   20.7%    0.59   -28.7%      9.6%
ew_universe              15.3%   20.8%    0.80   -37.2%

-- IS (69 months) --
                          CAGR     vol  Sharpe    maxDD
mom12_1                  29.3%   24.9%    1.17   -30.1%
mom12_1+mkt              20.8%   19.0%    1.10   -21.0%
mom6                     26.7%   26.8%    1.02   -31.2%
mom6+mkt                 17.1%   21.0%    0.86   -24.6%
nifty50                  13.1%   23.9%    0.64   -28.7%
ew_universe              14.5%   22.3%    0.73   -37.2%

-- OOS (37 months) --
                          CAGR     vol  Sharpe    maxDD
mom12_1                  26.6%   27.3%    1.00   -33.6%
mom12_1+mkt              23.7%   22.3%    1.07   -14.8%
mom6                     19.7%   27.3%    0.80   -26.4%
mom6+mkt                 24.3%   22.2%    1.09   -12.8%
nifty50                   5.9%   13.0%    0.50   -13.1%
ew_universe              16.9%   18.0%    0.96   -22.5%

-- avg names held / avg one-way turnover per rebalance (sum of |weight change|) --
mom12_1                 20.0    0.62
mom12_1+mkt             14.7    0.58
mom6                    20.0    0.76
mom6+mkt                14.7    0.68

-- excess return vs equal-weight universe, annualised, 95% interval (6-mo blocks) --
mom12_1               full  +11.9% [+3.0, +19.0]   OOS-only interval [-7.1, +20.4]
mom12_1+mkt           full   +5.3% [-4.4, +13.9]   OOS-only interval [-12.9, +20.2]
mom6                  full   +8.9% [-0.3, +17.2]   OOS-only interval [-13.4, +16.3]
mom6+mkt              full   +3.6% [-7.7, +14.0]   OOS-only interval [-14.5, +24.4]

-- calendar-year returns --
year         mom12_1   mom12_1+mkt          mom6      mom6+mkt       nifty50   ew_universe
2017            8.6%          8.6%          6.0%          6.0%          1.2%          4.3%
2018           -6.7%        -12.7%         -4.8%        -13.8%          5.2%        -10.2%
2019           12.1%          0.3%         15.4%         -1.1%         13.4%          0.7%
2020           42.1%         42.7%         51.5%         41.3%         23.8%         27.2%
2021           72.8%         72.8%         77.2%         77.2%         19.0%         44.8%
2022           10.4%          2.1%         -1.4%         -1.1%          5.8%          3.0%
2023           88.5%         64.3%         73.9%         52.3%         19.9%         47.8%
2024           39.3%         39.3%         40.1%         40.1%          9.7%         22.7%
2025           -5.0%         11.2%        -17.3%          2.6%         12.0%          7.0%
2026           17.8%         -6.1%          9.1%         -1.1%        -12.7%          1.5%

-- verdicts (rule fixed in advance) --
mom12_1       FAIL: OOS drawdown > 5 pts worse than Nifty 50
mom12_1+mkt   FAIL: full-period excess vs equal-weight universe interval includes 0
mom6          FAIL: OOS drawdown > 5 pts worse than Nifty 50; full-period excess vs equal-weight universe interval includes 0
mom6+mkt      FAIL: full-period excess vs equal-weight universe interval includes 0
```
