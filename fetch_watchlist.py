"""
Fetches per-SYMBOL data (company details, market depth) for stocks.

By default this now fetches ALL actively listed securities (~500+), not
just a hand-picked few -- since getCompanyDetails() and
getSymbolMarketDepth() both require a specific symbol, there's no
"fetch everyone at once" endpoint; this script simply loops through
every symbol one at a time.

IMPORTANT: this means ~500-1000+ individual HTTP requests to NEPSE per
run. That's slow (several minutes) and puts real load on their server.
See the "How often to run this" note in fetch-floorsheet.yml / README.md --
this should run much less often than the 5-minute floorsheet/live-price
fetchers (e.g. once or a few times a day), not every 5 minutes.

If you'd rather track a specific short list instead of the whole market,
set WATCHLIST_OVERRIDE below to a list of symbols.

Usage:
    python fetch_watchlist.py
"""

import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client, Client
from nepse import Nepse

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# Set this to a list like ["NABIL", "KBL", "NICA"] to limit to specific
# stocks instead of the whole market. Leave as None to fetch everything.
WATCHLIST_OVERRIDE = None

# Small pause between requests so we're not hammering NEPSE's server.
REQUEST_DELAY_SECONDS = 0.3


def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_nepse_client() -> Nepse:
    nepse = Nepse()
    nepse.setTLSVerification(False)
    return nepse


def get_symbols_to_fetch(nepse) -> list[str]:
    if WATCHLIST_OVERRIDE:
        return WATCHLIST_OVERRIDE
    try:
        securities = nepse.getSecurityList()
    except Exception as e:
        print(f"Failed to fetch security list: {e}")
        return []
    # Only actively traded securities (activeStatus "A"), based on the
    # real fields confirmed via inspect_all.py.
    symbols = [s["symbol"] for s in securities if s.get("activeStatus") == "A" and s.get("symbol")]
    return symbols


def fetch_company_details(nepse, supabase, symbol, fetched_at):
    try:
        data = nepse.getCompanyDetails(symbol)
    except Exception as e:
        print(f"  [{symbol}] getCompanyDetails() failed: {e}")
        return False
    if not data:
        return False
    row = {"symbol": symbol, "raw": data, "fetched_at": fetched_at}
    try:
        supabase.table("company_details").upsert([row], on_conflict="symbol").execute()
        return True
    except Exception as e:
        print(f"  [{symbol}] failed to store company details: {e}")
        return False


def fetch_market_depth(nepse, supabase, symbol, fetched_at):
    try:
        data = nepse.getSymbolMarketDepth(symbol)
    except Exception as e:
        print(f"  [{symbol}] getSymbolMarketDepth() failed: {e}")
        return False
    if not data:
        return False
    row = {"symbol": symbol, "fetched_at": fetched_at, "raw": data}
    try:
        supabase.table("market_depth_snapshots").insert(row).execute()
        return True
    except Exception as e:
        print(f"  [{symbol}] failed to store market depth: {e}")
        return False


def fetch_and_store():
    nepse = get_nepse_client()
    supabase = get_supabase_client()
    fetched_at = datetime.now(timezone.utc).isoformat()

    # Market depth (the live order book) only exists while NEPSE is
    # actually open -- outside trading hours, the endpoint returns an
    # empty response for every symbol, not real data. Check once up
    # front instead of failing 500+ times.
    try:
        market_status = nepse.isNepseOpen()
        market_is_open = isinstance(market_status, dict) and market_status.get("isOpen") == "OPEN"
    except Exception as e:
        print(f"Could not check market status ({e}); will still attempt market depth.")
        market_is_open = True  # fail open, so we don't wrongly skip during real trading hours

    if not market_is_open:
        print("Market is CLOSED -- skipping market depth fetch (order book is only "
              "available while trading is live). Company details will still be fetched.")

    symbols = get_symbols_to_fetch(nepse)
    print(f"[{datetime.now()}] Fetching watchlist data for {len(symbols)} symbol(s)...")

    details_ok, depth_ok = 0, 0
    for i, symbol in enumerate(symbols, start=1):
        details_ok += fetch_company_details(nepse, supabase, symbol, fetched_at)
        if market_is_open:
            depth_ok += fetch_market_depth(nepse, supabase, symbol, fetched_at)
        if i % 25 == 0 or i == len(symbols):
            print(f"  progress: {i}/{len(symbols)} symbols processed")
        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Watchlist fetch complete. company_details stored: {details_ok}, "
          f"market_depth stored: {depth_ok}"
          + (" (market was closed, so this is expected to be 0)" if not market_is_open else ""))


if __name__ == "__main__":
    fetch_and_store()

