# Hosted research runs

This repository can run deterministic tests and walk-forward research on GitHub-hosted runners. A local Python environment is not required to execute those jobs.

## Manual trigger

Open [Actions → Hosted Research Runner](https://github.com/SiddhantMis/TA/actions/workflows/research-runner.yml), choose **Run workflow**, then select:

- `tests`: run regression tests and Python compilation.
- `paper_audit`: run the tests and validate the published paper scorecard, if one exists.
- `liquid500_backtest`: run the current Nifty 500 / point-in-time liquid-200 portfolio backtest and publish its Markdown report and monthly CSV as an artifact.

The backtest may take a long time because it downloads historical data for hundreds of symbols. A failed data-provider request must be treated as a failed run, not as a zero-return result.

## Agent / Task / Gem trigger

After this workflow is merged into the default branch, external agents that have a secure GitHub API connection can request a run using GitHub's `repository_dispatch` endpoint:

```http
POST https://api.github.com/repos/SiddhantMis/TA/dispatches
Accept: application/vnd.github+json
Authorization: Bearer $GITHUB_DISPATCH_TOKEN
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json

{"event_type":"run-tests","client_payload":{"task":"tests","requested_by":"chatgpt-task"}}
```

Supported event types and payloads:

| Event type | Payload task | Purpose |
|---|---|---|
| `run-tests` | `tests` | Regression suite and compile checks |
| `paper-audit` | `paper_audit` | Tests plus scorecard integrity audit |
| `run-backtest` | `liquid500_backtest` | Nifty 500 liquid-200 walk-forward research |

For a backtest, the payload may include `years` (1–99) and `cost_pct` (0–5; default 0.30). Example:

```json
{"event_type":"run-backtest","client_payload":{"task":"liquid500_backtest","years":10,"cost_pct":0.30,"requested_by":"gem"}}
```

**Security:** never put a PAT in a Task/Gem prompt or repository file. Store the dispatch token in the calling agent's secure connection/secret store. Restrict it to this repository and only the permissions required to create repository dispatch events. If the calling environment cannot make authenticated GitHub API requests, use the manual Actions trigger above instead. The currently connected GitHub tools in this conversation can read workflow runs, but they do not expose a direct workflow-dispatch action.

## Result-reading protocol for Tasks and Gems

1. Do not say a run started until GitHub returns dispatch success or a workflow run is visible.
2. Poll the Actions run until `status=completed`; report its conclusion verbatim.
3. For tests, report the pass/fail summary and link to the run.
4. For `paper_audit`, inspect the audit output and list missing month-end scans, stale snapshots, or incomplete periods.
5. For `liquid500_backtest`, download and read `portfolio_report_liquid500.md` and `portfolio_monthly_liquid500.csv`. Compare FULL, IS and OOS metrics, drawdown, turnover, transaction costs, and the same-universe equal-weight control. Do not describe a backtest as live performance.
6. Report failures, missing data, rate limits, survivorship bias, and any unverified result. Do not retry a failed backtest indefinitely or alter strategy rules just to improve a score.

## Privacy boundary

Hosted jobs publish only strategy-level research artifacts: market-data-derived reports, the scorecard and public leader snapshots. They must not upload `.local/`, broker holdings, cash balances, fills, average costs, credentials or personal AI briefs. Private portfolio state remains outside this hosted workflow.
