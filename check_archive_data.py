"""Read-only. Finds where your archived trades really are. Changes nothing.
Run from D:\\nepse_floorsheet:   python check_archive_data.py"""
import glob, os, sqlite3

print("== 1) CSV files on disk ==")
for folder in ["data/raw/floorsheet", "data/raw", "data"]:
    files = glob.glob(os.path.join(folder, "**", "*.csv.gz"), recursive=True)
    print(f"{folder}: exists={os.path.isdir(folder)}, .csv.gz files found={len(files)}")
    if files:
        files.sort()
        print("  first:", files[0]); print("  last: ", files[-1])
        break
print("current folder:", os.getcwd())

print("\n== 2) Inside nepse_archive.db ==")
c = sqlite3.connect("file:data/nepse_archive.db?mode=ro", uri=True)
tables = [r[0] for r in c.execute("select name from sqlite_master where type in ('table','view')")]
print("tables:", tables)
if "floorsheet" in tables:
    cols = [r[1] for r in c.execute("pragma table_info(floorsheet)")]
    print("floorsheet columns:", cols)
    print("total rows:", c.execute("select count(*) from floorsheet").fetchone()[0])
    print("date range:", c.execute("select min(trade_date), max(trade_date) from floorsheet").fetchone())
    print("\ntrading days and trades per month:")
    for r in c.execute("""select substr(trade_date,1,7), count(distinct trade_date), count(*)
                          from floorsheet group by 1 order by 1"""):
        print(" ", r)