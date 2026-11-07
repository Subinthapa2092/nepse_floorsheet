"""
Reads the saved quarterly report pictures (table report_docs) and puts the key figures into company_financials as 'review'.
NOTHING is published by this script: you approve the figures first. Each figure is marked checked / single / mismatch.

    python read_reports.py --dry-run          # read, print a summary, save nothing
    python read_reports.py                    # read up to 30 new reports and save the figures
    python read_reports.py --limit 100        # more at once
    python read_reports.py --symbol NABIL     # one company
    python read_reports.py --export --limit 60   # copy the pictures out (no reading) so they can be read by eye
    python read_reports.py --redo             # read again even if the report was read before (published figures are never touched)

Needs: tesseract (apt install tesseract-ocr), pip install pillow numpy httpx supabase python-dotenv
Run sql/company_financials.sql in Supabase once first.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import report_reader as rr

BUCKET = "announcement-docs"
IMAGE_EXT = {"gif", "jpg", "jpeg", "png"}
ORD = {"1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3, "4th": 4, "fourth": 4}
MONTH_Q = {"ashwin": 1, "ashoj": 1, "aswin": 1, "poush": 2, "paush": 2, "chaitra": 3, "chait": 3, "ashadh": 4, "asar": 4, "ashad": 4, "asadh": 4}


def fy_label(start):
    """2083 -> '083/084'"""
    return f"{start % 1000:03d}/{(start + 1) % 1000:03d}"


def detect_period(text):
    """(fiscal_year, 'Q1'..'Q4') from the picture's own heading, or (None, None).
    Looks for '1st Quarter of FY 2025-26 (2082/83)' first, then 'Quarter ended 31st Ashwin 2083'."""
    t = re.sub(r"\s+", " ", text or "")
    q = None
    m = re.search(r"\b(1st|first|2nd|second|3rd|third|4th|fourth)\s+quarter", t, re.I)
    if m:
        q = ORD[m.group(1).lower()]
    else:
        m = re.search(r"\b([1-4])\s*(?:st|nd|rd|th)?\s+quarter", t, re.I)  # the small 'st' is often lost by OCR
        if m:
            q = int(m.group(1))
    fy = None
    m2 = re.search(r"\b(208\d)\s*[/-]\s*(\d{2,4})\b", t)
    if m2:
        fy = int(m2.group(1))
    m3 = re.search(r"quarter\s+end(?:ed|ing)?\s*(?:on)?\s*(?:\d{1,2}\w{0,2}\s+)?([A-Za-z]+)\s+(208\d)", t, re.I)
    if m3 and m3.group(1).lower() in MONTH_Q:
        mq = MONTH_Q[m3.group(1).lower()]
        yr = int(m3.group(2))
        start = yr if mq in (1, 2) else yr - 1
        if q is None:
            q = mq
        if fy is None:
            fy = start
    if q and fy:
        return fy_label(fy), f"Q{q}"
    return None, None


def confidence(measure, checks_ok, agree=1):
    """checked = the EPS cross-check passed, or two reading passes gave the same number. mismatch = the cross-check failed."""
    if measure in ("net_profit", "paid_up_capital", "eps_annualized") and checks_ok is False:
        return "mismatch"
    if (measure in ("net_profit", "paid_up_capital", "eps_annualized") and checks_ok is True) or agree >= 2:
        return "checked"
    return "single"


def main():
    dry = "--dry-run" in sys.argv
    redo = "--redo" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 30
    only = sys.argv[sys.argv.index("--symbol") + 1].upper() if "--symbol" in sys.argv else None
    export = "--export" in sys.argv
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are missing. Put them in the .env file here, or run the workflow on GitHub.")
    from supabase import create_client

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    return run(sb, dry, redo, limit, only, export)


def run(sb, dry, redo, limit, only, export=False):
    docs = sb.table("report_docs").select("announcement_id,doc_path").limit(5000).execute().data or []
    reps = {r["announcement_id"]: r for r in (sb.table("quarterly_reports").select("symbol,announcement_id,fiscal_year,date_text").limit(5000).execute().data or [])}
    done = set()
    if not redo:
        for r in sb.table("company_financials").select("source").limit(20000).execute().data or []:
            if r.get("source"):
                done.add(r["source"])
    todo, why = [], {"no file saved": 0, "no matching report row": 0, "PDF (not read yet)": 0, "other file type": 0, "already read": 0}
    for d in docs:
        path = d.get("doc_path") or ""
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        aid = d["announcement_id"]
        rep = reps.get(aid)
        if not path:
            why["no file saved"] += 1
            continue
        if not rep:
            why["no matching report row"] += 1
            continue
        if only and rep["symbol"] != only:
            continue
        if ext == "pdf":
            why["PDF (not read yet)"] += 1
            continue
        if ext not in IMAGE_EXT:
            why["other file type"] += 1
            continue
        if aid in done:
            why["already read"] += 1
            continue
        todo.append((aid, rep["symbol"], path))
    print(f"{len(docs)} rows in report_docs. Left out: " + ", ".join(f"{k} {v}" for k, v in why.items() if v) + f". {len(todo)} pictures to read, reading {min(limit, len(todo))}.\n")
    keep = Path("debug_pics")
    kept = 0
    if export:  # just copy the pictures out so they can be read by eye: no reading, nothing saved to the database
        keep.mkdir(exist_ok=True)
        for aid, sym, path in todo[:limit]:
            try:
                (keep / f"{sym}_{aid}.{path.rsplit('.', 1)[-1].lower()}").write_bytes(sb.storage.from_(BUCKET).download(path))
                kept += 1
            except Exception as e:
                print(f"{sym} {aid}: could not copy ({str(e)[:80]})")
        print(f"Copied {kept} pictures. On the run page, open Artifacts at the bottom and download debug-pictures.")
        return 0

    summary = {"ok": 0, "mismatch": 0, "no_check": 0, "no_period": 0, "error": 0}
    for aid, sym, path in todo[:limit]:
        try:
            blob = sb.storage.from_(BUCKET).download(path)
            with tempfile.TemporaryDirectory() as td:
                f = Path(td) / ("r." + path.rsplit(".", 1)[-1])
                f.write_bytes(blob)
                res = rr.read_multi(str(f))
        except Exception as e:
            summary["error"] += 1
            print(f"{sym:8s} {aid}: could not read ({str(e)[:80]})")
            continue
        fy, period = detect_period((res.get("heading") or "") + " " + (res.get("text") or ""))
        chk = rr.checks(res)
        eps_chk = next((ok for name, ok, _ in chk if name.startswith("EPS")), None)
        n = len(res["found"])
        weak = (not period) or n < 6 or eps_chk is None
        if weak and kept < 25:
            keep.mkdir(exist_ok=True)
            (keep / f"{sym}_{aid}.{path.rsplit('.', 1)[-1].lower()}").write_bytes(blob)
            (keep / f"{sym}_{aid}.txt").write_text("HEADING\n" + (res.get("heading") or "") + "\n\nFOUND\n" + "\n".join(f"{k}: {v['value']}  <- {v['label']!r} {v['numbers']}" for k, v in res["found"].items()) + "\n\nTEXT\n" + (res.get("text") or ""), encoding="utf-8")
            kept += 1
        if not period:
            summary["no_period"] += 1
            print(f"{sym:8s} {aid}: {n} figures but the quarter could not be read from the heading, skipped")
            continue
        summary["ok" if eps_chk is True else "mismatch" if eps_chk is False else "no_check"] += 1
        flag = "EPS ok" if eps_chk is True else "EPS MISMATCH" if eps_chk is False else "no EPS check"
        print(f"{sym:8s} {fy} {period}: {n:2d} figures, {flag}")
        if dry:
            continue
        existing = {(r["metric"]): r["status"] for r in (sb.table("company_financials").select("metric,status").eq("symbol", sym).eq("fiscal_year", fy).eq("period", period).execute().data or [])}
        rows = []
        for metric, v in res["found"].items():
            if metric == "eps_annualized" and eps_chk is not True:
                continue  # an EPS that could not be confirmed (a lost decimal point, or last year's column) would only mislead the reviewer
            if existing.get(metric, "review") != "review":
                continue  # a figure you already approved or rejected is never overwritten
            rows.append({
                "symbol": sym, "fiscal_year": fy, "period": period, "metric": metric, "value": v["value"], "status": "review",
                "confidence": confidence(metric, eps_chk, v.get("agree", 1)), "source": aid, "source_url": None,
                "note": None if eps_chk is not False else "EPS does not match profit / share capital",
            })
        if rows:
            sb.table("company_financials").upsert(rows, on_conflict="symbol,fiscal_year,period,metric").execute()
    total = sum(summary.values())
    if kept:
        print(f"\n{kept} pictures that were hard to read were saved for me: on the run page, open Artifacts at the bottom and download debug-pictures.")
    print(f"\nRead {total}: EPS check passed {summary['ok']}, mismatch {summary['mismatch']}, no check possible {summary['no_check']}, quarter unreadable {summary['no_period']}, errors {summary['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
