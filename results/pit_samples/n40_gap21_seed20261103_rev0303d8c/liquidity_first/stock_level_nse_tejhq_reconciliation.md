# Stock-level official NSE vs TejHQ raw OHLC reconciliation

TejHQ dataset revision: `0303d8c95b4519765a9d5556fd9c2d430f8f81d8`
Overall status: **UNVERIFIED**
Deterministic sample: six corporate-action-flagged equities (NESTLEIND, AJANTPHARM, AARTIDRUGS, BSOFT, SUZLON, VEDL) plus four clean controls (ADANIGREEN, NAVINFLUOR, DIXON, DMART). For each stock, the comparison window is 20 calendar days either side of its first sample signal date.
Comparison is raw NSE EQ OHLC against TejHQ raw_open/raw_high/raw_low/raw_close, not adjusted prices.

| Symbol | Sample | Signal date | Status | Common sessions | Max abs open diff | high diff | low diff | close diff |
|---|---|---|---|---:|---:|---:|---:|---:|
| AARTIDRUGS | flagged_CA | 2020-10-05 | UNVERIFIED | 0 |  |  |  |  |
| AJANTPHARM | flagged_CA | 2020-05-07 | UNVERIFIED | 0 |  |  |  |  |
| BSOFT | flagged_CA | 2020-10-05 | UNVERIFIED | 0 |  |  |  |  |
| NESTLEIND | flagged_CA | 2020-05-07 | UNVERIFIED | 0 |  |  |  |  |
| SUZLON | flagged_CA | 2022-04-27 | UNVERIFIED | 0 |  |  |  |  |
| VEDL | flagged_CA | 2021-04-05 | UNVERIFIED | 0 |  |  |  |  |
| ADANIGREEN | clean_control | 2020-03-24 | UNVERIFIED | 0 |  |  |  |  |
| NAVINFLUOR | clean_control | 2020-03-24 | UNVERIFIED | 0 |  |  |  |  |
| DIXON | clean_control | 2020-03-24 | UNVERIFIED | 0 |  |  |  |  |
| DMART | clean_control | 2020-03-24 | UNVERIFIED | 0 |  |  |  |  |

NSE official equity-history endpoint could not provide a complete verifiable sample from this GitHub Actions run. Stock-level reconciliation is therefore **UNVERIFIED**; the NIFTYBEES benchmark comparison is not a substitute.
Homepage bootstrap error: HTTPError: 403 Client Error: Forbidden for url: https://www.nseindia.com/
- AARTIDRUGS: JSONDecodeError: Expecting value: line 2 column 1 (char 1)
- AJANTPHARM: JSONDecodeError: Expecting value: line 2 column 1 (char 1)
- BSOFT: JSONDecodeError: Expecting value: line 2 column 1 (char 1)
- NESTLEIND: JSONDecodeError: Expecting value: line 2 column 1 (char 1)
- SUZLON: JSONDecodeError: Expecting value: line 2 column 1 (char 1)
- VEDL: JSONDecodeError: Expecting value: line 2 column 1 (char 1)
- ADANIGREEN: JSONDecodeError: Expecting value: line 2 column 1 (char 1)
- NAVINFLUOR: JSONDecodeError: Expecting value: line 2 column 1 (char 1)
- DIXON: JSONDecodeError: Expecting value: line 2 column 1 (char 1)
- DMART: JSONDecodeError: Expecting value: line 2 column 1 (char 1)

Per-session exact OHLC values and absolute differences: `stock_level_nse_tejhq_reconciliation.csv`.
Per-symbol summary: `stock_level_nse_tejhq_reconciliation_summary.csv`.
