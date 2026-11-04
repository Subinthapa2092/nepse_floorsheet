-- Run once in Supabase > SQL Editor.
-- Adds a 'verified' flag. Dates confirmed from a company notice are verified = true.
-- Dates you add from another source (such as a list you typed) should be verified = false: the chart shows them dimmed with "Unverified",
-- and the notice reader replaces them with the confirmed date when the company posts its notice.
alter table public.promoter_unlock add column if not exists verified boolean not null default true;
update public.promoter_unlock set verified = true;          -- the three you confirmed from notices (VLUCL, MKCL, NWCL)
alter table public.promoter_unlock alter column verified set default false;   -- anything added from now on is unverified unless you say otherwise
