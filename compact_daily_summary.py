"""
One-off: give back the dead space in floorsheet_daily_summary WITHOUT needing free room.

Why: deleting rows (August and September) leaves the disk space inside the table, so Supabase still counts it.
VACUUM FULL would need a second copy of the table. This does it another way:

  1) python compact_daily_summary.py export     saves every row to daily_summary_backup.csv (exact numbers)
  2) in the Supabase SQL Editor:  truncate table public.floorsheet_daily_summary;     (gives back all the space)
  3) python compact_daily_summary.py import     puts the rows back, in batches

Run it from the nepse_floorsheet folder (it reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from .env).
Do it when no job is running (a weekend evening is best). Keep the CSV until you have checked the totals.
"""
import csv
import json
import os
import sys
from decimal import Decimal

import httpx
from dotenv import load_dotenv

load_dotenv()
URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
TABLE = "floorsheet_daily_summary"
FILE = "daily_summary_backup.csv"
COLS = ["business_date", "symbol", "broker", "buy_qty", "buy_amt", "buy_trans", "sell_qty", "sell_amt", "sell_trans"]
NUM = COLS[3:]
PAGE = 1000      # the API returns at most 1000 rows per request
BATCH = 2000     # rows per insert

H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
client = httpx.Client(base_url=f"{URL}/rest/v1", headers=H, timeout=120)


def get_page(offset: int):
    r = client.get(
        f"/{TABLE}",
        params={"select": ",".join(COLS), "order": "business_date,symbol,broker", "limit": PAGE, "offset": offset},
    )
    r.raise_for_status()
    return json.loads(r.text, parse_float=Decimal, parse_int=Decimal)  # exact numbers, no rounding


def table_has_rows() -> bool:
    r = client.get(f"/{TABLE}", params={"select": "business_date", "limit": 1})
    r.raise_for_status()
    return len(r.json()) > 0


def export():
    if os.path.exists(FILE):
        sys.exit(f"{FILE} already exists. Move or rename it first, so a good backup is never overwritten.")
    n = 0
    totals = {c: Decimal(0) for c in NUM}
    with open(FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        offset = 0
        while True:
            rows = get_page(offset)
            if not rows:
                break
            for r in rows:
                w.writerow([r[c] for c in COLS])
                n += 1
                for c in NUM:
                    totals[c] += Decimal(r[c] or 0)
            offset += len(rows)
            if n % 20000 < PAGE:
                print(f"  exported {n:,} rows ...")
    print(f"\nExported {n:,} rows to {FILE}")
    for c in NUM:
        print(f"  sum({c}) = {totals[c]}")
    print("\nCompare these with the SQL totals you ran before. If they match, truncate the table next.")


def do_import():
    if not os.path.exists(FILE):
        sys.exit(f"{FILE} not found. Run the export first.")
    if table_has_rows():
        sys.exit("The table is not empty. Run the truncate first (or it would add everything twice).")
    n = 0
    totals = {c: Decimal(0) for c in NUM}
    batch = []

    def send():
        nonlocal batch
        if not batch:
            return
        r = client.post(f"/{TABLE}", content=json.dumps(batch, default=str),
                        headers={"Content-Type": "application/json", "Prefer": "return=minimal"})
        if r.status_code >= 300:
            sys.exit(f"Insert failed after {n:,} rows: {r.status_code} {r.text[:300]}\nNothing is lost: the CSV is still there. Fix the cause and run import again after a truncate.")
        batch = []

    with open(FILE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            batch.append({c: (r[c] if r[c] != "" else None) for c in COLS})
            n += 1
            for c in NUM:
                totals[c] += Decimal(r[c] or 0)
            if len(batch) >= BATCH:
                send()
                if n % 20000 < BATCH:
                    print(f"  imported {n:,} rows ...")
    send()
    print(f"\nImported {n:,} rows from {FILE}")
    for c in NUM:
        print(f"  sum({c}) = {totals[c]}")
    print("\nNow run the check SQL and compare the count and totals.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        export()
    elif cmd == "import":
        do_import()
    else:
        sys.exit("Usage: python compact_daily_summary.py export   |   python compact_daily_summary.py import")
