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


## Price-history audit results (workflow run #41484828635)

The generated, reproducible audits are:
- `results/pit_price_history_audit.csv`: every calendar symbol without a usable 253-bar history, membership-window overlap, first/last membership dates, provider outcome, and returned bar count.
- `results/pit_daily_coverage_audit.csv`: active-member bar coverage for each backtest session.

For the 2017-11-08 through 2026-10-13 test window:
- 806 of 970 calendar symbols loaded; 164 did not meet the 253-bar requirement.
- 105 of 878 symbols with a membership interval overlapping the test window lacked 253 usable bars; 59 additional missing symbols had no overlap with this test window.
- Of those 105, 85 returned no history and 20 returned fewer than 253 bars.
- 19 of the 105 were still members at the end of the calendar, all first entering on 2026-03-30 or 2026-09-30. Their recent entry dates explain why they cannot yet supply the 252-session momentum lookback. The other 86 were former constituents; 84 returned no history and two returned only one bar. These former-member gaps are the material residual survivorship/data-availability concern.

## Zero-stock-bar sessions

The audit found eight dates in the ETF benchmark calendar on which none of the 806 loaded stock histories had a bar:
`2019-02-13`, `2019-03-29`, `2020-02-01`, `2023-11-12`, `2024-01-20`, `2024-03-02`, `2024-05-18`, and `2026-02-01`.

These are not all ordinary holidays. The 2019-02-13 and 2019-03-29 dates are weekdays with NIFTY 50 index history. The other six are documented special sessions: Budget-day trading on 2020-02-01 and 2026-02-01, Muhurat trading on 2023-11-12, and special live sessions on 2024-01-20, 2024-03-02, and 2024-05-18.

The stock-price source therefore has missing session data even on real exchange sessions. The portfolio engine forward-fills stock OHLC for up to five sessions; on these dates that means stale stock marks while the ETF benchmark calendar advances. This is a calendar/data-source mismatch that can distort daily returns and comparisons. The dates are deliberately **not** silently removed or populated with fabricated prices. A decision-grade rerun needs constituent data that covers those sessions, or an explicit, consistently applied exclusion across the strategy and every benchmark with the omitted dates disclosed.

The PIT run and its metrics remain diagnostic, not decision-grade, until the former-constituent histories and the eight zero-stock-bar sessions are resolved. The membership calendar reduces one source of survivorship bias; it does not eliminate missing-return bias.

The underlying dataset is derived from public NSE Indices press releases and NSE exchange circulars. Nifty index names are trademarks of NSE Indices Limited; this repository is independent and not endorsed by NSE.
