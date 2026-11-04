"""
import_sharehub_index_daily.py - ONE-TIME copy of real daily open / high / low for the NEPSE index
(and sector indices when you add them), for ALL the years their daily chart holds.

What it does:
  1. asks their server for the daily candles of the index - ONE request per index, 4 seconds apart
  2. keeps only days that have a REAL candle (open, high and low differ). Old years that only have a closing
     value are skipped: they stay as they are.
  3. keeps only days whose closing value matches OUR closing value within 1% (so a candle never contradicts your chart)
  4. saves one small row per day in your table index_day_range (the chart already reads it)
Closing values are NOT touched: the chart keeps using your own closing values.

Safe by default: without --save it only PRINTS what it would do and writes nothing.

Run in D:\\nepse_floorsheet (next to your working .env):
    python import_sharehub_index_daily.py                 # test: prints a summary, saves nothing
    python import_sharehub_index_daily.py --save          # saves the NEPSE index days
Other indices, once their names are known:
    python import_sharehub_index_daily.py --symbols "BANKING=Banking SubIndex" --save
          (format: THEIR_SYMBOL=OUR_INDEX_NAME, comma separated)

It STOPS at once if their server answers 401, 403 or 429. It never tries to get around a refusal.
To undo: delete from public.index_day_range where samples = 99;
"""
import argparse, json, os, re, time, urllib.error, urllib.request
from datetime import datetime, timezone

BASE = "https://sharehubnepal.com/data/api/v1/candle-chart/history"
PAUSE = 4.0
TOL = 0.01      # their close must match ours within 1%
MARK = 99       # samples value written, so these rows can be found (and undone) later


class Refused(Exception):
    pass


def fetch_daily(symbol):
    url = f"{BASE}?symbol={symbol}&resolution=1D&countback=0&isAdjust=false"
    req = urllib.request.Request(url, headers={"User-Agent": "ArthotixImport/1.0 (arthotix.com; one-time history copy)"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            if isinstance(d, dict):
                d = next((d[k] for k in ("data", "candles", "result", "items") if isinstance(d.get(k), list)), [])
            return d
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise Refused(f"HTTP {e.code}")
            if attempt == 2:
                raise
        except Exception:
            if attempt == 2:
                raise
        time.sleep(10)


def real_days(candles, ours_close):
    """-> ({date_str: (open, high, low, close)}, stats). ours_close: {date_str: our closing value} or None."""
    out, flat, mismatch, nodate = {}, 0, 0, 0
    for c in candles:
        try:
            d = datetime.fromtimestamp(float(c["time"]) / 1000, timezone.utc).date().isoformat()
            o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if min(o, h, l, cl) <= 0:
            continue
        if h == l and o == cl:
            flat += 1          # closing value only: no real candle
            continue
        if ours_close is not None:
            mine = ours_close.get(d)
            if mine is None:
                nodate += 1
                continue
            if abs(mine - cl) > TOL * mine:
                mismatch += 1
                continue
        h, l = max(h, o, cl), min(l, o, cl)
        out[d] = (o, h, l, cl)
    return out, {"flat": flat, "mismatch": mismatch, "not_in_ours": nodate}


_WORDS = {"sen": "sensitive", "manu": "manufacturing", "pro": "processing", "dev": "development", "hydro": "hydropower", "nonlife": "non life"}


def idx_key(name):
    """Same loose key the chart uses: "Banking SubIndex", "Banking" and "BANKING" are one index."""
    t = name.lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\bsub ?index\b|\bindex\b|\bindices\b", " ", t)
    return "".join(_WORDS.get(w, w) for w in t.split()).replace("hydropowerpower", "hydropower")


def spellings(sb, ours):
    """every name this index is stored under (the old import and the live pipeline may differ)"""
    names = {ours}
    try:
        for r in sb.rpc("sub_index_names").execute().data or []:
            nm = str(r.get("index_name") or "")
            if nm and idx_key(nm) == idx_key(ours):
                names.add(nm)
    except Exception:
        pass
    return sorted(names)


def our_closes(sb, ours):
    tbl = "nepse_index" if ours == "NEPSE" else "nepse_sub_indices"
    names = [ours] if ours == "NEPSE" else spellings(sb, ours)
    if len(names) > 1:
        print("  our spellings of this index:", ", ".join(names))
    got, start = {}, 0
    while start < 30000:
        q = sb.table(tbl).select("business_date, index_value")
        if tbl != "nepse_index":
            q = q.in_("index_name", names)
        rows = q.order("business_date").order("index_name" if tbl != "nepse_index" else "business_date").range(start, start + 999).execute().data or []
        for r in rows:
            if r.get("index_value") is not None:
                got[str(r["business_date"])[:10]] = float(r["index_value"])
        if len(rows) < 1000:
            break
        start += 1000
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="NEPSE=NEPSE")
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()

    from dotenv import load_dotenv
    from supabase import create_client
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    pairs = [p.split("=", 1) for p in a.symbols.split(",") if "=" in p]
    for k, (their, ours) in enumerate(pairs):
        their, ours = their.strip(), ours.strip()
        if k:
            time.sleep(PAUSE)
        try:
            candles = fetch_daily(their)
        except Refused as e:
            print(f"{their}: their server refused ({e}). Stopping, nothing more will be asked.")
            return
        mine = our_closes(sb, ours)
        days, st = real_days(candles, mine)
        print(f"\n{their} -> {ours}: {len(candles)} candles from them, {len(mine)} closing values of ours")
        if not days:
            print("  no usable days")
            continue
        ds = sorted(days)
        print(f"  real candles that match our closes: {len(days)} days, {ds[0]} to {ds[-1]}")
        print(f"  skipped: {st['flat']} closing-value-only days, {st['mismatch']} whose close differs from ours by more than 1%, {st['not_in_ours']} dates we do not have")
        for d in ds[-3:]:
            o, h, l, c = days[d]
            print(f"  {d}  open {o:.2f}  high {h:.2f}  low {l:.2f}  close {c:.2f}")

        if a.save:
            rows = [{"index_name": ours, "business_date": d, "open_value": days[d][0], "high_value": days[d][1],
                     "low_value": days[d][2], "samples": MARK} for d in ds]
            for i in range(0, len(rows), 200):
                sb.table("index_day_range").upsert(rows[i:i + 200], on_conflict="index_name,business_date").execute()
            print(f"  saved {len(rows)} days in index_day_range")
        else:
            print("  (test only: nothing saved. Add --save to save.)")


if __name__ == "__main__":
    main()