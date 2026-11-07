"""
PROBE (read-only, saves nothing): how readable are the quarterly report FILES, across years and sectors?
Downloads a handful of reports ONCE (one request every 2 seconds), then prints for each: file type, size, and the lines that
mention profit, equity, capital, EPS. PDFs are read by their text layer; pictures are read with OCR (tesseract).
Run it from GitHub: Actions > Probe report files > Run workflow. Copy the "Read the files" log into the chat.
"""
import io
import re
import subprocess
import sys
import tempfile
import time

import httpx
from PIL import Image

PAGE = "https://merolagani.com/AnnouncementDetail.aspx?id={}&ntf=true"
FILE_RE = re.compile(r"(?:https?://images\.merolagani\.com)?/+Uploads/Repository/[0-9A-Za-z_\-]+\.(pdf|gif|jpe?g|png)", re.I)
# (announcement id, what it is)
SAMPLES = [
    ("68093", "NABIL Q1 2083/84 (bank, newest)"), ("68087", "SBL Q1 2083/84 (bank)"), ("68074", "SINDU Q1 2083/84 (microfinance)"),
    ("62237", "NABIL Q1 2082/83"), ("55613", "NABIL 2024"), ("48043", "NABIL 2023"), ("40521", "NABIL 2021-22"), ("33256", "NABIL older"), ("29581", "NABIL oldest on page 1"),
]
KEY = re.compile(r"net profit|operating profit|total equity|share capital|paid.?up|earning.? per share|\beps\b|total assets|return on equity|net worth|non.?performing|capital adequacy|distributable", re.I)


def find_file(html):
    found = []
    for m in FILE_RE.finditer(html or ""):
        path = re.sub(r"^.*?/+Uploads/", "/Uploads/", m.group(0))
        found.append(("https://images.merolagani.com/Uploads/" + path.split("/Uploads/", 1)[1].lstrip("/"), m.group(1).lower()))
    for url, ext in found:
        if ext == "pdf":
            return url, ext
    return found[0] if found else (None, None)


def show(lines, n=22):
    shown = 0
    for ln in lines:
        ln = re.sub(r"\s+", " ", ln).strip()
        if len(ln) > 6 and KEY.search(ln):
            print("     ", ln[:170])
            shown += 1
            if shown >= n:
                break
    if shown == 0:
        print("      (no line with the key words)")


def main():
    with httpx.Client(headers={"User-Agent": "Arthotix/1.0 (report readability probe)"}, timeout=40, follow_redirects=True) as http:
        for aid, label in SAMPLES:
            print(f"\n=== {aid}  {label}")
            try:
                page = http.get(PAGE.format(aid))
                time.sleep(2)
                url, ext = find_file(page.text)
                print("   page:", page.status_code, "| file:", url, ext)
                if not url:
                    continue
                f = http.get(url)
                time.sleep(2)
                data = f.content
                print("   file answered:", f.status_code, "| bytes:", len(data))
                if ext == "pdf":
                    with tempfile.NamedTemporaryFile(suffix=".pdf") as t:
                        t.write(data)
                        t.flush()
                        info = subprocess.run(["pdfinfo", t.name], capture_output=True, text=True).stdout
                        pages = re.search(r"Pages:\s+(\d+)", info)
                        txt = subprocess.run(["pdftotext", "-layout", t.name, "-"], capture_output=True, text=True).stdout
                    print("   PDF pages:", pages.group(1) if pages else "?", "| text characters:", len(txt), "(0 or tiny = scanned picture inside a PDF)")
                    show(txt.split("\n"))
                else:
                    im = Image.open(io.BytesIO(data))
                    print("   picture size:", im.size, im.mode)
                    im = im.convert("L")
                    scale = 3 if im.width < 2500 else 1
                    im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
                    with tempfile.NamedTemporaryFile(suffix=".png") as t:
                        im.save(t.name)
                        txt = subprocess.run(["tesseract", t.name, "-", "--psm", "6"], capture_output=True, text=True).stdout
                    print("   OCR characters:", len(txt))
                    show(txt.split("\n"))
            except Exception as e:
                print("   problem:", type(e).__name__, str(e)[:150])


if __name__ == "__main__":
    main()
