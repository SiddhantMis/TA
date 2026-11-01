#!/usr/bin/env python3
"""Export a public-safe market preview without account, cash or execution data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args()

    state_path = Path(args.state_file)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    with state_path.open(encoding="utf-8") as handle:
        state = json.load(handle)

    market = state.get("market_regime") or {}
    quality = state.get("data_quality") or {}
    rules = state.get("portfolio_rules") or {}
    targets = state.get("target_portfolio") or []

    preview = {
        "schema_version": 1,
        "preview_only": True,
        "as_of": state.get("as_of"),
        "benchmark": state.get("benchmark"),
        "market_regime": {
            key: market.get(key)
            for key in ("regime", "benchmark_close", "sma200", "above_sma200", "reason", "as_of")
        },
        "data_quality": {
            key: quality.get(key)
            for key in ("requested", "loaded", "failed", "coverage_pct", "rankable", "liquid", "above_200dma")
        },
        "rebalance_status": state.get("rebalance_status"),
        "selection_rules": {
            key: rules.get(key)
            for key in ("portfolio_size", "liquid_universe_top", "holding_buffer_rank",
                        "stock_eligibility", "market_filter")
        },
        "target_portfolio": [
            {
                key: item.get(key)
                for key in ("ticker", "leader_rank", "last_close",
                            "relative_strength_12_1_pct", "relative_strength_6m_pct",
                            "relative_strength_3m_pct", "data_status")
            }
            for item in targets
        ],
        "interpretation_limits": [
            "This is a strategy preview, not an account-aware recommendation.",
            "No broker holdings, cash, capital, execution history, cost basis, quantities or proposed orders are included.",
            "The preview was calculated using data no later than the requested market session.",
            "The Top-30 retention buffer and monitoring statuses are operational hypotheses, not proven return improvements.",
            "A target list is not evidence of a profitable strategy and must not be treated as executed trades.",
        ],
    }
    (outdir / "portfolio_preview.json").write_text(
        json.dumps(preview, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )

    tickers = preview["target_portfolio"]
    table = [
        "| Rank | Ticker | Close | 12-1 RS vs benchmark | 6M RS |",
        "|---:|---|---:|---:|---:|",
    ]
    for item in tickers:
        table.append(
            f"| {item.get('leader_rank')} | {item.get('ticker')} | {item.get('last_close')} | "
            f"{item.get('relative_strength_12_1_pct')} | {item.get('relative_strength_6m_pct')} |"
        )
    list_text = "\n".join(table) if tickers else "No eligible equities were selected."

    common = (
        f"- Data session: {preview.get('as_of')}\n"
        f"- Benchmark: {preview.get('benchmark')}\n"
        f"- Market regime: {market.get('regime')} ({market.get('reason')})\n"
        f"- Universe coverage: {quality.get('loaded')}/{quality.get('requested')} "
        f"({quality.get('coverage_pct')}%)\n"
        f"- Rebalance status: {preview.get('rebalance_status')}\n"
    )
    disclaimer = (
        "\nThis is a market-only strategy preview. No user's actual holdings, cash, starting capital, "
        "fills, cost basis or quantities were loaded. Do not describe the target list as executed "
        "positions or issue personalized trade instructions.\n"
    )
    gemini = (
        f"# Fundamental and catalyst review input — {preview.get('as_of')}\n\n"
        "Review these Indian listed companies for fundamental durability and material catalysts. "
        "Use dated primary sources and cite links. Do not change the model's selection or infer execution.\n\n"
        "## Market and data context\n" + common +
        "\n## Model target candidates\n" + list_text + disclaimer +
        "\nFor each candidate assess recent results, revenue and earnings quality, debt, operating cash "
        "flow, guidance, order-book visibility where relevant, promoter pledges, auditor changes, "
        "institutional ownership, sector concentration and upcoming catalysts. Separate verified facts "
        "from interpretation. Highlight missing or unverified information.\n"
    )
    chatgpt = (
        f"# News and portfolio-risk review input — {preview.get('as_of')}\n\n"
        "Search current official NSE/BSE announcements, company filings and reputable financial news. "
        "Report exact publication dates, event dates, URLs and retrieval time. Do not infer that no event "
        "exists merely because a search returned nothing.\n\n"
        "## Market and data context\n" + common +
        "\n## Model target candidates\n" + list_text + disclaimer +
        "\nFor each candidate check the last 72 hours of material announcements, results and board-meeting "
        "dates, regulatory matters, credit-rating actions, auditor or management changes, pledges and "
        "insider activity, block/bulk deals, liquidity, gaps and correlated sector/theme exposures. "
        "Flag results within the next three trading sessions as an event-risk review. Do not change "
        "membership and do not provide order instructions.\n"
    )
    (outdir / "gemini_fundamental_review.md").write_text(gemini, encoding="utf-8")
    (outdir / "chatgpt_news_risk_review.md").write_text(chatgpt, encoding="utf-8")

    print(f"Preview exported for {preview.get('as_of')}: {len(tickers)} candidates.")
    print(f"Data coverage: {quality.get('loaded')}/{quality.get('requested')} ({quality.get('coverage_pct')}%).")
    print("Private account fields and execution details were excluded from the artifact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
