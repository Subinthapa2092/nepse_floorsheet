"""
READ-ONLY. Sends nothing anywhere. Reads your local nepse_archive.db and
estimates how much room the daily broker x symbol summary (and, for
comparison, raw trades) would take inside Supabase.

It samples some evenly spaced days instead of scanning all 17 million rows,
so it finishes in a minute or two.

Usage (from nepse_floorsheet):
    python estimate_summary_size.py
    python estimate_summary_size.py --file data/nepse_archive.db --sample 12

The byte sizes below are ROUGH guesses for Postgres (row + indexes), good to
about +/- 40%. Use them to decide, not as exact numbers.
"""

import argparse
import os
import sqlite3

SUMMARY_BYTES_PER_ROW = 250   # one summary row incl. primary key + 2 indexes
RAW_BYTES_PER_ROW = 300       # one raw trade row incl. primary key + 4 indexes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/nepse_archive.db")
    ap.add_argument("--sample", type=int, default=12, help="how many days to measure")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(f"Can't find {args.file}. Pass --file if it is somewhere else.")
        return

    conn = sqlite3.connect(args.file)
    days = [r[0] for r in conn.execute(
        "select trade_date from archive_manifest where dataset='floorsheet' order by trade_date"
    )]
    if not days:
        print("No floorsheet days found in archive_manifest.")
        return

    step = max(1, len(days) // args.sample)
    sample = days[::step][: args.sample]
    print(f"{len(days)} days in the archive. Measuring {len(sample)} of them...\n")

    summary_counts, raw_counts = [], []
    for d in sample:
        pairs = conn.execute(
            """
            select count(*) from (
                select symbol, buyer_broker as b from floorsheet
                  where trade_date = ? and buyer_broker is not null and buyer_broker <> ''
                union
                select symbol, seller_broker from floorsheet
                  where trade_date = ? and seller_broker is not null and seller_broker <> ''
            )
            """,
            (d, d),
        ).fetchone()[0]
        raw = conn.execute("select count(*) from floorsheet where trade_date = ?", (d,)).fetchone()[0]
        summary_counts.append(pairs)
        raw_counts.append(raw)
        print(f"  {d}: {raw:>7,} raw trades  ->  {pairs:>6,} summary rows")

    avg_summary = sum(summary_counts) / len(summary_counts)
    avg_raw = sum(raw_counts) / len(raw_counts)
    mb = lambda rows, per: rows * per / 1024 / 1024

    print(f"\nAverage per day: {avg_raw:,.0f} raw trades, {avg_summary:,.0f} summary rows")
    print("\nRough Supabase size if imported as a daily broker x stock SUMMARY:")
    for n in sorted({min(x, len(days)) for x in (30, 60, 90, 143, len(days))}):
        print(f"  last {n:>3} days: about {mb(avg_summary * n, SUMMARY_BYTES_PER_ROW):>6.0f} MB")

    print("\nFor comparison, raw trades (what got deleted from Supabase before):")
    for n in (1, 5, 10, 30):
        print(f"  {n:>2} day(s) of raw trades: about {mb(avg_raw * n, RAW_BYTES_PER_ROW):>6.0f} MB")

    print("\nRemember: your Supabase free limit is 500 MB TOTAL, and you were at 484 MB.")
    conn.close()


if __name__ == "__main__":
    main()