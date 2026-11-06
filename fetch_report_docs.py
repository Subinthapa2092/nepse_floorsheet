"""
Saves the PDF of each recent quarterly report into our own file storage, so the Reports page can open it.
Run sql/report_docs.sql in Supabase once first.

    python fetch_report_docs.py --dry-run     # only list what it would copy
    python fetch_report_docs.py               # copy (up to 40 per run)
    python fetch_report_docs.py --limit 100

The report list is our own `quarterly_reports` table. Each report's announcement_id is the page number of the
announcement on Merolagani, whose owner has allowed Arthotix to copy these report files. Be gentle: one request every
2 seconds, only reports from the last 120 days, each file copied once, and a report that has no file is tried at most 3 times.
"""
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()  # reads the .env file next to this script, if there is one (on GitHub the keys come from secrets)
except ImportError:
    pass

KEEP_DAYS = 45
MAX_BYTES = 5 * 1024 * 1024
DEFAULT_LIMIT = 40
PAUSE = 2.0
BUCKET = "announcement-docs"
UA = "Arthotix/1.0 (quarterly report documents)"
PAGE = "https://merolagani.com/AnnouncementDetail.aspx?id={}&ntf=true"
FILE_RE = re.compile(r"(?:https?://images\.merolagani\.com)?/+Uploads/Repository/[0-9A-Za-z_\-]+\.(pdf|gif|jpe?g|png)", re.I)
MAGIC = {"pdf": (b"%PDF",), "gif": (b"GIF8",), "jpg": (b"\xff\xd8",), "jpeg": (b"\xff\xd8",), "png": (b"\x89PNG",)}
CTYPE = {"pdf": "application/pdf", "gif": "image/gif", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}


def report_day(date_text):
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_text or "")
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def find_file_url(html):
    """The report's file on the announcement page: a PDF when there is one, otherwise the image the company uploaded."""
    found = []
    for m in FILE_RE.finditer(html or ""):
        path = re.sub(r"^.*?/+Uploads/", "/Uploads/", m.group(0))
        found.append(("https://images.merolagani.com" + path.replace("/Uploads/", "//Uploads/", 1).replace("//", "/", 1), m.group(1).lower()))
    for url, ext in found:
        if ext == "pdf":
            return url, ext
    return found[0] if found else (None, None)


def main():
    dry = "--dry-run" in sys.argv
    limit = DEFAULT_LIMIT
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    from supabase import create_client
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are missing. Put them in the .env file in this folder (same as your other scripts), or just run the workflow on GitHub.")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    cutoff = date.today() - timedelta(days=KEEP_DAYS)

    reports = sb.table("quarterly_reports").select("symbol,announcement_id,date_text").order("date_text", desc=True).limit(3000).execute().data or []
    recent = []
    for r in reports:
        d = report_day(r.get("date_text"))
        if d and d >= cutoff and (r.get("announcement_id") or "").isdigit():
            recent.append((r["announcement_id"], r["symbol"], d))
    have = {h["announcement_id"]: h for h in (sb.table("report_docs").select("announcement_id,doc_path,attempts").limit(5000).execute().data or [])}
    todo = [x for x in recent if not (have.get(x[0]) or {}).get("doc_path") and (have.get(x[0]) or {}).get("attempts", 0) < 3]
    print(f"{len(recent)} reports in the last {KEEP_DAYS} days, {len(todo)} still need a file.")
    if dry:
        for aid, sym, d in todo[:15]:
            print("  ", d, sym, aid)
        return

    ok = missing = total = 0
    reasons = {}
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as http:
        for aid, sym, d in todo[:limit]:
            path = None
            why = None
            try:
                page = http.get(PAGE.format(aid))
                time.sleep(PAUSE)
                if page.status_code != 200:
                    why = f"page answered {page.status_code}"
                else:
                    url, ext = find_file_url(page.text)
                    if not url:
                        why = "page has no file link"
                    else:
                        f = http.get(url)
                        time.sleep(PAUSE)
                        if f.status_code != 200:
                            why = f"file answered {f.status_code}"
                        elif not f.content.startswith(MAGIC[ext]):
                            why = f"file is not a real {ext}"
                        elif len(f.content) > MAX_BYTES:
                            why = "file is over 5 MB"
                        else:
                            name = f"reports/{aid}.{ext}"
                            sb.storage.from_(BUCKET).upload(path=name, file=f.content, file_options={"content-type": CTYPE[ext], "upsert": "true"})
                            path = name
                            total += len(f.content)
            except Exception as e:  # tried again on the next run, up to 3 times
                why = type(e).__name__ + ": " + str(e)[:80]
            if why:
                reasons[why] = reasons.get(why, 0) + 1
                if sum(reasons.values()) <= 3:
                    print(f"  {sym} {aid}: {why}")
            prev = (have.get(aid) or {}).get("attempts", 0)
            sb.table("report_docs").upsert(
                {"announcement_id": aid, "symbol": sym, "report_date": d.isoformat(), "doc_path": path,
                 "attempts": prev + (0 if path else 1), "tried_at": datetime.now(timezone.utc).isoformat()},
                on_conflict="announcement_id").execute()
            ok += 1 if path else 0
            missing += 0 if path else 1
    if reasons:
        print("Why files were not saved:", reasons)
    print(f"Saved {ok} report files ({total / 1048576:.1f} MB, about {total / max(ok, 1) / 1048576:.2f} MB each), {missing} without a file this time.")

    old = sb.table("report_docs").select("announcement_id,doc_path").lt("report_date", cutoff.isoformat()).limit(300).execute().data or []
    if old:
        files = [o["doc_path"] for o in old if o.get("doc_path")]
        if files:
            sb.storage.from_(BUCKET).remove(files)
        sb.table("report_docs").delete().in_("announcement_id", [o["announcement_id"] for o in old]).execute()
        print(f"Removed {len(old)} report files older than {KEEP_DAYS} days.")


if __name__ == "__main__":
    main()