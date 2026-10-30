"""
Run this ONCE against your local nepse_archive.db before we write any real
import script. It only reads the file -- doesn't touch Supabase, doesn't
change anything in the archive. Paste me everything it prints.

Usage (from your nepse_floorsheet folder):
    python inspect_archive.py
    python inspect_archive.py --file data/nepse_archive.db
    python inspect_archive.py --file nepse_archive.db
"""

import argparse
import os
import sqlite3

ap = argparse.ArgumentParser()
ap.add_argument("--file", default="data/nepse_archive.db")
args = ap.parse_args()

DB_PATH = args.file

if not os.path.exists(DB_PATH):
    print(f"Can't find {DB_PATH} from the folder you're running this in.")
    print("Either move nepse_archive.db there, or pass its real location, e.g.:")
    print(r"    python inspect_archive.py --file nepse_archive.db")
    print(r"    python inspect_archive.py --file D:\some\other\path\nepse_archive.db")
    raise SystemExit(1)

print(f"Reading: {os.path.abspath(DB_PATH)}")
print(f"File size (MB): {os.path.getsize(DB_PATH) / 1024 / 1024:.2f}")
print()

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

print("=" * 70)
print("TABLES IN THE DATABASE")
print("=" * 70)
tables = [r[0] for r in conn.execute(
    "select name from sqlite_master where type='table' order by name"
)]
for t in tables:
    print(" -", t)

for t in tables:
    print()
    print("=" * 70)
    print(f"TABLE: {t}")
    print("=" * 70)

    print("-- columns --")
    for col in conn.execute(f"pragma table_info('{t}')"):
        # cid, name, type, notnull, dflt_value, pk
        print(f"  {col[1]:<25} {col[2]:<12} {'NOT NULL' if col[3] else ''} {'PRIMARY KEY' if col[5] else ''}")

    try:
        count = conn.execute(f"select count(*) from '{t}'").fetchone()[0]
        print(f"\n-- row count: {count:,} --")
    except Exception as e:
        print(f"\n-- couldn't count rows: {e} --")
        continue

    if count == 0:
        print("(empty table)")
        continue

    print(f"\n-- 3 sample rows --")
    for row in conn.execute(f"select * from '{t}' limit 3"):
        print(" ", dict(row))

    # If this table has an obvious date-like column, show the real date range
    col_names = [c[1] for c in conn.execute(f"pragma table_info('{t}')")]
    date_col = next(
        (c for c in col_names if c.lower() in
         ("business_date", "trade_date", "date", "contract_date")),
        None
    )
    if date_col:
        row = conn.execute(
            f"select min({date_col}), max({date_col}), count(distinct {date_col}) from '{t}'"
        ).fetchone()
        print(f"\n-- date range on '{date_col}': min={row[0]}  max={row[1]}  distinct_days={row[2]} --")

conn.close()
print()
print("=" * 70)
print("Done. Paste all of the above back to Claude.")
print("=" * 70)