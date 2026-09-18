"""
Tests every historical-data endpoint with a real call, so we can see the
actual field names AND how far back the data actually goes, before
building a real backfill script.

Edit TEST_SYMBOL and the dates below if you want to test something else.

Usage:
    python inspect_historical.py
"""

import json
import traceback
from nepse import Nepse

TEST_SYMBOL = "NABIL"
A_RECENT_TRADING_DATE = "2026-09-10"    # pick a date you know the market was open
A_LONG_TIME_AGO = "2015-01-01"          # to test how far back data actually exists


def show_paginated(label, value):
    """For endpoints that return {content, totalElements, totalPages, ...}."""
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    if not value:
        print("(no data returned)")
        return
    content = value.get("content", [])
    print(f"totalElements: {value.get('totalElements')}")
    print(f"totalPages: {value.get('totalPages')}")
    print(f"items on this page: {len(content)}")
    if content:
        print("\nMost recent item (first in list):")
        print(json.dumps(content[0], indent=2, default=str))
        print("\nOldest item on this page (last in list):")
        print(json.dumps(content[-1], indent=2, default=str))


def show_raw_list(label, value):
    """For endpoints that return a plain list (of dicts OR of raw arrays)."""
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    if not value:
        print("(no data returned)")
        return
    print(f"Total items: {len(value)}")
    print("Type of each item:", type(value[0]).__name__)
    print("First item (raw):", value[0])
    print("Last item (raw):", value[-1])


def try_call(label, fn, shower):
    try:
        shower(label, fn())
    except Exception:
        print(f"\n{'=' * 70}\n{label}\n{'=' * 70}\nFULL ERROR:")
        traceback.print_exc()


def main():
    nepse = Nepse()
    nepse.setTLSVerification(False)

    try_call(
        f"getPriceVolumeHistory(business_date='{A_RECENT_TRADING_DATE}') "
        f"-- ALL stocks, one past date",
        lambda: nepse.getPriceVolumeHistory(business_date=A_RECENT_TRADING_DATE),
        show_paginated,
    )

    try_call(
        f"getCompanyPriceVolumeHistory('{TEST_SYMBOL}') -- default range (last 365 days)",
        lambda: nepse.getCompanyPriceVolumeHistory(TEST_SYMBOL),
        show_paginated,
    )

    try_call(
        f"getCompanyPriceVolumeHistory('{TEST_SYMBOL}', start_date='{A_LONG_TIME_AGO}') "
        f"-- testing how far back data actually exists",
        lambda: nepse.getCompanyPriceVolumeHistory(TEST_SYMBOL, start_date=A_LONG_TIME_AGO),
        show_paginated,
    )

    try_call(
        f"getPriceVolumeHistory(business_date='2020-01-15') "
        f"-- testing whether the ALL-STOCKS-by-date endpoint also caps at ~1yr, "
        f"or whether it genuinely has older data",
        lambda: nepse.getPriceVolumeHistory(business_date="2020-01-15"),
        show_paginated,
    )

    try_call(
        f"getPriceVolumeHistory(business_date='2016-06-01') "
        f"-- an even older date, to find roughly where real data actually stops",
        lambda: nepse.getPriceVolumeHistory(business_date="2016-06-01"),
        show_paginated,
    )

    try_call(
        f"getFloorSheetOf('{TEST_SYMBOL}', business_date='{A_RECENT_TRADING_DATE}') "
        f"-- one stock's trades on a past date",
        lambda: nepse.getFloorSheetOf(TEST_SYMBOL, business_date=A_RECENT_TRADING_DATE),
        show_raw_list,
    )

    try_call(
        "getDailyNepseIndexGraph() -- historical index time series",
        nepse.getDailyNepseIndexGraph,
        show_raw_list,
    )

    print("\n\nDone. Paste this full output back -- it tells us the real field "
          "names, real date ranges, and the exact error (if any) with a full "
          "traceback we can actually diagnose.")


if __name__ == "__main__":
    main()
