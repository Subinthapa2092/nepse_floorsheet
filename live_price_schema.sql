-- Run this in the Supabase SQL Editor, same as supabase_schema.sql.
-- This creates a SEPARATE table from floorsheet, for live per-stock prices.

create table if not exists live_prices (
    -- symbol is the natural unique key here: one row per stock, always
    -- overwritten with its latest price (unlike floorsheet, we don't want
    -- history of every tick -- just the current snapshot per stock).
    symbol           text primary key,
    security_name    text,
    ltp              numeric,        -- last traded price
    point_change     numeric,
    percent_change   numeric,
    open_price       numeric,
    high_price       numeric,
    low_price        numeric,
    previous_close   numeric,
    volume           numeric,
    business_date    date,
    fetched_at       timestamptz default now()
);

create index if not exists idx_live_prices_business_date on live_prices (business_date);

-- OPTIONAL: if you'd rather keep a full history of every price snapshot
-- over time (not just the latest), use this table instead and insert
-- (not upsert) into it. This grows fast if polled every minute, so only
-- do this if you actually want a price history / time series.
--
-- create table if not exists live_prices_history (
--     id               bigserial primary key,
--     symbol           text,
--     ltp              numeric,
--     percent_change   numeric,
--     volume           numeric,
--     fetched_at       timestamptz default now()
-- );
-- create index if not exists idx_live_prices_history_symbol_time
--     on live_prices_history (symbol, fetched_at);

-- Used by fetch_watchlist.py -- per-symbol company details (kept as raw
-- JSON since the exact shape of getCompanyDetails() varies by symbol type).
create table if not exists company_details (
    symbol       text primary key,
    raw          jsonb,
    fetched_at   timestamptz default now()
);

-- Used by fetch_watchlist.py -- market depth snapshots (order book) over
-- time. Uses insert, not upsert, since each snapshot is a distinct moment.
create table if not exists market_depth_snapshots (
    id           bigserial primary key,
    symbol       text,
    raw          jsonb,
    fetched_at   timestamptz default now()
);
create index if not exists idx_market_depth_symbol_time
    on market_depth_snapshots (symbol, fetched_at);
