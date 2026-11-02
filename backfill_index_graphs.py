"""
One-off: saves TODAY's full session (1-minute candles) for the NEPSE index and every sector index,
right now, so the index minute charts are not empty until tomorrow.

Run it on your PC, in the nepse_floorsheet folder, once, after the market has closed and before the
next session starts (the graphs hold only the latest session):
    python backfill_index_graphs.py

Needs sql/intraday_bars.sql to have been run in Supabase, and your .env (the same one the other
scripts use). Safe to run twice.
"""
import fetch_all as fa
import index_graphs as ig


def main():
    nepse = fa.get_nepse_client()
    supabase = fa.get_supabase_client()
    ig.save_index_graphs(nepse, supabase, full_day=True)


if __name__ == "__main__":
    main()
