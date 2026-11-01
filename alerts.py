"""
Discord webhook alerting. Set DISCORD_WEBHOOK_URL as a GitHub Actions
repo secret (Settings > Secrets and variables > Actions) — never hardcode
it here or paste it anywhere outside that settings page.
"""
import os
import json
import urllib.error
import urllib.request


DISCORD_CONTENT_LIMIT = 2000


def build_alert_content(flagged: list[dict], session_note: str,
                        watch: list[dict] | None = None, breadth: float | None = None,
                        leaders: list[dict] | None = None,
                        benchmark: str = "NIFTYBEES.NS",
                        scan_coverage: dict | None = None,
                        wide_leaders: dict | None = None) -> str:
    """Pure function, no network -- separated specifically so the
    truncation logic can be unit-tested without a webhook, a mock
    server, or letting a test actually hit Discord."""
    watch_line = ""
    if watch:
        shown_watch = watch[:10]
        watch_line = "\nWatch only (pattern OK, trade plan failed the R:R gate): " + ", ".join(
            f"{w['ticker']} (R:R {w.get('rr')})" for w in shown_watch)
        if len(watch) > len(shown_watch):
            watch_line += f", +{len(watch) - len(shown_watch)} more on the Pages site"
    breadth_line = ""
    if breadth is not None and breadth < 0.25:
        breadth_line = (f"\n⚠ Only {breadth:.0%} of the watchlist is above its 50-day average — "
                        "reversal setups are riskier in broad weakness (see backtest by-breadth table).")
    coverage_line = ""
    if scan_coverage and scan_coverage.get("missing_tickers"):
        missing = scan_coverage["missing_tickers"]
        shown = ", ".join(missing[:8])
        if len(missing) > 8:
            shown += f", +{len(missing) - 8} more"
        coverage_line = (
            f"\n⚠ Partial scan: {scan_coverage['scored']}/{scan_coverage['requested']} "
            f"instruments scored. Missing: {shown}."
        )

    leader_block = ""
    if leaders is not None:
        if leaders:
            leader_rows = []
            for r in leaders[:5]:
                rs12 = r.get("relative_strength_12_1_pct")
                rs1 = r.get("relative_strength_1m_pct")
                rs6 = r.get("relative_strength_6m_pct")
                rank = r.get("leader_rank")
                detail = f"#{rank} `{r['ticker']}` {rs12:+.1f} pp vs {benchmark} (12-1)"
                if rs1 is not None:
                    detail += f", {rs1:+.1f} pp (1m)"
                if rs6 is not None:
                    detail += f", {rs6:+.1f} pp (6m)"
                leader_rows.append(detail)
            leader_block = (
                f"\n\n**Equity momentum leaders — relative return vs {benchmark}:**\n"
                + "\n".join(leader_rows)
                + "\n_Rank is watchlist-relative context; commodity ETFs are excluded. This is not a validated entry signal._"
            )
        else:
            leader_block = f"\n\n_Momentum ranking unavailable: no valid 12-1 data versus {benchmark}._"
    if wide_leaders:
        if wide_leaders.get("error"):
            leader_block += f"\n_Wide-universe leaders unavailable today: {str(wide_leaders['error'])[:120]}_"
        elif wide_leaders.get("leaders"):
            rows = []
            fired_rows = []
            for r in wide_leaders["leaders"]:
                p = r.get("plan") or {}
                for s in p.get("fired") or []:
                    fired_rows.append(f"\u25b6 `{r['ticker'].replace('.NS', '')}` **{s}** fired: buy next open, stop ~{p['stop_if_filled_at_ref']:.0f} "
                                      f"(-2 ATR, {p['risk_pct']}% risk), trail 3 ATR, {p['shares_per_1000_risk']} sh per Rs1,000 risk")
            for r in wide_leaders["leaders"][:6]:
                st = r.get("structure") or {}
                lv = ""
                if st.get("support_level") is not None:
                    lv += f" | S {st['support_level']:.0f} ({st.get('support_touches') or 0}x)"
                res = st.get("resistance_ladder") or []
                if res:
                    lv += f" R {res[0]['level']:.0f}"
                trig = ((r.get("plan") or {}).get("triggers") or {}).get("breakout55_close_above")
                rows.append(f"#{r['leader_rank']} `{r['ticker'].replace('.NS', '')}` RS {r['relative_strength_12_1_pct']:+.0f}pp"
                            f" | 6m {r.get('relative_strength_6m_pct') or 0:+.0f} | {r.get('pct_below_52w_high')}% off high{lv}"
                            + (f" | BO>{trig:.0f}" if trig else ""))
            c = wide_leaders.get("counts", {})
            leader_block = (f"\n\n**Momentum leaders** (liquid Nifty 500 top {c.get('liquid')}, above 200-DMA, "
                            f"{c.get('above_200dma')} qualify; RS = 12-1 vs {benchmark}):\n" + "\n".join(rows)
                            + ("\n" + "\n".join(fired_rows[:4]) if fired_rows else "\nNo setup fired today in the top 20.")
                            + f"\n_{str(wide_leaders.get('setup_record') or '')[:230]}_"
                            + (f"\n_{str(wide_leaders['scorecard_text'])[:200]}_" if wide_leaders.get("scorecard_text") else ""))
    if not flagged:
        content = (f"EOD screen: nothing worth a manual look from the legacy reversal checklist today "
                   f"(this is a pre-filter, not a verdict). {session_note}{coverage_line}{breadth_line}{watch_line}"
                   f"{leader_block}")
        return content[:DISCORD_CONTENT_LIMIT - 1] + "…" if len(content) > DISCORD_CONTENT_LIMIT else content

    lines = [f"**EOD screen — {len(flagged)} worth a manual look** {session_note}{coverage_line}{breadth_line}{leader_block}"]
    for r in flagged:
        plan = ""
        if r.get("entry") is not None and r.get("risk_pct") is not None:
            plan = (f"buy > {r['entry']} stop {r['stop']} target {r['target']} "
                    f"R:R {r['rr']} (risk {r['risk_pct']:.1%}) | ")
        lines.append(
            f"`{r['ticker']}` @ {r['close']} — {r['pattern']} | {plan}"
            f"trend: {r['trend']} | vol: {r['volume_ratio']}x | "
            f"support: {r['support_level']} ({r['support_touches']} touches) | "
            f"{r['checks_passed']}/{r['checks_total']} checks, confidence {r['confidence']}% | "
            f"{r['recommendation']}"
        )
    footer = watch_line + "\n_Pre-filter output — R:R is pre-checked against the auto plan; sizing and time stop (sections 7-9) are still by hand._"
    content = "\n".join(lines) + footer

    # Discord's hard content limit is 2000 chars. At 48 tickers this
    # isn't hypothetical anymore -- before this, an oversized payload
    # meant the whole alert silently failed (caught by the network
    # except block, logged to an Actions run nobody's watching live),
    # with no indication in Discord itself that anything was missed.
    if len(content) > DISCORD_CONTENT_LIMIT:
        shown = []
        budget = DISCORD_CONTENT_LIMIT - len(footer) - 100  # room for the truncation line + footer
        running = len(lines[0]) + 1
        for line in lines[1:]:
            if running + len(line) + 1 > budget:
                break
            shown.append(line)
            running += len(line) + 1
        omitted = len(lines) - 1 - len(shown)
        content = "\n".join([lines[0]] + shown)
        content += f"\n_...+{omitted} more flagged, truncated for Discord's message limit — see the full list on the Pages site._"
        content += footer

    return content


