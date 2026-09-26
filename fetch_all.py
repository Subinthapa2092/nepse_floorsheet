"""
Fetches every "no symbol needed" NEPSE data point (market summary, index,
sub-indices, daily prices, rankings, company list, supply/demand) and
upserts each into its own Supabase table.

Run inspect_all.py FIRST and compare its output against the normalize_*
functions below -- field names here are best-guesses and likely need
adjusting for at least a couple of these, since several of NEPSE's
endpoints are undocumented.

Usage:
    python fetch_all.py
"""

import os
from datetime import datetime, date, timezone

from dotenv import load_dotenv
from supabase import create_client, Client
from nepse import Nepse

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]


def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_nepse_client() -> Nepse:
    nepse = Nepse()
    nepse.setTLSVerification(False)
    return nepse


def today_str(raw=None) -> str:
    if raw:
        try:
            return str(date.fromisoformat(str(raw)[:10]))
        except ValueError:
            pass
    return str(date.today())


def safe_upsert(supabase, table, rows, on_conflict, label):
    if not rows:
        print(f"  [{label}] no rows to store, skipping.")
        return
    try:
        supabase.table(table).upsert(rows, on_conflict=on_conflict).execute()
        print(f"  [{label}] stored {len(rows)} row(s) in '{table}'.")
    except Exception as e:
        print(f"  [{label}] FAILED to store into '{table}': {e}")


