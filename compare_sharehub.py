"""
compare_sharehub.py - READ-ONLY check. Saves NOTHING in your database.

Question it answers: do their 1-minute candles (turned into hourly candles with OUR rules)
match the hourly candles we recorded ourselves, for the days we have (29 Oct, 30 Oct, 2 Nov)?

Run in D:\\nepse_floorsheet (next to your working .env):
    python compare_sharehub.py NABIL
It makes ONE request to their server (then keeps the reply in a file so you never need to ask again),
and only READS your Supabase table intraday_candles.
"""
import os, sys, json, urllib.request
from datetime import datetime, timedelta, timezone

SYMBOL = (sys.argv[1] if len(sys.argv) > 1 else "NABIL").upper()
DAYS = ("2026-10-29", "2026-10-30", "2026-11-02")
NPT = timezone(timedelta(hours=5, minutes=45))
URL = ("https://live.nepsesharehub.com/v1/daily-graph/candle-chart/history"
       f"?symbol={SYMBOL}&resolution=1&countback=0&isAdjust=false")
CACHE = f"sharehub_{SYMBOL}_1m.json"


def unwrap(data):
    """their reply is a small box: the candle list is inside it. Find the list of candles."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("data", "candles", "result", "items"):
            if isinstance(data.get(k), list):
                return data[k]
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "time" in v[0]:
                return v
            if isinstance(v, dict):
                r = unwrap(v)
                if r:
                    return r
    return []


def load_theirs():
    if os.path.exists(CACHE):
        print("using saved file", CACHE)
        return unwrap(json.load(open(CACHE, encoding="utf-8")))
    req = urllib.request.Request(URL, headers={"User-Agent": "ArthotixProbe/1.0 (arthotix.com; one-off test)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    open(CACHE, "wb").write(raw)
    return unwrap(json.loads(raw))


def hourly_from_minutes(minutes):
    """their 1-minute candles -> {bucket 'YYYY-MM-DDTHH:00:00': [o,h,l,c,volume]} with OUR rules:
    nothing before 11:00; candles start on the hour; the last minute (14:59) belongs to the 14:00 candle."""
    out = {}
    for m in sorted(minutes, key=lambda x: x["time"]):
        t = datetime.fromtimestamp(m["time"] / 1000, NPT)
        if t.hour < 11 or t.hour > 15:
            continue
        key = t.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00")
        c = out.get(key)
        o, h, l, cl, v = m["open"], m["high"], m["low"], m["close"], m["volume"] or 0
        if c is None:
            out[key] = [o, h, l, cl, v]
        else:
            c[1] = max(c[1], h); c[2] = min(c[2], l); c[3] = cl; c[4] += v
    return out


def load_ours():
    from dotenv import load_dotenv
    from supabase import create_client
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    res = (sb.table("intraday_candles").select("bucket,open,high,low,close,volume")
           .eq("symbol", SYMBOL).eq("tf", 60)
           .gte("bucket", DAYS[0] + "T00:00:00").lte("bucket", DAYS[-1] + "T23:59:59")
           .order("bucket").execute())
    return {r["bucket"][:19].replace(" ", "T"): [r["open"], r["high"], r["low"], r["close"], r["volume"]]
            for r in res.data}


def main():
    data = load_theirs()
    print(f"their 1-minute candles: {len(data)}")
    theirs = hourly_from_minutes(data)
    ours = load_ours()
    keys = sorted(k for k in set(theirs) | set(ours) if k[:10] in DAYS)
    same = diff = only_t = only_o = 0
    print(f"\n{SYMBOL} hourly candles  (open high low close volume)\n")
    for k in keys:
        t, o = theirs.get(k), ours.get(k)
        if t is None:
            only_o += 1; print(f"{k}  ONLY OURS   {o}"); continue
        if o is None:
            only_t += 1; print(f"{k}  ONLY THEIRS {t}"); continue
        ok = all(abs(float(a) - float(b)) < 0.005 for a, b in zip(t[:4], o[:4]))
        vol_ok = abs(float(t[4]) - float(o[4])) <= max(1.0, 0.0005 * float(o[4]))
        if ok and vol_ok:
            same += 1
        else:
            diff += 1
            print(f"{k}  DIFFERENT\n    theirs: {t}\n    ours:   {o}")
    print(f"\nSUMMARY: same {same}   different {diff}   only theirs {only_t}   only ours {only_o}")


main()