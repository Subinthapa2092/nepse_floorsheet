"""
PROBE 2 (read-only, saves nothing). Two questions left after the first NEPSE probe:
  A. Do the recent company disclosures carry the quarterly report as a PDF with real text, or as a picture?
  B. Does NEPSE's Annual Report spreadsheet (.xlsx) contain figures for each company?
Run it from GitHub: Actions > Probe NEPSE reports 2 > Run workflow. Then copy the "Look again" log into the chat.
"""
import io
import json
import re

from playwright.sync_api import sync_playwright

BASE = "https://www.nepalstock.com"
BLOCK = r"google|doubleclick|facebook|adsbygoogle|analytics|clarity|hotjar|\.(png|jpe?g|gif|svg|woff2?|ico)(\?|$)"


def main():
    disclosure, reports = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent="Arthotix/1.0 (NEPSE reports probe 2)", ignore_https_errors=True, viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        page.route("**/*", lambda route: route.abort() if re.search(BLOCK, route.request.url, re.I) else route.continue_())

        def on(r):
            try:
                if "json" not in r.headers.get("content-type", ""):
                    return
                if "news/companies/disclosure" in r.url:
                    disclosure.append(json.loads(r.body()))
                if "report/reportByCategory/3" in r.url:
                    reports.append(json.loads(r.body()))
            except Exception:
                pass

        page.on("response", on)
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)

        print("== A. documents attached to the latest company disclosures ==")
        if disclosure:
            news = disclosure[0].get("companyNews", [])
            print("disclosures:", len(news))
            kinds = {}
            for n in news:
                docs = n.get("applicationDocumentDetailsList") or []
                print(f"- {str(n.get('newsHeadline'))[:90]!r}  docs={len(docs)}")
                for d in docs[:3]:
                    print("     ", json.dumps(d, ensure_ascii=False)[:300])
                    fp = str(d.get("filePath") or d.get("fileName") or "")
                    ext = fp.rsplit(".", 1)[-1].lower() if "." in fp else "?"
                    kinds[ext] = kinds.get(ext, 0) + 1
            print("file types:", kinds)
        else:
            print("no disclosure data captured")

        print("\n== B. NEPSE annual report spreadsheet ==")
        page.goto(BASE + "/reports/annual-reports", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        files = []
        if reports:
            for r in reports[0].get("content", [])[:3]:
                files.append((r.get("filename"), r.get("filePath")))
        print("report files:", files)
        for name, fp in files[:2]:
            if not fp or not fp.lower().endswith(".xlsx"):
                continue
            url = f"{BASE}/api/web/report/download-report/{fp}"
            try:
                resp = ctx.request.get(url, timeout=60000)
                print(f"\n{name}: status {resp.status}, {len(resp.body())} bytes")
                if resp.status != 200:
                    continue
                import openpyxl

                wb = openpyxl.load_workbook(io.BytesIO(resp.body()), data_only=True, read_only=True)
                print("sheets:", wb.sheetnames)
                for ws in wb.worksheets[:12]:
                    print(f"  -- {ws.title}: {ws.max_row} rows x {ws.max_column} cols")
                    shown = 0
                    for row in ws.iter_rows(values_only=True):
                        cells = [str(c)[:22] for c in row if c not in (None, "")]
                        if cells:
                            print("     ", " | ".join(cells[:10]))
                            shown += 1
                        if shown >= 4:
                            break
            except Exception as e:
                print("could not read:", str(e)[:200])
        b.close()


if __name__ == "__main__":
    main()