def fetch_market_summary(nepse, supabase):
    print("Fetching market summary...")
    try:
        data = nepse.getSummary()
    except Exception as e:
        print(f"  getSummary() failed: {e}")
        return
    if not data:
        print("  no data returned.")
        return

    # getSummary() returns a LIST of {"detail": "...", "value": ...} pairs,
    # not a flat dict -- convert it to a lookup by matching label substrings.
    lookup = {}
    for entry in data:
        detail = (entry.get("detail") or "").lower()
        value = entry.get("value")
        if "turnover" in detail:
            lookup["total_turnover"] = value
        elif "traded shares" in detail or "trade shares" in detail:
            lookup["total_traded_shares"] = value
        elif "transactions" in detail:
            lookup["total_transactions"] = value
        elif "scrips traded" in detail:
            lookup["total_scrips_traded"] = value
        elif "market cap" in detail:
            lookup["market_cap"] = value

    row = {
        "business_date": today_str(),
        "total_turnover": lookup.get("total_turnover"),
        "total_traded_shares": lookup.get("total_traded_shares"),
        "total_transactions": lookup.get("total_transactions"),
        "total_scrips_traded": lookup.get("total_scrips_traded"),
        "market_cap": lookup.get("market_cap"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    safe_upsert(supabase, "market_summary", [row], "business_date", "market_summary")


# def fetch_nepse_index(nepse, supabase):
#     print("Fetching NEPSE index...")
#     try:
#         data = nepse.getNepseIndex()
#     except Exception as e:
#         print(f"  getNepseIndex() failed: {e}")
#         return
#     if not data:
#         print("  no data returned.")
#         return

#     # getNepseIndex() returns SEVERAL indices (NEPSE Index, Sensitive Index,
#     # Float Index, etc.) -- find the main "NEPSE Index" by name specifically,
#     # rather than blindly taking the first entry.
#     entry = next((e for e in data if e.get("index") == "NEPSE Index"), None)
#     if entry is None:
#         print("  couldn't find an entry named 'NEPSE Index' -- storing all "
#               "entries' names so we can check the exact label:")
#         print("  Available index names:", [e.get("index") for e in data])
#         entry = data[0]  # fallback so something is stored, but flagged above

#     row = {
#         "business_date": today_str(),
#         "index_value": entry.get("currentValue"),
#         "point_change": entry.get("change"),
#         "percent_change": entry.get("perChange"),
#         "fetched_at": datetime.now(timezone.utc).isoformat(),
#     }
#     safe_upsert(supabase, "nepse_index", [row], "business_date", "nepse_index")
# Paste this whole function in place of the is_stale_repeat this REPLACES the
# existing `fetch_nepse_index` function in fetch_all.py -- delete the old
# one entirely and put this in its place (same spot in the file is fine).
#
# It adds one small helper, is_stale_repeat(), used only by this function.


def is_stale_repeat(supabase, table, row, match_cols=("index_name",)):
    """
    True when `row` is about to create a row for a NEW business_date whose
    index_value / point_change / percent_change are identical to the most
    recent EARLIER date already stored -- the signature of a holiday, where
    NEPSE's own API just echoes the last real close with no "closed" flag.

    Safe by design: it only compares against a strictly EARLIER date, so a
    same-day refresh (running every 5 minutes on a real trading day) is
    never affected, only ever a brand-new calendar date.
    """
    q = supabase.table(table).select("business_date,index_value,point_change,percent_change")
    for col in match_cols:
        if col in row:
            q = q.eq(col, row[col])
    q = q.lt("business_date", row["business_date"]).order("business_date", desc=True).limit(1)
    prev = (q.execute().data or [None])[0]
    if not prev:
        return False
    return (
        prev["index_value"] == row["index_value"]
        and prev["point_change"] == row["point_change"]
        and prev["percent_change"] == row["percent_change"]
    )


def fetch_nepse_index(nepse, supabase):
    print("Fetching NEPSE index...")
    try:
        data = nepse.getNepseIndex()
    except Exception as e:
        print(f"  getNepseIndex() failed: {e}")
        return
    if not data:
        print("  no data returned.")
        return

    # getNepseIndex() returns SEVERAL indices (NEPSE Index, Sensitive Index,
    # Float Index, etc.) -- find the main "NEPSE Index" by name specifically,
    # rather than blindly taking the first entry.
    entry = next((e for e in data if e.get("index") == "NEPSE Index"), None)
    if entry is None:
        print("  couldn't find an entry named 'NEPSE Index' -- storing all "
              "entries' names so we can check the exact label:")
        print("  Available index names:", [e.get("index") for e in data])
        entry = data[0]  # fallback so something is stored, but flagged above

    row = {
        "business_date": today_str(),
        "index_value": entry.get("currentValue"),
        "point_change": entry.get("change"),
        "percent_change": entry.get("perChange"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    if is_stale_repeat(supabase, "nepse_index", row, match_cols=()):
        print("  looks like a holiday (same close as the last trading day) "
              "-- not writing a new dated row.")
        return

    safe_upsert(supabase, "nepse_index", [row], "business_date", "nepse_index")


def fetch_sub_indices(nepse, supabase):
    print("Fetching sub-indices...")
    fetched_at = datetime.now(timezone.utc).isoformat()
    business_date = today_str()  # these endpoints don't return their own date
    rows = []

    # Sector-wise sub-indices (Banking, Hydropower, Microfinance, etc.)
    try:
        sector_data = nepse.getNepseSubIndices()
    except Exception as e:
        print(f"  getNepseSubIndices() failed: {e}")
        sector_data = []

    for entry in sector_data or []:
        rows.append({
            "index_name": entry.get("index"),
            "business_date": business_date,
            "index_value": entry.get("currentValue"),
            "point_change": entry.get("change"),
            "percent_change": entry.get("perChange"),
            "fetched_at": fetched_at,
        })

    # ALSO store the other main index variants here (Sensitive, Float,
    # Sensitive Float) -- getNepseIndex() returns 4 entries total, and
    # fetch_nepse_index() above only keeps "NEPSE Index" for the headline
    # nepse_index table. The other 3 were previously being discarded
    # entirely -- store them here instead, alongside the sector indices,
    # since this table already supports multiple named indices per day.
    try:
        main_indices = nepse.getNepseIndex()
    except Exception as e:
        print(f"  getNepseIndex() (for sub-index storage) failed: {e}")
        main_indices = []

    for entry in main_indices or []:
        name = entry.get("index")
        if name == "NEPSE Index":
            continue  # already stored separately in the nepse_index table
        rows.append({
            "index_name": name,
            "business_date": business_date,
            "index_value": entry.get("currentValue"),
            "point_change": entry.get("change"),
            "percent_change": entry.get("perChange"),
            "fetched_at": fetched_at,
        })

    rows = [r for r in rows if r["index_name"]]
    safe_upsert(supabase, "nepse_sub_indices", rows, "index_name,business_date", "sub_indices")


def fetch_daily_prices(nepse, supabase):
    print("Fetching daily price/volume for all stocks...")
    business_date = today_str()

    try:
        response = nepse.getPriceVolumeHistory(business_date=business_date)
        data = response.get("content", []) if response else []
    except Exception as e:
        print(f"  getPriceVolumeHistory() returned nothing for {business_date} "
              f"-- expected on weekends/holidays when NEPSE isn't trading, "
              f"since there's no price data for a day nothing traded. "
              f"(raw error, often blank: {e!r})")
        return
    if not data:
        print(f"  no data for {business_date} -- market likely closed today.")
        return
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for entry in data:
        symbol = entry.get("symbol")
        if not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "business_date": business_date,
            "open_price": entry.get("openPrice"),
            "high_price": entry.get("highPrice"),
            "low_price": entry.get("lowPrice"),
            "close_price": entry.get("closePrice"),
            "total_volume": entry.get("totalTradedQuantity"),
            "total_turnover": entry.get("totalTradedValue"),
            "fetched_at": fetched_at,
        })
    safe_upsert(supabase, "daily_prices", rows, "symbol,business_date", "daily_prices")


def fetch_rankings(nepse, supabase):
    print("Fetching rankings (gainers/losers/turnover/trade/transaction)...")
    fetched_at = datetime.now(timezone.utc).isoformat()
    business_date = today_str()

    categories = {
        "gainer": nepse.getTopGainers,
        "loser": nepse.getTopLosers,
        "turnover": nepse.getTopTenTurnoverScrips,
        "trade": nepse.getTopTenTradeScrips,
        "transaction": nepse.getTopTenTransactionScrips,
    }

    all_rows = []
    for category, fn in categories.items():
        try:
            data = fn()
        except Exception as e:
            print(f"  {fn.__name__}() failed: {e}")
            continue
        if not data:
            continue
        for i, entry in enumerate(data, start=1):
            symbol = entry.get("symbol") or entry.get("stockSymbol")
            if not symbol:
                continue
            value = (
                entry.get("percentageChange") or entry.get("perChange")
                or entry.get("turnover") or entry.get("totalTradeValue")
                or entry.get("shareTraded") or entry.get("totalTrades")
            )
            all_rows.append({
                "category": category,
                "rank": i,
                "symbol": symbol,
                "business_date": business_date,
                "value": value,
                "fetched_at": fetched_at,
            })

    safe_upsert(supabase, "market_rankings", all_rows, "category,business_date,rank", "rankings")


def fetch_companies(nepse, supabase):
    print("Fetching company/security list...")
    try:
        data = nepse.getSecurityList()
    except Exception as e:
        print(f"  getSecurityList() failed: {e}")
        return
    if not data:
        print("  no data returned.")
        return

    # getSecurityList() itself has no sector field -- build a symbol -> sector
    # lookup from getSectorScrips() instead, and merge it in. Written
    # defensively since the exact shape hasn't been confirmed via
    # inspect_all.py yet -- handles a couple of plausible shapes:
    #   (a) a list of groups: [{"sector": "Banking", "scrips": [...]}, ...]
    #   (b) a flat list of securities that already include a sector field
    symbol_to_sector = {}
    try:
        sector_data = nepse.getSectorScrips()
    except Exception as e:
        print(f"  getSectorScrips() failed: {e} -- sector column will stay empty.")
        sector_data = None

    if sector_data:
        if isinstance(sector_data, dict):
            # shape: {"Banking": ["NABIL", "KBL", ...], "Hydropower": [...]}
            for sector_name, symbols in sector_data.items():
                if isinstance(symbols, list):
                    for s in symbols:
                        sym = s.get("symbol") if isinstance(s, dict) else s
                        if sym:
                            symbol_to_sector[sym] = sector_name
        elif isinstance(sector_data, list):
            for entry in sector_data:
                if not isinstance(entry, dict):
                    continue
                # shape (a): a group with its own scrip list
                sector_name = entry.get("sector") or entry.get("sectorName")
                scrips = entry.get("scrips") or entry.get("securities") or entry.get("symbols")
                if sector_name and isinstance(scrips, list):
                    for s in scrips:
                        sym = s.get("symbol") if isinstance(s, dict) else s
                        if sym:
                            symbol_to_sector[sym] = sector_name
                else:
                    # shape (b): flat entry that already has both fields
                    sym = entry.get("symbol")
                    sector_name = entry.get("sector") or entry.get("sectorName")
                    if sym and sector_name:
                        symbol_to_sector[sym] = sector_name

        if not symbol_to_sector:
            print("  getSectorScrips() returned data in an unexpected shape -- "
                  "run inspect_all.py and check getSectorScrips() output, then "
                  "adjust the parsing above.")

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for entry in data:
        symbol = entry.get("symbol")
        if not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "security_name": entry.get("securityName") or entry.get("companyName"),
            "sector": symbol_to_sector.get(symbol),
            "raw": entry,
            "fetched_at": fetched_at,
        })
    matched = sum(1 for r in rows if r["sector"])
    print(f"  matched sector for {matched}/{len(rows)} companies.")
    safe_upsert(supabase, "companies", rows, "symbol", "companies")


def fetch_supply_demand(nepse, supabase):
    print("Fetching supply/demand snapshot...")
    try:
        data = nepse.getSupplyDemand()
    except Exception as e:
        print(f"  getSupplyDemand() failed: {e}")
        return
    if not data:
        print("  no data returned.")
        return
    row = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "raw": data,
    }
    safe_upsert(supabase, "supply_demand_snapshots", [row], "fetched_at", "supply_demand")


def fetch_and_store():
    nepse = get_nepse_client()
    supabase = get_supabase_client()

    print(f"[{datetime.now()}] Running full fetch...")
    fetch_market_summary(nepse, supabase)
    fetch_nepse_index(nepse, supabase)
    fetch_sub_indices(nepse, supabase)
    fetch_daily_prices(nepse, supabase)
    fetch_rankings(nepse, supabase)
    fetch_companies(nepse, supabase)
    fetch_supply_demand(nepse, supabase)
    print("Full fetch complete.")


if __name__ == "__main__":
    fetch_and_store()
