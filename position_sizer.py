"""
Position Sizing & Capital Allocation Helper (position_sizer.py)

Adapts trade-budget & risk management rules from day-trader-skill:
1. Calculates exact share count based on maximum account risk percentage
2. Enforces maximum position capital allocation cap (prevents overallocating to high-priced / low-vol names)
3. Computes exact Rupee risk, total capital deployed, and expected payout at Target
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class SizingPlan:
    capital: float
    risk_budget_pct: float      # e.g. 1.0% (0.01)
    risk_amount: float          # Rupee amount risked (e.g. ₹5,000)
    entry: float
    stop: float
    target: float
    shares: int
    capital_required: float     # shares * entry
    capital_pct: float          # fraction of total account
    reward_amount: float        # profit if target hit
    planned_rr: float
    sizing_ok: bool
    warning: Optional[str] = None


def calculate_position_size(
    entry: float,
    stop: float,
    target: float,
    capital: float = 500_000.0,       # default ₹5 Lakhs account
    risk_pct: float = 0.01,           # default 1% risk per trade (₹5,000)
    max_position_pct: float = 0.25,   # max 25% of account in one name (₹1.25L)
) -> SizingPlan:
    """Calculates position size in shares for a planned trade."""
    risk_per_share = entry - stop
    if risk_per_share <= 0 or entry <= 0:
        return SizingPlan(
            capital=capital,
            risk_budget_pct=risk_pct,
            risk_amount=0.0,
            entry=entry,
            stop=stop,
            target=target,
            shares=0,
            capital_required=0.0,
            capital_pct=0.0,
            reward_amount=0.0,
            planned_rr=0.0,
            sizing_ok=False,
            warning="Invalid stop level: stop is at or above entry",
        )

    risk_budget_in_rupees = capital * risk_pct
    raw_shares = risk_budget_in_rupees / risk_per_share
    shares = int(raw_shares)

    # Check maximum position capital cap
    max_capital_allowed = capital * max_position_pct
    capital_needed = shares * entry

    warning = None
    if capital_needed > max_capital_allowed:
        # Cap shares by capital constraint
        shares = int(max_capital_allowed / entry)
        capital_needed = shares * entry
        warning = f"Position capped at {max_position_pct*100:.0f}% of portfolio capital (max ₹{max_capital_allowed:,.0f})"

    actual_risk = shares * risk_per_share
    reward_per_share = max(0.0, target - entry)
    reward_amount = shares * reward_per_share
    planned_rr = reward_per_share / risk_per_share if risk_per_share > 0 else 0.0

    return SizingPlan(
        capital=capital,
        risk_budget_pct=risk_pct,
        risk_amount=round(actual_risk, 2),
        entry=round(entry, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        shares=shares,
        capital_required=round(capital_needed, 2),
        capital_pct=round(capital_needed / capital, 4) if capital > 0 else 0.0,
        reward_amount=round(reward_amount, 2),
        planned_rr=round(planned_rr, 2),
        sizing_ok=shares > 0,
        warning=warning,
    )
