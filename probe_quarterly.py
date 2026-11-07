"""
PROBE (read-only, saves nothing): where do the numbers in Merolagani's "Quarterly Report" tab come from?
It opens ONE company page (NABIL) once, clicks the tab, and prints what the page asked for and what the table holds.
Run it from GitHub: Actions > Probe quarterly figures > Run workflow. Then copy the whole log into the chat.
"""
import re
import sys

from playwright.sync_api import sync_playwright

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "NABIL"
URL = f"https://merolagani.com/CompanyDetail.aspx?symbol={SYMBOL}"


def main():
    seen = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent="Arthotix/1.0 (quarterly figures probe)", viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        page.on("response", lambda r: seen.append((r.request.method, r.status, r.url, r.headers.get("content-type", ""), r.request.post_data)))
        page.goto(URL, wait_until="networkidle", timeout=60000)
        before = len(seen)
        print("page title:", page.title())

        tabs = page.locator("a[data-toggle='tab'], ul.nav-tabs a, .nav-tabs a, a[href^='#']").all()
        print("\n== tab-like links ==")
        for t in tabs[:40]:
            try:
                print(" -", (t.inner_text() or "").strip()[:40], "|", t.get_attribute("href"), "|", t.get_attribute("id"))
            except Exception:
                pass

        clicked = False
        for sel in ("text=Quarterly Report", "a:has-text('Quarterly')"):
            try:
                page.locator(sel).first.click(timeout=8000)
                clicked = True
                break
            except Exception:
                continue
        print("\nclicked the Quarterly tab:", clicked)
        page.wait_for_timeout(6000)

        print("\n== requests made AFTER the click (method, status, url, type, posted data) ==")
        for m, s, u, ct, pd in seen[before:]:
            if re.search(r"\.(png|jpe?g|gif|svg|css|woff2?|ico)(\?|$)|google|facebook|doubleclick|analytics|adsbygoogle", u, re.I):
                continue
            print(f" {m} {s} {u[:200]} | {ct[:40]} | {(pd or '')[:200]}")

        print("\n== text of tables that mention profit / EPS / net worth ==")
        n = 0
        for tb in page.locator("table").all():
            try:
                txt = tb.inner_text()
            except Exception:
                continue
            if re.search(r"net profit|eps|net worth|paid up", txt, re.I):
                n += 1
                rows = [re.sub(r"\s+", " ", r).strip() for r in txt.split("\n") if r.strip()]
                print(f"--- table {n}: {len(rows)} lines (first 45) ---")
                for r in rows[:45]:
                    print("  ", r[:160])
                if n >= 3:
                    break
        if n == 0:
            print("(no table with those words found)")
            body = re.sub(r"\s+", " ", page.inner_text("body"))
            i = body.lower().find("quarter")
            print("text near 'quarter':", body[max(i - 100, 0): i + 600])
        b.close()


if __name__ == "__main__":
    main()
