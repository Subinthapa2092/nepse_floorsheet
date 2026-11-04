"""
Reads new lock-in notices saved by collect_company_news.py: downloads each notice PDF from NEPSE, reads it with OCR,
and works out the first day the shares can trade.

  - A date is published to `promoter_unlock` ONLY when the Nepali date, converted with a calendar library, equals the English
    date printed beside it in the same notice, and it does not disagree with a date you already entered.
  - Everything else is left in `company_news` with status 'review' and the reason, for a person to check.
"""
import os
import subprocess
import sys
import tempfile
from datetime import date

from dotenv import load_dotenv
from supabase import create_client

from nepse import Nepse
from notice_parse import parse

load_dotenv()
LIMIT = 15


def ocr_pdf(pdf_bytes: bytes) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        pdf = os.path.join(tmp, "n.pdf")
        with open(pdf, "wb") as f:
            f.write(pdf_bytes)
        subprocess.run(["pdftoppm", "-r", "220", "-png", pdf, os.path.join(tmp, "p")], check=True)
        text = ""
        for name in sorted(x for x in os.listdir(tmp) if x.endswith(".png")):
            r = subprocess.run(["tesseract", os.path.join(tmp, name), "-", "-l", "nep+eng", "--psm", "6"], capture_output=True, text=True)
            text += r.stdout + "\n"
        return text


def main():
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    todo = (
        db.table("company_news").select("source,news_id,title,raw")
        .eq("flagged", True).eq("source", "company").is_("status", "null").limit(LIMIT).execute().data or []
    )
    if not todo:
        print("No new lock-in notices to read.")
        return

    nepse = Nepse()
    nepse.setTLSVerification(False)  # NEPSE's server has a known incomplete cert chain
    today = date.today()

    for row in todo:
        title = row["title"] or ""
        paths = [d["filePath"] for d in (row["raw"] or {}).get("applicationDocumentDetailsList", []) if d.get("filePath")]
        results, texts, failed = [], [], False
        for p in paths:
            try:
                r = nepse.client.get(nepse.get_full_url(api_url="/api/nots/security/fetchFiles?fileLocation=" + p), headers=nepse.getAuthorizationHeaders())
                if r.status_code != 200 or r.content[:4] != b"%PDF":
                    failed = True
                    continue
                text = ocr_pdf(r.content)
                texts.append(text)
                results.append(parse(title, text, today=today))
            except Exception as e:  # leave it for the next run
                print(f"  could not read {p}: {type(e).__name__}")
                failed = True
        if failed and not results:
            print(f"[retry later] {title}")
            continue

        good = [r for r in results if r["status"] == "publish"]
        unlocks = {g["unlock"] for g in good}
        if len(unlocks) == 1:
            g = good[0]
            status, why = "published", g["why"]
            old = db.table("promoter_unlock").select("unlock_date").eq("symbol", g["symbol"]).eq("share_type", g["share_type"]).execute().data or []
            if old and str(old[0]["unlock_date"])[:10] != g["unlock"]:
                status, why = "review", f"differs from the date already entered ({old[0]['unlock_date']}); notice says {g['unlock']}"
            elif not old:
                db.table("promoter_unlock").insert({
                    "symbol": g["symbol"], "share_type": g["share_type"], "unlock_date": g["unlock"],
                    "source": f"Read from the company's NEPSE notice (company news {row['news_id']}); BS date matches the printed English date",
                }).execute()
            result = {**g, "status": status, "why": why}
        else:
            status = "review"
            why = "; ".join(r["why"] for r in results) or "nothing readable"
            if len(unlocks) > 1:
                why = "the notice's files give different dates: " + ", ".join(sorted(unlocks))
            result = {"status": status, "why": why}

        db.table("company_news").update({
            "status": status, "result": result, "reviewed": status == "published", "ocr_text": "\n\n=====\n\n".join(texts)[:20000],
        }).eq("source", row["source"]).eq("news_id", row["news_id"]).execute()
        print(f"[{status}] {title}  ->  {result.get('unlock', '')}  {result['why']}")


if __name__ == "__main__":
    sys.exit(main())
