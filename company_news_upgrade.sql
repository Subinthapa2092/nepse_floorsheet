-- Run once in Supabase > SQL Editor. Adds the columns the notice reader needs.
alter table public.company_news
  add column if not exists status   text,    -- null = not read yet, 'published' = date added automatically, 'review' = check by hand
  add column if not exists result   jsonb,   -- what was read, and why it was or was not published
  add column if not exists ocr_text text;

-- Your "check by hand" list:
--   select news_id, title, added_on, result->>'why' as why from public.company_news where status = 'review' and reviewed = false order by added_on desc;
