"""
One long-running job for the whole trading session.

Why: GitHub Actions cannot start a new run faster than every 5 minutes, and
each run wastes about a minute installing Python packages. This script starts
ONCE before the market opens and then loops until it closes, so the light data
can refresh every minute.

Every 60 seconds (cheap, one call each):
    live prices, NEPSE index, sub-indices, market summary
Every minute, a rolling slice of market depth (the order book):
    DEPTH_PER_TICK symbols per minute, so every stock is refreshed in a few
    minutes. Only the LATEST depth per stock is kept (table market_depth_latest),
    so the database does not grow.
Every 5 minutes (heavy, many rows or many calls):
    floorsheet, daily prices, rankings, supply/demand
Once at start:
    company list
Once after the close (15:05):
    company details for every stock (they barely change during the day)

Trading days and hours are Nepal time. Monday to Friday, 11:00-15:00.
The script starts a few minutes early, waits for the open, and exits at 15:10.

Usage:
    python live_loop.py              # normal run (waits for the market window)
    python live_loop.py --now        # ignore the clock once and run a single pass
"""

import sys
import time
from datetime import datetime, time as dtime

import pytz

import fetch_all as fa
import fetch_floorsheet as ff
import fetch_live_price as fl
import fetch_watchlist as fw

NEPAL_TZ = pytz.timezone("Asia/Kathmandu")
TRADING_WEEKDAYS = {0, 1, 2, 3, 4}          # Monday to Friday (Nepal)
START_WAIT_FROM = dtime(10, 45)             # script may begin waiting from here
OPEN_AT = dtime(10, 58)                     # first fetch, a little before the 11:00 open
FINAL_HEAVY_AT = dtime(15, 5)               # one last full pass after the close
END_AT = dtime(15, 20)                      # hard stop (company details need a few minutes after 15:05)

LIGHT_EVERY = 60                            # seconds
HEAVY_EVERY = 300                           # seconds
DEPTH_PER_TICK = 60                         # stocks whose order book is refreshed each minute
DEPTH_DELAY = 0.3                           # pause between NEPSE requests (seconds)
DEPTH_TIME_BUDGET = 35                      # stop a depth slice after this many seconds
DEPTH_TABLE = "market_depth_latest"


def now_npt() -> datetime:
    return datetime.now(NEPAL_TZ)


def log(msg: str) -> None:
    print(f"[{now_npt():%H:%M:%S}] {msg}", flush=True)


def new_clients():
    return fa.get_nepse_client(), fa.get_supabase_client()


# ---------- light steps ----------
def step_live_prices(nepse, supabase) -> None:
    raw = nepse.getLiveMarket()
    if not raw:
        log("live prices: nothing returned")
        return
    fetched_at = datetime.now(pytz.utc).isoformat()
    rows = [r for r in (fl.normalize_row(x, fetched_at) for x in raw) if r]
    for i in range(0, len(rows), fl.UPSERT_CHUNK_SIZE):
        supabase.table(fl.TABLE_NAME).upsert(rows[i:i + fl.UPSERT_CHUNK_SIZE], on_conflict="symbol").execute()
    log(f"live prices: {len(rows)} rows")


def step_floorsheet(nepse, supabase) -> None:
    raw = nepse.getFloorSheet()
    if not raw:
        log("floorsheet: nothing returned")
        return
    fetched_at = datetime.now(pytz.utc).isoformat()
    rows = [r for r in (ff.normalize_row(x, fetched_at) for x in raw) if r]
    for i in range(0, len(rows), ff.UPSERT_CHUNK_SIZE):
        supabase.table(ff.TABLE_NAME).upsert(rows[i:i + ff.UPSERT_CHUNK_SIZE], on_conflict="contract_no").execute()
    log(f"floorsheet: {len(rows)} rows")


_depth = {"symbols": [], "pos": 0}


