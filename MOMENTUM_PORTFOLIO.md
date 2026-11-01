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

## AI briefs

Both briefs are generated from one portfolio-state snapshot and saved under .local/. That folder is git-ignored because the files contain private holdings, cash and transaction information. Gemini focuses on fundamental durability and sector/catalyst context. ChatGPT focuses on filings, current news, event risk and portfolio exposure. Neither AI can update actual_holdings or execute a proposed trade.

## Privacy and automation

This repository is public. Do not commit the state file, execution history, account balance or AI briefs. Defaults write to .local/, which is git-ignored. The GitHub Actions workflow only runs tests and compilation; it does not run a scheduled live scan, upload state as an artifact, or publish private portfolio data. Scheduled hosted scans should be enabled only after a private state store is configured.
