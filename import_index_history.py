"""
One-time backfill: loads nepse_indices.sqlite (NEPSE index + all 16 sector
sub-indices, back to 2014) into your EXISTING Supabase tables `nepse_index`
and `nepse_sub_indices` -- the same two tables your live pipeline already
writes to every 5 minutes.

WHERE TO RUN IT: in your nepse_floorsheet folder, next to fetch_brokers.py
(same .env, same SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).

WHERE THE DATA COMES FROM: copy nepse_indices.sqlite into that same folder
first.

SAFETY -- this can only ADD rows, never change or remove existing ones:
  - It first reads which dates you already have, then inserts only the
    dates you don't -- a plain insert, not an upsert, so there is no way
    for it to overwrite a row your live pipeline already wrote.
  - It never touches `floorsheet`, `live_prices`, or any other table.
  - Running it twice is harmless -- the second run finds nothing left to add.

ONE ROW IS DROPPED ON PURPOSE: "Nepse1" in the sqlite file is a byte-for-byte
duplicate of "NEPSE" (checked: identical date range, identical values on
every date) -- almost certainly a labelling artifact from whatever produced
this file. It carries no extra information, so it's skipped rather than
imported as if it were a real 18th index.

Run:
    python import_index_history.py
Optional: point it at the file explicitly --
    python import_index_history.py --file /path/to/nepse_indices.sqlite
"""

import argparse
import os
import sqlite3

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

BATCH_SIZE = 500
DUPLICATE_INDEX_NAMES = {"Nepse1"}  # confirmed identical to "NEPSE"; skipped


def chunks(rows, size):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def existing_dates(supabase, table, select, key):
    """Every date (or (name, date) pair) already stored, so we only ever add
    what's missing -- never touch what's already there."""
    out = set()
    start = 0
    while True:
        res = supabase.table(table).select(select).range(start, start + 999).execute()
        rows = res.data or []
        for r in rows:
            out.add(key(r))
        if len(rows) < 1000:
            break
        start += 1000
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="nepse_indices.sqlite")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(f"Can't find {args.file}. Copy nepse_indices.sqlite next to this script,")
        print("or pass --file /full/path/to/nepse_indices.sqlite")
        return

    con = sqlite3.connect(args.file)
    cur = con.cursor()
    cur.execute("select index_name, date, index_value, abs_change, pct_change from index_history")
    all_rows = cur.fetchall()
    con.close()

    nepse_rows = []
    sub_rows = []
    skipped = 0
    for name, date, value, abs_change, pct_change in all_rows:
        if name in DUPLICATE_INDEX_NAMES:
            skipped += 1
            continue
        row = {
            "business_date": date,
            "index_value": value,
            "point_change": abs_change,
            "percent_change": pct_change,
        }
        if name == "NEPSE":
            nepse_rows.append(row)
        else:
            sub_rows.append({**row, "index_name": name})

    print(f"Read {len(all_rows)} rows from {args.file}:")
    print(f"  {len(nepse_rows)} NEPSE index rows")
    print(f"  {len(sub_rows)} sector sub-index rows")
    print(f"  {skipped} rows skipped (duplicate 'Nepse1' label)")
    print()

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Checking which dates nepse_index already has...")
    have_nepse = existing_dates(supabase, "nepse_index", "business_date", lambda r: r["business_date"])
    new_nepse = [r for r in nepse_rows if r["business_date"] not in have_nepse]
    print(f"  {len(have_nepse)} already there, {len(new_nepse)} missing -> will be added")

    print("Checking which (sector, date) pairs nepse_sub_indices already has...")
    have_sub = existing_dates(
        supabase, "nepse_sub_indices", "index_name,business_date",
        lambda r: (r["index_name"], r["business_date"])
    )
    new_sub = [r for r in sub_rows if (r["index_name"], r["business_date"]) not in have_sub]
    print(f"  {len(have_sub)} already there, {len(new_sub)} missing -> will be added")
    print()

    print("Adding missing NEPSE index days...")
    added = 0
    for batch in chunks(new_nepse, BATCH_SIZE):
        supabase.table("nepse_index").insert(batch).execute()
        added += len(batch)
        print(f"  {added}/{len(new_nepse)}")

    print("\nAdding missing sector sub-index days...")
    added = 0
    for batch in chunks(new_sub, BATCH_SIZE):
        supabase.table("nepse_sub_indices").insert(batch).execute()
        added += len(batch)
        print(f"  {added}/{len(new_sub)}")

    print("\nDone. Nothing that already existed was changed; only missing historical days were added.")


if __name__ == "__main__":
    main()