def step_market_depth(nepse, supabase) -> None:
    """Refresh the order book for the next slice of stocks (round robin)."""
    try:
        status = nepse.isNepseOpen()
        if isinstance(status, dict) and status.get("isOpen") != "OPEN":
            log("market depth: market not open, skipped")
            return
    except Exception:  # noqa: BLE001 - if the check fails, still try
        pass

    if _depth["pos"] >= len(_depth["symbols"]):
        _depth["symbols"] = fw.get_symbols_to_fetch(nepse)
        _depth["pos"] = 0
        if not _depth["symbols"]:
            log("market depth: no symbols")
            return

    started = time.monotonic()
    fetched_at = datetime.now(pytz.utc).isoformat()
    rows = []
    for sym in _depth["symbols"][_depth["pos"]:_depth["pos"] + DEPTH_PER_TICK]:
        if time.monotonic() - started > DEPTH_TIME_BUDGET:
            break
        try:
            data = nepse.getSymbolMarketDepth(sym)
        except Exception as e:  # noqa: BLE001
            log(f"depth {sym} failed: {e}")
            data = None
        _depth["pos"] += 1
        if data:
            rows.append({"symbol": sym, "raw": data, "fetched_at": fetched_at})
        time.sleep(DEPTH_DELAY)
    if rows:
        supabase.table(DEPTH_TABLE).upsert(rows, on_conflict="symbol").execute()
    log(f"market depth: {len(rows)} stocks ({_depth['pos']}/{len(_depth['symbols'])} this round)")


def step_company_details(nepse, supabase) -> None:
    """Once a day after the close: company details for every active stock."""
    symbols = fw.get_symbols_to_fetch(nepse)
    fetched_at = datetime.now(pytz.utc).isoformat()
    ok = 0
    for sym in symbols:
        if now_npt().time() >= END_AT:
            break
        ok += bool(fw.fetch_company_details(nepse, supabase, sym, fetched_at))
        time.sleep(DEPTH_DELAY)
    log(f"company details: {ok}/{len(symbols)} stocks")


LIGHT_STEPS = [
    ("live prices", step_live_prices),
    ("nepse index", fa.fetch_nepse_index),
    ("sub-indices", fa.fetch_sub_indices),
    ("market summary", fa.fetch_market_summary),
    ("market depth", step_market_depth),
]
HEAVY_STEPS = [
    ("floorsheet", step_floorsheet),
    ("daily prices", fa.fetch_daily_prices),
    ("rankings", fa.fetch_rankings),
    ("supply/demand", fa.fetch_supply_demand),
]
ONCE_STEPS = [("companies", fa.fetch_companies)]


def run_steps(steps, nepse, supabase) -> int:
    """Run every step; one failing step never stops the others. Returns failure count."""
    failed = 0
    for name, fn in steps:
        try:
            fn(nepse, supabase)
        except Exception as e:  # noqa: BLE001 - keep the loop alive
            failed += 1
            log(f"{name} FAILED: {e}")
    return failed


def main(once: bool = False) -> int:
    now = now_npt()
    if not once:
        if now.weekday() not in TRADING_WEEKDAYS:
            log("Not a trading day (Mon-Fri). Nothing to do.")
            return 0
        if now.time() >= END_AT:
            log("Market window is over for today. Nothing to do.")
            return 0
        if now.time() < START_WAIT_FROM:
            log("Too early. Nothing to do.")
            return 0

    nepse, supabase = new_clients()
    run_steps(ONCE_STEPS, nepse, supabase)

    while True:
        now = now_npt()
        if not once and now.time() < OPEN_AT:
            time.sleep(15)
            continue
        if not once and now.time() >= END_AT:
            log("Market window finished. Bye.")
            return 0

        tick_start = time.monotonic()

        fails = run_steps(LIGHT_STEPS, nepse, supabase)
        last_heavy = getattr(main, "_last_heavy", 0.0)
        is_final = (not once) and now.time() >= FINAL_HEAVY_AT and not getattr(main, "_did_final", False)
        if is_final or time.monotonic() - last_heavy >= HEAVY_EVERY:
            run_steps(HEAVY_STEPS, nepse, supabase)
            main._last_heavy = time.monotonic()
            if is_final:
                main._did_final = True

        if is_final:
            run_steps([("company details", step_company_details)], nepse, supabase)
            log("Final pass done. Bye.")
            return 0

        if fails == len(LIGHT_STEPS):
            # Everything failed in a row: the NEPSE session is probably stale. Start fresh.
            log("All light steps failed. Reconnecting.")
            try:
                nepse, supabase = new_clients()
            except Exception as e:  # noqa: BLE001
                log(f"reconnect FAILED: {e}")

        if once:
            return 0
        time.sleep(max(1.0, LIGHT_EVERY - (time.monotonic() - tick_start)))


if __name__ == "__main__":
    sys.exit(main(once="--now" in sys.argv))
