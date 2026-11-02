```
Stock universe: TejHQ adjusted NSE OHLC (dataset revision f7fa8343af92cf1289f3960c9267ed23fa9dbbcb), back-adjusted for splits, bonuses and dividends; raw exchange volume/turnover retained; mergers/demergers/rights/buybacks are not scaled. Benchmark: NSE NextApi raw NIFTYBEES OHLC, supplemented only with TejHQ raw NSE bhavcopy bars on validated NSE-calendar sessions absent from NextApi, split-adjusted for the 10:1 face-value split effective 2019-12-19 and cross-checked against TejHQ raw bars on common dates; the ETF is not dividend-adjusted. Session calendar: pandas_market_calendars==5.6.0 NSE holiday schedule, observed official NIFTY 50 index sessions, and the documented NSE special session on 2024-03-02 (Circular MSD/60677). The full calendar has 2480 sessions; all strategy and benchmark series use the same 2466 comparison sessions. Excluded 14 official sessions with zero stock bars across the loaded universe: 2016-10-30, 2017-10-19, 2018-11-07, 2019-10-27, 2020-02-01, 2020-11-14, 2021-11-04, 2022-10-24, 2023-11-12, 2024-03-02, 2024-05-18, 2024-11-01, 2025-10-21, 2026-02-01. The complete calendar and exclusion flags remain in pit_session_calendar_audit.csv. The comparison fails closed on any missing NIFTYBEES or NIFTY 50 bar on an included session; no benchmark prices are synthesized. Missing stock opens, eligibility and returns are never forward-filled; close carry-forward is used only to mark existing holdings to market.
Daily-return correlation split-adjusted NIFTYBEES vs official NSE NIFTY 50: 0.973
Stock source: TejHQ prices_adjusted NSE parquet | dataset revision f7fa8343af92cf1289f3960c9267ed23fa9dbbcb | series EQ, BE, BZ (TejHQ published NSE coverage)
Adjustment scope: splits, bonuses and dividends; mergers, demergers, rights and buybacks are not scaled
Data quality status: NOT DECISION-GRADE — 27 active-window symbols lack a full 253-bar history; the provider does not scale mergers/demergers/rights/buybacks
Portfolio rules: 951 loaded price histories for PIT Nifty 500, daily engine 2017-10-23 to 2026-10-13, IS/OOS split 2023-08-18, cost 0.3% round trip, cash 0%
PIT calendar: 1151 intervals / 970 symbols; source coverage through 2026-10-13; source categories {'press_release': 632, 'snapshot_floor': 516, 'merger': 2, 'snapshot': 1}
PIT active-member count during test: 498–507 (nominal index size 500; source documents historical count drift and a 499-name 2026 snapshot)
Price-history coverage across full calendar: 920/970 symbols loaded; 50 missing/unusable
Missing histories overlapping test window: 27/878 active-window symbols; 23 additional missing symbols have no overlap with this backtest window
Active-window missing load outcomes: {'insufficient_history': 22, 'no_history': 5}; first 20: ['BAGMANE:no_history(0 bars)', 'BHARATCOAL:insufficient_history(181 bars)', 'BIRET:no_history(0 bars)', 'CANHLIFE:insufficient_history(242 bars)', 'CLEANMAX:insufficient_history(152 bars)', 'CMPDI:insufficient_history(134 bars)', 'EMBASSY:no_history(0 bars)', 'EMMVEE:insufficient_history(223 bars)', 'FRACTAL:insufficient_history(162 bars)', 'GROWW:insufficient_history(227 bars)', 'ICICIAMC:insufficient_history(200 bars)', 'LENSKART:insufficient_history(229 bars)', 'LGEINDIA:insufficient_history(245 bars)', 'MEESHO:insufficient_history(207 bars)', 'PINELABS:insufficient_history(225 bars)', 'PIRAMALFIN:insufficient_history(230 bars)', 'PWL:insufficient_history(223 bars)', 'RUBICON:insufficient_history(243 bars)', 'SGPC:no_history(0 bars)', 'SHTV:no_history(0 bars)']
Daily active-member bars covered: min 98.6%, p10 98.8%, median 100.0%; 0.0% of sessions below 90% coverage
Zero active-member-coverage sessions: 0; dates: []
Zero-stock-bar sessions: 0; dates: []
Worst coverage sessions (date: active bars/expected, coverage, all loaded-symbol bars): 2017-10-23: 496/503 (98.6%), all-symbol bars=708; 2017-10-24: 496/503 (98.6%), all-symbol bars=706; 2017-10-25: 496/503 (98.6%), all-symbol bars=707; 2017-10-26: 496/503 (98.6%), all-symbol bars=707; 2017-10-27: 496/503 (98.6%), all-symbol bars=707; 2017-10-30: 496/503 (98.6%), all-symbol bars=709; 2017-10-31: 496/503 (98.6%), all-symbol bars=707; 2017-11-01: 496/503 (98.6%), all-symbol bars=707
Missing opens are never forward-filled; close carry-forward is used only to value existing holdings, while eligibility, returns and stops use observed closes.
Stale-close diagnostics: 0 held-position stale-close days across variants; maximum consecutive stale sessions=0.
Benchmark: NSE NextApi raw NIFTYBEES OHLC, supplemented only by TejHQ raw NSE bhavcopy bars on validated NSE-calendar sessions absent from NextApi; common dates reconciled | 2466 observed bars; max abs daily move 10.16%; stale official sessions=0 (max consecutive 0)
Session calendar / regime diagnostic: pandas_market_calendars==5.6.0 NSE holiday calendar + observed NIFTY 50 index sessions + NSE Circular MSD/60677 (2024-03-02) | 2466 bars; max abs daily move 12.98%
NIFTY50_price_index is an official NSE PRICE index (not a total-return index).
CAGR / vol / Sharpe(rf=0) / max drawdown (daily)

-- FULL --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    20.3%   20.9%    0.99   -28.4%
V3_live_nobuf                  17.1%   21.0%    0.86   -34.6%
V2_live                        17.8%   20.8%    0.89   -31.5%
V4a_stop20                     15.3%   19.1%    0.84   -33.4%
V4b_stop30                     16.8%   20.2%    0.87   -32.0%
V5_nofilter                    22.8%   24.9%    0.95   -46.0%
V6_half                        20.4%   21.8%    0.96   -34.7%
V7_nifty50_filter              14.9%   20.5%    0.78   -44.1%
NIFTYBEES_adjusted_buyhold     10.8%   15.1%    0.76   -36.3%
EW_universe_daily              11.6%   20.1%    0.65   -55.8%
NIFTY50_price_index             9.6%   16.7%    0.63   -38.4%

-- IS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    16.9%   19.9%    0.88   -28.4%
V3_live_nobuf                  12.4%   20.1%    0.68   -34.6%
V2_live                        13.7%   19.8%    0.75   -31.5%
V4a_stop20                     12.0%   18.0%    0.72   -33.4%
V4b_stop30                     13.4%   19.2%    0.75   -32.0%
V5_nofilter                    23.0%   23.8%    0.99   -46.0%
V6_half                        18.5%   20.7%    0.92   -34.7%
V7_nifty50_filter               9.4%   19.2%    0.57   -44.1%
NIFTYBEES_adjusted_buyhold     13.2%   16.5%    0.83   -36.3%
EW_universe_daily               8.8%   20.8%    0.51   -55.8%
NIFTY50_price_index            11.9%   18.4%    0.70   -38.4%

-- OOS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    26.8%   22.6%    1.16   -20.5%
V3_live_nobuf                  26.4%   22.5%    1.16   -23.0%
V2_live                        25.7%   22.6%    1.13   -25.6%
V4a_stop20                     21.6%   21.0%    1.04   -21.8%
V4b_stop30                     23.2%   21.8%    1.07   -25.9%
V5_nofilter                    22.5%   26.9%    0.89   -40.9%
V6_half                        24.0%   23.7%    1.03   -31.0%
V7_nifty50_filter              25.7%   22.6%    1.13   -25.6%
NIFTYBEES_adjusted_buyhold      6.6%   11.9%    0.59   -15.2%
EW_universe_daily              17.0%   18.6%    0.94   -22.7%
NIFTY50_price_index             5.4%   13.2%    0.47   -15.8%

-- activity --
                             rebalances  avg turnover stop-outs  days in cash
V1_baseline                         108          0.58         0           22%
V3_live_nobuf                       108          0.58         0           23%
V2_live                             108          0.47         0           23%
V4a_stop20                          108          0.47       228           23%
V4b_stop30                          108          0.46        75           23%
V5_nofilter                         108          0.47         0            0%
V6_half                             108          0.46         0            0%
V7_nifty50_filter                   108          0.48         0           27%

-- what the NSE-sourced NIFTYBEES filter sees: 507 BEAR days (23% of known-regime days), 1705 BULL days --
annualised adjusted ETF return on ETF-BEAR days: +15.8%; same-universe equal-weight: +22.2%
annualised adjusted ETF return on ETF-BULL days: +9.4%; same-universe equal-weight: +8.7%
^NSEI filter: 547 BEAR / 1665 BULL days; disagrees with NSE-sourced ETF regime on 42/2212 common days
annualised ^NSEI price-index return on ^NSEI-BEAR days: +16.9%; same-universe equal-weight: +21.5%

-- comparisons (rules fixed in advance) --
live rules vs old baseline                          DIFFERENT: IS CAGR differs by > 2 points; max drawdown > 3 points worse
28th trigger vs month-end (timing only)             DIFFERENT: IS CAGR differs by > 2 points; max drawdown > 3 points worse
buffer 30 vs none                                   turnover 0.47 vs 0.58 (+19% lower); CAGR +0.6 pts -> NOT SHOWN TO HELP
V4a_stop20 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points; OOS CAGR falls by more than 2 points
V4b_stop30 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points; OOS CAGR falls by more than 2 points
V5_nofilter vs V2_live                              FULL CAGR +5.0 pts; FULL maxDD -14.5 pts; OOS CAGR -3.2 pts; OOS maxDD -15.3 pts
V6_half vs V2_live                                  FULL CAGR +2.6 pts; FULL maxDD -3.2 pts; OOS CAGR -1.6 pts; OOS maxDD -5.4 pts
V7_nifty50_filter vs V2_live                        FULL CAGR -2.9 pts; FULL maxDD -12.6 pts; OOS CAGR +0.0 pts; OOS maxDD +0.0 pts
```
