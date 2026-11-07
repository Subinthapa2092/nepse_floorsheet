"""
Turns new company announcements (dividend / bonus, right share, IPO) into short News drafts, English and Nepali.
Every sentence comes from the announcement text we already saved; nothing is predicted or guessed.

    python announcement_stories.py --dry-run     # print what would be written, save nothing
    python announcement_stories.py               # save new drafts (or published, see below)
    python announcement_stories.py --hours 72    # look further back (default 36)
    python announcement_stories.py --max 8       # at most this many stories per run (default 6)

Stories are saved as DRAFTS. Open /admin, read, press Publish. Set the GitHub variable ANNOUNCE_AUTOPUBLISH to true
only after you trust them. Each announcement gets one story, ever (slug ann-<kind>-<id>), so reruns never duplicate.
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from daily_summary import ne_digits, dividend_text  # noqa: E402

SITE = os.environ.get("SITE_URL", "https://arthotix.com").rstrip("/")
WANT = ("dividend", "right", "ipo")


def clean(text, limit=700):
    t = re.sub(r"<[^>]+>", " ", str(text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MON_NE = ["जनवरी", "फेब्रुअरी", "मार्च", "अप्रिल", "मे", "जुन", "जुलाई", "अगस्ट", "सेप्टेम्बर", "अक्टोबर", "नोभेम्बर", "डिसेम्बर"]


def field_date(text, label, lang):
    """'Book Close Date: 11/24/2026' (month/day/year) -> '24 Nov 2026', or None."""
    m = re.search(label + r"\s*:?\s*(\d{1,2})/(\d{1,2})/(\d{4})", text or "", flags=re.I)
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), m.group(3)
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return ne_digits(f"{d} ") + MON_NE[mo - 1] + ne_digits(f" {y}") if lang == "ne" else f"{d} {MON[mo - 1]} {y}"


def pct(s, lang):
    s = f"{float(s):g}"
    return ne_digits(s) if lang == "ne" else s


def rs(v, lang):
    s = f"{v:,.2f}".rstrip("0").rstrip(".")
    return f"रु {ne_digits(s)}" if lang == "ne" else f"Rs {s}"


def build(a, price, lang):
    """(title, summary, body) for one announcement row."""
    L = lambda en, ne: ne if lang == "ne" else en
    sym, cat = a["symbol"], a["category"]
    text = clean(a.get("body"))
    link = f"/announcements?symbol={sym}"
    note = ["", "::: note", L("Written automatically from the NEPSE announcement. Check the original notice before you act.",
                              "नेप्सेको सूचनाबाट स्वचालित रूपमा तयार गरिएको। कदम चाल्नुअघि मूल सूचना हेर्नुहोस्।"), ":::"]
    if cat == "dividend":
        got = dict(dividend_text(a.get("body")))
        cash, bonus = got.get("Cash"), got.get("Bonus")
        parts_en, parts_ne = [], []
        if cash:
            parts_en.append(f"{pct(cash, 'en')}% cash dividend")
            parts_ne.append(f"{pct(cash, 'ne')}% नगद लाभांश")
        if bonus:
            parts_en.append(f"{pct(bonus, 'en')}% bonus shares")
            parts_ne.append(f"{pct(bonus, 'ne')}% बोनस शेयर")
        title = L(f"{sym} announces " + " and ".join(parts_en), f"{sym} ले " + " र ".join(parts_ne) + " घोषणा गर्‍यो")
        summary = L(f"{sym} has announced " + " and ".join(parts_en) + ". Here is what that means for 100 shares.",
                    f"{sym} ले " + " र ".join(parts_ne) + " घोषणा गरेको छ। १०० कित्ता शेयरमा यसको अर्थ यस्तो हुन्छ।")
        body = [L(f"**{sym}** has announced " + " and ".join(parts_en) + ".", f"**{sym}** ले " + " र ".join(parts_ne) + " घोषणा गरेको छ।"), ""]
        body += ["::: stats"]
        if cash:
            body.append(L(f"Cash dividend | {pct(cash, 'en')}%", f"नगद लाभांश | {pct(cash, 'ne')}%"))
        if bonus:
            body.append(L(f"Bonus shares | {pct(bonus, 'en')}%", f"बोनस शेयर | {pct(bonus, 'ne')}%"))
        if price:
            body.append(L(f"Last traded price | {rs(price, 'en')}", f"अन्तिम कारोबार मूल्य | {rs(price, 'ne')}"))
        book, agm = field_date(text, r"book clos\w* date", lang), field_date(text, r"agm date", lang)
        fy = re.search(r"fiscal year\s*:?\s*(\d{4}-\d{2,4})", text, flags=re.I)
        if fy:
            body.append(L(f"Fiscal year | {fy.group(1)}", f"आर्थिक वर्ष | {ne_digits(fy.group(1))}"))
        if book:
            body.append(L(f"Book close date | {book}", f"किताब बन्द मिति | {book}"))
        if agm:
            body.append(L(f"AGM date | {agm}", f"साधारण सभा मिति | {agm}"))
        body += [":::", ""]
        if book:
            body += [L(f"Shareholders on the register when the books close on **{book}** are the ones who get it.",
                       f"**{book}** मा किताब बन्द हुँदा नाम दर्ता भएका शेयरधनीले यो पाउँछन्।"), ""]
        body += [L("## What it means for 100 shares", "## १०० कित्ता शेयरमा असर"), ""]
        if cash:
            body.append(L(f"- Cash: {rs(float(cash) * 100, 'en')} per 100 shares before tax (percentages apply to the Rs 100 face value).",
                          f"- नगद: १०० कित्तामा कर अघि {rs(float(cash) * 100, 'ne')} (प्रतिशत रु १०० अंकित मूल्यमा लागू हुन्छ)।"))
        if bonus:
            body.append(L(f"- Bonus: {float(bonus):g} extra shares per 100 held.", f"- बोनस: १०० कित्तामा {pct(bonus, 'ne')} थप कित्ता।"))
        if cash and price:
            body.append(L(f"- Cash dividend against the last price: {float(cash) / price * 100:.2f}% (cash per 100 shares ÷ cost of 100 shares).",
                          f"- अन्तिम मूल्यको तुलनामा नगद लाभांश: {ne_digits(f'{float(cash) / price * 100:.2f}')}%।"))
        body += ["", L("## From the announcement", "## सूचनामा भनिएको"), "", "> " + (text or a.get("title") or ""), ""]
        body += [L(f"See every [{sym} announcement]({link}).",
                   f"[{sym} का सबै सूचना]({link}) हेर्नुहोस्।")]
        return title, summary, "\n".join(body + note)

    kind_en, kind_ne = {"right": ("right share", "हकप्रद शेयर"), "ipo": ("IPO and listing", "आईपीओ तथा सूचीकरण")}[cat]
    an = "an" if kind_en[0] in "aeiou" else "a"
    title = L(f"{sym}: new {kind_en} notice", f"{sym}: {kind_ne} सम्बन्धी नयाँ सूचना")
    summary = L(f"NEPSE has published {an} {kind_en} notice for {sym}. The notice is quoted below.", f"{sym} को {kind_ne} सम्बन्धी सूचना नेप्सेले प्रकाशित गरेको छ। सूचना तल उद्धृत छ।")
    body = [L(f"A new {kind_en} notice was published for **{sym}**.", f"**{sym}** को {kind_ne} सम्बन्धी नयाँ सूचना प्रकाशित भएको छ।"), "",
            L("## From the announcement", "## सूचनामा भनिएको"), "", "> " + (clean(a.get("title"), 300) if not text else clean(a.get("title"), 300) + ". " + text), ""]
    if lang == "ne":
        body += ["(नेप्सेको मूल सूचना अंग्रेजीमा प्रकाशित छ।)", ""]
    body += [L(f"See every [{sym} announcement]({link}).", f"[{sym} का सबै सूचना]({link}) हेर्नुहोस्।")]
    return title, summary, "\n".join(body + note)


def candidates(sb, hours):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = sb.table("announcements").select("kind,nepse_id,symbol,title,body,category,added_at").gte("added_at", since).order("added_at", desc=True).limit(300).execute().data or []
    out = []
    for a in rows:
        if a.get("category") not in WANT or not a.get("symbol"):
            continue
        if a["category"] == "dividend" and not dividend_text(a.get("body")):
            continue  # no figures, nothing honest to say
        out.append(a)
    return out


def price_of(sb, sym):
    try:
        r = sb.table("live_prices").select("ltp").eq("symbol", sym).limit(1).execute().data or []
        v = float(r[0]["ltp"]) if r and r[0].get("ltp") else 0.0
        return v or None
    except Exception:
        return None


def run(sb, hours=36, cap=6, publish=False, dry=False):
    msgs, made = [], 0
    for a in candidates(sb, hours):
        if made >= cap:
            break
        slug = f"ann-{a['kind']}-{a['nepse_id']}"
        if (sb.table("articles").select("id").eq("slug", slug).limit(1).execute().data or []):
            continue
        price = price_of(sb, a["symbol"]) if a["category"] == "dividend" else None
        t, s, b = build(a, price, "en")
        tn, sn, bn = build(a, price, "ne")
        if dry:
            print(f"\n===== {slug} =====\n{t}\n{s}\n\n{b}\n\n--- ne ---\n{tn}\n{sn}\n\n{bn}")
            made += 1
            continue
        now = datetime.now(timezone.utc).isoformat()
        sb.table("articles").insert({"slug": slug, "title": t, "summary": s[:400], "body": b, "title_ne": tn, "summary_ne": sn[:400], "body_ne": bn,
                                     "ne_status": "reviewed", "category": "news", "author": "Arthotix", "cover_url": None,
                                     "status": "published" if publish else "draft", "published_at": now if publish else None, "updated_at": now}).execute()
        made += 1
        msgs.append(f"{slug}: saved as {'PUBLISHED' if publish else 'a draft'}")
    msgs.append(f"{made} new {'story' if made == 1 else 'stories'}")
    return msgs


def main():
    args = sys.argv[1:]
    val = lambda k, d: type(d)(args[args.index(k) + 1]) if k in args else d
    publish = "--publish" in args or os.environ.get("ANNOUNCE_AUTOPUBLISH", "").lower() == "true"
    from supabase import create_client

    missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not os.environ.get(k)]
    if missing:
        sys.exit("Missing " + ", ".join(missing) + ". Put them in the .env file next to this script.")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    for m in run(sb, val("--hours", 36), val("--max", 6), publish, "--dry-run" in args):
        print(m)


if __name__ == "__main__":
    main()
