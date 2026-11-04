-- Run once in Supabase > SQL Editor. Private table: only the nightly job (service key) writes and reads it.
create table if not exists public.company_news (
  source     text   not null,          -- 'exchange' (NEPSE's own) or 'company' (posted by a company)
  news_id    bigint not null,
  title      text,
  company    text,
  added_on   date,
  file_path  text,                     -- the attached notice, as NEPSE stores it
  flagged    boolean not null default false,  -- mentions lock-in / promoter shares: check it
  reviewed   boolean not null default false,  -- you set this to true once you have dealt with it
  raw        jsonb,
  first_seen timestamptz not null default now(),
  primary key (source, news_id)
);
alter table public.company_news enable row level security;  -- no public policy on purpose
