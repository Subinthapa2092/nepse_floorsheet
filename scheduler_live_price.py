"""
Runs fetch_live_price.fetch_and_store() on a tight loop during NEPSE market
hours. This is separate from scheduler.py (which handles the floorsheet)
because live prices are cheap to fetch and worth polling much more often.

IMPORTANT: this only works if this script keeps running continuously
(your own machine, or a small always-on VPS). GitHub Actions cannot poll
faster than every 5 minutes, so sub-minute polling is NOT possible there --
see README.md for details.

Usage:
    python scheduler_live_price.py
"""

import time
from datetime import datetime

import pytz

from fetch_live_price import fetch_and_store

NEPAL_TZ = pytz.timezone("Asia/Kathmandu")

MARKET_START_HOUR, MARKET_START_MIN = 11, 0
MARKET_END_HOUR, MARKET_END_MIN = 15, 0
TRADING_WEEKDAYS = {6, 0, 1, 2, 3}  # Sun, Mon, Tue, Wed, Thu

POLL_INTERVAL_SECONDS = 60          # how often to fetch live prices during market hours
IDLE_CHECK_INTERVAL_SECONDS = 15 * 60


def is_market_hours(now: datetime) -> bool:
    if now.weekday() not in TRADING_WEEKDAYS:
        return False
    start = now.replace(hour=MARKET_START_HOUR, minute=MARKET_START_MIN, second=0, microsecond=0)
    end = now.replace(hour=MARKET_END_HOUR, minute=MARKET_END_MIN, second=0, microsecond=0)
    return start <= now <= end


def main():
    print(f"NEPSE live price scheduler started (polling every "
          f"{POLL_INTERVAL_SECONDS}s during market hours). Press Ctrl+C to stop.")
    while True:
        now = datetime.now(NEPAL_TZ)

        if is_market_hours(now):
            try:
                fetch_and_store()
            except Exception as e:
                print(f"[{now}] Fetch failed: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)
        else:
            print(f"[{now}] Outside market hours, waiting...")
            time.sleep(IDLE_CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
