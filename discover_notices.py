"""
One-time discovery: does NEPSE's own site publish company notices (lock-in, disclosures) through an API we can read?

It does two things and WRITES NOTHING to your database:
  1. Reads the NEPSE website's own scripts and lists every /api/ address mentioning news, notice, disclosure or announcement.
  2. Tries those addresses (plus a few likely ones) and prints what came back, a short sample of each.

Run it from GitHub -> Actions -> "Discover NEPSE notices" -> Run workflow. Then send the log (or the saved file) to Claude.
"""

import json
import re
import sys

import httpx

from nepse import Nepse

KEYWORDS = re.compile(r"news|notice|disclos|announce|lock|bulletin|circular", re.I)
LIKELY = [
    "/api/nots/news/companies/disclosure",
    "/api/nots/news/media/news-list",
    "/api/nots/news/notices",
    "/api/web/news/companies",
    "/api/web/disclosure",
    "/api/web/notice",
    "/api/nots/news/exchange-messages",
    "/api/nots/market/exchange-messages",
]


def sample(data, n=700):
    try:
        text = json.dumps(data, ensure_ascii=False)
    except Exception:
        text = str(data)
    return text[:n] + (" ..." if len(text) > n else "")


def find_paths():
    found = set()
    with httpx.Client(verify=False, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as c:
        try:
            home = c.get("https://www.nepalstock.com/").text
        except Exception as e:
            print("Could not open the NEPSE home page:", e)
            return found
        scripts = re.findall(r'src="([^"]+\.js)"', home)
        print(f"Home page opened. {len(scripts)} script files found.")
        for s in scripts:
            url = s if s.startswith("http") else "https://www.nepalstock.com/" + s.lstrip("/")
            try:
                js = c.get(url).text
            except Exception as e:
                print("  could not read", url, e)
                continue
            for m in re.findall(r"""["'`](/api/[A-Za-z0-9_\-/\.]+)""", js):
                if KEYWORDS.search(m):
                    found.add(m)
    return found


def main():
    paths = sorted(find_paths())
    print("\n== Addresses in NEPSE's own scripts that look relevant ==")
    for p in paths:
        print("  ", p)
    if not paths:
        print("   (none found)")

    nepse = Nepse()
    nepse.setTLSVerification(False)  # NEPSE's server has a known incomplete cert chain

    print("\n== Trying them (GET only) ==")
    for p in dict.fromkeys(paths + LIKELY):
        p = p.rstrip("/")
        try:
            data = nepse.requestGETAPI(url=p)
            print(f"\nOK   {p}\n     {sample(data)}")
        except Exception as e:
            print(f"\nFAIL {p}  ->  {type(e).__name__}: {str(e)[:120]}")
    print("\nDone. Nothing was saved to your database.")


if __name__ == "__main__":
    sys.exit(main())
