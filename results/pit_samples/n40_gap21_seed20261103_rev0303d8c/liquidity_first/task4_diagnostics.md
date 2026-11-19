# Task 4 — PIT sample diagnostics

Dataset: TejHQ `tejhq/indian-markets`, revision `0303d8c95b4519765a9d5556fd9c2d430f8f81d8`. Sample: 40 liquidity-first, top-20 baskets, 21-session minimum spacing. The windows overlap, so the per-sample IC observations are not independent.

## 1. Cross-sectional factor rank-IC

For each sample, Spearman rank correlation is calculated between each selected-stock factor value on the signal date and that stock's forward close-to-close net return. The table reports the unweighted mean of sample-level ICs, using only complete baskets at each horizon.

| Horizon | Complete baskets | 12–1 momentum | 126d traded value | % below 52w high |
|---|---:|---:|---:|---:|
| 1M | 40 | -0.008 | -0.023 | -0.065 |
| 3M | 37 | 0.000 | +0.024 | -0.007 |
| 6M | 29 | +0.006 | +0.033 | -0.005 |

Interpretation: all three factors have near-zero average rank-IC in this already-selected top-20 cohort. Turnover has a small positive relationship at 3M/6M, but the magnitude is weak. These results do not validate the current momentum ranking as a forward-return predictor. This is descriptive only: the sample is small, windows overlap, and conditioning on the selected top-20 universe truncates the cross-section.

## 2. Six-month incomplete-basket audit

Of 40 attempted six-month baskets, 29 are complete and 11 are incomplete. The 11 incomplete baskets contain 12 affected stock positions. No basket is reweighted after an invalid holding is detected.

| Sample | Signal date | Unsupported holding(s) |
|---|---|---|
| S2 | 2020-05-07 | NESTLEIND |
| S3 | 2020-06-19 | AJANTPHARM, NESTLEIND |
| S5 | 2020-10-05 | AARTIDRUGS |
| S6 | 2020-11-25 | AARTIDRUGS |
| S7 | 2021-01-06 | AARTIDRUGS |
| S8 | 2021-02-08 | AARTIDRUGS |
| S13 | 2022-02-08 | BSOFT |
| S14 | 2022-03-16 | BSOFT |
| S15 | 2022-04-27 | SUZLON |
| S16 | 2022-06-01 | SUZLON |
| S40 | 2026-03-10 | VEDL |

The published six-month return summary is therefore conditional on the 29 complete baskets. Its +17.91% raw mean and +8.87% benchmark mean must not be interpreted as a 40-basket result.

## 3. NSE / TejHQ NIFTYBEES price reconciliation

- NSE NextApi bars: 2,477; TejHQ bars: 2,466.
- Common sessions: 2,463 (99.43% of NSE bars; 99.88% of TejHQ bars).
- Maximum absolute OHLC difference on common sessions: 0.0; maximum relative difference: 0.0.
- NSE-only dates: 14. They are special/holiday dates with no stock bars across the loaded universe and are excluded from the common comparison calendar.
- TejHQ-only dates accepted as supplements after NSE-calendar validation: 2016-10-13, 2020-05-05, 2020-08-13.
- The benchmark series has no missing bars on included comparison sessions.

Source detail: `results/bench_check.md` and `results/tejhq_source_metadata.md`.

## 4. Intra-window maximum drawdown

The daily reconstruction is implemented in `scripts/study_pit_sample_drawdown.py` and wired into `.github/workflows/rules-test.yml`. It measures equal-weight buy-and-hold basket equity from adjusted next-session entry open to each horizon's exit, using daily adjusted closes and carry-forward only for held-position marking. Incomplete baskets are excluded, never reweighted. The output is `intra_window_drawdown.csv` and `intra_window_drawdown.md` in this directory; these will be populated by the pinned-data CI run.
