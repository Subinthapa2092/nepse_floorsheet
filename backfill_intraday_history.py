"""
Rebuilds 5-minute and hourly candles for PAST days, for every stock that traded, from the trades
(with their time of day) that the NEPSE site gives for any past date. Only the small candles are
saved (table intraday_candles); the trades themselves are never stored.

Run it in the nepse_floorsheet folder on your PC, next to your working .env:

    python backfill_intraday_history.py --probe            # 1 minute: checks the site really gives trade times
    python backfill_intraday_history.py --days 30          # the last 30 calendar days
    python backfill_intraday_history.py --days 400         # as far back as the site allows (takes hours)

It starts from the newest day and goes backwards. It can be stopped any time (Ctrl+C) and run again:
finished days are remembered in backfill_intraday_progress.json and are skipped.
5-minute candles are saved for the last 90 days only (older ones would just be deleted again by the
nightly job); hourly candles are saved for every day. Needs sql/intraday_bars.sql run once in Supabase.
Candles are built with exactly the same rules as the database function save_intraday_candles():
trades before 11:00 are left out and the 15:00 closing trade belongs to the last candle.
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, time as dtime

import fetch_all as fa

OPEN_AT = dtime(11, 0)
LAST_SECOND = dtime(14, 59, 59)
PROGRESS = "backfill_intraday_progress.json"
FIVE_MIN_DAYS = 90          # matches the nightly clean-up in save_all_intraday_candles()
MIN_SYMBOLS_DONE = 100      # a day with at least this many stocks already saved counts as done


def parse_ts(v):
    s = str(v or "").replace(" ", "T")[:26]          # keep the fraction of a second: it orders trades within a second
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.fromisoformat(s[:19])
        except ValueError:
            return None


def build_candles(rows, tfs):
    """rows: raw floorsheet rows of ONE stock on ONE day -> {tf: [(bucket_str, o, h, l, c, volume, trades)]}."""
    trades = []
    for r in rows or []:
        ts = parse_ts(r.get("tradeTime"))
        try:
            rate = float(r.get("contractRate"))
            qty = float(r.get("contractQuantity") or 0)
        except (TypeError, ValueError):
            continue
        if ts is None or rate <= 0:
            continue
        if ts.time() < OPEN_AT:
            continue                                   # before the 11:00 open
        if ts.time() > LAST_SECOND:                    # the 15:00 closing trade joins the last candle
            ts = ts.replace(hour=14, minute=59, second=59, microsecond=0)
        trades.append((ts, str(r.get("contractId") or r.get("contractNo") or ""), rate, qty))
    trades.sort(key=lambda x: (x[0], x[1]))
    out = {}
    for tf in tfs:
        buckets = {}
        for ts, _cid, rate, qty in trades:
            mins = ts.hour * 60 + ts.minute
            b = ts.replace(hour=(mins // tf * tf) // 60, minute=(mins // tf * tf) % 60, second=0, microsecond=0)
            c = buckets.get(b)
            if c is None:
                buckets[b] = [rate, rate, rate, rate, qty, 1]
            else:
                c[1] = max(c[1], rate)
                c[2] = min(c[2], rate)
                c[3] = rate
                c[4] += qty
                c[5] += 1
        out[tf] = [(b.strftime("%Y-%m-%dT%H:%M:00"), *v) for b, v in sorted(buckets.items())]
    return out


def retry(fn, tries=3, wait=2.0):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(wait * (i + 1))
    raise last


def traded_symbols(nepse, d):
    resp = retry(lambda: nepse.getPriceVolumeHistory(business_date=d))
    content = (resp or {}).get("content", []) if isinstance(resp, dict) else []
    return sorted({str(x.get("symbol")) for x in content if x.get("symbol")})


def already_saved(sb, d):
    seen, start = set(), 0
    while True:
        res = (sb.table("intraday_candles").select("symbol").eq("tf", 60)
               .gte("bucket", f"{d}T00:00:00").lt("bucket", f"{d}T23:59:59").range(start, start + 999).execute())
        rows = res.data or []
        seen.update(r["symbol"] for r in rows)
        if len(rows) < 1000:
            return len(seen)
        start += 1000


def day_rows(nepse, sym, d, tfs):
    rows = retry(lambda: nepse.getFloorSheetOf(sym, d))
    if rows and not any(r.get("tradeTime") for r in rows):
        raise SystemExit(f"STOP: the NEPSE site gave trades for {sym} on {d} WITHOUT a time of day. "
                         "Hourly history cannot be rebuilt for that date.")
    return build_candles(rows, tfs), len(rows or [])


def save_rows(sb, sym, tf, candles, dry):
    rows = [{"symbol": sym, "tf": tf, "bucket": b, "open": o, "high": h, "low": l, "close": c, "volume": v, "trades": n}
            for b, o, h, l, c, v, n in candles]
    if dry or not rows:
        return len(rows)
    for i in range(0, len(rows), 500):
        sb.table("intraday_candles").upsert(rows[i:i + 500], on_conflict="symbol,tf,bucket").execute()
    return len(rows)


def weekdays(frm, to):
    d = to
    while d >= frm:
        if d.weekday() < 5:
            yield d
        d -= timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="how many calendar days back from yesterday (default 30)")
    ap.add_argument("--from", dest="frm", help="oldest date, YYYY-MM-DD (overrides --days)")
    ap.add_argument("--to", dest="to", help="newest date, YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--probe", action="store_true", help="only test 3 dates with one stock; saves nothing")
    ap.add_argument("--dry-run", action="store_true", help="fetch and compute, but save nothing")
    ap.add_argument("--delay", type=float, default=0.2, help="pause between requests in seconds")
    ap.add_argument("--max-days", type=int, default=0, help="stop after this many NEW days (0 = no limit)")
    a = ap.parse_args()

    to = date.fromisoformat(a.to) if a.to else date.today() - timedelta(days=1)
    frm = date.fromisoformat(a.frm) if a.frm else to - timedelta(days=a.days)
    nepse = fa.get_nepse_client()

    if a.probe:
        for d in (to, to - timedelta(days=60), to - timedelta(days=200)):
            while d.weekday() >= 5:
                d -= timedelta(days=1)
            try:
                c, n = day_rows(nepse, "NABIL", d.isoformat(), (5, 60))
                print(f"{d}: {n} trades -> {len(c[5])} five-minute and {len(c[60])} hourly candles"
                      + (f"; first hourly {c[60][0][0]} close {c[60][0][4]}" if c[60] else ""))
            except SystemExit as e:
                print(f"{d}: {e}")
            except Exception as e:  # noqa: BLE001
                print(f"{d}: ERROR {type(e).__name__}: {str(e)[:150]}")
        return

    sb = fa.get_supabase_client()
    prog = json.load(open(PROGRESS)) if os.path.exists(PROGRESS) else {}
    new_days, t_start = 0, time.time()
    print(f"Days {frm} .. {to}, newest first. 5-minute candles for the last {FIVE_MIN_DAYS} days, hourly for all.")
    for d in weekdays(frm, to):
        ds = d.isoformat()
        if ds in prog:
            continue
        syms = traded_symbols(nepse, ds)
        if not syms:
            print(f"{ds}: no trading (holiday or no data), skipped")
            prog[ds] = {"symbols": 0, "candles": 0}
            json.dump(prog, open(PROGRESS, "w"))
            continue
        if not a.dry_run and already_saved(sb, ds) >= MIN_SYMBOLS_DONE:
            print(f"{ds}: already saved, skipped")
            prog[ds] = {"symbols": len(syms), "candles": -1}
            json.dump(prog, open(PROGRESS, "w"))
            continue
        tfs = (5, 60) if (date.today() - d).days <= FIVE_MIN_DAYS else (60,)
        t0, saved, failed = time.time(), 0, []
        for sym in syms:
            try:
                cs, _n = day_rows(nepse, sym, ds, tfs)
                for tf in tfs:
                    saved += save_rows(sb, sym, tf, cs[tf], a.dry_run)
            except SystemExit:
                raise
            except Exception as e:  # noqa: BLE001
                failed.append(sym)
                print(f"   {sym} failed: {type(e).__name__}: {str(e)[:100]}")
            time.sleep(a.delay)
        ok = len(failed) <= max(3, len(syms) // 20)
        print(f"{ds}: {len(syms)} stocks, {saved} candles{' (dry run)' if a.dry_run else ''}, {len(failed)} failed, "
              f"{(time.time() - t0) / 60:.1f} min" + ("" if ok else "  -> NOT marked done, run again"))
        if ok and not a.dry_run:
            prog[ds] = {"symbols": len(syms), "candles": saved}
            json.dump(prog, open(PROGRESS, "w"))
        new_days += 1
        if a.max_days and new_days >= a.max_days:
            print("Reached --max-days. Run again to continue.")
            break
    print(f"Done in {(time.time() - t_start) / 60:.0f} min.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped. Run the same command again to continue; finished days are skipped.")
        sys.exit(0)
