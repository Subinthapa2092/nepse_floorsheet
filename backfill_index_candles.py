"""
Fills old 1-minute index candles into your table index_candles (with ShareHub's permission).
Only ADDS missing minutes. Candles your own collector already saved are never changed.

Run from D:\nepse_floorsheet (same .env as your other scripts):
  python backfill_index_candles.py --all --write   -> fills every index (safe to run again)
  python backfill_index_candles.py                      -> look only (nothing is saved)
  python backfill_index_candles.py --probe              -> which index names ShareHub knows
  python backfill_index_candles.py --write              -> save NEPSE
  python backfill_index_candles.py --write --symbol BANKING --key banking
"""
import argparse, collections, datetime as dt, os, sys, time
import requests

BASE = "https://live.nepsesharehub.com/v1/daily-graph/candle-chart/history"
HEAD = {"User-Agent": "Arthotix/1.0 (data used with permission)"}
NPT = dt.timedelta(hours=5, minutes=45)
VARIANTS = {
    "nepse": ["NEPSE"], "float": ["FLOAT"], "sensitive": ["SENSITIVE"], "sensitivefloat": ["SENFLOAT"],
    "banking": ["BANKING"], "hydropower": ["HYDROPOWER"], "microfinance": ["MICROFINANCE"],
    "finance": ["FINANCE"], "investment": ["INVESTMENT"], "others": ["OTHERS"],
    "developmentbank": ["DEVBANK"], "hotelsandtourism": ["HOTELS"], "tradings": ["TRADING"],
    "manufacturingandprocessing": ["MANUFACTURING", "MANUPRO", "MANU", "MANUFACTURINGPROCESSING", "MANUFACTURING AND PROCESSING",
        "MANUFACTURING & PROCESSING", "MANUFACTURING_AND_PROCESSING", "MANUPROCESSING", "MANUF", "MNP", "MFG", "PROCESSING",
        "MANUFACTURE", "MANUFACTURING PROCESSING", "MANUFACTURINGANDPROCESSING", "MANUFACTURING-AND-PROCESSING"],
    "lifeinsurance": ["LIFE", "LIFEINS", "LIFEINSURANCE", "LIFE INSURANCE", "LIFE_INSURANCE", "LINS", "LIFEI", "INSLIFE",
        "LIFE-INSURANCE", "LI", "LIFEINSU"],
    "nonlifeinsurance": ["NONLIFE", "NONLIFEINS", "NONLIFEINSURANCE", "NON LIFE", "NON-LIFE", "NON_LIFE", "NLIFE", "NLINS",
        "NONLIFE INSURANCE", "NON LIFE INSURANCE", "NLI", "NONLIFEINSU"],
    "mutualfund": ["MUTUAL", "MUTUALFUND", "MUTUAL FUND", "MF", "MUTUAL_FUND", "MUTUAL-FUND", "MUTFUND", "MFUND", "MUTUALFUNDS"],
}
KEYS = ["nepse", "float", "sensitive", "sensitivefloat", "banking", "hydropower", "manufacturingandprocessing",
        "lifeinsurance", "nonlifeinsurance", "developmentbank", "microfinance", "finance", "hotelsandtourism",
        "investment", "tradings", "others", "mutualfund"]


def fetch(symbol, resolution="1", countback="0"):
    r = requests.get(BASE, headers=HEAD, timeout=60,
                     params={"symbol": symbol, "resolution": resolution, "countback": countback, "isAdjust": "true"})
    r.raise_for_status()
    j = r.json()
    return j.get("data") or []


def to_rows(data, key):
    rows = []
    for c in data:
        try:
            t = dt.datetime.fromtimestamp(int(c["time"]) / 1000, dt.timezone.utc).replace(tzinfo=None) + NPT
            o, h, l, cl = (float(c[k]) for k in ("open", "high", "low", "close"))
        except Exception:
            continue
        if min(o, h, l, cl) <= 0 or h < l:
            continue
        if not (dt.time(10, 30) <= t.time() <= dt.time(15, 0)):   # market hours only
            continue
        rows.append({"index_key": key, "bucket": t.strftime("%Y-%m-%d %H:%M:00"),
                     "open": o, "high": h, "low": l, "close": cl})
    return rows


def show(data, rows):
    print(f"  ShareHub sent {len(data)} candles; {len(rows)} usable (market hours).")
    if not rows:
        return
    days = collections.Counter(r["bucket"][:10] for r in rows)
    ds = sorted(days)
    print(f"  from {ds[0]} to {ds[-1]}  ({len(ds)} trading days)")
    print("  candles per day (last 5):", ", ".join(f"{d[5:]}:{days[d]}" for d in ds[-5:]))
    print("  first:", rows[0]["bucket"], rows[0]["close"], "| last:", rows[-1]["bucket"], rows[-1]["close"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="NEPSE")
    ap.add_argument("--key", default="nepse")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    if a.probe:
        for k in KEYS:
            for s in dict.fromkeys([k.upper(), k]):
                try:
                    n = len(fetch(s, "1", "5"))
                except Exception as e:
                    n = f"error {e}"
                print(f"{k:28s} symbol={s:28s} -> {n}")
                time.sleep(0.4)
                if n == "error" or (isinstance(n, int) and n > 0):
                    break
        return

    if a.all:
        from dotenv import load_dotenv
        from supabase import create_client
        load_dotenv()
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]) if a.write else None
        missing = []
        for key, names in VARIANTS.items():
            if key == "nepse":
                continue
            got = None
            for sym in names:
                try:
                    data = fetch(sym)
                except Exception:
                    data = []
                time.sleep(0.4)
                if data:
                    got = (sym, data)
                    break
            if not got:
                missing.append(key)
                print(f"{key:28s} NOT FOUND")
                continue
            rows = to_rows(got[1], key)
            days = len({r["bucket"][:10] for r in rows})
            print(f"{key:28s} {got[0]:28s} {len(rows)} candles, {days} days, last close {rows[-1]['close'] if rows else '-'}")
            if a.write and rows:
                for i in range(0, len(rows), 500):
                    sb.table("index_candles").upsert(rows[i:i + 500], on_conflict="index_key,bucket", ignore_duplicates=True).execute()
        print("Still missing:", ", ".join(missing) or "none")
        return

    print(f"Reading {a.symbol} ...")
    data = fetch(a.symbol)
    rows = to_rows(data, a.key)
    show(data, rows)
    if not a.write:
        print("Nothing saved (look only). Add --write to save.")
        return
    if not rows:
        sys.exit("Nothing to save.")
    from dotenv import load_dotenv
    from supabase import create_client
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    done = 0
    for i in range(0, len(rows), 500):
        part = rows[i:i + 500]
        sb.table("index_candles").upsert(part, on_conflict="index_key,bucket", ignore_duplicates=True).execute()
        done += len(part)
        print(f"  sent {done}/{len(rows)}", end="\r")
    print(f"\nDone. Missing minutes were added; existing ones were left alone.")


if __name__ == "__main__":
    main()
