# TA Screener

EOD pre-filter for a swing-trading watchlist. Flags candidates worth manual
review — it does not decide entries, stops, or position size. That's still
on you, using Trade_Evaluation_Sheet.xlsx sections 6-9.

## What's actually been verified vs. what hasn't

**Verified (runs with zero network access, checked in this session):**
Pattern detection logic (`test_patterns.py`) — 8/8 passing, including
regression checks against real HDFCBANK/ETERNAL/MCX candles that were
hand-verified earlier this week.

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

A ticker is flagged when it passes 4 of 5 automated checks:
1. Defined trend (not choppy) over the last 15 candles
2. A candlestick pattern present, in the right context for that trend
3. Price within 2% of a 20-day rolling support/resistance level
4. Volume at or above its 20-day average
5. Price above both the 20 EMA and 50 SMA

This mirrors sections 1-5 of the manual checklist. Sections 6 (risk:reward),
7 (position sizing), and 8 (time stop) are deliberately not automated —
those need a real entry and stop price, which only make sense once you've
looked at the flagged chart yourself.

## Optional: Supabase persistence

`schema.sql` has a `daily_flags` table for history/trend-over-time
tracking. Not wired into `main.py` yet — phase 2, once the core screener
has run clean for a couple of weeks against live data.
