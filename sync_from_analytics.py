"""
Copy fresh data from the nepse-analytics project into the main Arthotix project.

  1. daily_prices          -> nepse_analytics_prices   (the chart + Pattern Scanner history)
  2. company_fundamentals  -> company_fundamentals     (EPS / book value)
  3. fundamentals_history  -> fundamentals_history     (dividend / bonus / right)

Safe by default: with no flags it only SHOWS what it would do. Add --go to write.
Needs:  py -m pip install requests
Keys go in a file called sync.env next to this script (never paste them in chat):
    SRC_URL=https://<nepse-analytics-project>.supabase.co
    SRC_KEY=<service_role key of nepse-analytics>
    DST_URL=https://<main-project>.supabase.co
    DST_KEY=<service_role key of the main project>
The same four names can instead be set as environment variables (GitHub Actions secrets).
"""
import os, sys, json, datetime as dt
import requests

GO = '--go' in sys.argv
OVERLAP_DAYS = 3  # re-copy the last few days so a late-filled close price is picked up


def load_env():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync.env')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    for k in ('SRC_URL', 'SRC_KEY', 'DST_URL', 'DST_KEY'):
        if not os.environ.get(k):
            sys.exit(f'Missing {k}. Put it in sync.env (see the top of this file).')


def hdr(key, extra=None):
    h = {'apikey': key, 'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
    if extra:
        h.update(extra)
    return h


def get_all(url, key, table, params, page=1000):
    out, start = [], 0
    while True:
        r = requests.get(f'{url}/rest/v1/{table}', params=params,
                         headers=hdr(key, {'Range-Unit': 'items', 'Range': f'{start}-{start + page - 1}'}), timeout=60)
        if r.status_code not in (200, 206):
            sys.exit(f'Read {table} failed: {r.status_code} {r.text[:300]}')
        rows = r.json()
        out += rows
        if len(rows) < page:
            return out
        start += page


def insert(url, key, table, rows, upsert_on=None, chunk=500):
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        params, extra = {}, {'Prefer': 'return=minimal'}
        if upsert_on:
            params['on_conflict'] = upsert_on
            extra['Prefer'] = 'resolution=merge-duplicates,return=minimal'
        r = requests.post(f'{url}/rest/v1/{table}', params=params, data=json.dumps(part), headers=hdr(key, extra), timeout=120)
        if r.status_code not in (200, 201, 204):
            sys.exit(f'Write {table} failed: {r.status_code} {r.text[:400]}\nNothing else was changed. Run the script again to retry.')


def num(v):
    try:
        return None if v in (None, '') else float(v)
    except ValueError:
        return None


def sync_prices(S, D):
    print('\n[1] daily_prices -> nepse_analytics_prices')
    r = requests.get(f"{D[0]}/rest/v1/nepse_analytics_prices", params={'select': '*', 'order': 'fetched_at.desc', 'limit': 1}, headers=hdr(D[1]), timeout=60)
    if r.status_code != 200:
        sys.exit(f'Cannot read nepse_analytics_prices: {r.status_code} {r.text[:300]}')
    sample = r.json()
    if not sample:
        sys.exit('nepse_analytics_prices is empty; this script only tops up an existing table.')
    cols = set(sample[0].keys())
    last = str(sample[0]['fetched_at'])[:10]
    start = (dt.date.fromisoformat(last) - dt.timedelta(days=OVERLAP_DAYS)).isoformat()
    print(f'    main project has price history up to {last}; copying from {start}')
    print(f'    columns in the target table: {sorted(cols)}')
    need = {'fetched_at', 'symbol', 'open', 'high', 'low', 'ltp', 'qty'}
    if not need <= cols:
        sys.exit(f'The target table lacks {sorted(need - cols)}. Stop here and tell Claude this list.')

    src = get_all(S[0], S[1], 'daily_prices',
                  {'select': 'symbol,business_date,open_price,high_price,low_price,close_price,total_volume,total_turnover',
                   'business_date': f'gte.{start}', 'order': 'business_date.asc,symbol.asc'})
    rows, skipped = [], 0
    for s in src:
        close = num(s['close_price'])
        if close is None:  # the day is not finished/complete for this stock yet; the next run picks it up
            skipped += 1
            continue
        row = {'fetched_at': s['business_date'], 'symbol': s['symbol'], 'open': num(s['open_price']), 'high': num(s['high_price']),
               'low': num(s['low_price']), 'ltp': close, 'qty': num(s['total_volume'])}
        for name in ('turnover', 'total_turnover', 'amount', 'amt'):
            if name in cols:
                row[name] = num(s['total_turnover'])
        rows.append(row)
    days = sorted({r['fetched_at'] for r in rows})
    print(f'    source rows: {len(src)} · usable: {len(rows)} · skipped (no close yet): {skipped}')
    print(f'    days to write: {days[0] if days else "-"} .. {days[-1] if days else "-"} ({len(days)} days)')
    if not rows:
        return
    if not GO:
        print('    (dry run: nothing written)')
        return
    d = requests.delete(f"{D[0]}/rest/v1/nepse_analytics_prices", params={'fetched_at': f'gte.{start}'}, headers=hdr(D[1], {'Prefer': 'return=minimal'}), timeout=120)
    if d.status_code not in (200, 204):
        sys.exit(f'Clearing the overlap days failed: {d.status_code} {d.text[:300]}')
    insert(D[0], D[1], 'nepse_analytics_prices', rows)
    print(f'    wrote {len(rows)} rows')


def sync_fund(S, D):
    print('\n[2] company_fundamentals')
    f = get_all(S[0], S[1], 'company_fundamentals', {'select': 'symbol,eps,eps_fy,pe_ratio,book_value,book_value_fy,pbv,scraped_at'})
    print(f'    source rows: {len(f)}')
    if GO and f:
        insert(D[0], D[1], 'company_fundamentals', f, upsert_on='symbol')
        print('    upserted')
    print('[3] fundamentals_history')
    h = get_all(S[0], S[1], 'fundamentals_history', {'select': 'symbol,event_type,fiscal_year,value_text'})
    print(f'    source rows: {len(h)}')
    if GO and h:
        insert(D[0], D[1], 'fundamentals_history', h, upsert_on='symbol,event_type,fiscal_year')
        print('    upserted')


if __name__ == '__main__':
    load_env()
    S = (os.environ['SRC_URL'].rstrip('/'), os.environ['SRC_KEY'])
    D = (os.environ['DST_URL'].rstrip('/'), os.environ['DST_KEY'])
    print('MODE:', 'WRITE' if GO else 'DRY RUN (add --go to write)')
    sync_prices(S, D)
    sync_fund(S, D)
    print('\nDone.' if GO else '\nDry run finished. If the numbers look right, run again with --go')
