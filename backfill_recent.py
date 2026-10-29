"""
Fill in the last few days of daily prices (daily_prices table).

Use it when the daily job was down for a while, so the price history has a
gap. It only touches the days you ask for, one NEPSE request per day, and it
is safe to run again: rows are upserted, so nothing is duplicated.

Holidays and closed days return no data and are skipped automatically.

Usage:
    python backfill_recent.py          # last 21 days, including today
    python backfill_recent.py 40       # last 40 days
"""

import sys
import time
from datetime import date, timedelta

from fetch_historical_backfill import backfill_date, get_nepse_client, get_supabase_client

DEFAULT_DAYS = 21
DELAY_SECONDS = 0.5


def weekdays_back(days: int) -> list[str]:
    """Monday-Friday dates from today back `days` calendar days, newest first."""
    out = []
    for n in range(days + 1):
        d = date.today() - timedelta(days=n)
        if d.weekday() < 5:
            out.append(d.isoformat())
    return out


def main(days: int) -> None:
    nepse = get_nepse_client()
    supabase = get_supabase_client()
    todo = weekdays_back(days)
    print(f"Checking {len(todo)} weekdays ({todo[-1]} to {todo[0]})...")
    total, filled = 0, 0
    for d in todo:
        n = backfill_date(nepse, supabase, d)
        if n:
            filled += 1
            total += n
            print(f"  [{d}] stored {n} rows")
        time.sleep(DELAY_SECONDS)
    print(f"Done. {filled} trading day(s) saved, {total} rows in total.")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    main(int(arg) if arg.isdigit() and 1 <= int(arg) <= 120 else DEFAULT_DAYS)
