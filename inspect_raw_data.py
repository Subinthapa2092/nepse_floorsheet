"""
Run this FIRST, before touching fetch_floorsheet.py.

NepseUnofficialApi's exact field names (e.g. whether a trade's identifier is
called "contractId" or "contractNo") can shift between versions. Rather than
guessing, this script pulls one real floorsheet response and prints:
  1. The keys present in a single row
  2. A pretty-printed sample row

Use what you see here to fix up the `normalize_row()` mapping in
fetch_floorsheet.py so it matches reality exactly.
"""

import json
from nepse import Nepse


def main():
    nepse = Nepse()
    nepse.setTLSVerification(False)  # NEPSE's server has a known incomplete cert chain

    print("Checking market status...")
    try:
        print("Market open:", nepse.isNepseOpen())
    except Exception as e:
        print("Could not check market status:", e)

    print("\nFetching floorsheet (this can take a little while, it's paginated)...")
    data = nepse.getFloorSheet()

    if not data:
        print("Got no data back. Market may be closed with no cached floorsheet, "
              "or the site's auth scheme has changed (see README troubleshooting).")
        return

    print(f"\nTotal rows fetched: {len(data)}")
    first_row = data[0]
    print("\nKeys in a row:")
    print(list(first_row.keys()))
    print("\nSample row:")
    print(json.dumps(first_row, indent=2, default=str))


if __name__ == "__main__":
    main()
