"""
Builds daily broker x stock SUMMARY rows from your archived CSV files
(data\\raw\\floorsheet\\YYYY-MM-DD.csv.gz) and uploads them to Supabase's
floorsheet_daily_summary. Only the summary goes up, never the raw trades.

Put it in D:\\nepse_floorsheet, venv active.

  1) Look first (uploads nothing):
     python import_summary_from_csv.py --since 2026-07-24 --until 2026-09-15 --limit 1 --dry-run
  2) Upload for real:
     python import_summary_from_csv.py --since 2026-07-24 --until 2026-09-15

Safety:
  - reads the archive files only; never changes them
  - skips a day already in the summary table
  - skips a day whose raw trades are still live in Supabase
  - skips a day whose number of CSV rows differs from the manifest row_count
    (use --force to override)
  - stops with a clear message if it can't recognise the CSV column names
"""
import argparse
import csv
import gzip
import os
import sqlite3

BATCH = 1000

NAMES = {
    "symbol": ["symbol", "stock_symbol", "stocksymbol", "scrip"],
    "buyer":  ["buyer_broker", "buyer", "buyerbroker", "buyer_member_id", "buyermemberid", "buyer_broker_no"],
    "seller": ["seller_broker", "seller", "sellerbroker", "seller_member_id", "sellermemberid", "seller_broker_no"],
    "qty":    ["quantity", "qty", "contract_quantity", "contractquantity"],
    "amt":    ["amount", "amt", "contract_amount", "contractamount"],
}


def num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return 0.0


def find_columns(header):
    lower = {h.strip().lower(): h for h in header}
    out = {}
    for key, options in NAMES.items():
        hit = next((lower[o] for o in options if o in lower), None)
        if hit is None:
            raise SystemExit(
                f"Can't recognise the '{key}' column. The CSV header is:\n  {header}\n"
                "Send me this line and I'll adjust the script.")
        out[key] = hit
    return out


def read_day(path):
    """Returns (rows_in_file, summary_rows_dict)."""
    agg, n = {}, 0
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        col = find_columns(rd.fieldnames)
        for r in rd:
            n += 1
            sym = (r[col["symbol"]] or "").strip()
            if not sym:
                continue
            q, a = num(r[col["qty"]]), num(r[col["amt"]])
            for side, key in (("buy", "buyer"), ("sell", "seller")):
                br = (r[col[key]] or "").strip()
                if not br:
                    continue
                d = agg.setdefault((sym, br), {"buy_qty": 0.0, "buy_amt": 0.0, "buy_trans": 0,
                                               "sell_qty": 0.0, "sell_amt": 0.0, "sell_trans": 0})
                d[f"{side}_qty"] += q
                d[f"{side}_amt"] += a
                d[f"{side}_trans"] += 1
    return n, agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/nepse_archive.db")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.file}?mode=ro", uri=True)
    days = conn.execute("select trade_date, row_count, archive_path from archive_manifest "
                        "where dataset='floorsheet' order by trade_date").fetchall()
    if args.since:
        days = [d for d in days if d[0] >= args.since]
    if args.until:
        days = [d for d in days if d[0] <= args.until]
    if args.limit:
        days = days[: args.limit]
    print(f"{len(days)} day(s) to look at.")

    sb = None
    if not args.dry_run:
        from dotenv import load_dotenv
        from supabase import create_client
        load_dotenv()
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    added = 0
    for day, want_rows, path in days:
        path = os.path.normpath(path.replace("\\", os.sep))
        if not os.path.exists(path):
            print(f"  {day}: file not found ({path}) -- skipped")
            continue

        if sb is not None:
            if sb.table("floorsheet_daily_summary").select("business_date").eq("business_date", day).limit(1).execute().data:
                print(f"  {day}: already in summary -- skipped")
                continue
            live = sb.table("floorsheet").select("contract_no", count="exact").eq("business_date", day).limit(1).execute().count
            if live:
                print(f"  {day}: {live} raw trades still live in Supabase -- skipped")
                continue

        n, agg = read_day(path)
        if n != want_rows and not args.force:
            print(f"  {day}: file has {n} rows but manifest says {want_rows} -- skipped (use --force)")
            continue
        if not agg:
            print(f"  {day}: nothing to add up -- skipped")
            continue

        rows = [{"business_date": day, "symbol": s, "broker": b,
                 **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}}
                for (s, b), d in agg.items()]

        if args.dry_run:
            tq = sum(d["buy_qty"] for d in agg.values())
            print(f"  {day}: {n} trades -> {len(rows)} summary rows, total bought qty {tq:,.0f}  (dry run, nothing uploaded)")
            continue

        for i in range(0, len(rows), BATCH):
            sb.table("floorsheet_daily_summary").insert(rows[i:i + BATCH]).execute()
        print(f"  {day}: {n} trades -> {len(rows)} summary rows added.")
        added += 1

    print(f"\nDone. {added} day(s) uploaded." if not args.dry_run else "\nDry run finished. Nothing was uploaded.")


if __name__ == "__main__":
    main()