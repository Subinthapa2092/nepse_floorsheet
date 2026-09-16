# """
# Fetches every "no symbol needed" NEPSE data point (market summary, index,
# sub-indices, daily prices, rankings, company list, supply/demand) and
# upserts each into its own Supabase table.

# Run inspect_all.py FIRST and compare its output against the normalize_*
# functions below -- field names here are best-guesses and likely need
# adjusting for at least a couple of these, since several of NEPSE's
# endpoints are undocumented.

# Usage:
#     python fetch_all.py
# """

# import os
# from datetime import datetime, date, timezone

# from dotenv import load_dotenv
# from supabase import create_client, Client
# from nepse import Nepse

# load_dotenv()

# SUPABASE_URL = os.environ["SUPABASE_URL"]
# SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]


# def get_supabase_client() -> Client:
#     return create_client(SUPABASE_URL, SUPABASE_KEY)


# def get_nepse_client() -> Nepse:
#     nepse = Nepse()
#     nepse.setTLSVerification(False)
#     return nepse


# def today_str(raw=None) -> str:
#     if raw:
#         try:
#             return str(date.fromisoformat(str(raw)[:10]))
#         except ValueError:
#             pass
#     return str(date.today())


# def safe_upsert(supabase, table, rows, on_conflict, label):
#     if not rows:
#         print(f"  [{label}] no rows to store, skipping.")
#         return
#     try:
#         supabase.table(table).upsert(rows, on_conflict=on_conflict).execute()
#         print(f"  [{label}] stored {len(rows)} row(s) in '{table}'.")
#     except Exception as e:
#         print(f"  [{label}] FAILED to store into '{table}': {e}")


# def fetch_market_summary(nepse, supabase):
#     print("Fetching market summary...")
#     try:
#         data = nepse.getSummary()
#     except Exception as e:
#         print(f"  getSummary() failed: {e}")
#         return
#     if not data:
#         print("  no data returned.")
#         return
#     business_date = today_str(data.get("businessDate") if isinstance(data, dict) else None)
#     row = {
#         "business_date": business_date,
#         "total_turnover": data.get("totalTurnover") if isinstance(data, dict) else None,
#         "total_traded_shares": data.get("totalTradedShares") if isinstance(data, dict) else None,
#         "total_transactions": data.get("totalTransactions") if isinstance(data, dict) else None,
#         "total_scrips_traded": data.get("totalScripsTraded") if isinstance(data, dict) else None,
#         "market_cap": data.get("marketCapitalization") if isinstance(data, dict) else None,
#         "fetched_at": datetime.now(timezone.utc).isoformat(),
#     }
#     safe_upsert(supabase, "market_summary", [row], "business_date", "market_summary")


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
#     # getNepseIndex() may return a list with one entry, or a dict directly.
#     entry = data[0] if isinstance(data, list) and data else data
#     if not isinstance(entry, dict):
#         print("  unexpected shape, skipping -- check inspect_all.py output.")
#         return
#     business_date = today_str(entry.get("businessDate"))
#     row = {
#         "business_date": business_date,
#         "index_value": entry.get("currentValue") or entry.get("indexValue"),
#         "point_change": entry.get("change") or entry.get("pointChange"),
#         "percent_change": entry.get("perChange") or entry.get("percentChange"),
#         "fetched_at": datetime.now(timezone.utc).isoformat(),
#     }
#     safe_upsert(supabase, "nepse_index", [row], "business_date", "nepse_index")


# def fetch_sub_indices(nepse, supabase):
#     print("Fetching sub-indices...")
#     try:
#         data = nepse.getNepseSubIndices()
#     except Exception as e:
#         print(f"  getNepseSubIndices() failed: {e}")
#         return
#     if not data:
#         print("  no data returned.")
#         return
#     fetched_at = datetime.now(timezone.utc).isoformat()
#     rows = []
#     for entry in data:
#         business_date = today_str(entry.get("businessDate"))
#         rows.append({
#             "index_name": entry.get("index") or entry.get("indexName"),
#             "business_date": business_date,
#             "index_value": entry.get("currentValue") or entry.get("indexValue"),
#             "point_change": entry.get("change") or entry.get("pointChange"),
#             "percent_change": entry.get("perChange") or entry.get("percentChange"),
#             "fetched_at": fetched_at,
#         })
#     rows = [r for r in rows if r["index_name"]]
#     safe_upsert(supabase, "nepse_sub_indices", rows, "index_name,business_date", "sub_indices")


# def fetch_daily_prices(nepse, supabase):
#     print("Fetching daily price/volume for all stocks...")
#     try:
#         data = nepse.getPriceVolume()
#     except Exception as e:
#         print(f"  getPriceVolume() failed: {e}")
#         return
#     if not data:
#         print("  no data returned.")
#         return
#     fetched_at = datetime.now(timezone.utc).isoformat()
#     rows = []
#     for entry in data:
#         symbol = entry.get("symbol") or entry.get("stockSymbol")
#         if not symbol:
#             continue
#         business_date = today_str(entry.get("businessDate"))
#         rows.append({
#             "symbol": symbol,
#             "business_date": business_date,
#             "open_price": entry.get("openPrice"),
#             "high_price": entry.get("highPrice"),
#             "low_price": entry.get("lowPrice"),
#             "close_price": entry.get("closePrice") or entry.get("lastTradedPrice"),
#             "total_volume": entry.get("totalTradeQuantity") or entry.get("volume"),
#             "total_turnover": entry.get("totalTradeValue") or entry.get("turnover"),
#             "fetched_at": fetched_at,
#         })
#     safe_upsert(supabase, "daily_prices", rows, "symbol,business_date", "daily_prices")


