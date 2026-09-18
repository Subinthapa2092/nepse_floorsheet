"""
ONE-TIME BACKFILL -- run this manually once (not on a schedule), to load
roughly the last year of daily OHLC price history for every stock into
your daily_prices table.

Confirmed via inspect_historical.py: getPriceVolumeHistory(business_date)
gives full open/high/low/close/volume/turnover for ALL ~340 stocks in a
single call, for any given past date. NEPSE's per-company history endpoint
was confirmed capped at ~1 year regardless of requested start date, so
that's the realistic depth available in one pull -- looping day-by-day
using the ALL-STOCKS endpoint is more complete (has open price + market
cap, which the per-company endpoint lacks) and needs far fewer calls than
looping per-symbol (365 calls total vs. 540+ calls with less data each).

This will take a while (one request per trading day, ~250-260 trading
days in a year) and puts real, sustained load on NEPSE's server -- that's
expected for a one-time backfill, just don't run it repeatedly.

Usage:
    python fetch_historical_backfill.py
"""

import os
import time
from datetime import date, timedelta, datetime, timezone

from dotenv import load_dotenv
from supabase import create_client, Client
from nepse import Nepse

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

DAYS_BACK = 365          # how far back to attempt (NEPSE caps around here anyway)
REQUEST_DELAY_SECONDS = 0.5
UPSERT_CHUNK_SIZE = 500


def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_nepse_client() -> Nepse:
    nepse = Nepse()
    nepse.setTLSVerification(False)
    return nepse


def trading_days_back(days_back: int) -> list[str]:
    """NEPSE trades Monday-Friday (current schedule, since April 2026)."""
    days = []
    d = date.today() - timedelta(days=1)  # start from yesterday
    while len(days) < days_back:
        if d.weekday() < 5:  # 0=Mon ... 4=Fri
            days.append(d.isoformat())
        d -= timedelta(days=1)
    return days


def backfill_date(nepse, supabase, business_date: str) -> int:
    try:
        response = nepse.getPriceVolumeHistory(business_date=business_date)
        data = response.get("content", []) if response else []
    except Exception as e:
        print(f"  [{business_date}] fetch failed: {e}")
        return 0

    if not data:
        print(f"  [{business_date}] no data (likely a holiday/closed day) -- skipping.")
        return 0

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for entry in data:
        symbol = entry.get("symbol")
        if not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "business_date": business_date,
            "open_price": entry.get("openPrice"),
            "high_price": entry.get("highPrice"),
            "low_price": entry.get("lowPrice"),
            "close_price": entry.get("closePrice"),
            "total_volume": entry.get("totalTradedQuantity"),
            "total_turnover": entry.get("totalTradedValue"),
            "fetched_at": fetched_at,
        })

    if not rows:
        return 0

    try:
        for i in range(0, len(rows), UPSERT_CHUNK_SIZE):
            chunk = rows[i:i + UPSERT_CHUNK_SIZE]
            supabase.table("daily_prices").upsert(chunk, on_conflict="symbol,business_date").execute()
    except Exception as e:
        print(f"  [{business_date}] failed to store: {e}")
        return 0

    return len(rows)


def main():
    nepse = get_nepse_client()
    supabase = get_supabase_client()

    days = trading_days_back(DAYS_BACK)
    print(f"Backfilling {len(days)} candidate trading days "
          f"({days[-1]} to {days[0]})...")

    total_rows = 0
    for i, business_date in enumerate(days, start=1):
        stored = backfill_date(nepse, supabase, business_date)
        total_rows += stored
        if stored:
            print(f"  [{business_date}] stored {stored} rows "
                  f"({i}/{len(days)} days processed)")
        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\nBackfill complete. Total rows stored: {total_rows}")


if __name__ == "__main__":
    main()
