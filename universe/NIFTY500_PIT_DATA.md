# Nifty 500 point-in-time membership data

This file is a filtered copy of `index_history/data/index_membership_history.csv`, selecting NSE Indices `index_id=221` (Nifty 500) from [aditya-jha/nse-historical-membership](https://github.com/aditya-jha/nse-historical-membership).

- Source CSV blob SHA: `4b762a75376b14b9db6304ef70237270bc8da397`
- Source repository data licence: [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
- Rows copied: 1151
- Unique symbols: 970
- Source categories: `snapshot_floor=516`, `press_release=632`, `merger=2`, `snapshot=1`
- Source coverage statement: index membership through 2026-10-13; latest Nifty 500 interval start in this extract is 2026-09-30.
- Interval semantics: `valid_from` is inclusive; `valid_to` is exclusive; blank `valid_to` means open-ended.

## Important quality limits

This is a survivorship-bias-reduction dataset, not a complete authoritative daily constituent archive. The source documents high confidence from 2017 onward, but marks `snapshot_floor` intervals as approximate starts and reports historical internal-consistency/cardinality drift. Its validation report records 44 Nifty 500 cardinality failures across the dates it checked; historical counts in this extract are 501–504 on some dates rather than exactly 500, and the 2026-09-30 snapshot contains 499 members. The source also reports wider consistency gaps for several other indices.

The backtest uses the interval dates as published and preserves the source labels. It does not fabricate missing inclusion/exclusion dates or force a 500-stock count. In particular, `snapshot_floor` rows seed membership from 2014-01-01 and should not be read as exact historical inclusion dates. Metrics begin after the 252-session warm-up, in late 2017 for a 10-year run.

Price data is a separate limitation. Yahoo Finance may not return histories for delisted, liquidated, renamed, or otherwise unavailable symbols. Those names remain in the membership calendar but cannot enter the ranking without price bars. The research report therefore shows daily active-member price coverage and missing symbols. Poor coverage means residual survivorship/data-availability bias remains; the calendar alone cannot recover delisting returns.

The portfolio backtest is capped at 2026-10-13, the membership source's stated coverage-through date, rather than extrapolating this calendar into later sessions.


## Adjusted-price and coverage audit (workflow run [#41521787219](https://github.com/SiddhantMis/TA/actions/runs/41521787219))

The reproducible outputs are:
- `results/pit_price_history_audit.csv`: all missing or sub-253-bar PIT histories, with membership-window overlap and loader status.
- `results/pit_daily_coverage_audit.csv`: daily active-member coverage on the common comparison calendar.
- `results/tejhq_symbol_continuity_audit.csv`: one row per PIT symbol with aliases, ISIN/chain counts, bar count, first/last dates and status.
- `results/tejhq_source_metadata.md`: pinned dataset revision, adjustment validation, source scope and data terms.
- `results/pit_session_calendar_audit.csv`: full NSE calendar, source-bar flags, and explicit comparison inclusion/exclusion.
- `results/pit_tejhq_coverage_audit.csv`: coverage-only TejHQ API re-probe of the 27 active-window symbols that still lack a full 253-bar history.
- `results/pit_tejhq_initial_coverage_probe.csv`: preserved 105-symbol probe from workflow run [#41492471661](https://github.com/SiddhantMis/TA/actions/runs/41492471661).
- `results/portfolio_rules_report.md` and `results/bench_check.md`: strategy comparison and independent NSE benchmark reconciliation.

### Historical symbol coverage

The integrated loader uses one pinned TejHQ `prices_adjusted` NSE parquet revision (`f7fa8343af92cf1289f3960c9267ed23fa9dbbcb)) for the stock universe. It loaded 951 symbol histories with at least one bar; 920 of 970 PIT symbols have the full 253-bar minimum, 31 have some but insufficient history, and 19 have no history. Of 878 symbols whose membership intervals overlap the tested window, 27 lack the 253-bar minimum: 22 are short-history cases and five return no history. Another 23 missing/unusable symbols do not overlap the tested window.

The 27-row TejHQ API audit returned history for the same 22 short-history symbols with the same bar counts as the adjusted-parquet loader; the other five returned no history. The API probe is coverage-only and does not feed raw prices into the backtest. The earlier 105-symbol probe returned some history for 102/105 symbols: 82 had at least 253 bars, 20 had fewer, and three had none. These two probes use different input sets and should not be combined into one coverage denominator.

The continuity audit covers all 970 PIT symbols and resolves 937 instrument chains across 1,146 ISINs. It records 116 symbols with multiple ISINs and 115 with multiple aliases. The chain rule is the same ISIN, or a new ISIN for the same symbol when the gap is at most 30 calendar days; ambiguous overlapping different-ISIN intervals and duplicate symbol/session rows fail validation. The five symbols with no resolved chain and no history are BAGMANE, BIRET, EMBASSY, SGPC and SHTV. BAGMANE, BIRET and EMBASSY first appear in the membership extract on 2026-09-30; SGPC and SHTV are former constituents with no returned history.

The adjustment-factor check passed: adjusted close matches raw close multiplied by the published cumulative factor, and adjusted OHLC is checked on the same basis. TejHQ adjusts for splits, bonuses and dividends and retains raw volume/turnover, but does not scale mergers, demergers, rights or buybacks. Consequently, the source is consistent across the stock universe but is not complete for every corporate-action type.

### NSE session alignment and missing bars

The full calendar contains 2,480 NSE sessions from 2016-10-13 through 2026-10-13. Fourteen official sessions have no stock bar for any loaded symbol:
`2016-10-30`, `2017-10-19`, `2018-11-07`, `2019-10-27`, `2020-02-01`, `2020-11-14`, `2021-11-04`, `2022-10-24`, `2023-11-12`, `2024-03-02`, `2024-05-18`, `2024-11-01`, `2025-10-21`, and `2026-02-01`. The 2024-03-02 session is explicitly included in the official calendar using [NSE Circular MSD/60677](https://nsearchives.nseindia.com/content/circulars/MSD60677.pdf); the NIFTY 50 index feed has no row for that date.

To avoid a stale, flat stock portfolio mark being compared with a moving ETF/index benchmark, those 14 dates remain visible in the full audit but are excluded from every strategy and benchmark series. All variants and benchmarks therefore use the same 2,466 comparison sessions. There are no off-calendar stock dates, no missing NIFTYBEES bars, and no missing NIFTY 50 index bars on included comparison sessions. The benchmark is not forward-filled in the validated run. Missing stock opens, eligibility and returns are not forward-filled; close carry-forward is reserved for valuing existing holdings. The completed run reports zero held-position stale-close days.

Daily active-member bar coverage on the comparison calendar is 98.6% minimum, 98.8% at the 10th percentile and 100% median; no session falls below 90% and none has zero active-member bars. The session audit retains all 2,480 dates and flags the 14 exclusions explicitly.

### Strategy comparison and interpretation

All variants use the same PIT membership calendar, 2,466 comparison sessions, 2017-10-23 through 2026-10-13 test dates after the 253-bar warm-up, 2023-08-18 IS/OOS split, 0.30% round-trip transaction cost and zero cash allocation. The full comparison is in `results/portfolio_rules_report.md`.

For context only, the V2 live-rule variant reports 17.8% full-period CAGR, 20.8% volatility, 0.89 Sharpe and -31.5% maximum drawdown; the V1 baseline reports 20.3%, 20.9%, 0.99 and -28.4%. OOS V2 reports 25.7% CAGR and -25.6% maximum drawdown, versus 26.8% and -20.5% for V1. These are backtest outputs, not validated forecasts or evidence to change live rules.

The NIFTYBEES benchmark is split-adjusted for its 10:1 face-value split effective 2019-12-19 and reconciled against TejHQ raw bars: common-date OHLC differences are zero. The ETF is not dividend-adjusted, and the NSE NIFTY 50 series used is a price index, not a total-return index. This is a further return-basis limitation versus dividend-adjusted stock prices.

### Remaining quality and licensing limits

This remains **NOT DECISION-GRADE**. The 27 active-window symbols without 253 bars, the PIT membership source's 44 documented cardinality failures (501–504 names on some dates and a 499-name 2026 snapshot), approximate `snapshot_floor` starts, and unsupported corporate actions can still bias results. The membership calendar reduces survivorship bias but does not eliminate missing-return bias.

TejHQ's data terms (updated 2026-10-30) permit personal research and backtesting, but state that TejHQ holds no NSE/BSE data licence and its MIT licence covers code, not market data. Exchange terms still apply; commercial use or redistribution requires separate rights review. No raw market-price rows are committed to this repository. See [TejHQ data terms](https://tejhq.dev/data-terms) and the [dataset card](https://huggingface.co/datasets/tejhq/indian-markets).

The research branch changes only data loading, validation, comparison-session selection and audit/report generation. It does not change `portfolio.py`, the live portfolio rules or the main branch. The PR remains draft pending review of the residual coverage, membership and corporate-action limitations.
