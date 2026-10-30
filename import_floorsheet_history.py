"""
Reads your local nepse_archive.db, and for every day marked
supabase_deleted=1 in archive_manifest (the days genuinely missing from
Supabase), computes daily broker x symbol totals and uploads ONLY that
summary -- not the individual trades -- into the new
floorsheet_daily_summary table.

WHERE TO RUN IT: in nepse_floorsheet, next to your working .env.

BEFORE RUNNING: run sql/floorsheet_history_table.sql once in Supabase's
SQL Editor first (creates the destination table).

SAFETY:
  - For each day, it first checks Supabase's raw `floorsheet` table for
    that date. If real trades are already there, that day is SKIPPED
    entirely (the archive_manifest flag might be stale -- this check
    doesn't trust it blindly).
  - It also checks floorsheet_daily_summary itself, so this script is
    safe to re-run: already-summarised days aren't recomputed or re-sent.
  - It never reads or writes anything in the raw `floorsheet` table.

Run:
    python import_floorsheet_history.py
Optional:
    python import_floorsheet_history.py --file data/nepse_archive.db
    python import_floorsheet_history.py --limit 5      # test on 5 days first
"""

import argparse
import os
import sqlite3

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

BATCH_SIZE = 1000


def aggregate_day(conn, trade_date):
    """
    One row per (symbol, broker) for this single day, both as a buyer and
    as a seller, computed straight from the archive's raw trade rows via
    plain SQL GROUP BY -- exactly the same arithmetic the app's own
    SQL functions already do for live data.
    """
    buys = conn.execute(
        """
        select symbol, buyer_broker as broker,
               sum(quantity) as qty, sum(amount) as amt, count(*) as trans
        from floorsheet
        where trade_date = ? and buyer_broker is not null and buyer_broker <> ''
        group by symbol, buyer_broker
        """,
        (trade_date,),
    ).fetchall()
    sells = conn.execute(
        """
        select symbol, seller_broker as broker,
               sum(quantity) as qty, sum(amount) as amt, count(*) as trans
        from floorsheet
        where trade_date = ? and seller_broker is not null and seller_broker <> ''
        group by symbol, seller_broker
        """,
        (trade_date,),
    ).fetchall()

    rows = {}
    for symbol, broker, qty, amt, trans in buys:
        rows[(symbol, broker)] = {
            "business_date": trade_date, "symbol": symbol, "broker": broker,
            "buy_qty": qty, "buy_amt": amt, "buy_trans": trans,
            "sell_qty": 0, "sell_amt": 0, "sell_trans": 0,
        }
    for symbol, broker, qty, amt, trans in sells:
        key = (symbol, broker)
        if key in rows:
            rows[key]["sell_qty"] = qty
            rows[key]["sell_amt"] = amt
            rows[key]["sell_trans"] = trans
        else:
            rows[key] = {
                "business_date": trade_date, "symbol": symbol, "broker": broker,
                "buy_qty": 0, "buy_amt": 0, "buy_trans": 0,
                "sell_qty": qty, "sell_amt": amt, "sell_trans": trans,
            }
    return list(rows.values())


def chunks(rows, size):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/nepse_archive.db")
    ap.add_argument("--limit", type=int, default=None, help="only process this many days (for a test run)")
    ap.add_argument("--from-table", action="store_true",
                    help="take the days straight from the archive's floorsheet table instead of the "
                         "manifest flag (use this for days the manifest marks supabase_deleted=0)")
    ap.add_argument("--dry-run", action="store_true", help="add up the days and print counts, upload nothing")
    ap.add_argument("--since", default=None, help="only days on/after this date, e.g. 2026-07-28")
    ap.add_argument("--until", default=None, help="only days on/before this date, e.g. 2026-09-15")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(f"Can't find {args.file}. Pass --file if it's somewhere else.")
        return

    archive = sqlite3.connect(args.file)
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    missing_days = [
        r[0] for r in archive.execute(
            "select trade_date from archive_manifest "
            "where dataset='floorsheet' and supabase_deleted=1 "
            "order by trade_date"
        ).fetchall()
    ]
    if args.from_table:
        missing_days = [r[0] for r in archive.execute(
            "select distinct trade_date from floorsheet order by trade_date").fetchall()]
    if args.since:
        missing_days = [d for d in missing_days if d >= args.since]
    if args.until:
        missing_days = [d for d in missing_days if d <= args.until]
    if args.limit:
        missing_days = missing_days[: args.limit]
    print(f"{len(missing_days)} day(s) to process.")

    def already_summarised(day):
        # one small check per day. (The old version read ALL summary rows at once,
        # but Supabase returns only 1000 rows per request, so it missed most days.)
        r = (supabase.table("floorsheet_daily_summary").select("business_date")
             .eq("business_date", day).limit(1).execute().data)
        return bool(r)

    done = skipped_already_summary = skipped_live_data = 0
    for day in missing_days:
        if already_summarised(day):
            skipped_already_summary += 1
            continue

        # Trust, but verify: don't rely on the manifest's flag alone.
        live_count = (
            supabase.table("floorsheet")
            .select("contract_no", count="exact")
            .eq("business_date", day)
            .limit(1)
            .execute()
            .count
        )
        if live_count and live_count > 0:
            print(f"  {day}: manifest says deleted, but {live_count} raw row(s) still live in Supabase -- skipping.")
            skipped_live_data += 1
            continue

        rows = aggregate_day(archive, day)
        if not rows:
            print(f"  {day}: no rows in the archive for this day (nothing to import).")
            continue

        if args.dry_run:
            print(f"  {day}: {len(rows)} (symbol, broker) rows would be added (dry run, nothing uploaded).")
            continue

        for batch in chunks(rows, BATCH_SIZE):
            supabase.table("floorsheet_daily_summary").insert(batch).execute()
        print(f"  {day}: {len(rows)} (symbol, broker) rows added.")
        done += 1

    print(f"\nDone. {done} day(s) imported, {skipped_already_summary} already done, "
          f"{skipped_live_data} skipped because raw data was still live.")


if __name__ == "__main__":
    main()