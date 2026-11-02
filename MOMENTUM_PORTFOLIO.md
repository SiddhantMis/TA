# Momentum portfolio operating model

## Core separation

- actual_holdings is the execution ledger. It changes only through the record-fill command.
- target_holdings is the model's monthly membership proposal.
- proposed_changes is a list of unexecuted BUY/SELL ideas. It never changes quantities or cash.
- Daily monitoring is descriptive. It reports HEALTHY, WATCH, EXIT_REVIEW or DATA_UNAVAILABLE; it never places orders.

## First-version strategy rules

1. Universe and liquidity ranking come from leaders.py: top 200 by 126-session average traded value.
2. Eligibility requires valid benchmark-aligned relative-strength data and close above the 200-DMA.
3. Ranking uses the existing 12-1 relative-strength field from leaders.py.
4. The target is up to 20 stocks. Actual holdings may be retained through rank 30 to reduce monthly boundary churn.
5. A NIFTYBEES close at or below its 200-DMA makes the target portfolio cash at the monthly rebalance. It does not liquidate actual holdings automatically.
6. No fixed percentage stops, profit targets, arbitrary 0-100 health score, or automatic daily rotation are enabled.

The rank-30 buffer and daily monitor are operational hypotheses, not validated portfolio improvements. Compare them with the unbuffered monthly baseline before treating them as performance-enhancing.

## Recording a confirmed execution

After a broker-confirmed fill, run from the repository root:

    python momentum_portfolio.py --record-fill RELIANCE.NS BUY 10 1450.50 --execution-date 2026-11-03 --execution-id broker-order-123 --fill-costs 18.50

For a sale:

    python momentum_portfolio.py --record-fill RELIANCE.NS SELL 10 1520.00 --execution-date 2026-11-12 --execution-id broker-order-456 --fill-costs 24.00

Execution IDs are idempotent. Re-running the same ID does not double count a fill. The ledger rejects over-selling and buys that exceed recorded cash.

Set initial capital to the account's actual starting cash with the --capital option. The command-line default is ₹10 lakh and should not be treated as your real account balance unless that is correct.

## Rebalance timing

The first scan builds an initial target. Subsequent automatic rebalances occur on the first scan on or after the 28th of a new calendar month. A manual force-rebalance option is available. This calendar rule is an operational approximation; verify the exchange calendar and next-session execution timing before relying on it.

## Hosted Friday-data preview

After this PR is merged, use **Actions → Momentum Portfolio Friday Preview → Run workflow**. The default session is **2026-10-30**. The scanner truncates both benchmark and stock history to that exact exchange session and fails if the benchmark does not contain it; it cannot silently substitute Monday's data or use later prices.

The workflow runs on a GitHub-hosted runner. It uses a fresh temporary state with a nominal ₹1 capital only to satisfy the ledger's positive-capital requirement; this is **not** an account balance and is not used to publish quantities or orders. The workflow exports only a market-data preview and two review-input files for Gemini and ChatGPT. It excludes actual holdings, broker fills, cash, capital, cost basis, suggested quantities and private state. Temporary state and internal briefs are not uploaded or committed.

The preview is a market/strategy test, not a personalized account run. It starts with an empty actual-holdings ledger, so the Top-30 retention rule cannot account for existing positions until those are reconciled from broker-confirmed holdings. Do not treat the preview's target tickers as trades.

Run the first trial with the default date (Friday, 30 October 2026), inspect universe coverage and benchmark regime, then have the Gemini and ChatGPT review inputs analysed separately. If the data provider cannot return the exact requested session, the workflow must fail rather than switch dates.

## AI briefs

Both briefs are generated from one portfolio-state snapshot and saved under .local/. That folder is git-ignored because the files contain private holdings, cash and transaction information. Gemini focuses on fundamental durability and sector/catalyst context. ChatGPT focuses on filings, current news, event risk and portfolio exposure. Neither AI can update actual_holdings or execute a proposed trade.

## Privacy and automation

This repository is public. Do not commit the state file, execution history, account balance or AI briefs. Defaults write to .local/, which is git-ignored. GitHub Actions runs validation and offers the manually triggered, account-free historical preview described above. The preview keeps the temporary state and internal briefs in the runner and uploads only the filtered strategy candidates and review inputs. It does not persist an account ledger or publish private portfolio data. A persistent hosted portfolio requires a separate private state store; do not add that state to this public repository.


## Historical NIFTYBEES benchmark source (research backtest)

The portfolio-rules research backtest downloads NIFTYBEES daily traded OHLCV from NSE's own historical trade-data endpoint (\`getHistoricalTradeData\`, symbol \`NIFTYBEES\`, series \`EQ\`). Requests are split into inclusive 100-calendar-day windows, parsed by exchange date, and rejected if a window is empty or produces duplicate sessions.

The exchange series is unadjusted. To express historical prices in today's Rs 1 face-value units, the loader applies the NSE circular CML/42873 split effective 19 December 2019: pre-ex-date Open, High, Low and Close are multiplied by 0.1, and volume by 10. No price-jump heuristic is used to alter benchmark bars. The 200-day regime filter and benchmark series are calculated from this explicit split-adjusted NSE history.

A hard gate rejects missing/non-positive closes or daily moves above 25%, and a separate daily-return correlation check compares NIFTYBEES against the \`^NSEI\` price index. The index remains a diagnostic only; it does not replace the ETF filter. Yahoo's NIFTYBEES history is retained only as an independent diagnostic in \`bench_check.py\`, not as a strategy input.

This is an exchange-traded price series, not fund NAV or a separately constructed total-return series. The strategy's technical regime uses traded closes.

## Point-in-time Nifty 500 research variant

The daily rules backtest now uses `universe/nifty500_membership_history.csv` instead of applying today's Nifty 500 list to the entire past. At each signal date, only symbols whose published interval includes that date can enter the 126-session traded-value top-200 liquidity ranking or the 12–1 momentum eligibility/rank. Intervals are start-inclusive and end-exclusive.

Run it with:

    python portfolio_rules.py --years 10 --oos-frac 0.35 --cost-pct 0.30

The membership calendar is a CC0-filtered Nifty 500 extract from [aditya-jha/nse-historical-membership](https://github.com/aditya-jha/nse-historical-membership). It has known gaps: some initial 2014 membership starts are approximate, the source validation notes historical count drift, and Yahoo Finance may not provide price histories for delisted or renamed companies. The run stops at the calendar's stated 2026-10-13 coverage date and prints both symbol-level and daily member-price coverage. Treat the result as **survivorship-bias-reduced**, not survivorship-bias-free; poor price coverage means the corrected CAGR is not decision-grade. The prior current-constituent result is preserved at [results/portfolio_rules_report_survivor_biased_baseline.md](results/portfolio_rules_report_survivor_biased_baseline.md) for side-by-side comparison. See [universe/NIFTY500_PIT_DATA.md](universe/NIFTY500_PIT_DATA.md) for provenance and limitations.

