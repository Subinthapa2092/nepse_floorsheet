"""
PROBE (read-only, saves nothing): does NEPSE's own website publish company financial figures as data?
Opens nepalstock.com pages like a visitor, and prints
  1. the menu links that look related (reports, disclosures, financial, listing, company),
  2. for each page visited: the data requests the page made (JSON) with their field names and one sample row,
  3. the file links on the page (pdf, jpg, gif, xlsx).
Run it from GitHub: Actions > Probe NEPSE reports > Run workflow. Then copy the "Look at NEPSE" log into the chat.
"""
import json
import re
import sys

from playwright.sync_api import sync_playwright

BASE = "https://www.nepalstock.com"
BLOCK = r"google|doubleclick|facebook|adsbygoogle|analytics|clarity|hotjar|\.(png|jpe?g|gif|svg|woff2?|ico)(\?|$)"
WANT = re.compile(r"report|disclos|financ|quarter|annual|listing|company|result|fundamental|announce|news", re.I)
FILE = re.compile(r"\.(pdf|xlsx?|docx?|zip|jpe?g|gif|png)(\?|$)", re.I)

# extra pages worth trying even if the menu does not link them
TRY = ["/", "/reports/annual-reports", "/reports/agm-reports", "/reports/other-reports", "/company/detail/131", "/company", "/disclosure", "/company-disclosure"]


def shape(x, depth=0):
    """Field names of a JSON value, one sample row, short."""
    if isinstance(x, list):
        return f"list[{len(x)}] of " + (shape(x[0], depth + 1) if x else "nothing")
    if isinstance(x, dict):
        keys = list(x.keys())
        if depth < 1:
            inner = {k: shape(v, depth + 1) for k, v in list(x.items())[:14] if isinstance(v, (list, dict))}
            return "{" + ", ".join(keys[:30]) + "}" + (f" nested: {inner}" if inner else "")
        return "{" + ", ".join(keys[:20]) + "}"
    return type(x).__name__


def visit(ctx, path, seen_urls):
    page = ctx.new_page()
    page.route("**/*", lambda route: route.abort() if re.search(BLOCK, route.request.url, re.I) else route.continue_())
    got = []

    def on_resp(r):
        try:
            ct = r.headers.get("content-type", "")
            if "json" in ct and "nepalstock" in r.url:
                got.append((r.request.method, r.status, r.url, r.request.post_data, r.body()))
        except Exception:
            pass

    page.on("response", on_resp)
    url = path if path.startswith("http") else BASE + path
    print(f"\n######## {url}")
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        print("status:", resp.status if resp else None)
        page.wait_for_timeout(6000)
    except Exception as e:
        print("could not open:", str(e)[:200])
        page.close()
        return []
    print("title:", page.title()[:100])
    text = re.sub(r"\s+", " ", page.inner_text("body"))[:500]
    print("text start:", text)
    files = page.eval_on_selector_all("a[href]", "els => els.map(e => [e.innerText.trim().slice(0,60), e.href])")
    fl = [(t, h) for t, h in files if FILE.search(h)]
    print(f"file links: {len(fl)}")
    for t, h in fl[:8]:
        print("   ", t, "->", h[:200])
    print(f"data requests: {len(got)}")
    for m, s, u, pd, body in got[:14]:
        key = (m, u)
        print(f"  {m} {s} {u[:200]} {('| posted ' + pd[:120]) if pd else ''}")
        if key in seen_urls:
            continue
        seen_urls.add(key)
        try:
            j = json.loads(body.decode("utf-8", "replace"))
            print("     shape:", shape(j)[:600])
            sample = j[0] if isinstance(j, list) and j else (j.get("content", [None])[0] if isinstance(j, dict) and isinstance(j.get("content"), list) and j["content"] else None)
            if sample:
                print("     sample:", json.dumps(sample, ensure_ascii=False)[:500])
        except Exception as e:
            print("     (not readable json)", str(e)[:80])
    links = page.eval_on_selector_all("a[href]", "els => els.map(e => [e.innerText.trim().slice(0,50), e.href])")
    page.close()
    return links


def main():
    seen = set()
    with sync_playwright() as p:
        b = p.chromium.launch()
        # nepalstock.com has had certificate trouble before; this is a read-only look, so do not stop on it
        ctx = b.new_context(user_agent="Arthotix/1.0 (NEPSE reports probe)", viewport={"width": 1400, "height": 1000}, ignore_https_errors=True)
        menu = visit(ctx, "/", seen)
        print("\n== menu links that look related ==")
        pages, shown = [], set()
        for t, h in menu:
            if h.startswith(BASE) and h not in shown and (WANT.search(t) or WANT.search(h)):
                shown.add(h)
                print(f"  {t!r:50} {h}")
                pages.append(h)
        todo = [BASE + t for t in TRY[1:]] + [h for h in pages if h.rstrip("/") not in {BASE + t.rstrip("/") for t in TRY}]
        done = set()
        for u in todo[:14]:
            if u in done:
                continue
            done.add(u)
            visit(ctx, u, seen)
        b.close()


if __name__ == "__main__":
    sys.exit(main())
