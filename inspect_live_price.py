"""
Run this FIRST, before touching fetch_live_price.py.

Just like the floorsheet, NepseUnofficialApi's live market data field names
need to be confirmed against a real response before we trust them.
"""

import json
from nepse import Nepse


def main():
    nepse = Nepse()
    nepse.setTLSVerification(False)

    print("Fetching live market data...")
    data = nepse.getLiveMarket()

    if not data:
        print("Got no data back. Market may be closed, or the site's auth "
              "scheme has changed.")
        return

    print(f"\nTotal securities: {len(data)}")
    first_row = data[0]
    print("\nKeys in a row:")
    print(list(first_row.keys()))
    print("\nSample row:")
    print(json.dumps(first_row, indent=2, default=str))


if __name__ == "__main__":
    main()
