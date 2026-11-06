"""
Saves NEPSE's company announcements and exchange notices into the `announcements` table.
Run the SQL file sql/announcements.sql in Supabase once first.

    python fetch_announcements.py            # fetch and save
    python fetch_announcements.py --dry-run  # only show what it would save

NEPSE shows a rolling window (about the last 4 weeks), so this runs every 30 minutes and our own table keeps the history.
Safe to run any number of times: an item is saved once (matched by NEPSE's id), later runs only update it.
"""
import html
import mimetypes
import os
import re
import sys
from datetime import datetime, timedelta, timezone

NPT = timezone(timedelta(hours=5, minutes=45))
KEEP_DAYS = 400
DOC_KEEP_DAYS = 120          # documents are kept this long, then removed to stay inside the free 1 GB file storage
DOC_MAX_BYTES = 5 * 1024 * 1024
DOC_PER_RUN = 25
DOC_BUCKET = "announcement-docs"
DOC_TYPES = {"pdf", "jpg", "jpeg", "png", "doc", "docx", "xls", "xlsx"}

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
            "_file": next((d.get("filePath") for d in (r.get("applicationDocumentDetailsList") or []) if isinstance(d, dict) and d.get("filePath")), None),
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
            "has_file": bool(r.get("filePath")), "added_at": added, "_file": r.get("filePath") or None,
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
    files = {(r["kind"], r["nepse_id"]): r["_file"] for r in rows if r.get("_file")}
    sb.table("announcements").upsert([{k: v for k, v in r.items() if k != "_file"} for r in rows], on_conflict="kind,nepse_id").execute()
    print(f"Saved {len(rows)} items.")
    save_documents(sb, nepse, files)
    drop_old_documents(sb)
    cutoff = (datetime.now(NPT) - timedelta(days=KEEP_DAYS)).isoformat()
    sb.table("announcements").delete().lt("added_at", cutoff).execute()


def save_documents(sb, nepse, files):
    """Copies each announcement's document into our own file storage, so the website can open it.
    NEPSE only hands documents to a logged-in app, so a plain link to NEPSE would not open."""
    if not files:
        return
    ids = sorted({i for _, i in files})
    have = sb.table("announcements").select("kind,nepse_id,doc_path").in_("nepse_id", ids).execute().data or []
    done = {(h["kind"], h["nepse_id"]) for h in have if h.get("doc_path")}
    todo = [(k, f) for k, f in files.items() if k not in done][:DOC_PER_RUN]
    ok = skipped = 0
    for (kind, nid), path in todo:
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext not in DOC_TYPES:
            skipped += 1
            continue
        try:
            r = nepse.client.get(nepse.get_full_url(api_url="/api/nots/security/fetchFiles?fileLocation=" + path), headers=nepse.getAuthorizationHeaders())
            if r.status_code != 200 or not r.content or len(r.content) > DOC_MAX_BYTES:
                skipped += 1
                continue
            if ext == "pdf" and r.content[:4] != b"%PDF":
                skipped += 1
                continue
            name = f"{kind}/{nid}.{ext}"
            sb.storage.from_(DOC_BUCKET).upload(path=name, file=r.content, file_options={"content-type": mimetypes.guess_type(name)[0] or "application/octet-stream", "upsert": "true"})
            sb.table("announcements").update({"doc_path": name}).eq("kind", kind).eq("nepse_id", nid).execute()
            ok += 1
        except Exception as e:  # try again on the next run
            print(f"  could not save document for {kind} {nid}: {type(e).__name__}")
    print(f"Documents: {ok} saved, {skipped} skipped, {max(0, len([k for k in files if k not in done]) - len(todo))} left for the next run.")


def drop_old_documents(sb):
    cutoff = (datetime.now(NPT) - timedelta(days=DOC_KEEP_DAYS)).isoformat()
    old = sb.table("announcements").select("kind,nepse_id,doc_path").lt("added_at", cutoff).not_.is_("doc_path", "null").limit(200).execute().data or []
    if not old:
        return
    sb.storage.from_(DOC_BUCKET).remove([o["doc_path"] for o in old])
    for o in old:
        sb.table("announcements").update({"doc_path": None}).eq("kind", o["kind"]).eq("nepse_id", o["nepse_id"]).execute()
    print(f"Removed {len(old)} documents older than {DOC_KEEP_DAYS} days.")

if __name__ == "__main__":
    main()