def send_discord_alert(flagged: list[dict], webhook_url: str | None = None, run_timestamp=None,
                       watch: list[dict] | None = None, breadth: float | None = None,
                       leaders: list[dict] | None = None,
                       benchmark: str = "NIFTYBEES.NS",
                       scan_coverage: dict | None = None,
                       wide_leaders: dict | None = None) -> None:
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("[alerts] DISCORD_WEBHOOK_URL not set, skipping alert")
        return

    ts_str = run_timestamp.strftime("%Y-%m-%d %H:%M IST") if run_timestamp else "unknown time"
    session_note = f"(last COMPLETE session as of {ts_str} — for planning tomorrow's open, not today's close)"
    content = build_alert_content(flagged, session_note, watch=watch, breadth=breadth,
                                  leaders=leaders, benchmark=benchmark,
                                  scan_coverage=scan_coverage, wide_leaders=wide_leaders)

    payload = json.dumps({"content": content}).encode()
    # Discord's endpoint sits behind Cloudflare, which has been known to
    # 403 the default urllib User-Agent ("Python-urllib/3.x") outright,
    # independent of whether the webhook URL itself is valid. A real UA
    # string avoids that specific false-positive block.
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; TA-screener-bot/1.0)",
        },
    )
    # A failed alert should never take down the whole run -- by the time
    # this is called, main.py has already written latest_screen.json, so
    # the only thing lost on failure is the notification, not the data.
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"[alerts] Discord post failed: HTTP {e.code} — {body}")
    except urllib.error.URLError as e:
        print(f"[alerts] Discord post failed: {e.reason}")


def send_discord_failure(message: str, webhook_url: str | None = None, run_timestamp=None) -> None:
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("[alerts] DISCORD_WEBHOOK_URL not set, skipping failure alert")
        return

    ts_str = run_timestamp.strftime("%Y-%m-%d %H:%M IST") if run_timestamp else "unknown time"
    payload = json.dumps({
        "content": f"**EOD screen failed** at {ts_str}: {message}"
    }).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; TA-screener-bot/1.0)",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"[alerts] Discord failure post failed: HTTP {e.code} — {body}")
    except urllib.error.URLError as e:
        print(f"[alerts] Discord failure post failed: {e.reason}")
