"""
PROBE (read-only, saves nothing): what is inside Merolagani's "Quarterly Report" tab?
Opens ONE company page once, opens the tab, and prints the table text, the dropdowns, the paging links and the requests made.
Run it from GitHub: Actions > Probe quarterly figures > Run workflow. Then copy the "Look at the page" log into the chat.
"""
import re
import sys

from playwright.sync_api import sync_playwright

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "NABIL"
URL = f"https://merolagani.com/CompanyDetail.aspx?symbol={SYMBOL}"
TAB_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_lnkQuaterlyTab"
BLOCK = r"google|doubleclick|facebook|adsbygoogle|analytics|clarity|hotjar|\.(png|jpe?g|gif|svg|woff2?)(\?|$)"


def lines_of(text, n):
    rows = [re.sub(r"\s+", " ", r).strip() for r in text.split("\n") if r.strip()]
    return rows[:n], len(rows)


def main():
    seen = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent="Arthotix/1.0 (quarterly figures probe)", viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        page.route("**/*", lambda route: route.abort() if re.search(BLOCK, route.request.url, re.I) else route.continue_())
        page.on("response", lambda r: seen.append((r.request.method, r.status, r.url, r.headers.get("content-type", ""), r.request.post_data)))
        resp = page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        print("page status:", resp.status if resp else None)
        page.wait_for_timeout(4000)
        before = len(seen)

        info = page.evaluate("""(id) => {
            const a = document.getElementById(id);
            if (!a) return {found: false};
            const out = {found: true, href: a.getAttribute('href'), onclick: a.getAttribute('onclick'), text: a.innerText};
            a.click();
            return out;
        }""", TAB_ID)
        print("tab link:", info)
        page.wait_for_timeout(8000)

        print("\n== requests made AFTER the click (method, status, url, type, posted data) ==")
        for m, s, u, ct, pd in seen[before:]:
            print(f" {m} {s} {u[:220]} | {ct[:40]} | {(pd or '')[:300]}")

        panel = page.locator("#divQuaterly")
        print("\npanel found:", panel.count(), "| visible:", panel.first.is_visible() if panel.count() else None)
        if panel.count():
            txt = panel.first.inner_text()
            rows, total = lines_of(txt, 120)
            print(f"\n== text inside #divQuaterly: {total} lines (first 120) ==")
            for r in rows:
                print("  ", r[:180])
            print("\n== dropdowns inside the panel ==")
            for sel in panel.first.locator("select").all():
                opts = [o.inner_text().strip() for o in sel.locator("option").all()]
                print(" select", sel.get_attribute("id"), "->", opts[:30])
            print("\n== paging / links inside the panel ==")
            for a in panel.first.locator("a").all()[:40]:
                print(" ", (a.inner_text() or "").strip()[:30], "|", a.get_attribute("href"), "|", a.get_attribute("id"))
            html = panel.first.inner_html()
            print("\npanel html length:", len(html))
            print("first 1500 chars of panel html:\n", re.sub(r"\s+", " ", html)[:1500])
        b.close()


if __name__ == "__main__":
    main()
