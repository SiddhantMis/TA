# Momentum swing scanner: build plan

## Product goal

Help review a daily list of Indian cash-equity swing candidates by answering,
in order:

1. Which stocks are leading their benchmark and the chosen watchlist?
2. Is the price structure suitable for a continuation setup, and where are the
   nearby levels that could invalidate it?
3. What would the entry trigger, stop, target, costs, and event risks be?
4. After the fact, did the screen improve decisions after costs?

The scanner is decision support. A ranking or chart pattern is not an order or
a claim of a profitable edge.

## Where this repo stands

- `analyzer.py` currently scores candle patterns, short trend, support
  proximity, volume, and RSI. Its `flag` is a reversal checklist, not a
  momentum signal.
- `backtest.py` has a walk-forward daily-bar simulation for that checklist and
  its trade plan.
- `research.py` tested breakout, pullback, and relative-strength breakout
  variants. The report at `results/research_report.md` says none met the fixed
  held-out criteria.
- `pattern_lab.py` tested geometric patterns. The report at
  `results/pattern_lab_report.md` did not validate any tested pattern.
- `portfolio.py` compared monthly momentum portfolios with benchmarks. The
  report at `results/portfolio_report_liquid500.md` did not meet its candidate
  rule; its out-of-sample sample is also limited.
- The daily output is JSON, a small read-only Pages table, and a Discord
  notification. Live data-fetch reliability still needs a manual Actions run.

The first product change is a relative-strength leaderboard against
`NIFTYBEES.NS`, separate from the old reversal checklist. It reports a 12-1
adjusted-return comparison and a 6-month excess-return context field. The rank
is only within the configured watchlist. It is not a validated entry filter.

## What established screeners make useful

The useful product patterns are presentation and workflow features: saved
filters, sortable performance and technical columns, chart views, multiple
timeframes, and alerts with a history. TradingView documents these in its
[stock screener guide](https://www.tradingview.com/support/solutions/43000718866-tradingview-stock-screener-trade-smarter-not-harder/)
and its [multi-condition alert guide](https://www.tradingview.com/support/solutions/43000761492-multi-condition-alerts/).
NSE Indices describes its Nifty200 Momentum 30 score as combining 6- and
12-month returns adjusted for volatility; see the
[official index page](https://www.niftyindices.com/indices/equity/strategy-indices/nifty200-momentum-30).
That is a useful reference for factor construction, but this repo's much
simpler relative-return leaderboard is not an implementation of that index.

## Build sequence

### 1. Make the daily view leader-first

- Keep raw 12-1 stock return, benchmark return, and excess return visible.
- Keep the 6-month excess field as a separate horizon; do not blend horizons
  into a tuned composite score.
- Show rank, percentile, rank universe size, and data date for every result.
- Keep the current pattern checklist and its confidence in a distinct section.
- Show unavailable or stale inputs explicitly; do not silently turn missing
  data into a low score.

**Gate:** the board must reproduce the same values from the same closed-bar
inputs and clearly disclose that the universe is the configured watchlist.

### 2. Improve the universe and data record

- Replace the hand-maintained symbol list with a versioned, reviewable universe
  file; keep ETFs separate from operating companies.
- Record exchange, symbol, instrument type, benchmark, price-adjustment mode,
  last complete bar, and fetch status.
- Add average traded value and missing-session checks before widening coverage.
- Preserve daily snapshots so future evaluation uses the universe and inputs
  that were available at that time.

**Gate:** no candidate is shown as current if its bars, benchmark, or symbol
mapping are stale or incomplete.

### 3. Add chart structure for continuation setups

- Add weekly trend context next to the daily view.
- For each support/resistance zone, show its price band, distinct touch dates,
  time since the latest touch, and whether price later closed through it.
- Measure reaction distance and volume at each touch for manual review.
- Report a level that changed from support to resistance as a historical event.
- Treat touch counts, pattern labels, and reactions as descriptions until a
  fixed research test shows predictive value.

**Gate:** all pivots and zones must be computed using bars available on the
screen date; confirmed pivots cannot be backdated as if they were known at the
price extreme.

### 4. Separate setup families instead of one blended score

Start with three long-only continuation candidates:

- a breakout from a defined base or prior range;
- a pullback in an established leader;
- a fresh high after a contraction or retest.

For each one, output the exact rule that fired, the trend and relative-strength
context, supporting and conflicting observations, and the date of the trigger.
Keep candlestick and geometric patterns as context unless separately
validated.

**Gate:** register the definitions before scoring the historical sample, use
matched controls, account for costs, and reserve a later period as the
out-of-sample set. A setup does not get promoted because it looks intuitive.

### 5. Make trade plans auditable

- Base entry triggers on the next session or a stated price level, not the
  signal-day close.
- Derive invalidation from recent structure and ATR, and state why that level
  was selected.
- Show target source, gross and net R:R, expected round-trip costs, and the
  price gap that would invalidate an order.
- Keep sizing dependent on the user's per-trade risk budget and actual costs;
  avoid presenting a fixed position size as universally appropriate.

**Gate:** walk-forward simulation must use only information known at each
signal date and conservative same-bar/gap assumptions. Keep failed plans
visible with the reason.

### 6. Add event risk as a separate checklist

- Show earnings/results dates, exchange filings, and other scheduled events
  with timestamp, source URL, and retrieval time.
- Keep news summary and sentiment separate from the price/volume score.
- Log any event-based veto so later analysis can compare vetoed and non-vetoed
  candidates.

**Gate:** every displayed event must have a source and date; missing event data
must be labeled unknown, not clear.

### 7. Keep a paper-trade journal and measure the full workflow

Log the scan snapshot, candidate state, hypothetical trigger, fills, exits,
costs, missed fills, and manual overrides. Report return in R, net return,
drawdown, turnover, and results by year and market regime. Use a point-in-time
universe where possible and keep a separate untouched validation period.

**Gate:** a new filter stays descriptive until it adds repeatable out-of-sample
value after costs versus a reasonable matched baseline.

## Do not prioritize yet

- More named candle or geometric patterns by themselves.
- A single opaque confidence score mixing correlated indicators.
- AI-generated bullish/bearish sentiment as a trade signal.
- Live broker orders or automatic position sizing.

The original momentum research is not proof against momentum generally; it is
evidence that these particular tested rules did not clear the repo's fixed
criteria. The next research question should be narrow: does leader context
improve a fixed continuation setup in an untouched period, after costs?
