"""
Saves NEPSE's company announcements and exchange notices into the `announcements` table.
Run the SQL file sql/announcements.sql in Supabase once first.

    python fetch_announcements.py            # fetch and save
    python fetch_announcements.py --dry-run  # only show what it would save

NEPSE shows a rolling window (about the last 4 weeks), so this runs every 30 minutes and our own table keeps the history.
Safe to run any number of times: an item is saved once (matched by NEPSE's id), later runs only update it.
"""
import html
import os
import re
import sys
from datetime import datetime, timedelta, timezone

NPT = timezone(timedelta(hours=5, minutes=45))
KEEP_DAYS = 400

# First rule that matches wins. Lower-case text is tested.
RULES = [
    ("promoter", r"conversion of promoter|promoter share.*(converted|conversion)"),
    ("sale", r"sale of (promoter )?share|intention (for|to) sale|intention to sell|sale of (the )?(shares|securities|bonus)|share sale"),
    ("right", r"right share|rights? issue|right offering|\bright\b.*(share|issue)"),
    ("dividend", r"dividend|bonus share|bonus"),
    ("agm", r"\bagm\b|\bsgm\b|general meeting|book closure|book close"),
    ("ipo", r"\bipo\b|\bfpo\b|public issue|listing|allotment|debenture|ordinary share issue|mutual fund|scheme|nav\b"),
    ("report", r"quarter|annual report|financial statement|unaudited|audited|\bq[1-4]\b"),
    ("board", r"\bbod\b|board|appointment|director|auditor|\bceo\b|chief executive|resign|merger|acquisition|amalgamation"),
]


def classify(title: str, body: str) -> str:
    t = f"{title} {body[:200]}".lower()
    for cat, pat in RULES:
        if re.search(pat, t):
            return cat
    return "other"


def clean(text, limit=600):
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", " ", str(text))
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


def symbol_of(title: str):
    m = re.search(r"\[([A-Z][A-Z0-9]{1,11})\]", title) or re.search(r"\(([A-Z][A-Z0-9]{1,11})\)\s*$", title)
    return m.group(1) if m else None


def when(s):
    try:
        return datetime.fromisoformat(str(s)).replace(tzinfo=NPT).isoformat()
    except Exception:
        return None


def build(data):
    rows = []
    for r in data.get("companyNews") or []:
        title = clean(r.get("newsHeadline"), 300)
        added = when(r.get("addedDate"))
        if not title or not added or r.get("id") is None:
            continue
        body = clean(r.get("newsBody"))
        rows.append({
            "kind": "company", "nepse_id": int(r["id"]), "symbol": symbol_of(title), "title": title, "body": body or None,
            "source": clean(r.get("newsSource"), 80) or None, "category": classify(title, body),
            "has_file": bool(r.get("applicationDocumentDetailsList")), "added_at": added,
        })
    for r in data.get("exchangeMessages") or []:
        title = clean(r.get("messageTitle"), 300)
        added = when(r.get("addedDate"))
        if not title or not added or r.get("id") is None:
            continue
        body = clean(r.get("messageBody"))
        rows.append({
            "kind": "exchange", "nepse_id": int(r["id"]), "symbol": symbol_of(title), "title": title, "body": body or None,
            "source": "NEPSE", "category": classify(title, body),
            "has_file": bool(r.get("filePath")), "added_at": added,
        })
    return rows


def main():
    from nepse import Nepse

    dry = "--dry-run" in sys.argv
    nepse = Nepse()
    nepse.setTLSVerification(False)  # NEPSE's server has a known incomplete cert chain
    data = nepse.requestGETAPI("/api/nots/news/companies/disclosure")
    if not isinstance(data, dict):
        raise SystemExit(f"Unexpected answer from NEPSE: {type(data).__name__}")
    rows = build(data)
    print(f"{len(rows)} items from NEPSE")
    by_cat = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    print("by category:", by_cat)
    if dry or not rows:
        for r in rows[:8]:
            print(" ", r["added_at"][:16], r["category"].ljust(9), (r["symbol"] or "-").ljust(7), r["title"][:80])
        return

    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    sb.table("announcements").upsert(rows, on_conflict="kind,nepse_id").execute()
    print(f"Saved {len(rows)} items.")
    cutoff = (datetime.now(NPT) - timedelta(days=KEEP_DAYS)).isoformat()
    sb.table("announcements").delete().lt("added_at", cutoff).execute()


if __name__ == "__main__":
    main()
