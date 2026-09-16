"""
Runs fetch_and_store() automatically, on a loop, but ONLY during NEPSE
trading hours (Sun-Thu, roughly 11:00-15:00 Nepal time). Outside that
window it just sleeps and checks again periodically.

Keep this running with something that survives reboots/crashes, e.g.:
    - a systemd service (Linux server / Raspberry Pi)
    - `pm2 start scheduler.py --interpreter python3` (if you use pm2)
    - a simple `nohup python scheduler.py &` for a quick test
    - or don't use this file at all, and use the GitHub Actions workflow
      in .github/workflows/fetch-floorsheet.yml instead (no server needed)

Usage:
    python scheduler.py
"""

import time
from datetime import datetime

import pytz

from fetch_floorsheet import fetch_and_store

NEPAL_TZ = pytz.timezone("Asia/Kathmandu")

# NEPSE trading window (adjust if NEPSE changes official hours)
MARKET_START_HOUR, MARKET_START_MIN = 11, 0
MARKET_END_HOUR, MARKET_END_MIN = 15, 0

# Python's date.weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
# NEPSE trades Sunday through Thursday.
TRADING_WEEKDAYS = {6, 0, 1, 2, 3}  # Sun, Mon, Tue, Wed, Thu

POLL_INTERVAL_SECONDS = 5 * 60      # how often to fetch during market hours
IDLE_CHECK_INTERVAL_SECONDS = 15 * 60  # how often to check the clock when market's closed


def is_market_hours(now: datetime) -> bool:
    if now.weekday() not in TRADING_WEEKDAYS:
        return False
    start = now.replace(hour=MARKET_START_HOUR, minute=MARKET_START_MIN, second=0, microsecond=0)
    end = now.replace(hour=MARKET_END_HOUR, minute=MARKET_END_MIN, second=0, microsecond=0)
    return start <= now <= end


def main():
    print("NEPSE floorsheet scheduler started. Press Ctrl+C to stop.")
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
