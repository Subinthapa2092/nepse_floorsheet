"""
Bulk trades history: READ-ONLY check. Changes nothing, uploads nothing.
Looks at the old trades in data/nepse_archive.db and prints how many days there are,
how many big trades there are at each size, and about how much Supabase space a summary would need.

Run in the nepse_floorsheet folder (next to data/nepse_archive.db):
    py bulk_history_check.py
Optional:  py bulk_history_check.py --file data/nepse_archive.db
"""
import argparse, os, sqlite3

ap = argparse.ArgumentParser()
ap.add_argument('--file', default='data/nepse_archive.db')
a = ap.parse_args()
if not os.path.exists(a.file):
    raise SystemExit(f"Can't find {a.file}. Run this in the nepse_floorsheet folder, or pass --file.")

db = sqlite3.connect('file:' + os.path.abspath(a.file).replace('\\', '/') + '?mode=ro', uri=True)  # read-only
days = db.execute("select min(trade_date), max(trade_date), count(distinct trade_date), count(*) from floorsheet").fetchone()
print(f'Days in the archive: {days[2]}  ({days[0]} to {days[1]})')
print(f'Trades in the archive: {days[3]:,}')

print('\nTrades at or above a size (all archive days):')
for q in (1000, 3000, 5000, 10000, 20000):
    n = db.execute('select count(*) from floorsheet where quantity >= ?', (q,)).fetchone()[0]
    per_day = n / max(days[2], 1)
    print(f'  {q:>6,} shares or more: {n:>10,} trades   (about {per_day:,.0f} a day)')

pairs = db.execute('select count(*) from (select 1 from floorsheet group by trade_date, symbol)').fetchone()[0]
print(f'\nDay x stock pairs (one row each in a size-count table): {pairs:,}')
print(f'Rough space for that table in Supabase: {pairs * 110 / 1e6:.0f} MB')
for q in (5000, 10000, 20000):
    n = db.execute('select count(*) from floorsheet where quantity >= ?', (q,)).fetchone()[0]
    print(f'Rough space to keep every trade of {q:,}+ shares: {n * 160 / 1e6:.0f} MB')
print('\nNothing was changed. Send these lines to Claude.')
