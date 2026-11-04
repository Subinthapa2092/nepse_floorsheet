"""
Saves NEPSE's newest announcements (NEPSE's own and the ones companies post) into `company_news`,
and marks the ones that mention lock-in or promoter shares so a person can check them.
It never publishes anything to the website. Unlock dates are added only by hand, from the notice itself.

Runs from GitHub Actions a few times a day, with the same secrets as your other jobs.
"""
import json
import os
import re
import sys

from dotenv import load_dotenv
from supabase import create_client

from nepse import Nepse

load_dotenv()

URL = "/api/nots/news/companies/disclosure"
FLAG = re.compile(r"lock[\s\-]*in|locking|promoter|संस्थापक|लक\s*इन", re.I)


def first(d: dict, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def clean(html) -> str:
    t = re.sub(r"<[^>]+>", " ", str(html or ""))
    t = re.sub(r"&nbsp;|&quot;|&amp;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def file_of(item: dict):
    p = item.get("filePath")
    if p:
        return p
    for doc in item.get("applicationDocumentDetailsList") or []:
        if doc.get("filePath"):
            return doc["filePath"]
    return None


def row(source: str, item: dict) -> dict:
    text = json.dumps(item, ensure_ascii=False)
    title = first(item, ("messageTitle", "newsHeadline", "newsHeading", "headline", "title", "subject"))
    body = first(item, ("messageBody", "newsBody", "body", "description"))
    company = first(item, ("companyName", "company", "issuerName", "symbol"))
    day = first(item, ("addedDate", "submittedDate", "newsDate", "approvedDate"))
    return {
        "source": source,
        "news_id": int(item["id"]),
        "title": clean(title)[:300] if title else (clean(body)[:200] if body else None),
        "company": clean(company)[:150] if company else None,
        "added_on": str(day)[:10] if day else None,
        "file_path": file_of(item),
        "flagged": bool(FLAG.search(text)),
        "raw": item,
    }


def main():
    nepse = Nepse()
    nepse.setTLSVerification(False)  # NEPSE's server has a known incomplete cert chain
    data = nepse.requestGETAPI(url=URL)
    rows = []
    for key, source in (("exchangeMessages", "exchange"), ("companyNews", "company")):
        for it in (data.get(key) or []) if isinstance(data, dict) else []:
            if isinstance(it, dict) and it.get("id") is not None:
                rows.append(row(source, it))
    if not rows:
        print("Nothing returned.")
        return

    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    # keep what is already saved (and your 'reviewed' marks): only insert items not seen before
    have = db.table("company_news").select("source,news_id").in_("news_id", [r["news_id"] for r in rows]).execute().data or []
    seen = {(h["source"], h["news_id"]) for h in have}
    new = [r for r in rows if (r["source"], r["news_id"]) not in seen]
    if new:
        db.table("company_news").insert(new).execute()
    print(f"{len(rows)} items on NEPSE now, {len(new)} new saved, {sum(1 for r in new if r['flagged'])} flagged.")
    for r in new:
        print(("  FLAG " if r["flagged"] else "       ") + f"[{r['source']}] {r['added_on']}  {r['company'] or ''}  {r['title'] or ''}")


if __name__ == "__main__":
    sys.exit(main())
