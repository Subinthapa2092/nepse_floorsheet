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

    NOTE: field names are best-guess based on common NEPSE API shapes.
    Run inspect_live_price.py and compare against the real response --
    fix the .get(...) keys here if they don't match.
    """
    symbol = row.get("symbol") or row.get("stockSymbol")
    if not symbol:
        return None

    business_date_raw = row.get("businessDate") or row.get("tradeDate")
    business_date = None
    if business_date_raw:
        try:
            business_date = str(date.fromisoformat(str(business_date_raw)[:10]))
        except ValueError:
            business_date = None

    return {
        "symbol": str(symbol),
        "security_name": row.get("securityName") or row.get("securityDesc"),
        "ltp": row.get("lastTradedPrice") or row.get("ltp"),
        "point_change": row.get("pointChange") or row.get("change"),
        "percent_change": row.get("percentageChange") or row.get("percentChange"),
        "open_price": row.get("openPrice"),
        "high_price": row.get("highPrice"),
        "low_price": row.get("lowPrice"),
        "previous_close": row.get("previousClose") or row.get("closePrice"),
        "volume": row.get("totalTradeQuantity") or row.get("volume"),
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
