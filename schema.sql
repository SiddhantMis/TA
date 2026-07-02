-- Optional persistence layer. Run this in Supabase SQL editor once you're
-- ready to store history for the "last 10 day report" view — not wired
-- into main.py yet, that's the next phase after the core screener is
-- validated against live data.

create table if not exists daily_flags (
    id bigint generated always as identity primary key,
    ticker text not null,
    scan_date date not null,
    close numeric,
    trend text,
    pattern text,
    near_support boolean,
    support_level numeric,
    resistance_level numeric,
    volume_ratio numeric,
    rsi numeric,
    checks_passed int,
    checks_total int,
    flagged boolean,
    created_at timestamptz default now(),
    unique (ticker, scan_date)
);

create index if not exists idx_daily_flags_ticker_date
    on daily_flags (ticker, scan_date desc);
