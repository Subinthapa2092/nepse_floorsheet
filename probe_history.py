"""
probe_history.py  -  ONE request, read-only test. Changes nothing, saves nothing.

How to run (PowerShell, in the folder where this file is):
    python probe_history.py "PASTE_THE_URL_HERE"

It sends a single polite request, then prints:
  - the HTTP status (200 = ok, 401/403 = they refuse, and we STOP there)
  - how many candles came back, the first and last time (Nepal time)
  - the first 5 candles
It never sends cookies or logins, and it does not try to get around a refusal.
"""
import sys, json, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

NPT = timezone(timedelta(hours=5, minutes=45))

def fmt(ts):
    ts = float(ts)
    if ts > 1e12:          # milliseconds
        ts /= 1000.0
    return datetime.fromtimestamp(ts, NPT).strftime("%Y-%m-%d %H:%M")

def main():
    if len(sys.argv) != 2:
        print('Usage: python probe_history.py "URL"')
        return
    url = sys.argv[1]
    req = urllib.request.Request(url, headers={
        "User-Agent": "ArthotixProbe/1.0 (arthotix.com; one-off test)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, body = r.status, r.read()
            ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} - the server refused this request.")
        print("That is their decision. We stop here and do NOT try to get around it.")
        return
    except Exception as e:
        print("Could not connect:", type(e).__name__, e)
        return

    print(f"HTTP {status}   type: {ctype}   size: {len(body)} bytes")
    try:
        data = json.loads(body)
    except Exception:
        print("Reply is not JSON. First 300 characters:")
        print(body[:300].decode("utf-8", "replace"))
        return

    # Format A: TradingView style  {"t":[...],"o":[...],"h":[...],"l":[...],"c":[...],"v":[...]}
    d = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(d, dict) and "t" in d and "c" in d:
        t, o, h, l, c = d["t"], d.get("o", []), d.get("h", []), d.get("l", []), d["c"]
        v = d.get("v", [])
        print(f"candles: {len(t)}")
        if t:
            print("first:", fmt(t[0]), "   last:", fmt(t[-1]))
            print("time (Nepal)      open     high     low      close    volume")
            for i in range(min(5, len(t))):
                print(fmt(t[i]), o[i] if o else "", h[i] if h else "",
                      l[i] if l else "", c[i], v[i] if v else "")
        return

    # Format B: a list of candle objects
    if isinstance(d, list) and d and isinstance(d[0], dict):
        print(f"candles: {len(d)}   fields: {list(d[0].keys())}")
        for row in d[:5]:
            print(row)
        print("last:", d[-1])
        return

    print("Reply is JSON but a different shape. Top-level keys:",
          list(data.keys()) if isinstance(data, dict) else type(data).__name__)

main()
