"""
Second look (read-only, writes nothing): what exactly is inside NEPSE's company disclosure list?
Prints the field names, a clean summary of the first 8 items, how many mention lock-in, and whether there is more than one page.
"""
import json
import re
import sys

from nepse import Nepse

URL = "/api/nots/news/companies/disclosure"


def text(html):
    t = re.sub(r"<[^>]+>", " ", str(html or ""))
    t = re.sub(r"&nbsp;|&quot;|&amp;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def main():
    n = Nepse()
    n.setTLSVerification(False)
    data = n.requestGETAPI(url=URL)
    print("Top-level type:", type(data).__name__)
    if isinstance(data, dict):
        print("Top-level keys:", list(data.keys()))
    items = data.get("exchangeMessages") if isinstance(data, dict) else data
    print("Number of items:", len(items or []))
    for k, v in data.items() if isinstance(data, dict) else []:
        if k != "exchangeMessages":
            print(f"  other field {k}: {json.dumps(v, ensure_ascii=False)[:300]}")
    items = items or []
    if items:
        print("\nFields of one item:", list(items[0].keys()))
    print("\n== First 8 items (clean) ==")
    for it in items[:8]:
        row = {k: (text(v)[:220] if k == "messageBody" else v) for k, v in it.items()}
        print(json.dumps(row, ensure_ascii=False)[:900])
        print()
    hits = [it for it in items if re.search(r"lock|लक.?इन", json.dumps(it, ensure_ascii=False), re.I)]
    print(f"\nItems mentioning lock-in anywhere: {len(hits)} of {len(items)}")
    for it in hits[:5]:
        print(json.dumps({k: (text(v)[:300] if k == "messageBody" else v) for k, v in it.items()}, ensure_ascii=False)[:1200])
        print()
    for extra in ("?page=1&size=100", "?size=200"):
        try:
            d2 = n.requestGETAPI(url=URL + extra)
            l2 = d2.get("exchangeMessages") if isinstance(d2, dict) else d2
            print(f"With {extra}: {len(l2 or [])} items")
        except Exception as e:
            print(f"With {extra}: failed ({type(e).__name__})")


if __name__ == "__main__":
    sys.exit(main())
