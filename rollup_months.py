"""
Rolls up every complete past month that isn't in floorsheet_monthly_summary
yet. Run this once now, and once a month after that (the workflow does it
automatically on the 2nd of each month).

FIX (this replaces an earlier, buggy version of this file): it used to
list months by reading every row of floorsheet_daily_summary, but
Supabase caps a plain .select() at 1000 rows per request. With your
table now holding well over a million rows, that silently saw only a
random slice and could miss months entirely. This version calls two
small SQL functions (distinct_daily_summary_months,
distinct_monthly_summary_months) that return just the handful of
distinct months directly, so the 1000-row cap is never hit.

Needs sql/monthly_rollup.sql installed first, and this file's matching
SQL (distinct_daily_summary_months / distinct_monthly_summary_months)
-- see rollup_months_functions.sql.

Only ADDS to floorsheet_monthly_summary. Never touches
floorsheet_daily_summary, floorsheet, or anything else. Safe to re-run --
a month already rolled up is skipped.

Usage:
    python rollup_months.py                 # roll up every month that's missing
    python rollup_months.py --dry-run        # only print which months it would do
"""
import argparse
import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def month_starts_in_daily_summary():
    rows = sb.rpc("distinct_daily_summary_months", {}).execute().data
    return sorted(str(r["month_start"]) for r in rows)


def already_rolled_up():
    rows = sb.rpc("distinct_monthly_summary_months", {}).execute().data
    return {str(r["month_start"]) for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    candidates = month_starts_in_daily_summary()
    done = already_rolled_up()
    todo = [m for m in candidates if m not in done]
    print(f"{len(candidates)} month(s) found in floorsheet_daily_summary: {candidates}")
    print(f"{len(done)} already rolled up: {sorted(done)}")
    print(f"{len(todo)} month(s) to roll up: {todo or 'none'}")

    if args.dry_run:
        return

    ok = failed = 0
    for m in todo:
        try:
            res = sb.rpc("rollup_month", {"p_month": m}).execute().data
            print(f"  {m}: {res}")
            ok += 1
        except Exception as e:
            # Most likely reason: this month isn't finished yet (the
            # current, still-running month) -- that's expected and fine,
            # it will simply get rolled up next month.
            print(f"  {m}: skipped -> {e}")
            failed += 1
    print(f"\nDone. {ok} month(s) rolled up, {failed} skipped.")


if __name__ == "__main__":
    main()
