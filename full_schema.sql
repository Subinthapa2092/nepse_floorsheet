-- Run this in Supabase SQL Editor, alongside supabase_schema.sql and
-- live_price_schema.sql. Covers every "no symbol needed" endpoint.
--
-- IMPORTANT: field names below are best-guess. Run inspect_all.py first,
-- compare against fetch_all.py's normalize_* functions, and adjust both
-- the Python mapping AND these column names/types if reality differs
-- meaningfully (e.g. a field turns out to be text where we assumed numeric).

-- One row per day: overall market summary
create table if not exists market_summary (
    business_date       date primary key,
    total_turnover       numeric,
    total_traded_shares   numeric,
    total_transactions    numeric,
    total_scrips_traded   numeric,
    market_cap            numeric,
    fetched_at            timestamptz default now()
);

-- One row per day: main NEPSE index value
create table if not exists nepse_index (
    business_date   date primary key,
    index_value     numeric,
    point_change    numeric,
    percent_change  numeric,
    fetched_at      timestamptz default now()
);

-- One row per sector index per day
create table if not exists nepse_sub_indices (
    index_name      text,
    business_date   date,
    index_value     numeric,
    point_change    numeric,
    percent_change  numeric,
    fetched_at      timestamptz default now(),
    primary key (index_name, business_date)
);

-- One row per stock per day: today's price/volume summary (distinct from
-- live_prices, which only ever holds the LATEST snapshot -- this is a
-- daily-close style record you can look back on).
create table if not exists daily_prices (
    symbol           text,
    business_date    date,
    open_price       numeric,
    high_price       numeric,
    low_price        numeric,
    close_price      numeric,
    total_volume     numeric,
    total_turnover   numeric,
    fetched_at       timestamptz default now(),
    primary key (symbol, business_date)
);

-- Rankings: gainers / losers / turnover / trade / transaction leaders.
-- "category" distinguishes which ranking a row belongs to.
create table if not exists market_rankings (
    category         text,   -- 'gainer' | 'loser' | 'turnover' | 'trade' | 'transaction'
    rank             int,
    symbol           text,
    business_date    date,
    value            numeric,   -- meaning depends on category (e.g. % change, turnover amount)
    fetched_at       timestamptz default now(),
    primary key (category, business_date, rank)
);

-- Company/security master list -- rarely changes, safe to upsert on symbol.
create table if not exists companies (
    symbol           text primary key,
    security_name    text,
    sector           text,
    raw              jsonb,   -- keep the full raw row too, in case useful fields exist
    fetched_at       timestamptz default now()
);

-- Market-wide supply/demand snapshot (structure varies, so we keep it as
-- raw JSON rather than guessing a rigid schema up front).
create table if not exists supply_demand_snapshots (
    fetched_at   timestamptz primary key default now(),
    raw          jsonb
);
