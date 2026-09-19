"""
Fetches current NEPSE live market prices (one row per stock) and upserts
them into Supabase, keyed by symbol.

Run inspect_live_price.py FIRST to confirm real field names, then adjust
normalize_row() below if they differ from what's assumed here.

Usage:
    python fetch_live_price.py
"""

import os
from datetime import datetime, date, timezone

from dotenv import load_dotenv
from supabase import create_client, Client
from nepse import Nepse

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
TABLE_NAME = "live_prices"
UPSERT_CHUNK_SIZE = 500


def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_nepse_client() -> Nepse:
    nepse = Nepse()
    nepse.setTLSVerification(False)
    return nepse


def normalize_row(row: dict, fetched_at: str) -> dict | None:
    """
    Map one raw live-market row into our Supabase table shape.

    Confirmed via inspect_live_price.py against real NEPSE data -- the real
    field names are: securityId, securityName, symbol, indexId, openPrice,
    highPrice, lowPrice, totalTradeQuantity, totalTradeValue,
    lastTradedPrice, percentageChange, lastUpdatedDateTime,
    lastTradedVolume, previousClose, averageTradedPrice.

    Two things NEPSE does NOT provide directly, so we derive them:
    - point_change: no such field exists -- calculated as
      lastTradedPrice - previousClose.
    - business_date: no separate field -- derived from the date portion
      of lastUpdatedDateTime instead.
    """
    symbol = row.get("symbol")
    if not symbol:
        return None

    ltp = row.get("lastTradedPrice")
    previous_close = row.get("previousClose")
    point_change = None
    if ltp is not None and previous_close is not None:
        point_change = round(ltp - previous_close, 4)

    business_date = None
    last_updated = row.get("lastUpdatedDateTime")
    if last_updated:
        try:
            business_date = str(date.fromisoformat(str(last_updated)[:10]))
        except ValueError:
            business_date = None

    return {
        "symbol": str(symbol),
        "security_name": row.get("securityName"),
        "ltp": ltp,
        "point_change": point_change,
        "percent_change": row.get("percentageChange"),
        "open_price": row.get("openPrice"),
        "high_price": row.get("highPrice"),
        "low_price": row.get("lowPrice"),
        "previous_close": previous_close,
        "volume": row.get("totalTradeQuantity"),
        "business_date": business_date,
        "fetched_at": fetched_at,
    }


def fetch_and_store() -> int:
    nepse = get_nepse_client()
    supabase = get_supabase_client()

    print(f"[{datetime.now()}] Fetching live market prices...")
    raw_data = nepse.getLiveMarket()

    if not raw_data:
        print("No data returned from NEPSE (market closed or no live data yet).")
        return 0

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = [normalize_row(r, fetched_at) for r in raw_data]
    rows = [r for r in rows if r is not None]

    if not rows:
        print("Got raw data but couldn't map any rows -- check normalize_row() "
              "against inspect_live_price.py output.")
        return 0

    print(f"Upserting {len(rows)} rows into '{TABLE_NAME}'...")
    for i in range(0, len(rows), UPSERT_CHUNK_SIZE):
        chunk = rows[i:i + UPSERT_CHUNK_SIZE]
        supabase.table(TABLE_NAME).upsert(chunk, on_conflict="symbol").execute()

    print("Done.")
    return len(rows)


if __name__ == "__main__":
    fetch_and_store()
