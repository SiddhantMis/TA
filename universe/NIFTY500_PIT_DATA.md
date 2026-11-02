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

The underlying dataset is derived from public NSE Indices press releases and NSE exchange circulars. Nifty index names are trademarks of NSE Indices Limited; this repository is independent and not endorsed by NSE.
