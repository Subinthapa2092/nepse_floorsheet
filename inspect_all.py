"""
Run this FIRST. It calls every "no parameter needed" NEPSE endpoint once and
prints what keys come back, so we can confirm fetch_all.py's field mapping
matches reality before relying on it.

This does NOT call endpoints that require a symbol (getCompanyDetails,
getCompanyPriceVolumeHistory, getSymbolMarketDepth, getFloorSheetOf) --
those are covered separately by fetch_watchlist.py.
"""

import json
from nepse import Nepse


def show(label, value):
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    if value is None:
        print("(no data returned)")
    elif isinstance(value, list):
        print(f"Total items: {len(value)}")
        if value:
            print("Keys in a row:", list(value[0].keys()))
            print("Sample row:")
            print(json.dumps(value[0], indent=2, default=str))
    elif isinstance(value, dict):
        print("Keys:", list(value.keys()))
        print(json.dumps(value, indent=2, default=str))
    else:
        print(value)


def try_call(label, fn):
    try:
        show(label, fn())
    except Exception as e:
        print(f"\n{'=' * 70}\n{label}\n{'=' * 70}\nERROR: {e}")


def main():
    nepse = Nepse()
    nepse.setTLSVerification(False)

    try_call("isNepseOpen()", nepse.isNepseOpen)
    try_call("getSummary()", nepse.getSummary)
    try_call("getNepseIndex()", nepse.getNepseIndex)
    try_call("getNepseSubIndices()", nepse.getNepseSubIndices)
    try_call("getPriceVolume()", nepse.getPriceVolume)
    try_call("getTopGainers()", nepse.getTopGainers)
    try_call("getTopLosers()", nepse.getTopLosers)
    try_call("getTopTenTurnoverScrips()", nepse.getTopTenTurnoverScrips)
    try_call("getTopTenTradeScrips()", nepse.getTopTenTradeScrips)
    try_call("getTopTenTransactionScrips()", nepse.getTopTenTransactionScrips)
    try_call("getSupplyDemand()", nepse.getSupplyDemand)
    try_call("getSecurityList()", nepse.getSecurityList)
    try_call("getSectorScrips()", nepse.getSectorScrips)

    print("\n\nDone. Compare the printed keys above against fetch_all.py's "
          "normalize_* functions and fix any mismatches before trusting it.")


if __name__ == "__main__":
    main()
