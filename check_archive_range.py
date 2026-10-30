"""Read-only. Shows what nepse_archive.db holds for Jul-Sep 2026. Changes nothing."""
import sqlite3, sys

path = sys.argv[1] if len(sys.argv) > 1 else "data/nepse_archive.db"
c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

print("== archive_manifest columns ==")
cols = [r[1] for r in c.execute("pragma table_info(archive_manifest)")]
print(cols)

print("\n== manifest: floorsheet days per month, by supabase_deleted flag ==")
for r in c.execute("""select substr(trade_date,1,7) m, supabase_deleted, count(*)
                      from archive_manifest where dataset='floorsheet'
                      group by 1,2 order by 1,2"""):
    print(r)

print("\n== manifest rows for 2026-07-15 .. 2026-09-30 ==")
for r in c.execute("""select * from archive_manifest where dataset='floorsheet'
                      and trade_date between '2026-07-15' and '2026-09-30'
                      order by trade_date"""):
    print(r)

print("\n== real trades in the archive's floorsheet table, per month ==")
for r in c.execute("""select substr(trade_date,1,7) m, count(distinct trade_date) days, count(*) trades
                      from floorsheet where trade_date >= '2026-01-01'
                      group by 1 order by 1"""):
    print(r)