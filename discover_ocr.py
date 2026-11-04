"""
Read-only test: can OCR (software that reads printed text from a picture) read the date and share counts from a NEPSE lock-in notice PDF?
Tries the newest lock-in notices (up to 3). Writes NOTHING to your database, needs no secrets.
Run from GitHub -> Actions -> "Test notice OCR" -> Run workflow.
"""
import os
import re
import subprocess
import sys
import tempfile

from nepse import Nepse

LIST = "/api/nots/news/companies/disclosure"
LOCK = re.compile(r"lock", re.I)
NEP = str.maketrans("०१२३४५६७८९", "0123456789")
DATE = re.compile(r"(20\d\d)\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})")


def docs(data):
    out = []
    for it in data.get("companyNews") or []:
        head = str(it.get("newsHeadline") or "").strip()
        if not LOCK.search(head):
            continue
        for d in it.get("applicationDocumentDetailsList") or []:
            if d.get("filePath"):
                out.append((head, d["filePath"]))
    return out


def ocr(pdf_bytes):
    with tempfile.TemporaryDirectory() as tmp:
        pdf = os.path.join(tmp, "n.pdf")
        open(pdf, "wb").write(pdf_bytes)
        subprocess.run(["pdftoppm", "-r", "220", "-png", pdf, os.path.join(tmp, "p")], check=True)
        text = ""
        for f in sorted(x for x in os.listdir(tmp) if x.endswith(".png")):
            r = subprocess.run(["tesseract", os.path.join(tmp, f), "-", "-l", "nep+eng", "--psm", "6"], capture_output=True, text=True)
            text += r.stdout + "\n"
        return text


def main():
    n = Nepse()
    n.setTLSVerification(False)  # NEPSE's server has a known incomplete cert chain
    data = n.requestGETAPI(url="/api/nots/news/companies/disclosure")
    items = docs(data)[:3]
    if not items:
        print("No lock-in notice with a file found right now.")
        return
    for head, path in items:
        print("\n" + "=" * 70)
        print("Notice:", head)
        print("File:", path)
        r = n.client.get(n.get_full_url(api_url="/api/nots/security/fetchFiles?fileLocation=" + path), headers=n.getAuthorizationHeaders())
        if r.status_code != 200 or r.content[:4] != b"%PDF":
            print("Could not download:", r.status_code)
            continue
        text = ocr(r.content)
        flat = text.translate(NEP)
        print("\n----- what OCR read (first 1800 characters) -----")
        print(text.strip()[:1800])
        print("----- end -----")
        print("\nDates found (as written, digits converted):", [m.group(0) for m in DATE.finditer(flat)])
        print("Big numbers found:", re.findall(r"\d{1,3}(?:,\d{2,3})+", flat)[:12])


if __name__ == "__main__":
    sys.exit(main())
