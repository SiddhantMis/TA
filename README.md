# TA Screener

EOD technical-analysis and momentum watchlist for Indian equities. It ranks
relative-strength leaders and reports chart structure for manual review. It
does not make validated buy calls, decide position size, or replace the trade
plan in Trade_Evaluation_Sheet.xlsx.

See [MOMENTUM_SCANNER_PLAN.md](MOMENTUM_SCANNER_PLAN.md) for the staged product
plan and the validation gates for future features.

## What's actually been verified vs. what hasn't

**Verified locally:**
Offline suite (`test_patterns.py`) — 93/93 passing, covering
single-candle (Marubozu, Doji, Spinning Top, Hammer/Hanging Man,
Shooting Star/Inverted Hammer), two-candle (Engulfing, Piercing, Dark
Cloud Cover, Harami), and three-candle (Morning Star, Evening Star)
patterns, plus trend regression, pivot S/R, RSI, relative-strength windows,
watchlist ranking, and Discord formatting.

**Live data check (2026-10-31):** `run_screen()` fetched and scored all 48
watchlist tickers and ranked 48/48 against NIFTYBEES.NS, with common data
through 2026-10-30. This did not exercise Discord delivery, GitHub Actions
publishing, or the scheduled workflow. Run the manual trigger below before
trusting production scheduling.

## First-time setup

1. **Rotate the access token used to push this code.** It was pasted into
   a chat conversation to get this pushed — treat it as burned regardless
   of whether you've deleted it. github.com/settings/tokens → delete →
   generate a new one only when you need it, and only paste future tokens
   into GitHub's own Secrets UI, never into a chat.

2. **Add a Discord webhook** (Server Settings → Integrations → Webhooks →
   New Webhook → Copy URL), then in this repo: Settings → Secrets and
   variables → Actions → New repository secret → name it
   `DISCORD_WEBHOOK_URL`.

3. **Test manually before trusting the schedule.** Actions tab → EOD Stock
   Screener → Run workflow. Check the run log for `[error]` lines per
   ticker — that's where yfinance issues would show up first.

4. Once a manual run succeeds cleanly, the cron (`.github/workflows/eod-scan.yml`)
   runs automatically weekdays at 4:00 PM IST.

## Editing the watchlist

Edit `WATCHLIST` at the top of `analyzer.py`. No other changes needed to
add tickers. Scaling past ~30-40 names hasn't been tested — yfinance
rate-limits, and `YF_SLEEP_SECONDS` in `analyzer.py` may need raising if
you see repeated `[error]` lines when scaling up.

## Momentum leaderboard

The daily screen now reports a separate momentum leaderboard, ranked by each
stock's adjusted 12-1 return excess versus `NIFTYBEES.NS`. The 12-1 window uses
the close 252 sessions back as its start and the close 21 sessions back as its
end, so it skips the latest month. The screen also reports 6-month excess
return as context. Returns use dates shared by the stock and benchmark, and
the percentile rank is only within the configured watchlist; it is not a
Nifty 200 or Nifty 500 rank.

This ranking is descriptive, not a buy signal. The pre-registered momentum
research on the `experiments` branch did not validate the tested entries in
its held-out period, and the portfolio comparison did not meet its full
candidate rule. The leaderboard makes relative strength visible for chart
review without turning that inconclusive evidence into a trade recommendation.
The chart checklist and its existing `flag` remain separate reversal context.

