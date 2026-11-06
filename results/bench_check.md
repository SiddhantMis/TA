Primary benchmark source: NSE NextApi raw NIFTYBEES with official-session TejHQ bhavcopy supplements
Requested range: 2016-10-13 through 2026-10-13
NSE bars: 2480; max absolute daily return: 10.16%
TejHQ cross-check bars: 2466; max abs daily move: 10.16%
NSE / TejHQ reconciliation: {'nse_api_bars': 2477, 'tejhq_bars': 2466, 'common_bars': 2463, 'nse_api_only_bars': 14, 'tejhq_only_bars': 3, 'common_fraction_of_nse': 0.9943480016148567, 'common_fraction_of_tejhq': 0.9987834549878345, 'max_abs_ohlc_diff': 0.0, 'max_rel_ohlc_diff': 0.0, 'nse_api_only_dates': ['2016-10-30', '2017-10-19', '2018-11-07', '2019-10-27', '2020-02-01', '2020-11-14', '2021-11-04', '2022-10-24', '2023-11-12', '2024-03-02', '2024-05-18', '2024-11-01', '2025-10-21', '2026-02-01'], 'tejhq_only_dates': ['2016-10-13', '2020-05-05', '2020-08-13']}
TejHQ-only bars accepted as supplements on validated NSE-calendar sessions: ['2016-10-13', '2020-05-05', '2020-08-13']
NSE session calendar: pandas_market_calendars==5.6.0 plus observed NSE NIFTY 50 sessions (2480 sessions)
NSE-calendar sessions missing NIFTY 50 index rows: 1; index coverage=99.960%; dates=['2024-03-02']
Official NSE NIFTY 50 index rows: 2479; source=NSE historicalOR/indicesHistory (NIFTY 50)
Daily-return correlation of split-adjusted NIFTYBEES vs available NIFTY 50 index rows: 0.9726
Corporate action: 10:1 face-value split effective 2019-12-19; pre-ex-date OHLC x0.1, volume x10.
Adjustment record: [{'ex_date': '2019-12-19', 'price_factor': 0.1, 'volume_factor': 10.0, 'source': 'https://archives.nseindia.com/content/circulars/CML42873.pdf'}]
== NSE raw exchange prices around the split
  2019-12-18 close=1292.54 volume=21946
  2019-12-19 close=130.20 volume=271593
  2019-12-20 close=130.34 volume=246690
  2019-12-23 close=129.93 volume=318322
== NSE prices on current face-value basis
  2019-12-18 close=129.254 volume=219460
  2019-12-19 close=130.200 volume=271593
  2019-12-20 close=130.340 volume=246690
  2019-12-23 close=129.930 volume=318322
== Yahoo adjusted-price diagnostic: 2469 bars; >25% daily moves: 2
  2019-12-19 -89.9%
  2019-12-23 +896.9%
== Yahoo split window (diagnostic only)
  2019-12-18 close=129.254
  2019-12-19 close=13.020
  2019-12-20 close=13.034
  2019-12-23 close=129.930
