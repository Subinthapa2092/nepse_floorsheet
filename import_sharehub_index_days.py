"""
import_sharehub_index_days.py - ONE-TIME copy of real daily open / high / low for the NEPSE index
(and sector indices when you add them), so old index candles get proper wicks.

What it does:
  1. asks their server for the minute candles of the index - ONE request per index, 4 seconds apart
  2. for each finished day: open = first minute's open, high = highest, low = lowest
     (minutes with no trading volume and obvious bad ticks are ignored)
  3. saves one small row per day in your table index_day_range (the chart already reads it)
  4. keeps nothing else: the minute data is thrown away after use
Closing values are NOT touched: the chart keeps using your own closing values.

Safe by default: without --save it only PRINTS what it would do and writes nothing.

Run in D:\\nepse_floorsheet (next to your working .env):
    python import_sharehub_index_days.py                 # test: prints a summary, saves nothing
    python import_sharehub_index_days.py --save          # saves the NEPSE index days
Other indices, once their names are known:
    python import_sharehub_index_days.py --symbols "BANKING=Banking SubIndex" --save
          (format: THEIR_SYMBOL=OUR_INDEX_NAME, comma separated)

It STOPS at once if their server answers 401, 403 or 429. It never tries to get around a refusal.
"""
import argparse, os, statistics, sys, time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

NPT = timezone(timedelta(hours=5, minutes=45))
PAUSE = 4.0
BAND = 0.05   # a minute further than 5% from that day's median is a bad tick (an index never moves that fast)
MIN_MINUTES = 20


def daily_from_minutes(minutes, today):
    """minute candles -> {date: (open, high, low, close_of_their_last_minute, n_minutes)} for finished days"""
    by_day = defaultdict(list)
    for m in minutes:
        try:
            t = datetime.fromtimestamp(float(m["time"]) / 1000, NPT)
            o, h, l, c = float(m["open"]), float(m["high"]), float(m["low"]), float(m["close"])
            v = float(m.get("volume") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if v <= 0 or min(o, h, l, c) <= 0:
            continue  # filler minutes after the close carry no volume
        if t.hour * 60 + t.minute < 10 * 60 + 30 or t.hour * 60 + t.minute > 15 * 60 + 5:
            continue
        by_day[t.date()].append((t, o, h, l, c))
    out = {}
    for d, rows in by_day.items():
        if d >= today:
            continue  # today is still being recorded by our own live loop
        rows.sort()
        med = statistics.median(r[4] for r in rows)
        good = [r for r in rows if abs(r[4] - med) <= BAND * med and abs(r[2] - med) <= BAND * med and abs(r[3] - med) <= BAND * med]
        if len(good) < MIN_MINUTES:
            continue
        out[d] = (good[0][1], max(r[2] for r in good), min(r[3] for r in good), good[-1][4], len(good))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="NEPSE=NEPSE")
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()

    from import_sharehub_history import Refused, fetch_minutes
    sb = None
    try:
        from dotenv import load_dotenv
        from supabase import create_client
        load_dotenv()
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    except Exception as e:
        print("Could not connect to the database:", e)
        if a.save:
            return

    today = datetime.now(NPT).date()
    pairs = [p.split("=", 1) for p in a.symbols.split(",") if "=" in p]
    for k, (their, ours) in enumerate(pairs):
        their, ours = their.strip(), ours.strip()
        if k:
            time.sleep(PAUSE)
        try:
            minutes = fetch_minutes(their)
        except Refused as e:
            print(f"{their}: their server refused ({e}). Stopping, nothing more will be asked.")
            return
        days = daily_from_minutes(minutes, today)
        if not days:
            print(f"{their}: no usable days")
            continue
        ds = sorted(days)
        print(f"\n{their} -> {ours}: {len(days)} finished days, {ds[0]} to {ds[-1]}")

        # compare their last minute with our own closing value (a sanity check, nothing is changed)
        if sb:
            try:
                tbl, col, nm = ("nepse_index", None, None) if ours == "NEPSE" else ("nepse_sub_indices", "index_name", ours)
                q = sb.table(tbl).select("business_date, index_value").gte("business_date", str(ds[0])).lte("business_date", str(ds[-1]))
                if col:
                    q = q.eq(col, nm)
                got = q.range(0, 999).execute().data or []
                ours_close = {r["business_date"][:10]: float(r["index_value"]) for r in got if r.get("index_value") is not None}
                same = sum(1 for d in ds if str(d) in ours_close and abs(ours_close[str(d)] - days[d][3]) <= 0.01 * days[d][3])
                have = sum(1 for d in ds if str(d) in ours_close)
                print(f"  closing check: {same} of {have} days match our own closing value within 1%")
            except Exception as e:
                print("  (closing check skipped:", e, ")")
        for d in ds[-4:]:
            o, h, l, c, n = days[d]
            print(f"  {d}  open {o:.2f}  high {h:.2f}  low {l:.2f}  (their last minute {c:.2f}, {n} minutes)")

        if a.save and sb:
            rows = [{"index_name": ours, "business_date": str(d), "open_value": days[d][0], "high_value": days[d][1],
                     "low_value": days[d][2], "samples": days[d][4]} for d in ds]
            for i in range(0, len(rows), 200):
                sb.table("index_day_range").upsert(rows[i:i + 200], on_conflict="index_name,business_date").execute()
            print(f"  saved {len(rows)} days in index_day_range")
        elif not a.save:
            print("  (test only: nothing saved. Add --save to save.)")


if __name__ == "__main__":
    main()
