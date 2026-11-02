"""
Saves 1-minute candles for the NEPSE index and every sector index, from the intraday
graphs the NEPSE site publishes (about 2 readings a minute for the whole session).

Needs sql/intraday_bars.sql to have been run once in Supabase (creates table index_candles).
Used by live_loop.py (every 5 minutes, last 30 minutes; after 15:00 the whole day).
Safe to run twice: a candle is simply written again.
"""
from datetime import datetime, timedelta

import pytz

NEPAL_TZ = pytz.timezone("Asia/Kathmandu")

# key (matches the website's index key) -> name of the NEPSE library function
GRAPHS = [
    ("nepse", "getDailyNepseIndexGraph"),
    ("sensitive", "getDailySensitiveIndexGraph"),
    ("float", "getDailyFloatIndexGraph"),
    ("sensitivefloat", "getDailySensitiveFloatIndexGraph"),
    ("banking", "getDailyBankSubindexGraph"),
    ("developmentbank", "getDailyDevelopmentBankSubindexGraph"),
    ("finance", "getDailyFinanceSubindexGraph"),
    ("hotelsandtourism", "getDailyHotelTourismSubindexGraph"),
    ("hydropower", "getDailyHydroSubindexGraph"),
    ("investment", "getDailyInvestmentSubindexGraph"),
    ("lifeinsurance", "getDailyLifeInsuranceSubindexGraph"),
    ("manufacturingandprocessing", "getDailyManufacturingSubindexGraph"),
    ("microfinance", "getDailyMicrofinanceSubindexGraph"),
    ("mutualfund", "getDailyMutualfundSubindexGraph"),
    ("nonlifeinsurance", "getDailyNonLifeInsuranceSubindexGraph"),
    ("others", "getDailyOthersSubindexGraph"),
    ("trading", "getDailyTradingSubindexGraph"),
]


def build_candles(points):
    """points: [[epoch_seconds, value], ...] -> list of (bucket 'YYYY-MM-DDTHH:MM:00', o, h, l, c), Nepal time.
    Bad points (not numbers, zero or negative) are skipped; points are put in time order first."""
    clean = []
    for p in points or []:
        try:
            ts, v = int(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if v > 0:
            clean.append((ts, v))
    clean.sort(key=lambda x: x[0])
    out = {}
    for ts, v in clean:
        local = datetime.fromtimestamp(ts, NEPAL_TZ).replace(second=0, microsecond=0, tzinfo=None)
        b = local.strftime("%Y-%m-%dT%H:%M:00")
        if b not in out:
            out[b] = [v, v, v, v]
        else:
            c = out[b]
            c[1] = max(c[1], v)
            c[2] = min(c[2], v)
            c[3] = v
    return [(b, c[0], c[1], c[2], c[3]) for b, c in sorted(out.items())]


def save_index_graphs(nepse, supabase, full_day=None, log=print):
    """Fetch every graph and save its 1-minute candles. full_day=None: decide from the clock."""
    now = datetime.now(NEPAL_TZ)
    if full_day is None:
        full_day = now.hour >= 15
    cutoff = None if full_day else (now - timedelta(minutes=30)).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:00")
    saved = failed = 0
    for key, fn in GRAPHS:
        try:
            candles = build_candles(getattr(nepse, fn)())
            if cutoff:
                candles = [c for c in candles if c[0] >= cutoff]
            rows = [{"index_key": key, "bucket": b, "open": o, "high": h, "low": l, "close": c} for b, o, h, l, c in candles]
            for i in range(0, len(rows), 500):
                supabase.table("index_candles").upsert(rows[i:i + 500], on_conflict="index_key,bucket").execute()
            saved += len(rows)
        except Exception as e:  # one failing index never stops the others
            failed += 1
            log(f"  index graph {key} FAILED: {e}")
    log(f"index graphs: {saved} candles saved, {failed} failed ({'whole day' if full_day else 'last 30 min'})")