This simple raw-return ranking is not the Nifty momentum-index methodology:
the official Nifty200 Momentum 30 score uses 6- and 12-month returns adjusted
for volatility and additional index rules. See the
[Nifty200 Momentum 30 methodology page](https://www.niftyindices.com/indices/equity/strategy-indices/nifty200-momentum-30).

## What "flagged" means

Each ticker gets a `confidence` score (0-100, weighted) and a `recommendation`
string — not a single pass/fail. `flag` is the existing reversal checklist
gate (4-of-5 checks), separate from the momentum leaderboard. Neither is a
trade signal; both are meant to help decide which charts to review.

The 5 checks, weighted (pattern + trend weighted highest, volume lowest):
1. **Trend defined** (weight 2) — linear regression over the last 15
   candles must clear both a minimum slope (%/bar) *and* a minimum R²
   (0.35). Replaces an earlier higher-high/lower-high counting method that
   measured direction changes but never consistency or magnitude.
2. **Pattern matches context** (weight 2) — candlestick pattern present,
   consistent with the trend read. Bullish patterns only ever pass this
   during a downtrend/choppy read (reversal setups). **No bearish-pattern
   branch exists — deliberate, not unresolved:** this trades cash equity
   delivery, not F&O, so there's no mechanism to act on a bearish signal
   (no shorting, no carrying a position down). Revisit only if a
   derivatives account enters the picture.

   Patterns detected, in priority order (3-candle > 2-candle > single —
   more candles agreeing is a stronger claim than one candle's shape):
   Morning Star / Evening Star (3-candle) → Engulfing / Piercing / Dark
   Cloud Cover / Harami (2-candle) → Marubozu / Doji / Hammer-Hanging Man
   / Shooting Star-Inverted Hammer / Spinning Top (single-candle).

   Two things worth knowing about these specifically:
   - **Harami is intentionally not weighted differently from
     engulfing/piercing in the checklist score**, even though it's a
     structurally weaker signal (an inside candle showing the prior move
     stalled, not reversed). This shows up as a note on the result
     instead — check `notes` before trusting a Harami-driven flag as much
     as an engulfing-driven one.
   - **Morning/Evening Star deliberately drop the textbook gap
     requirement.** Indian cash-equity names don't reliably gap the way
     the US-market version of this pattern assumes; the small "star"
     body plus the third candle reclaiming candle 1's midpoint carries
     the definition instead. If you're cross-checking a flagged Morning
     Star against a source that requires a gap, it may not match — that's
     the loosened rule, not a bug.
3. **Near a real support/resistance zone** (weight 1.5) — pivot-based
   clustering (swing highs/lows within 1.5% of each other = one zone),
   not a naive rolling min/max. Each result reports `support_touches`;
   a zone touched once is flagged as thin evidence in `notes`, not treated
   the same as one touched 3+ times.
4. **Volume ≥ 20-day average** (weight 1) — same-day bars are dropped
   before scoring (IST-aware) since Yahoo can hand back an unsettled
   same-day row with understated volume.
5. **RSI momentum agrees with the trend read** (weight 1) — RSI ≤45 in a
   downtrend context, or 35-65 in a choppy context. This replaced a
   flat "above/below both MAs" check, which turned out to overlap with
   check 1 about 84% of the time on synthetic data (MAs are themselves
   derived from the same price series driving the trend regression) —
   effectively double-counting one signal as two. RSI is a different
   input (momentum, not price level), so it's less redundant, but a
   follow-up test still showed ~75% agreement — RSI is still correlated
   with price trend, just less so. Treat check 5 as a weak second
   opinion, not an independent confirmation.

This mirrors sections 1-5 of the manual checklist. Sections 6 (risk:reward),
7 (position sizing), and 8 (time stop) are deliberately not automated —
those need a real entry and stop price, which only make sense once you've
looked at the flagged chart yourself.

**None of the above has run against live data yet** — same sandbox
limitation as before (no route to Yahoo from the build environment).
Trend/RSI/S-R logic is verified against synthetic OHLC only
(`test_patterns.py`). Run it for real before trusting any of it.

## Trade plan gate and backtest

`flag` is still the pattern/checklist gate (checks 1-5). On top of it each result
now carries an auto trade plan (`entry`, `stop`, `target`, `risk_pct`, `rr`,
`trade_ok`, built by `build_trade_plan`):

- **entry** — buy-stop just above the signal candle's high (needs follow-through,
  not bought blind at the close)
- **stop** — under the lower of the candle's low and the support zone
- **target** — nearest resistance above entry (`TARGET_LADDER_INDEX = 1` uses the next one)
- **trade_ok** — `rr >= MIN_RR` and stop no wider than `MAX_RISK_PCT`

Only `flag and trade_ok` setups are "flagged" in `latest_screen.json` and Discord;
setups that pass the pattern gate but fail R:R are listed under `watch` with the
reason in `notes`. This is checklist section 6 moved into code. `MIN_RR` and
`MAX_RISK_PCT` are starting values: set them to your sheet's numbers.

`backtest.py` replays the screener over 5 years of daily bars (no lookahead), plays
each plan forward (buy-stop, stop, target, time stop, gaps, costs) and prints R
results for: old flag vs R:R gate, each pattern, weak vs strong watchlist breadth,
and planned-R:R buckets. Run it from Actions -> Backtest -> Run workflow (the
report lands in the run summary). Tune `MIN_RR` / `TARGET_LADDER_INDEX` from its
table 4, not by feel. Biases: today's watchlist only (survivorship), daily bars,
flat cost percentage; fewer than ~30 trades per row is noise.

## Optional: Supabase persistence

`schema.sql` has a `daily_flags` table for history/trend-over-time
tracking. Not wired into `main.py` yet — phase 2, once the core screener
has run clean for a couple of weeks against live data.