# def fetch_rankings(nepse, supabase):
#     print("Fetching rankings (gainers/losers/turnover/trade/transaction)...")
#     fetched_at = datetime.now(timezone.utc).isoformat()
#     business_date = today_str()

#     categories = {
#         "gainer": nepse.getTopGainers,
#         "loser": nepse.getTopLosers,
#         "turnover": nepse.getTopTenTurnoverScrips,
#         "trade": nepse.getTopTenTradeScrips,
#         "transaction": nepse.getTopTenTransactionScrips,
#     }

#     all_rows = []
#     for category, fn in categories.items():
#         try:
#             data = fn()
#         except Exception as e:
#             print(f"  {fn.__name__}() failed: {e}")
#             continue
#         if not data:
#             continue
#         for i, entry in enumerate(data, start=1):
#             symbol = entry.get("symbol") or entry.get("stockSymbol")
#             if not symbol:
#                 continue
#             value = (
#                 entry.get("percentageChange") or entry.get("perChange")
#                 or entry.get("turnover") or entry.get("totalTradeValue")
#                 or entry.get("shareTraded") or entry.get("totalTrades")
#             )
#             all_rows.append({
#                 "category": category,
#                 "rank": i,
#                 "symbol": symbol,
#                 "business_date": business_date,
#                 "value": value,
#                 "fetched_at": fetched_at,
#             })

#     safe_upsert(supabase, "market_rankings", all_rows, "category,business_date,rank", "rankings")


# def fetch_companies(nepse, supabase):
#     print("Fetching company/security list...")
#     try:
#         data = nepse.getSecurityList()
#     except Exception as e:
#         print(f"  getSecurityList() failed: {e}")
#         return
#     if not data:
#         print("  no data returned.")
#         return
#     fetched_at = datetime.now(timezone.utc).isoformat()
#     rows = []
#     for entry in data:
#         symbol = entry.get("symbol")
#         if not symbol:
#             continue
#         rows.append({
#             "symbol": symbol,
#             "security_name": entry.get("securityName") or entry.get("companyName"),
#             "sector": entry.get("sectorName") or entry.get("sector"),
#             "raw": entry,
#             "fetched_at": fetched_at,
#         })
#     safe_upsert(supabase, "companies", rows, "symbol", "companies")


# def fetch_supply_demand(nepse, supabase):
#     print("Fetching supply/demand snapshot...")
#     try:
#         data = nepse.getSupplyDemand()
#     except Exception as e:
#         print(f"  getSupplyDemand() failed: {e}")
#         return
#     if not data:
#         print("  no data returned.")
#         return
#     row = {
#         "fetched_at": datetime.now(timezone.utc).isoformat(),
#         "raw": data,
#     }
#     safe_upsert(supabase, "supply_demand_snapshots", [row], "fetched_at", "supply_demand")


# def fetch_and_store():
#     nepse = get_nepse_client()
#     supabase = get_supabase_client()

#     print(f"[{datetime.now()}] Running full fetch...")
#     fetch_market_summary(nepse, supabase)
#     fetch_nepse_index(nepse, supabase)
#     fetch_sub_indices(nepse, supabase)
#     fetch_daily_prices(nepse, supabase)
#     fetch_rankings(nepse, supabase)
#     fetch_companies(nepse, supabase)
#     fetch_supply_demand(nepse, supabase)
#     print("Full fetch complete.")


# if __name__ == "__main__":
#     fetch_and_store()
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
    safe_upsert(supabase, "nepse_index", [row], "business_date", "nepse_index")


def fetch_sub_indices(nepse, supabase):
    print("Fetching sub-indices...")
    try:
        data = nepse.getNepseSubIndices()
    except Exception as e:
        print(f"  getNepseSubIndices() failed: {e}")
        return
    if not data:
        print("  no data returned.")
        return
    fetched_at = datetime.now(timezone.utc).isoformat()
    business_date = today_str()  # this endpoint doesn't return its own date
    rows = []
    for entry in data:
        rows.append({
            "index_name": entry.get("index"),
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
    try:
        data = nepse.getPriceVolume()
    except Exception as e:
        print(f"  getPriceVolume() failed: {e}")
        return
    if not data:
        print("  no data returned.")
        return
    fetched_at = datetime.now(timezone.utc).isoformat()
    business_date = today_str()  # this endpoint doesn't return its own date
    rows = []
    for entry in data:
        symbol = entry.get("symbol")
        if not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "business_date": business_date,
            # getPriceVolume() has no open/high/low/turnover fields -- only
            # last traded price, previous close, and % change are available.
            "open_price": None,
            "high_price": None,
            "low_price": None,
            "close_price": entry.get("lastTradedPrice") or entry.get("closePrice"),
            "total_volume": entry.get("totalTradeQuantity"),
            "total_turnover": None,
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
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for entry in data:
        symbol = entry.get("symbol")
        if not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "security_name": entry.get("securityName") or entry.get("companyName"),
            "sector": entry.get("sectorName") or entry.get("sector"),
            "raw": entry,
            "fetched_at": fetched_at,
        })
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
