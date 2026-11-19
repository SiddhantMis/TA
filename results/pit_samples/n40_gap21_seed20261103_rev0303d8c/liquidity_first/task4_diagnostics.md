# Task 4 — PIT sample diagnostics

Dataset: TejHQ `tejhq/indian-markets`, revision `0303d8c95b4519765a9d5556fd9c2d430f8f81d8`. Sample: 40 liquidity-first, top-20 baskets, 21-session minimum spacing. The windows overlap, so the per-sample IC observations are not independent.

## 1. All-eligible cross-sectional factor rank-IC

TejHQ dataset revision: `0303d8c95b4519765a9d5556fd9c2d430f8f81d8`
Eligibility: point-in-time NIFTY 500 members with at least 253 observed sessions, ranked by 126-session average raw traded value (top 200), adjusted close above the 200-DMA, and corporate-action quarantine eligibility. Factors are measured at the signal close. Forward returns use next-session adjusted open to the sample's fixed horizon exit close; names with an unsupported corporate action between signal and exit are omitted only from that horizon's return cross-section.

| Horizon | Factor | Sample dates | Mean eligible N | Mean valid-return N | Mean Spearman IC | Median Spearman IC |
|---|---|---:|---:|---:|---:|---:|
| 1M | 12–1 momentum | 40 | 125.7 | 125.2 | +0.0360 | +0.0541 |
| 1M | Distance above 200-DMA | 40 | 125.7 | 125.2 | -0.0014 | +0.0114 |
| 1M | Distance from 52-week high | 40 | 125.7 | 125.2 | +0.0111 | -0.0008 |
| 1M | 126-day traded value | 40 | 125.7 | 125.2 | +0.0155 | +0.0174 |
| 3M | 12–1 momentum | 40 | 125.7 | 124.4 | +0.0339 | +0.0347 |
| 3M | Distance above 200-DMA | 40 | 125.7 | 124.4 | +0.0104 | -0.0180 |
| 3M | Distance from 52-week high | 40 | 125.7 | 124.4 | +0.0101 | +0.0550 |
| 3M | 126-day traded value | 40 | 125.7 | 124.4 | -0.0079 | -0.0016 |
| 6M | 12–1 momentum | 40 | 125.7 | 123.2 | +0.0241 | +0.0053 |
| 6M | Distance above 200-DMA | 40 | 125.7 | 123.2 | +0.0272 | +0.0330 |
| 6M | Distance from 52-week high | 40 | 125.7 | 123.2 | +0.0194 | +0.0518 |
| 6M | 126-day traded value | 40 | 125.7 | 123.2 | -0.0313 | -0.0360 |

IC is computed across all eligible stocks on each signal date, not only the selected top-20. The 40 dates overlap and are descriptive rather than independent statistical trials. Per-date observations and summary CSVs are stored alongside this report.
## 2. Six-month incomplete-basket audit

Of 40 attempted six-month baskets, 29 are complete and 11 are incomplete. The 11 incomplete baskets contain 12 affected stock positions. No basket is reweighted after an invalid holding is detected.

| Sample | Signal date | Symbol | Exact ex-date | Corporate-action type |
|---|---|---|---|---|
| S13 | 2022-02-08 | BSOFT | 2022-07-14 | buyback |
| S14 | 2022-03-16 | BSOFT | 2022-07-14 | buyback |
| S15 | 2022-04-27 | SUZLON | 2022-10-03 | rights |
| S16 | 2022-06-01 | SUZLON | 2022-10-03 | rights |
| S2 | 2020-05-07 | NESTLEIND | 2020-10-29 | other |
| S3 | 2020-06-19 | AJANTPHARM | 2020-11-12 | buyback |
| S3 | 2020-06-19 | NESTLEIND | 2020-10-29 | other |
| S40 | 2026-03-10 | VEDL | 2026-04-30 | demerger |
| S5 | 2020-10-05 | AARTIDRUGS | 2021-03-30 | buyback |
| S6 | 2020-11-25 | AARTIDRUGS | 2021-03-30 | buyback |
| S7 | 2021-01-06 | AARTIDRUGS | 2021-03-30 | buyback |
| S8 | 2021-02-08 | AARTIDRUGS | 2021-03-30 | buyback |

The published six-month return summary is therefore conditional on the 29 complete baskets. Its +17.91% raw mean and +8.87% benchmark mean must not be interpreted as a 40-basket result.

## 3. NSE / TejHQ reconciliation

### NIFTYBEES benchmark (ETF only)

- NSE NextApi bars: 2,477; TejHQ bars: 2,466.
- Common sessions: 2,463 (99.43% of NSE bars; 99.88% of TejHQ bars).
- Maximum absolute OHLC difference on common sessions: 0.0; maximum relative difference: 0.0.
- NSE-only dates: 14. They are special/holiday dates with no stock bars across the loaded universe and are excluded from the common comparison calendar.
- TejHQ-only dates accepted as supplements after NSE-calendar validation: 2016-10-13, 2020-05-05, 2020-08-13.
- The benchmark series has no missing bars on included comparison sessions.

Source detail: `results/bench_check.md` and `results/tejhq_source_metadata.md`.

### Stock-level individual-equity reconciliation

**Status: UNVERIFIED.** The deterministic sample covers six dropped-basket corporate-action names (NESTLEIND, AJANTPHARM, AARTIDRUGS, BSOFT, SUZLON, VEDL) and four clean controls (ADANIGREEN, NAVINFLUOR, DIXON, DMART), using the signal date of each affected basket position. The GitHub Actions runner was blocked by the official NSE website: the NSE homepage bootstrap returned HTTP 403 Forbidden, and the historical EQ endpoint returned non-JSON responses for all 10 names. There are therefore zero verified common stock sessions and no defensible OHLC differences to report. **Do not infer stock-level accuracy from the 2,463-session NIFTYBEES benchmark match.** Individual-stock OHLC remains UNVERIFIED until official NSE equity history can be retrieved. Per-symbol errors and session counts are in `stock_level_nse_tejhq_reconciliation_summary.csv`; the empty per-session comparison file is `stock_level_nse_tejhq_reconciliation.csv`.
## 4. Intra-window maximum drawdown

The daily reconstruction is implemented in `scripts/study_pit_sample_drawdown.py` and wired into `.github/workflows/rules-test.yml`. It measures equal-weight buy-and-hold basket equity from adjusted next-session entry open to each horizon's exit, using daily adjusted closes and carry-forward only for held-position marking. Incomplete baskets are excluded, never reweighted. The output is `intra_window_drawdown.csv` and `intra_window_drawdown.md` in this directory; these will be populated by the pinned-data CI run.
