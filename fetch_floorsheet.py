"""
Fetches the current NEPSE floorsheet and upserts it into a Supabase table.

Run inspect_raw_data.py FIRST to confirm the real field names, then adjust
normalize_row() below if they differ from what's assumed here.

Usage:
    python fetch_floorsheet.py
"""

import os
from datetime import datetime, date, timezone

from dotenv import load_dotenv
from supabase import create_client, Client
from nepse import Nepse

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
TABLE_NAME = "floorsheet"
UPSERT_CHUNK_SIZE = 500  # keep individual requests to Supabase reasonably sized


def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_nepse_client() -> Nepse:
    nepse = Nepse()
    nepse.setTLSVerification(False)  # NEPSE's server has a known incomplete cert chain
    return nepse


def normalize_row(row: dict, fetched_at: str) -> dict | None:
    """
    Map one raw floorsheet row (as returned by NepseUnofficialApi) into the
    shape of our Supabase table.

    NOTE: field names below are best-guess based on common NEPSE API shapes.
    Run inspect_raw_data.py and compare against your actual response --
    fix the .get(...) keys here if they don't match.
    """
    contract_no = row.get("contractId") or row.get("contractNo") or row.get("id")
    if not contract_no:
        return None  # skip anything we can't uniquely identify

    business_date_raw = row.get("businessDate") or row.get("tradeDate")
    business_date = None
    if business_date_raw:
        try:
            business_date = str(date.fromisoformat(str(business_date_raw)[:10]))
        except ValueError:
            business_date = None

    return {
        "contract_no": str(contract_no),
        "symbol": row.get("stockSymbol") or row.get("symbol"),
        "buyer_broker": str(row.get("buyerBrokerName") or row.get("buyerMemberId") or ""),
        "seller_broker": str(row.get("sellerBrokerName") or row.get("sellerMemberId") or ""),
        "quantity": row.get("contractQuantity") or row.get("quantity"),
        "rate": row.get("contractRate") or row.get("rate"),
        "amount": row.get("contractAmount") or row.get("amount"),
        "trade_time": str(row.get("tradeTime") or row.get("businessDate") or ""),
        "business_date": business_date,
        "fetched_at": fetched_at,
    }


def fetch_and_store() -> int:
    """Fetch the floorsheet once and upsert it into Supabase. Returns row count stored."""
    nepse = get_nepse_client()
    supabase = get_supabase_client()

    print(f"[{datetime.now()}] Fetching floorsheet...")
    raw_data = nepse.getFloorSheet()

    if not raw_data:
        print("No data returned from NEPSE (market closed or no trades yet today).")
        return 0

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = [normalize_row(r, fetched_at) for r in raw_data]
    rows = [r for r in rows if r is not None]

    if not rows:
        print("Got raw data but couldn't map any rows -- check normalize_row() "
              "against inspect_raw_data.py output.")
        return 0

    print(f"Upserting {len(rows)} rows into '{TABLE_NAME}'...")
    for i in range(0, len(rows), UPSERT_CHUNK_SIZE):
        chunk = rows[i:i + UPSERT_CHUNK_SIZE]
        supabase.table(TABLE_NAME).upsert(chunk, on_conflict="contract_no").execute()

    print("Done.")
    return len(rows)


if __name__ == "__main__":
    fetch_and_store()
