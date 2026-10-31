# Antigravity Technical Handoff: Leaders-First TA Screener & Research Suite

**Repository**: [`https://github.com/SiddhantMis/TA`](file:///home/siddhant/.gemini/antigravity/scratch/TA)  
**Workspace Path**: `/home/siddhant/.gemini/antigravity/scratch/TA`  
**Active Development Branch**: `antigravity/leaders-scanner`  
**Latest Commits**:
* `8a0fdc9`: *Unify research lab, backtest frameworks, and comprehensive test suite into leaders-scanner*
* `92d6189`: *Implement Leaders-First scanner, advanced S/R touch engine, causal chart patterns, and ChatGPT task schema*
**Test Status**: **94 / 94 Unit Tests Passing** (`test_patterns.py`)

---

## 1. Executive Summary & Objective

This handoff unifies the work done across previous conversations with Claude, Codex's research branch, and Antigravity.

### The Problem Addressed
* **User's Requirement**: Build an institutional-grade daily Technical Analysis (TA) scanner that tracks recursive Support & Resistance (touch counts, exact touch dates, bounce clean-ness, weekly confluence), detects complex chart patterns (double bottoms/tops, triangles, flags, wedges, H&S), integrates with daily ChatGPT news/sentiment tasks via `docs/latest_screen.json`, and sends Discord alerts.
* **The Empirical Reality (Phase 1 Backtest)**: Standalone chart patterns and single/double candlesticks tested across 13,556 events on 360 liquid stocks (2017–2026) showed **zero directional alpha** (signs flip across market regimes).
* **The Solution ("Leaders-First" Architecture)**:
  1. Use **Relative Strength (RS) / Momentum** as the directional anchor (screening the top 20% market leaders first).
  2. Use **Multi-Touch S/R and Causal Geometric Patterns** not as blind buy signals, but for **Trade Architecture** (defining precise entry buy-stops, structural invalidation stop-losses, and reward:risk profit targets).
  3. Export a clean, RFC-8259 compliant JSON payload tailored for automated ChatGPT daily risk audits.

---

## 2. 3-Branch Scan & Audit

| Feature | `main` | `experiments` (Codex) | `antigravity/leaders-scanner` (Unified) |
| :--- | :--- | :--- | :--- |
| **Operational State** | Production EOD screener | Offline Research Sandbox | **Production EOD screener + Research Lab** |
| **Relative Strength** | ❌ None | ⚠️ Monthly momentum in `portfolio.py` | ✅ **Live RS Engine (`relative_strength.py`)** with 3M/6M/12-1M ranking |
| **S/R Engine** | ⚠️ Basic 1.5% clustering | ❌ None | ✅ **Multi-scale S/R Engine (`sr_engine.py`)** with touch ledger, dates, bounce quality, volume, role reversal, weekly MTF |
| **Chart Patterns** | Candlesticks only | 12 geometric patterns (`geo_patterns.py`) | ✅ **Candlesticks + 12 Causal Geometric Patterns** labeled as `unvalidated_context` |
| **Trade Planning & Sizing**| R:R gate (`build_trade_plan`) | Fixed R outcome simulator | ✅ **R:R gate + Position Sizing (`position_sizer.py`)** from `day-trader-skill` |
| **ChatGPT Schema** | ❌ `close: NaN` bug broke JSON | ❌ None | ✅ **Dedicated `chatgpt_daily_task` schema** in `docs/latest_screen.json` (valid RFC-8259) |
| **Test Suite** | 61 passing | 48 passing | ✅ **94 / 94 passing** |

---

## 3. Architecture & File Inventory

```
TA/
├── analyzer.py               # Master EOD technical screener & scoring pipeline
├── main.py                   # Scheduled runner, JSON sanitizer, ChatGPT payload generator
├── alerts.py                 # Discord webhook alerting with leader & MTF confluence tags
├── sr_engine.py              # [NEW] Multi-scale S/R engine, touch ledger, role reversal, weekly MTF
├── relative_strength.py      # [NEW] Relative Strength vs benchmark, RS Line trend, leader ranking
├── position_sizer.py         # [NEW] Position sizing & risk capital allocation (day-trader-skill)
├── swings.py                 # Causal ATR zigzag swing engine (no lookahead)
├── geo_patterns.py           # 12 causal geometric pattern detectors
├── backtest.py               # Walk-forward trade simulation in R (stops, targets, time exits, costs)
├── pattern_lab.py            # 10-year empirical evidence lab across 13,556 pattern events
├── portfolio.py              # Cross-sectional momentum vs buy-and-hold portfolio simulator
├── test_patterns.py          # Unified test harness (94 tests)
├── .github/workflows/
│   ├── eod-scan.yml          # Daily scheduled GitHub Action (7:00 PM IST)
│   ├── backtest.yml          # Manual walk-forward backtest workflow
│   └── research.yml          # Research lab workflow
├── results/                  # Research reports, constituent lists, and lab logs
│   ├── pattern_lab_report.md
│   ├── portfolio_report.md
│   ├── nifty200_symbols.txt
│   └── nifty500_symbols.txt
└── docs/
    └── latest_screen.json    # Published output for GitHub Pages & ChatGPT daily task
```

---

## 4. Detailed Component Breakdown

### A. Advanced Support & Resistance Engine ([`sr_engine.py`](file:///home/siddhant/.gemini/antigravity/scratch/TA/sr_engine.py))
* **Multi-Scale Pivots**: Detects local extrema across minor (3-bar), intermediate (8-bar), and major (20-bar) horizons.
* **Touch Ledger**: For every support and resistance zone, records exact calendar dates (`support_dates`, e.g. `['2026-06-15', '2026-08-20', '2026-10-14']`) and trading bars ago (`support_days_ago`, e.g. `[89, 39]`).
* **Bounce Quality**: Measures rejection wick percentage and post-touch expansion velocity (`High`, `Moderate`, `Tentative`).
* **Volume Confirmation**: Checks whether volume at touch bars exceeded $1.1\times$ the 20-day moving average.
* **Role Reversal (SR Flip)**: Identifies when a prior resistance peak was decisively broken and retested from above as support (`support_role_reversal: True`).
* **Weekly MTF Confluence**: Resamples daily bars to weekly bars (`W-FRI`) and flags daily levels that coincide with major multi-week pivots (`support_weekly_confluence: True`).

### B. Leaders-First Relative Strength Engine ([`relative_strength.py`](file:///home/siddhant/.gemini/antigravity/scratch/TA/relative_strength.py))
* **Weighted Momentum**: Evaluates composite momentum:
  $$\text{Score} = 0.40 \times R_{\text{3M}} + 0.30 \times R_{\text{6M}} + 0.30 \times R_{\text{12-1M}}$$
  *(skips the most recent month to avoid short-term mean-reversion trap)*.
* **RS Line Metrics**: Tracks $\text{Stock} / \text{NIFTYBEES.NS}$, testing whether the RS line is above its 50-day EMA and whether it is near a 60-day high.
* **Universe Percentile**: Assigns 0–100th percentile ranking; top 20% with bullish RS trend are designated `Market Leaders`.

### C. Causal Geometric Patterns ([`geo_patterns.py`](file:///home/siddhant/.gemini/antigravity/scratch/TA/geo_patterns.py) & [`swings.py`](file:///home/siddhant/.gemini/antigravity/scratch/TA/swings.py))
* Detects 12 classical patterns: Double Tops/Bottoms, Head & Shoulders, Inverse H&S, Ascending/Descending/Symmetrical Triangles, Bull/Bear Flags, Wedges, and Rectangles.
* Strictly causal: swing extremes are only known when price reverses by $\ge 3.0 \times \text{ATR}$ (`conf <= t`).
* Surfaced in results with `geo_pattern_key` (breakout trigger), `geo_pattern_stop`, and `geo_pattern_target` (measured move), labeled as `unvalidated_context`.

### D. Position Sizing Arithmetic ([`position_sizer.py`](file:///home/siddhant/.gemini/antigravity/scratch/TA/position_sizer.py))
* Adapted from `Jakeschincariol/day-trader-skill` (`trader-budget` and `trader-exit`).
* Calculates exact shares:
  $$\text{Shares} = \left\lfloor \frac{\text{Capital} \times \text{Risk \%}}{\text{Entry} - \text{Stop}} \right\rfloor$$
* Enforces a 25% single-stock capital cap and calculates Rupee risk, capital deployed, and expected payout at Target.

### E. ChatGPT Daily Task Schema & Sanitization ([`main.py`](file:///home/siddhant/.gemini/antigravity/scratch/TA/main.py))
* **Bug Fix**: Added `sanitize_for_json` which converts any `NaN` or `Infinity` into `None` / `null`, ensuring strict RFC-8259 compliance.
* **`chatgpt_daily_task` Structure**:
  ```json
  {
    "chatgpt_daily_task": {
      "task_instructions": "Review today's flagged setups and relative strength leaders...",
      "market_summary": {
        "run_timestamp": "2026-10-31T19:00:00+05:30",
        "market_breadth_above_sma50": 0.58,
        "market_regime": "Favorable / Bullish",
        "flagged_setups_count": 3,
        "market_leaders_count": 8
      },
      "flagged_candidates": [
        {
          "ticker": "HDFCBANK.NS",
          "close": 1740.5,
          "candlestick_pattern": "bullish_engulfing",
          "geometric_pattern": "double_bottom",
          "rs_rank": 3,
          "rs_percentile": 94.2,
          "is_leader": true,
          "support_level": 1720.0,
          "support_touches": 3,
          "support_touch_dates": ["2026-07-15", "2026-09-02", "2026-10-24"],
          "support_bounce_quality": "High",
          "support_role_reversal": true,
          "support_weekly_confluence": true,
          "trade_plan": {
            "entry_buy_stop": 1745.0,
            "stop_loss": 1711.4,
            "target_price": 1825.0,
            "risk_reward_ratio": 2.38,
            "risk_percent": 0.0193,
            "suggested_shares": 148,
            "capital_required": 258260.0,
            "rupee_risk": 4972.8
          },
          "news_audit_query": "Audit HDFCBANK.NS news and corporate actions in the last 72 hours: 1. Upcoming quarterly earnings...",
          "veto_rule": "VETO trade on HDFCBANK.NS if: (a) Earnings within 3 trading days..."
        }
      ]
    }
  }
  ```

---

## 5. Verification & Testing

Run the full unified test suite locally:
```bash
cd /home/siddhant/.gemini/antigravity/scratch/TA
/home/siddhant/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 test_patterns.py
```
**Result**:
```text
============================================================
PASS  test_alert_shows_plan_and_watch_and_breadth_warning
PASS  test_sr_engine_touch_ledger_and_dates
PASS  test_sr_role_reversal_detection
PASS  test_position_sizing_calculation
PASS  test_relative_strength_and_leader_ranking
PASS  test_geo_pattern_detection_integration
PASS  test_json_serialization_no_nan
PASS  test_zigzag_swings_and_causality
PASS  test_pattern_detection_has_no_lookahead
PASS  test_lab_end_to_end_on_random_stocks_validates_nothing
PASS  test_portfolio_selection_has_no_lookahead
...
94/94 passed
============================================================
```

---

## 6. How to Deploy / Push to GitHub

To push the new branch to your remote repository:
```bash
cd /home/siddhant/.gemini/antigravity/scratch/TA
git push -u origin antigravity/leaders-scanner
```

Once pushed, open a Pull Request from `antigravity/leaders-scanner` to `main` on GitHub to merge these improvements into production. The scheduled GitHub Action (`.github/workflows/eod-scan.yml`) will then automatically run this upgraded pipeline every weekday at 7:00 PM IST (13:30 UTC).
