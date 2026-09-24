"""
Fills the `brokers` table (broker number -> broker name) so NepseDrishti can
show "58  Naasa Securities" instead of just the name.

WHERE TO RUN IT: inside your nepse_floorsheet project folder (the one that has
fetch_floorsheet.py and your .env). Copy this file there, then:

    python fetch_brokers.py

You only need to run it once, then again now and then (new brokers are rare).
It reads NEPSE's floorsheet once and saves each broker's number and name.
It never touches the `floorsheet` table.
"""

import os

from dotenv import load_dotenv
from supabase import create_client
from nepse import Nepse

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# NEPSE's field names can differ slightly between versions, so try a few.
BUYER_NO = ("buyerMemberId", "buyerBrokerId", "buyerMemberCode", "buyerBrokerNo")
BUYER_NAME = ("buyerBrokerName", "buyerMemberName")
SELLER_NO = ("sellerMemberId", "sellerBrokerId", "sellerMemberCode", "sellerBrokerNo")
SELLER_NAME = ("sellerBrokerName", "sellerMemberName")


def first(row: dict, keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    return None


def main():
    nepse = Nepse()
    nepse.setTLSVerification(False)  # NEPSE's server has a known incomplete cert chain

    print("Fetching floorsheet (this can take a little while)...")
    data = nepse.getFloorSheet()
    if not data:
        print("No data returned (market closed with nothing cached). Try again during/after market hours.")
        return

    brokers = {}
    for row in data:
        for no_keys, name_keys in ((BUYER_NO, BUYER_NAME), (SELLER_NO, SELLER_NAME)):
            no = first(row, no_keys)
            name = first(row, name_keys)
            if no is not None and name:
                brokers[str(no).strip()] = str(name).strip()

    if not brokers:
        print("Could not find broker numbers/names in the data.")
        print("Keys in one row:", sorted(data[0].keys()))
        print("Tell me those keys and I will adjust BUYER_NO / BUYER_NAME above.")
        return

    rows = [{"broker_no": no, "broker_name": name} for no, name in sorted(brokers.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 10**9)]
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    supabase.table("brokers").upsert(rows, on_conflict="broker_no").execute()

    print(f"Saved {len(rows)} brokers. Examples:")
    for r in rows[:5]:
        print(f"  {r['broker_no']:>4}  {r['broker_name']}")


if __name__ == "__main__":
    main()
