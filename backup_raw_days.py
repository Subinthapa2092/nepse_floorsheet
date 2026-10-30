"""
Saves the individual trades of the days that are about to be archived from
Supabase into a LOCAL file (data/raw_backup.db) BEFORE they are deleted.
It only READS from Supabase. It never deletes or changes anything there,
and it never touches your nepse_archive.db.

Put it in D:\nepse_floorsheet, then:
    python backup_raw_days.py            # backs up every day rollup would archive
    python backup_raw_days.py --keep-raw 2

Safe to re-run: a day is only skipped if the local count already matches
Supabase exactly.
"""
import argparse
import os
import sqlite3

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

PAGE = 1000
COLS = ["contract_no", "symbol", "buyer_broker", "seller_broker", "quantity",
        "rate", "amount", "trade_time", "business_date"]


def remote_count(day):
    r = sb.table("floorsheet").select("contract_no", count="exact").eq("business_date", day).limit(1).execute()
    return r.count


def local_count(conn, day):
    return conn.execute("select count(*) from floorsheet where business_date=?", (day,)).fetchone()[0]


def backup_day(conn, day):
    want = remote_count(day)
    if local_count(conn, day) == want:
        print(f"  {day}: already saved ({want} trades), skipping")
        return True
    conn.execute("delete from floorsheet where business_date=?", (day,))  # redo cleanly
    start, got = 0, 0
    while True:
        rows = (sb.table("floorsheet").select(",".join(COLS)).eq("business_date", day)
                .order("contract_no").range(start, start + PAGE - 1).execute().data)
        if not rows:
            break
        conn.executemany(
            f"insert or replace into floorsheet ({','.join(COLS)}) values ({','.join('?'*len(COLS))})",
            [tuple(r[c] for c in COLS) for r in rows])
        got += len(rows)
        start += PAGE
        if len(rows) < PAGE:
            break
    conn.commit()
    ok = local_count(conn, day) == want
    print(f"  {day}: saved {local_count(conn, day)} of {want} trades -> {'OK' if ok else 'MISMATCH'}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-raw", type=int, default=2)
    args = ap.parse_args()

    days = sorted(r["business_date"] for r in sb.rpc("days_to_archive", {"p_keep": args.keep_raw}).execute().data)
    print(f"Days to back up: {days or 'none'}")

    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect("data/raw_backup.db")
    conn.execute("""create table if not exists floorsheet (
        contract_no text primary key, symbol text, buyer_broker text, seller_broker text,
        quantity real, rate real, amount real, trade_time text, business_date text)""")
    conn.execute("create index if not exists i_date on floorsheet(business_date)")

    bad = [d for d in days if not backup_day(conn, d)]
    if bad:
        raise SystemExit(f"NOT SAFE to archive: these days did not match: {bad}")
    print("All days saved and counts match. Safe to run rollup_and_prune.py.")


if __name__ == "__main__":
    main()