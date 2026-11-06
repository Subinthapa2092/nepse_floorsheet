"""
Daily job: save intraday candles, add up finished days into floorsheet_daily_summary, delete their
raw trades, and keep the current and previous month day by day. Older months are rolled into
floorsheet_monthly_summary (only when the totals match exactly) and then removed from the daily table.

Put this file in the nepse_floorsheet folder (next to fetch_floorsheet.py).
Run the SQL file rollup_and_prune.sql in Supabase first.

Usage:
    python rollup_and_prune.py                 # keep 2 raw days, 2 months day by day
    python rollup_and_prune.py --keep-raw 2 --keep-months 2
    python rollup_and_prune.py --dry-run       # only show what it WOULD archive and roll up

Safe to re-run any time. Each day is checked (totals must match the raw
trades) before its raw rows are deleted; a failed day changes nothing.
"""
import argparse
import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-raw", type=int, default=2, help="raw trading days to keep (default 2)")
    ap.add_argument("--keep-months", type=int, default=2, help="months kept day by day, counting the current one (default 2)")
    ap.add_argument("--keep-summary", type=int, default=240, help="only used if roll_and_prune_months is not installed yet (old rule: trading days kept)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Save the 5-minute and hourly candles of every day that still has raw trades BEFORE anything is deleted.
    # (Needs sql/intraday_bars.sql to have been run once in Supabase. If it was not, this only prints a warning.)
    if not args.dry_run:
        try:
            print("Intraday candles:", sb.rpc("save_all_intraday_candles").execute().data)
        except Exception as e:  # never block the normal archive
            print(f"Intraday candles NOT saved ({e}). Run sql/intraday_bars.sql in Supabase.")

    days = [r["business_date"] for r in sb.rpc("days_to_archive", {"p_keep": args.keep_raw}).execute().data]
    days.sort()  # oldest first
    print(f"Raw days to archive: {days or 'none'}")

    failed = 0
    if args.dry_run:
        try:
            print("Monthly roll-up (dry run):", sb.rpc("roll_and_prune_months", {"p_keep_months": args.keep_months, "p_apply": False}).execute().data)
        except Exception as e:
            print(f"Monthly roll-up not available ({e}). Run sql/cleanup_step3_month_rollup.sql in Supabase.")
    if not args.dry_run:
        for d in days:
            try:
                res = sb.rpc("archive_day", {"p_date": d}).execute().data
                print(f"  {d}: {res}")
            except Exception as e:  # keep going; a bad day is left untouched
                failed += 1
                print(f"  {d}: FAILED, nothing deleted -> {e}")
        try:
            res = sb.rpc("roll_and_prune_months", {"p_keep_months": args.keep_months, "p_apply": True}).execute().data
            print(f"Monthly roll-up: {res}")
        except Exception as e:  # SQL not installed yet: keep the old behaviour instead of failing
            print(f"Monthly roll-up NOT done ({e}). Using the old rule: keep {args.keep_summary} days.")
            res = sb.rpc("prune_summary", {"p_keep_days": args.keep_summary}).execute().data
            print(f"Summary window: {res}")

    if failed:
        raise SystemExit(f"{failed} day(s) failed")


if __name__ == "__main__":
    main()
