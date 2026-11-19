```
Stock universe: TejHQ adjusted NSE OHLC (dataset revision 0303d8c95b4519765a9d5556fd9c2d430f8f81d8), back-adjusted for splits, bonuses and dividends; raw exchange volume/turnover retained; mergers/demergers/rights/buybacks are not scaled; these and unclassified actions reset eligibility only from the ex-date, preserving earlier history. Held positions exposed to an unsupported action are liquidated at the prior session close after one-side transaction costs and their slots stay in cash until the next scheduled rebalance. The equal-weight control likewise exits affected constituents at prior close, charges the same per-side cost, and keeps the affected slots in cash for the event session without reweighting survivors. Performance benchmark: official NSE Indices NIFTY 500 gross TRI with dividends reinvested. NIFTYBEES remains the live regime filter and secondary price comparison. New listings and post-event histories are ineligible until 253 consecutive observed sessions exist. Corporate-action event details and reset decisions are in corporate_action_audit.csv and corporate_action_quarantine.csv. Benchmark: NSE NextApi raw NIFTYBEES OHLC, supplemented only with TejHQ raw NSE bhavcopy bars on validated NSE-calendar sessions absent from NextApi, split-adjusted for the 10:1 face-value split effective 2019-12-19 and cross-checked against TejHQ raw bars on common dates; the ETF is not dividend-adjusted. Session calendar: pandas_market_calendars==5.6.0 NSE holiday schedule, observed official NIFTY 50 index sessions, and the documented NSE special session on 2024-03-02 (Circular MSD/60677). The full calendar has 2480 sessions; all strategy and benchmark series use the same 2466 comparison sessions. Excluded 14 official sessions with zero stock bars across the loaded universe: 2016-10-30, 2017-10-19, 2018-11-07, 2019-10-27, 2020-02-01, 2020-11-14, 2021-11-04, 2022-10-24, 2023-11-12, 2024-03-02, 2024-05-18, 2024-11-01, 2025-10-21, 2026-02-01. The complete calendar and exclusion flags remain in pit_session_calendar_audit.csv. The comparison fails closed on any missing NIFTYBEES, NIFTY 50 or NIFTY 500 TRI bar on an included session; no benchmark prices are synthesized. Missing stock opens, eligibility and returns are never forward-filled; close carry-forward is used only to mark existing holdings to market.
Daily-return correlation split-adjusted NIFTYBEES vs official NSE NIFTY 50: 0.973
Stock source: TejHQ prices_adjusted NSE parquet | dataset revision 0303d8c95b4519765a9d5556fd9c2d430f8f81d8 | series EQ, BE, BZ (TejHQ published NSE coverage)
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

-- unsupported corporate-action handling --
Equal-weight control forced-exit events: 82 (prior-close liquidation; cash slot retained for the event session; no survivor reweighting).
  INFY.NS 2017-10-31: prior close 357.959961; cost 0.00000828; reason=unsupported_corporate_action
  COLPAL.NS 2017-12-18: prior close 871.684895; cost 0.00000835; reason=unsupported_corporate_action
  PEL.NS 2018-01-31: prior close 2437.499810; cost 0.00000868; reason=unsupported_corporate_action
  TATASTEEL.NS 2018-01-31: prior close 61.074690; cost 0.00000868; reason=unsupported_corporate_action
  BEL.NS 2018-02-08: prior close 44.494852; cost 0.00000822; reason=unsupported_corporate_action
  DHANI.NS 2018-02-09: prior close 236.272798; cost 0.00000844; reason=unsupported_corporate_action
  PIDILITIND.NS 2018-02-09: prior close 421.137575; cost 0.00000844; reason=unsupported_corporate_action
  HCLTECH.NS 2018-08-02: prior close 374.768822; cost 0.00000789; reason=unsupported_corporate_action
  KSCL.NS 2018-08-02: prior close 580.195788; cost 0.00000789; reason=unsupported_corporate_action
  TCS.NS 2018-08-14: prior close 1623.286006; cost 0.00000796; reason=unsupported_corporate_action
  JUSTDIAL.NS 2018-10-11: prior close 478.750000; cost 0.00000681; reason=unsupported_corporate_action
  LT.NS 2018-10-12: prior close 1090.786846; cost 0.00000670; reason=unsupported_corporate_action
  MPHASIS.NS 2018-10-24: prior close 866.644191; cost 0.00000662; reason=unsupported_corporate_action
  NATIONALUM.NS 2018-10-25: prior close 43.077205; cost 0.00000674; reason=unsupported_corporate_action
  BHEL.NS 2018-11-05: prior close 69.232649; cost 0.00000730; reason=unsupported_corporate_action
  BOSCHLTD.NS 2018-12-20: prior close 17862.324284; cost 0.00000750; reason=unsupported_corporate_action
  IOC.NS 2018-12-21: prior close 57.996862; cost 0.00000755; reason=unsupported_corporate_action
  ONGC.NS 2019-01-03: prior close 93.425585; cost 0.00000747; reason=unsupported_corporate_action
  NMDC.NS 2019-01-17: prior close 20.010451; cost 0.00000756; reason=unsupported_corporate_action
  AJANTPHARM.NS 2019-02-11: prior close 588.374807; cost 0.00000694; reason=unsupported_corporate_action
  COALINDIA.NS 2019-02-14: prior close 112.422155; cost 0.00000679; reason=unsupported_corporate_action
  TECHM.NS 2019-03-05: prior close 642.899988; cost 0.00000711; reason=unsupported_corporate_action
  IDEA.NS 2019-03-29: prior close 29.000000; cost 0.00000762; reason=unsupported_corporate_action
  BALRAMCHIN.NS 2019-04-16: prior close 131.055295; cost 0.00000774; reason=unsupported_corporate_action
  BHARTIARTL.NS 2019-04-23: prior close 336.038532; cost 0.00000751; reason=unsupported_corporate_action
  ADANIPORTS.NS 2019-06-20: prior close 389.587766; cost 0.00000685; reason=unsupported_corporate_action
  WIPRO.NS 2019-06-20: prior close 133.462383; cost 0.00000685; reason=unsupported_corporate_action
  ABREL.NS 2019-10-11: prior close 859.289700; cost 0.00000624; reason=unsupported_corporate_action
  DHANI.NS 2019-12-18: prior close 158.882967; cost 0.00000646; reason=unsupported_corporate_action
  PEL.NS 2019-12-30: prior close 1472.708308; cost 0.00000658; reason=unsupported_corporate_action
  COFORGE.NS 2020-03-11: prior close 308.707140; cost 0.00000556; reason=unsupported_corporate_action
  GRANULES.NS 2020-03-19: prior close 137.785873; cost 0.00000454; reason=unsupported_corporate_action
  RELIANCE.NS 2020-05-13: prior close 721.018077; cost 0.00000480; reason=unsupported_corporate_action
  ABFRL.NS 2020-06-30: prior close 127.400000; cost 0.00000569; reason=unsupported_corporate_action
  JUSTDIAL.NS 2020-07-02: prior close 398.400000; cost 0.00000574; reason=unsupported_corporate_action
  SHRIRAMFIN.NS 2020-07-09: prior close 135.569508; cost 0.00000589; reason=unsupported_corporate_action
  M&MFIN.NS 2020-07-22: prior close 204.340368; cost 0.00000593; reason=unsupported_corporate_action
  NESTLEIND.NS 2020-10-29: prior close 805.414199; cost 0.00000651; reason=unsupported_corporate_action
  AJANTPHARM.NS 2020-11-12: prior close 962.436100; cost 0.00000693; reason=unsupported_corporate_action
  NTPC.NS 2020-11-12: prior close 73.831880; cost 0.00000693; reason=unsupported_corporate_action
  NMDC.NS 2020-11-20: prior close 22.821971; cost 0.00000723; reason=unsupported_corporate_action
  TCS.NS 2020-11-26: prior close 2313.383368; cost 0.00000731; reason=unsupported_corporate_action
  WIPRO.NS 2020-12-10: prior close 163.827334; cost 0.00000799; reason=unsupported_corporate_action
  LTF.NS 2021-01-21: prior close 97.530754; cost 0.00000853; reason=unsupported_corporate_action
  GAIL.NS 2021-01-27: prior close 68.842736; cost 0.00000830; reason=unsupported_corporate_action
  NATIONALUM.NS 2021-02-05: prior close 38.893112; cost 0.00000882; reason=unsupported_corporate_action
  AARTIDRUGS.NS 2021-03-30: prior close 704.495393; cost 0.00000861; reason=unsupported_corporate_action
  BHARTIARTL.NS 2021-09-27: prior close 713.678111; cost 0.00001092; reason=unsupported_corporate_action
  INDHOTEL.NS 2021-11-11: prior close 212.133597; cost 0.00001160; reason=unsupported_corporate_action
  TCS.NS 2022-02-22: prior close 3225.776540; cost 0.00001020; reason=unsupported_corporate_action
  GAIL.NS 2022-04-21: prior close 94.911349; cost 0.00001089; reason=unsupported_corporate_action
  INDIAMART.NS 2022-05-10: prior close 2075.266354; cost 0.00001012; reason=unsupported_corporate_action
  ZYDUSLIFE.NS 2022-06-01: prior close 366.728039; cost 0.00001018; reason=unsupported_corporate_action
  BSOFT.NS 2022-07-14: prior close 321.143151; cost 0.00000963; reason=unsupported_corporate_action
  SUZLON.NS 2022-10-03: prior close 8.700000; cost 0.00001065; reason=unsupported_corporate_action
  TANLA.NS 2022-10-21: prior close 763.523930; cost 0.00001105; reason=unsupported_corporate_action
  PNBHOUSING.NS 2023-04-05: prior close 533.990333; cost 0.00000990; reason=unsupported_corporate_action
  WIPRO.NS 2023-06-16: prior close 179.858911; cost 0.00001136; reason=unsupported_corporate_action
  RELIANCE.NS 2023-07-20: prior close 1399.051844; cost 0.00001203; reason=unsupported_corporate_action
  INDIAMART.NS 2023-08-25: prior close 2958.145977; cost 0.00001254; reason=unsupported_corporate_action
  LT.NS 2023-09-12: prior close 2817.572019; cost 0.00001345; reason=unsupported_corporate_action
  BSE.NS 2023-09-14: prior close 428.556399; cost 0.00001320; reason=unsupported_corporate_action
  TCS.NS 2023-11-24: prior close 3189.070982; cost 0.00001344; reason=unsupported_corporate_action
  GRASIM.NS 2024-01-10: prior close 2042.333381; cost 0.00001550; reason=unsupported_corporate_action
  SAMMAANCAP.NS 2024-02-01: prior close 219.686749; cost 0.00001636; reason=unsupported_corporate_action
  BAJAJ-AUTO.NS 2024-02-29: prior close 7811.924418; cost 0.00001667; reason=unsupported_corporate_action
  TATACONSUM.NS 2024-07-26: prior close 1204.406836; cost 0.00002015; reason=unsupported_corporate_action
  AUROPHARMA.NS 2024-07-30: prior close 1399.745699; cost 0.00002085; reason=unsupported_corporate_action
  INDUSTOWER.NS 2024-08-09: prior close 401.875648; cost 0.00001994; reason=unsupported_corporate_action
  UPL.NS 2024-11-26: prior close 557.993014; cost 0.00001899; reason=unsupported_corporate_action
  ITC.NS 2025-01-06: prior close 443.889471; cost 0.00001940; reason=unsupported_corporate_action
  SIEMENS.NS 2025-04-07: prior close 4904.051467; cost 0.00001725; reason=unsupported_corporate_action
  INOXWIND.NS 2025-07-29: prior close 157.250000; cost 0.00001948; reason=unsupported_corporate_action
  TMPV.NS 2025-10-14: prior close 655.313965; cost 0.00002009; reason=unsupported_corporate_action
  INFY.NS 2025-11-14: prior close 1475.346563; cost 0.00002057; reason=unsupported_corporate_action
  ADANIENT.NS 2025-11-17: prior close 2515.675193; cost 0.00002071; reason=unsupported_corporate_action
  HINDUNILVR.NS 2025-12-05: prior close 2413.011929; cost 0.00002008; reason=unsupported_corporate_action
  AUROPHARMA.NS 2026-04-17: prior close 1386.500000; cost 0.00002067; reason=unsupported_corporate_action
  VEDL.NS 2026-04-30: prior close 758.508311; cost 0.00002120; reason=unsupported_corporate_action
  WIPRO.NS 2026-06-05: prior close 202.012864; cost 0.00002130; reason=unsupported_corporate_action
  BAJAJ-AUTO.NS 2026-06-24: prior close 10025.000000; cost 0.00002167; reason=unsupported_corporate_action
  OLAELEC.NS 2026-10-13: prior close 35.680000; cost 0.00002113; reason=unsupported_corporate_action

-- FULL --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    19.3%   20.9%    0.95   -31.8%
V3_live_nobuf                  15.4%   20.9%    0.79   -36.5%
V2_live                        15.4%   20.8%    0.79   -34.7%
V4a_stop20                     13.7%   19.1%    0.77   -36.4%
V4b_stop30                     15.0%   20.2%    0.80   -35.5%
V5_nofilter                    20.5%   24.7%    0.88   -45.6%
V6_half                        18.1%   21.7%    0.88   -35.4%
V7_nifty50_filter              13.1%   20.5%    0.70   -42.7%
NIFTYBEES_adjusted_buyhold     10.8%   15.1%    0.76   -36.3%
EW_universe_daily              11.6%   20.2%    0.65   -56.4%
NIFTY50_price_index             9.6%   16.7%    0.63   -38.4%
NIFTY500_TRI_buyhold           12.0%   16.6%    0.77   -38.1%

-- IS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    16.3%   19.8%    0.86   -31.8%
V3_live_nobuf                  10.6%   20.0%    0.61   -36.5%
V2_live                        12.2%   19.7%    0.68   -34.7%
V4a_stop20                     10.9%   17.9%    0.67   -36.4%
V4b_stop30                     12.0%   19.2%    0.69   -35.5%
V5_nofilter                    20.9%   23.5%    0.93   -45.6%
V6_half                        16.7%   20.5%    0.85   -35.4%
V7_nifty50_filter               8.7%   19.2%    0.53   -42.7%
NIFTYBEES_adjusted_buyhold     13.2%   16.5%    0.83   -36.3%
EW_universe_daily               8.5%   20.9%    0.50   -56.4%
NIFTY50_price_index            11.9%   18.4%    0.70   -38.4%
NIFTY500_TRI_buyhold           12.9%   17.8%    0.77   -38.1%

-- OOS --
                                CAGR     vol  Sharpe    maxDD
V1_baseline                    24.9%   22.8%    1.09   -23.3%
V3_live_nobuf                  24.7%   22.5%    1.10   -24.0%
V2_live                        21.7%   22.6%    0.98   -29.2%
V4a_stop20                     19.0%   21.2%    0.93   -25.2%
V4b_stop30                     20.8%   22.0%    0.97   -29.0%
V5_nofilter                    19.6%   26.8%    0.81   -43.6%
V6_half                        20.7%   23.7%    0.91   -34.2%
V7_nifty50_filter              21.7%   22.6%    0.98   -29.2%
NIFTYBEES_adjusted_buyhold      6.6%   11.9%    0.59   -15.2%
EW_universe_daily              17.6%   18.7%    0.96   -22.8%
NIFTY50_price_index             5.4%   13.2%    0.47   -15.8%
NIFTY500_TRI_buyhold           10.4%   14.2%    0.77   -18.6%

-- activity --
                             rebalances  avg turnover stop-outs  days in cash
V1_baseline                         115          0.55         0           22%
V3_live_nobuf                       114          0.56         0           23%
V2_live                             114          0.44         0           23%
V4a_stop20                          112          0.45       225           23%
V4b_stop30                          114          0.43        75           23%
V5_nofilter                         116          0.44         0            0%
V6_half                             116          0.43         0            0%
V7_nifty50_filter                   113          0.45         0           27%

-- what the NSE-sourced NIFTYBEES filter sees: 507 BEAR days (23% of known-regime days), 1705 BULL days --
annualised adjusted ETF return on ETF-BEAR days: +15.8%; same-universe equal-weight: +22.7%
annualised adjusted ETF return on ETF-BULL days: +9.4%; same-universe equal-weight: +8.5%
^NSEI filter: 547 BEAR / 1665 BULL days; disagrees with NSE-sourced ETF regime on 42/2212 common days
annualised ^NSEI price-index return on ^NSEI-BEAR days: +16.9%; same-universe equal-weight: +22.2%

-- comparisons (rules fixed in advance) --
live rules vs old baseline                          DIFFERENT: IS CAGR differs by > 2 points; OOS CAGR differs by > 2 points
28th trigger vs month-end (timing only)             DIFFERENT: IS CAGR differs by > 2 points; max drawdown > 3 points worse
buffer 30 vs none                                   turnover 0.44 vs 0.56 (+20% lower); CAGR +0.1 pts -> BUFFER HELPS
V4a_stop20 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points; OOS CAGR falls by more than 2 points
V4b_stop30 vs V2_live                               NO: FULL max drawdown improves by < 5 points; OOS max drawdown improves by < 5 points
V5_nofilter vs V2_live                              FULL CAGR +5.0 pts; FULL maxDD -10.9 pts; OOS CAGR -2.1 pts; OOS maxDD -14.5 pts
V6_half vs V2_live                                  FULL CAGR +2.6 pts; FULL maxDD -0.7 pts; OOS CAGR -1.0 pts; OOS maxDD -5.1 pts
V7_nifty50_filter vs V2_live                        FULL CAGR -2.3 pts; FULL maxDD -8.0 pts; OOS CAGR +0.0 pts; OOS maxDD -0.0 pts
```
