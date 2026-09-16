-- Run this in the Supabase SQL Editor (Project -> SQL Editor -> New query)
-- before running the fetcher for the first time.

create table if not exists floorsheet (
    -- contract_no is unique per trade, so we use it as the primary key.
    -- This is what lets us re-run the fetcher every few minutes all day
    -- without inserting the same trade twice (upsert on conflict).
    contract_no      text primary key,
    symbol           text,
    buyer_broker     text,
    seller_broker    text,
    quantity         numeric,
    rate             numeric,
    amount           numeric,
    trade_time       text,
    business_date    date,
    fetched_at       timestamptz default now()
);

create index if not exists idx_floorsheet_symbol on floorsheet (symbol);
create index if not exists idx_floorsheet_business_date on floorsheet (business_date);
create index if not exists idx_floorsheet_fetched_at on floorsheet (fetched_at);

-- Optional: row-level security. If you enable RLS on this table later,
-- remember the fetcher script uses the service role key, which bypasses
-- RLS automatically, so it will keep working either way.
