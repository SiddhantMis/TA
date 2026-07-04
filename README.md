# TA Screener

EOD pre-filter for a swing-trading watchlist. Flags candidates worth manual
review — it does not decide entries, stops, or position size. That's still
on you, using Trade_Evaluation_Sheet.xlsx sections 6-9.

## What's actually been verified vs. what hasn't

**Verified (runs with zero network access, checked in this session):**
Pattern detection logic (`test_patterns.py`) — 25/25 passing, covering
single-candle (Marubozu, Doji, Spinning Top, Hammer/Hanging Man,
Shooting Star/Inverted Hammer), two-candle (Engulfing, Piercing, Dark
Cloud Cover, Harami), and three-candle (Morning Star, Evening Star)
patterns, plus trend regression, pivot S/R, and RSI.

**Not yet verified:** the live `yfinance` fetch path (`fetch_ticker`,
`run_screen`). It couldn't be run in the build sandbox — no route to
Yahoo's data endpoints there. Test this for real using the manual
trigger below before trusting the daily schedule.

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

## What "flagged" means

Each ticker gets a `confidence` score (0-100, weighted) and a `recommendation`
string — not a single pass/fail. `flag` (bool) is kept only for backward
compatibility with the Discord alert threshold (4-of-5 weighted checks).
None of this is a trade signal; it's a ranking of how many boxes a setup
ticks, meant to cut 100+ tickers down to a handful worth opening a chart on.

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

## Optional: Supabase persistence

`schema.sql` has a `daily_flags` table for history/trend-over-time
tracking. Not wired into `main.py` yet — phase 2, once the core screener
has run clean for a couple of weeks against live data.
