"""
Daily job: add up finished days into floorsheet_daily_summary, delete their
raw trades, and keep only the last N days of summaries in Supabase.

Put this file in the nepse_floorsheet folder (next to fetch_floorsheet.py).
Run the SQL file rollup_and_prune.sql in Supabase first.

Usage:
    python rollup_and_prune.py                 # keep 2 raw days, 120 summary days
    python rollup_and_prune.py --keep-raw 2 --keep-summary 120
    python rollup_and_prune.py --dry-run       # only show what it WOULD archive

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
    ap.add_argument("--keep-summary", type=int, default=120, help="summary trading days to keep (default 120)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    days = [r["business_date"] for r in sb.rpc("days_to_archive", {"p_keep": args.keep_raw}).execute().data]
    days.sort()  # oldest first
    print(f"Raw days to archive: {days or 'none'}")

    failed = 0
    if not args.dry_run:
        for d in days:
            try:
                res = sb.rpc("archive_day", {"p_date": d}).execute().data
                print(f"  {d}: {res}")
            except Exception as e:  # keep going; a bad day is left untouched
                failed += 1
                print(f"  {d}: FAILED, nothing deleted -> {e}")
        res = sb.rpc("prune_summary", {"p_keep_days": args.keep_summary}).execute().data
        print(f"Summary window: {res}")

    if failed:
        raise SystemExit(f"{failed} day(s) failed")


if __name__ == "__main__":
    main()
