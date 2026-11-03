r"""
Read only. Looks for the daily raw trade files (floorsheet CSV files, e.g. 2025-08-24.csv.gz) on your PC
and checks whether they still have the TIME of each trade. Also shows which days raw_backup.db holds.
Nothing is changed, nothing is sent anywhere.

Run in the nepse_floorsheet folder:   python find_raw_days.py
"""
import gzip
import os
import re
import sqlite3

ROOTS = [r"D:\\", r"C:\Users\Lenovo"]
PAT = re.compile(r"^\d{4}-\d{2}-\d{2}\.csv(\.gz)?$", re.I)

print("Searching for daily floorsheet files (this can take a few minutes)...")
found = []
for root in ROOTS:
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d.lower() not in ("node_modules", ".git", "appdata", "$recycle.bin", "windows", "program files", "program files (x86)")]
        if "floorsheet" in dp.lower():
            for f in fn:
                if PAT.match(f):
                    found.append(os.path.join(dp, f))
found.sort(key=lambda p: os.path.basename(p))
print(f"Found {len(found)} daily files.")
if found:
    tot = sum(os.path.getsize(p) for p in found) / 1e6
    print(f"  total {tot:.0f} MB; first: {found[0]}")
    print(f"  last: {found[-1]}")
    for p in (found[0], found[len(found) // 2], found[-1]):
        op = gzip.open if p.lower().endswith(".gz") else open
        try:
            with op(p, "rt", encoding="utf-8", errors="replace") as fh:
                print(f"\n  {os.path.basename(p)}")
                print("   header:", fh.readline().strip()[:300])
                print("   row 1: ", fh.readline().strip()[:300])
        except Exception as e:  # noqa: BLE001
            print("   could not read:", e)

print("\nraw_backup.db: days it holds")
con = sqlite3.connect("file:data/raw_backup.db?mode=ro", uri=True)
for r in con.execute("select business_date, count(*), min(trade_time), max(trade_time) from floorsheet group by business_date order by business_date"):
    print("  ", r)
