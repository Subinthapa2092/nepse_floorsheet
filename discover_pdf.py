"""
Read-only test: can we download a company's notice PDF from NEPSE and read the text inside it?
Takes the newest lock-in notice in NEPSE's list and tries a few likely download addresses.
Writes NOTHING to your database. Run from GitHub -> Actions -> "Discover notice PDF" -> Run workflow.
"""
import io
import re
import sys

import httpx

from nepse import Nepse

LIST = "/api/nots/news/companies/disclosure"
LOCK = re.compile(r"lock", re.I)


def pick(data):
    docs = []
    for it in (data.get("companyNews") or []):
        head = str(it.get("newsHeadline") or "")
        for d in it.get("applicationDocumentDetailsList") or []:
            docs.append((bool(LOCK.search(head)), head.strip(), d))
    docs.sort(key=lambda x: not x[0])
    return docs


def find_in_site_scripts():
    print("\n== Download-related addresses in NEPSE's own scripts ==")
    seen = set()
    with httpx.Client(verify=False, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as c:
        home = c.get("https://www.nepalstock.com/").text
        for s in re.findall(r'src="([^"]+\.js)"', home):
            url = s if s.startswith("http") else "https://www.nepalstock.com/" + s.lstrip("/")
            try:
                js = c.get(url).text
            except Exception:
                continue
            for m in re.finditer(r"""["'`](/api/[A-Za-z0-9_\-/\.]*(?:[Ff]ile|[Dd]ownload|[Dd]ocument)[A-Za-z0-9_\-/\.\?=]*)""", js):
                if m.group(1) not in seen:
                    seen.add(m.group(1))
                    print("  ", m.group(1))
    if not seen:
        print("   (none found)")


def main():
    n = Nepse()
    n.setTLSVerification(False)  # NEPSE's server has a known incomplete cert chain
    data = n.requestGETAPI(url=LIST)
    docs = pick(data)
    if not docs:
        print("No notice with a file found right now.")
        return
    _, head, d = docs[0]
    enc, path = d.get("encryptedId"), d.get("filePath")
    print("Testing with notice:", head)
    print("File path:", path)

    find_in_site_scripts()

    tries = []
    for base in ("/api/nots/security/fetchFiles?fileLocation=", "/api/nots/news/fetchFiles?fileLocation=", "/api/web/fetchFiles?fileLocation="):
        if enc:
            tries.append(base + enc)
        if path:
            tries.append(base + path)
    print("\n== Trying download addresses ==")
    for t in tries:
        try:
            r = n.client.get(n.get_full_url(api_url=t), headers=n.getAuthorizationHeaders())
            body = r.content
            kind = r.headers.get("content-type", "?")
            print(f"\n{r.status_code}  {kind}  {len(body)} bytes  <- {t[:90]}")
            if body[:4] == b"%PDF":
                print("   This is a PDF.")
                try:
                    from pypdf import PdfReader

                    text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(body)).pages)
                    print(f"   Text found inside: {len(text.strip())} characters")
                    print("   ----- start of text -----")
                    print(text.strip()[:1500])
                    print("   ----- end -----")
                except Exception as e:
                    print("   Could not read the text:", type(e).__name__, str(e)[:100])
                return
            print("   Start of reply:", body[:200])
        except Exception as e:
            print(f"\nFAIL  {t[:90]}  ->  {type(e).__name__}: {str(e)[:100]}")
    print("\nNo PDF came back from these addresses.")


if __name__ == "__main__":
    sys.exit(main())
