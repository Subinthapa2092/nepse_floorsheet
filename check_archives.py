"""
Looks (read only) for any saved copy of old trades that still has the TIME of each trade.
Opens the files in data\ read-only, changes nothing, sends nothing anywhere.

Run in the nepse_floorsheet folder:   python check_archives.py
"""
import os
import sqlite3

DATA = "data"


def q(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except Exception as e:  # noqa: BLE001
        return f"ERROR {e}"


print("Files in", DATA)
for root, _dirs, files in os.walk(DATA):
    for f in sorted(files)[:40]:
        p = os.path.join(root, f)
        print(f"  {p}  {os.path.getsize(p) / 1e6:.1f} MB")
    if len(files) > 40:
        print(f"  ... and {len(files) - 40} more files in {root}")

for name in ("raw_backup.db", "archive_summaries.db", "nepse_archive.db"):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        continue
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    print("\n" + "=" * 60 + f"\n{path}\n" + "=" * 60)
    for (t,) in q(con, "select name from sqlite_master where type='table'"):
        cols = [r[1] for r in q(con, f"pragma table_info({t})")]
        n = q(con, f"select count(*) from {t}")
        print(f"table {t}: {n[0][0] if isinstance(n, list) else n} rows; columns: {cols}")
        if t == "archive_manifest":
            for r in q(con, f"select * from {t} order by trade_date limit 3"):
                print("   first:", r)
            for r in q(con, f"select * from {t} order by trade_date desc limit 3"):
                print("   last: ", r)
            print("   datasets:", q(con, f"select dataset, count(*) from {t} group by dataset"))
        else:
            for r in q(con, f"select * from {t} limit 2"):
                print("   sample:", tuple(str(x)[:60] for x in r))
