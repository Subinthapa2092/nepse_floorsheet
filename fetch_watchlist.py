"""
Fetches per-SYMBOL data (company details, price history, market depth) for
a list of stocks you care about. Unlike fetch_all.py, these endpoints need
a specific stock symbol -- fetching them for all ~300 listed companies on
every run would be slow and heavy, so this uses a WATCHLIST you control.

Edit WATCHLIST below to the stock symbols you actually want to track.

Usage:
    python fetch_watchlist.py
"""

import os
from datetime import datetime, date, timezone

from dotenv import load_dotenv
from supabase import create_client, Client
from nepse import Nepse

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# Edit this list to the stock symbols you want detailed data for.
WATCHLIST = ["NABIL", "KBL", "NICA"]


def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_nepse_client() -> Nepse:
    nepse = Nepse()
    nepse.setTLSVerification(False)
    return nepse


def fetch_company_details(nepse, supabase, symbol, fetched_at):
    try:
        data = nepse.getCompanyDetails(symbol)
    except Exception as e:
        print(f"  [{symbol}] getCompanyDetails() failed: {e}")
        return
    if not data:
        return
    row = {
        "symbol": symbol,
        "raw": data,
        "fetched_at": fetched_at,
    }
    try:
        supabase.table("company_details").upsert([row], on_conflict="symbol").execute()
        print(f"  [{symbol}] company details stored.")
    except Exception as e:
        print(f"  [{symbol}] failed to store company details: {e}")


def fetch_market_depth(nepse, supabase, symbol, fetched_at):
    try:
        data = nepse.getSymbolMarketDepth(symbol)
    except Exception as e:
        print(f"  [{symbol}] getSymbolMarketDepth() failed: {e}")
        return
    if not data:
        return
    row = {
        "symbol": symbol,
        "fetched_at": fetched_at,
        "raw": data,
    }
    try:
        supabase.table("market_depth_snapshots").insert(row).execute()
        print(f"  [{symbol}] market depth stored.")
    except Exception as e:
        print(f"  [{symbol}] failed to store market depth: {e}")


def fetch_and_store():
    nepse = get_nepse_client()
    supabase = get_supabase_client()
    fetched_at = datetime.now(timezone.utc).isoformat()

    print(f"[{datetime.now()}] Fetching watchlist data for: {', '.join(WATCHLIST)}")
    for symbol in WATCHLIST:
        print(f"Processing {symbol}...")
        fetch_company_details(nepse, supabase, symbol, fetched_at)
        fetch_market_depth(nepse, supabase, symbol, fetched_at)

    print("Watchlist fetch complete.")


if __name__ == "__main__":
    fetch_and_store()
