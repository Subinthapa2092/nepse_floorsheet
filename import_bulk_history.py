"""
Bulk trades history: copies a SUMMARY of your old trades into Supabase (not the raw trades).
  - bulk_size_counts : per day and stock, how many trades fell in each size bucket
  - bulk_trades      : every single trade of 5,000 shares or more
Reads data/nepse_archive.db (read-only). Keeps the last 365 days only.

By default this is a DRY RUN: it prints what it would upload and about how many MB, and changes nothing.
Add --go to upload.  Run sql/bulk_trades.sql in Supabase first.

Run in the nepse_floorsheet folder (next to your working .env):
    py import_bulk_history.py            # dry run
    py import_bulk_history.py --go       # upload
Options:  --file data/nepse_archive.db   --days 365   --limit 5 (only 5 days, for a test)   --force (redo days already uploaded)
"""
import argparse, datetime as dt, os, sqlite3

BULK_MIN = 5000
CHUNK = 1000
SIZES = """
  select symbol,
    sum(quantity <= 10), sum(quantity > 10 and quantity <= 100), sum(quantity > 100 and quantity < 1000),
    sum(quantity >= 1000 and quantity < 2500), sum(quantity >= 2500 and quantity < 5000),
    sum(quantity >= 5000 and quantity < 10000), sum(quantity >= 10000 and quantity <= 20000), sum(quantity > 20000)
  from floorsheet where trade_date = ? and symbol is not null group by symbol"""


def size_rows(db, day):
    names = ('c_10', 'c_100', 'c_999', 'c_2500', 'c_5k', 'c_10k', 'c_20k', 'c_big')
    return [dict(business_date=day, symbol=r[0], **{n: int(v or 0) for n, v in zip(names, r[1:])}) for r in db.execute(SIZES, (day,))]


def bulk_rows(db, day, cols):
    contract = next((c for c in ('contract_no', 'transaction_no') if c in cols), None)  # the archive calls it transaction_no
    pick = lambda c, alt='null': c if c in cols else alt
    sql = (f"select {contract or 'rowid'}, symbol, buyer_broker, seller_broker, quantity, {pick('rate')}, {pick('amount')}, {pick('trade_time')} "
           f"from floorsheet where trade_date = ? and quantity >= {BULK_MIN}")
    out, clashes = {}, 0
    for cno, sym, buy, sell, qty, rate, amt, tm in db.execute(sql, (day,)):
        key = str(cno) if contract else f'{day}-{cno}'
        if key in out:  # same number twice on one day: keep both by numbering the second one
            clashes += 1
            key = f'{key}-{clashes}'
        if amt is None and rate is not None:
            amt = qty * rate
        out[key] = dict(business_date=day, contract_no=key, symbol=sym, buyer_broker=buy, seller_broker=sell,
                        quantity=qty, rate=rate, amount=amt, trade_time=None if tm is None else str(tm))
    return list(out.values())


def upload(client, table, rows, conflict):
    for i in range(0, len(rows), CHUNK):
        client.table(table).upsert(rows[i:i + CHUNK], on_conflict=conflict).execute()


def main(argv=None, client=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default='data/nepse_archive.db')
    ap.add_argument('--days', type=int, default=365)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--go', action='store_true')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args(argv)
    if not os.path.exists(a.file):
        raise SystemExit(f"Can't find {a.file}. Run this in the nepse_floorsheet folder, or pass --file.")
    db = sqlite3.connect('file:' + os.path.abspath(a.file).replace('\\', '/') + '?mode=ro', uri=True)
    cols = {r[1] for r in db.execute('pragma table_info(floorsheet)')}
    need = {'trade_date', 'symbol', 'buyer_broker', 'seller_broker', 'quantity'}
    if not need <= cols:
        raise SystemExit(f'The archive floorsheet table lacks {sorted(need - cols)}. Columns found: {sorted(cols)}')
    print('Archive columns:', sorted(cols))
    cutoff = (dt.date.today() - dt.timedelta(days=a.days)).isoformat()
    days = [r[0] for r in db.execute('select distinct trade_date from floorsheet where trade_date >= ? order by trade_date', (cutoff,))]
    if a.limit:
        days = days[:a.limit]
    print(f'{len(days)} day(s) in the last {a.days} days ({days[0] if days else "-"} to {days[-1] if days else "-"}).')

    if a.go and client is None:
        from dotenv import load_dotenv
        from supabase import create_client
        load_dotenv()
        client = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
    done = set()
    if client is not None and not a.force:
        done = {r['business_date'] for r in client.table('bulk_size_counts').select('business_date').execute().data}
        print(f'{len(done)} day(s) already uploaded; skipped (use --force to redo).')

    n_size = n_bulk = 0
    for day in days:
        if day in done:
            continue
        s, b = size_rows(db, day), bulk_rows(db, day, cols)
        n_size += len(s); n_bulk += len(b)
        if a.go:
            upload(client, 'bulk_size_counts', s, 'business_date,symbol')
            upload(client, 'bulk_trades', b, 'business_date,contract_no')
            print(f'  {day}: {len(s)} size rows, {len(b)} trades')
    print(f'\n{"Uploaded" if a.go else "Would upload"}: {n_size:,} size rows and {n_bulk:,} trades of {BULK_MIN:,}+ shares '
          f'(about {(n_size * 110 + n_bulk * 160) / 1e6:.0f} MB).')
    if not a.go:
        print('Dry run: nothing was uploaded. Add --go to upload.')


if __name__ == '__main__':
    main()
