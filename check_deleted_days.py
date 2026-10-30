import sqlite3

conn = sqlite3.connect("data/nepse_archive.db")

rows = conn.execute(
    "select supabase_deleted, count(*) "
    "from archive_manifest where dataset='floorsheet' "
    "group by supabase_deleted"
).fetchall()

print("supabase_deleted -> day count:")
for deleted, count in rows:
    label = "deleted from Supabase (need import)" if deleted else "still in Supabase (would be a duplicate)"
    print(f"  {deleted} : {count} days  ({label})")

conn.close()