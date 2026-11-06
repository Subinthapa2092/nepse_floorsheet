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
        if v in (None, ''):
            return None
        f = float(v)
        return int(f) if f.is_integer() else f  # whole numbers go as 3460, not 3460.0 (a whole-number column refuses "3460.0")
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

    # Look at the source table first, so a different column name is found (and shown) instead of failing.
    pr = requests.get(f"{S[0]}/rest/v1/daily_prices", params={'select': '*', 'limit': 1}, headers=hdr(S[1]), timeout=60)
    if pr.status_code != 200:
        sys.exit(f'Cannot read daily_prices in the source project: {pr.status_code} {pr.text[:300]}')
    probe = pr.json()
    print(f"    source project starts with: {S[0].split('//')[-1][:6]} | target project starts with: {D[0].split('//')[-1][:6]}")
    if not probe:
        sys.exit('daily_prices is empty in the source project. Check that SRC_URL / SRC_KEY are the nepse-analytics project.')
    scols = set(probe[0].keys())
    print(f'    columns in the source table: {sorted(scols)}')

    def pick(*names):
        return next((n for n in names if n in scols), None)

    c = {'date': pick('business_date', 'trading_date', 'trade_date', 'date', 'fetched_at'), 'symbol': pick('symbol'),
         'open': pick('open_price', 'open', 'open_raw'), 'high': pick('high_price', 'high', 'high_raw'),
         'low': pick('low_price', 'low', 'low_raw'), 'close': pick('close_price', 'ltp', 'close', 'close_raw'),
         'vol': pick('total_volume', 'volume', 'qty'), 'turn': pick('total_turnover', 'turnover', 'amount')}
    extra = [k for k in ('pct_change', 'trend') if k in scols and k in cols]  # copied too when both tables have them
    lacking = [k for k in ('date', 'symbol', 'open', 'high', 'low', 'close', 'vol') if not c[k]]
    if lacking:
        sys.exit(f'The source daily_prices has no column for {lacking}. Send Claude the "columns in the source table" line above.')
    print(f'    using source columns: {c}')
    cols_sel = ','.join(sorted({v for v in c.values() if v} | set(extra)))
    src = get_all(S[0], S[1], 'daily_prices',
                  {'select': cols_sel, c['date']: f'gte.{start}', 'order': f"{c['date']}.asc,{c['symbol']}.asc"})
    rows, skipped = [], 0
    for s in src:
        close = num(s[c['close']])
        if close is None:  # the day is not finished/complete for this stock yet; the next run picks it up
            skipped += 1
            continue
        row = {'fetched_at': str(s[c['date']])[:10], 'symbol': s[c['symbol']], 'open': num(s[c['open']]), 'high': num(s[c['high']]),
               'low': num(s[c['low']]), 'ltp': close, 'qty': num(s[c['vol']])}
        for name in ('turnover', 'total_turnover', 'amount', 'amt'):
            if name in cols and c['turn']:
                row[name] = num(s[c['turn']])
        for k in extra:
            row[k] = s.get(k)
        rows.append(row)
    # One row per stock per day (the latest one wins if the source keeps several).
    rows = list({(r['fetched_at'], r['symbol']): r for r in rows}.values())
    days = sorted({r['fetched_at'] for r in rows})
    print(f'    source rows: {len(src)} · usable: {len(rows)} · skipped (no close yet): {skipped}')
    print(f'    days to write: {days[0] if days else "-"} .. {days[-1] if days else "-"} ({len(days)} days)')
    if not rows:
        return
    if not GO:
        print('    (dry run: nothing written)')
        return
    # A day is replaced only when the source has nearly as many stocks as the target already holds for that day,
    # so a half-filled day in the source never overwrites a complete one.
    keep_days = []
    for day in days:
        have = [r for r in rows if r['fetched_at'] == day]
        cur = get_all(D[0], D[1], 'nepse_analytics_prices', {'select': 'symbol', 'fetched_at': f'eq.{day}'})
        if cur and len(have) < 0.9 * len(cur):
            print(f'    {day}: source has {len(have)} stocks, target has {len(cur)}; left unchanged')
            continue
        keep_days.append(day)
    rows = [r for r in rows if r['fetched_at'] in keep_days]
    if not rows:
        print('    nothing to write')
        return
    # Keep a copy of the days about to be replaced. If writing the new rows fails, the copy is put back, so a failed run never leaves a gap.
    backup = get_all(D[0], D[1], 'nepse_analytics_prices', {'select': '*', 'fetched_at': f"in.({','.join(keep_days)})"})
    d = requests.delete(f"{D[0]}/rest/v1/nepse_analytics_prices", params={'fetched_at': f"in.({','.join(keep_days)})"}, headers=hdr(D[1], {'Prefer': 'return=minimal'}), timeout=120)
    if d.status_code not in (200, 204):
        sys.exit(f'Clearing the overlap days failed: {d.status_code} {d.text[:300]}')
    try:
        insert(D[0], D[1], 'nepse_analytics_prices', rows)
    except SystemExit as e:
        print(f'    writing failed, putting back the {len(backup)} rows that were replaced ...')
        try:
            d2 = requests.delete(f"{D[0]}/rest/v1/nepse_analytics_prices", params={'fetched_at': f"in.({','.join(keep_days)})"}, headers=hdr(D[1], {'Prefer': 'return=minimal'}), timeout=120)
            insert(D[0], D[1], 'nepse_analytics_prices', backup)
            print('    old rows are back')
        except SystemExit:
            print('    COULD NOT put the old rows back. Run the script again; it rewrites these days from the source.')
        raise e
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
    if S[0] == D[0]:
        sys.exit('SRC_URL and DST_URL are the same project. SRC must be nepse-analytics and DST the main Arthotix project.')
    print('MODE:', 'WRITE' if GO else 'DRY RUN (add --go to write)')
    sync_prices(S, D)
    sync_fund(S, D)
    print('\nDone.' if GO else '\nDry run finished. If the numbers look right, run again with --go')
