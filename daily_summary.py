"""
Writes the daily market summary story for the News section, from our own tables. Nothing is predicted: every
sentence is built from numbers we already store.

    python daily_summary.py --dry-run          # print the story, save nothing
    python daily_summary.py                    # save it as a DRAFT (or published, see below)
    python daily_summary.py --date 2026-11-06  # a specific trading day
    python daily_summary.py --force            # rewrite the text of a story that already exists

New stories are saved as drafts, so you can read the first few in /admin and press Publish. When you are happy,
set the GitHub variable SUMMARY_AUTOPUBLISH to true (Settings > Secrets and variables > Actions > Variables) and
they go live by themselves. Holidays are skipped. A day that already has a story is left alone.
"""
import os
import sys
from datetime import date, datetime, timezone

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SITE = os.environ.get("SITE_URL", "https://arthotix.com").rstrip("/")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
BS_NE = ["बैशाख", "जेठ", "असार", "श्रावण", "भदौ", "आश्विन", "कार्तिक", "मंसिर", "पौष", "माघ", "फाल्गुन", "चैत्र"]
NOT_SECTORS = {"nepse index", "sensitive index", "float index", "sensitive float index"}


# ---------------------------------------------------------------- number words
def ne_digits(s):
    return str(s).translate(str.maketrans("0123456789", "०१२३४५६७८९"))


def money(v, lang):
    """Rs 7.43 billion  /  रु ७.४३ अर्ब  (crore for smaller amounts)."""
    if v >= 1e9:
        n, en, ne = v / 1e9, "billion", "अर्ब"
    elif v >= 1e7:
        n, en, ne = v / 1e7, "crore", "करोड"
    else:
        n, en, ne = v, "", ""
    txt = f"{n:,.2f}" if en else f"{n:,.0f}"
    return f"रु {ne_digits(txt)}{(' ' + ne) if ne else ''}" if lang == "ne" else f"Rs {txt}{(' ' + en) if en else ''}"


def shares(v, lang):
    if v >= 1e7:
        n, en, ne = v / 1e7, "crore", "करोड"
    elif v >= 1e5:
        n, en, ne = v / 1e5, "lakh", "लाख"
    else:
        return ne_digits(f"{v:,.0f}") if lang == "ne" else f"{v:,.0f}"
    txt = f"{n:,.2f}"
    return f"{ne_digits(txt)} {ne}" if lang == "ne" else f"{txt} {en}"


def num(v, lang, dec=2):
    s = f"{v:,.{dec}f}"
    return ne_digits(s) if lang == "ne" else s


def whole(v, lang):
    return num(v, lang, 0)


# ---------------------------------------------------------------- Bikram Sambat (same table as the website)
_MONTHS = {
    2082: [31, 31, 32, 31, 31, 31, 30, 29, 30, 29, 30, 30],
    2083: [31, 31, 32, 31, 31, 31, 30, 29, 30, 29, 30, 30],
    2084: [31, 31, 32, 31, 31, 30, 30, 30, 29, 30, 30, 30],
    2085: [31, 32, 31, 32, 30, 31, 30, 30, 29, 30, 30, 30],
}


def bs_of(d):
    """Anchor: 2026-11-06 is 2083/07/20 (checked against NEPSE's own dates)."""
    days = (d - date(2026, 11, 6)).days
    y, m, dd = 2083, 7, 20
    while days > 0:
        if y not in _MONTHS:
            return None
        dd += 1
        if dd > _MONTHS[y][m - 1]:
            dd, m = 1, m + 1
            if m > 12:
                m, y = 1, y + 1
        days -= 1
    while days < 0:
        dd -= 1
        if dd < 1:
            m -= 1
            if m < 1:
                m, y = 12, y - 1
            if y not in _MONTHS:
                return None
            dd = _MONTHS[y][m - 1]
        days += 1
    return y, m, dd


# ---------------------------------------------------------------- reading the data
def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


SECTOR_NE = {
    "banking": "बैंकिङ", "commercial banks": "वाणिज्य बैंक", "development bank": "विकास बैंक", "development banks": "विकास बैंक",
    "finance": "वित्त कम्पनी", "hydropower": "जलविद्युत्", "life insurance": "जीवन बीमा", "non life insurance": "निर्जीवन बीमा",
    "microfinance": "लघुवित्त", "mutual fund": "म्युचुअल फण्ड", "investment": "लगानी", "hotels and tourism": "होटल तथा पर्यटन",
    "hotel and tourism": "होटल तथा पर्यटन", "manufacturing and processing": "उत्पादन तथा प्रशोधन", "trading": "व्यापार",
    "others": "अन्य", "other": "अन्य", "corporate debenture": "ऋणपत्र",
}


def sector_name(name, lang):
    if lang != "ne":
        return name
    key = name.lower().replace("&", "and").replace("-", " ").strip()
    return SECTOR_NE.get(key, name)


def clean_sector(name):
    import re

    return re.sub(r"\s*(sub[\s-]?)?index\s*$", "", str(name), flags=re.I).strip() or str(name)


def next_day(d):
    from datetime import timedelta

    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def dividend_text(body):
    """'Cash 3.78%, Bonus 3.7%' from the announcement text, or ''."""
    import re

    out = []
    for label, rx in (("Cash", r"cash dividend\s*:?\s*([\d.]+)\s*%"), ("Bonus", r"bonus (?:shares?|dividend)\s*:?\s*([\d.]+)\s*%"), ("Right", r"right (?:shares?)?\s*:?\s*([\d.]+)\s*%")):
        m = re.search(rx, body or "", flags=re.I)
        if m:
            out.append((label, m.group(1)))
    return out


ANN_ORDER = ["dividend", "right", "ipo", "agm", "sale", "promoter", "report"]
ANN_LABEL = {
    "dividend": ("Dividend & bonus", "लाभांश र बोनस"), "right": ("Right share", "हकप्रद शेयर"), "ipo": ("IPO & listing", "आईपीओ तथा सूचीकरण"),
    "agm": ("AGM", "साधारण सभा"), "sale": ("Share sale", "शेयर बिक्री"), "promoter": ("Promoter conversion", "संस्थापक शेयर रूपान्तरण"), "report": ("Report", "प्रतिवेदन"),
}


def gather(sb, want=None):
    """Everything the story needs for one trading day, or (None, reason)."""
    rows = sb.table("nepse_index").select("business_date,index_value,point_change,percent_change").order("business_date", desc=True).limit(12).execute().data or []
    rows = [r for r in rows if r.get("index_value") is not None]
    if not rows:
        return None, "no index data"
    pos = 0
    if want:
        pos = next((i for i, r in enumerate(rows) if str(r["business_date"]) == want), None)
        if pos is None:
            return None, f"no index row for {want}"
    cur = rows[pos]
    prev = rows[pos + 1] if pos + 1 < len(rows) else None
    if not prev:
        return None, "no earlier close to compare with"
    same = lambda a, b: f(a["index_value"]) == f(b["index_value"]) and f(a.get("point_change")) == f(b.get("point_change")) and f(a.get("percent_change")) == f(b.get("percent_change"))
    if same(cur, prev):
        return None, "market was closed (index row repeats the day before)"
    d = str(cur["business_date"])
    value, pv = f(cur["index_value"]), f(prev["index_value"])
    facts = {"date": d, "value": value, "pts": value - pv, "pct": (value - pv) / pv * 100 if pv else 0.0, "movers": None}

    # the last five sessions, for context
    week = [f(r["index_value"]) for r in rows[pos:pos + 5]]
    if len(rows) >= pos + 5:
        facts["week_hi"], facts["week_lo"] = max(week), min(week)
        if len(rows) > pos + 5:  # change over the five sessions, against the close just before them
            start = f(rows[pos + 5]["index_value"])
            facts["week_pct"] = (value - start) / start * 100 if start else 0.0

    ms = sb.table("market_summary").select("business_date,total_turnover,total_traded_shares,total_transactions,total_scrips_traded").lte("business_date", d).order("business_date", desc=True).limit(6).execute().data or []
    if ms and str(ms[0]["business_date"]) == d:
        facts["turnover"] = f(ms[0].get("total_turnover"))
        facts["volume"] = f(ms[0].get("total_traded_shares"))
        facts["trans"] = f(ms[0].get("total_transactions"))
        facts["scrips"] = f(ms[0].get("total_scrips_traded"))
        facts["prev_turnover"] = f(ms[1].get("total_turnover")) if len(ms) > 1 else 0.0
        earlier = [f(r.get("total_turnover")) for r in ms[1:6] if f(r.get("total_turnover")) > 0]
        if len(earlier) >= 3:
            facts["avg_turnover"] = sum(earlier) / len(earlier)
    if not facts.get("turnover"):
        return None, "turnover for that day is not saved yet"

    lp = sb.table("live_prices").select("symbol,ltp,percent_change,volume,business_date").limit(1000).execute().data or []
    today = [r for r in lp if str(r.get("business_date")) == d and f(r.get("volume")) > 0]
    if today:
        up = sorted([r for r in today if f(r["percent_change"]) > 0], key=lambda r: -f(r["percent_change"]))
        dn = sorted([r for r in today if f(r["percent_change"]) < 0], key=lambda r: f(r["percent_change"]))
        facts["advanced"], facts["declined"] = len(up), len(dn)
        facts["unchanged"] = len(today) - len(up) - len(dn)
        facts["gainers"] = [(r["symbol"], f(r["ltp"]), f(r["percent_change"])) for r in up[:5]]
        facts["losers"] = [(r["symbol"], f(r["ltp"]), f(r["percent_change"])) for r in dn[:5]]

    try:
        sec = sb.table("nepse_sub_indices").select("index_name,percent_change,business_date").eq("business_date", d).execute().data or []
        sec = [(clean_sector(r["index_name"]), f(r["percent_change"])) for r in sec if r.get("index_name") and str(r["index_name"]).strip().lower() not in NOT_SECTORS]
        sec.sort(key=lambda x: -x[1])
        if len(sec) >= 2:
            facts["sectors"] = sec
    except Exception:
        pass

    try:
        tot = sb.rpc("symbol_day_totals", {"p_date": d}).execute().data or []
        tot = sorted(tot, key=lambda r: -f(r.get("turnover")))[:5]
        if tot and f(tot[0].get("turnover")) > 0:
            facts["busiest"] = [(r["symbol"], f(r["turnover"])) for r in tot]
    except Exception:
        pass

    try:
        st = sb.rpc("broker_stats_by_broker", {"p_from": d, "p_to": d, "p_symbol": None}).execute().data or []
        names = {str(b["broker_no"]).strip(): str(b["broker_name"]).strip() for b in (sb.table("brokers").select("broker_no,broker_name").limit(1000).execute().data or [])}
        net = sorted([(str(r.get("broker")), f(r.get("buy_amt")) - f(r.get("sell_amt"))) for r in st], key=lambda x: -x[1])
        buyers = [(n, a) for n, a in net if a > 0][:3]
        sellers = [(n, a) for n, a in reversed(net) if a < 0][:3]
        if buyers and sellers:
            facts["brokers"] = {"buyers": [(n, names.get(n, ""), a) for n, a in buyers], "sellers": [(n, names.get(n, ""), -a) for n, a in sellers]}
    except Exception:
        pass

    try:
        start = f"{d}T00:00:00+05:45"
        end = f"{next_day(d)}T00:00:00+05:45"
        an = sb.table("announcements").select("symbol,title,body,category,added_at").gte("added_at", start).lt("added_at", end).limit(300).execute().data or []
        an = [a for a in an if a.get("category") in ANN_ORDER and a.get("symbol")]
        an.sort(key=lambda a: (ANN_ORDER.index(a["category"]), a["symbol"]))
        seen, keep = set(), []
        for a in an:
            k = (a["symbol"], a["category"])
            if k not in seen:
                seen.add(k)
                keep.append((a["symbol"], a["category"], dividend_text(a.get("body")) if a["category"] == "dividend" else []))
        if keep:
            facts["disclosures"] = keep[:10]
            facts["disclosure_count"] = len(keep)
    except Exception:
        pass
    return facts, None


# ---------------------------------------------------------------- writing the story
def long_date(d, lang):
    y, m, dd = (int(x) for x in d.split("-"))
    if lang == "ne":
        bs = bs_of(date(y, m, dd))
        if bs:
            return ne_digits(f"{bs[2]}") + f" {BS_NE[bs[1] - 1]} " + ne_digits(bs[0])
    return f"{dd} {MONTHS[m - 1]} {y}"


def table(headers, rows, right_from=1):
    """A markdown table the site shows as a proper table."""
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(("---:" if i >= right_from else "---") for i in range(len(headers))) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def build(fa, lang):
    """(title, summary, body) in 'en' or 'ne'."""
    ne = lang == "ne"
    L = lambda en, nep: nep if ne else en
    n2 = lambda v: num(abs(v), lang)
    sg = lambda p: ("+" if p > 0 else "-" if p < 0 else "") + n2(p) + "%"
    up = fa["pts"] >= 0
    flat = abs(fa["pts"]) < 0.005
    when = long_date(fa["date"], lang)
    turn = money(fa["turnover"], lang)
    traded = fa.get("advanced", 0) + fa.get("declined", 0) + fa.get("unchanged", 0)

    pc = None
    if fa.get("prev_turnover"):
        ch = (fa["turnover"] - fa["prev_turnover"]) / fa["prev_turnover"] * 100
        if abs(ch) >= 0.5:
            pc = ch
    avg = None
    if fa.get("avg_turnover"):
        ch = (fa["turnover"] - fa["avg_turnover"]) / fa["avg_turnover"] * 100
        if abs(ch) >= 0.5:
            avg = ch

    # ---- title and card summary
    if ne:
        title = f"नेप्से सूचकाङ्क {num(fa['value'], lang)} मा बन्द; कारोबार {turn}" if flat else f"नेप्से {n2(fa['pts'])} अङ्कले {'बढेर' if up else 'घटेर'} {num(fa['value'], lang)} मा बन्द; कारोबार {turn}"
        first = f"{when} मा नेप्से सूचकाङ्क {num(fa['value'], lang)} मा बन्द भयो।" if flat else f"{when} मा नेप्से सूचकाङ्क {n2(fa['pts'])} अङ्कले ({n2(fa['pct'])}%) {'बढेर' if up else 'घटेर'} {num(fa['value'], lang)} मा बन्द भयो।"
        summary = first + f" कारोबार रकम {turn} रह्यो।"
    else:
        title = f"NEPSE ends flat at {num(fa['value'], lang)}; turnover {turn}" if flat else f"NEPSE {'rises' if up else 'falls'} {n2(fa['pts'])} points to {num(fa['value'], lang)}; turnover {turn}"
        first = f"The NEPSE index closed flat at {num(fa['value'], lang)} on {when}." if flat else f"The NEPSE index {'rose' if up else 'fell'} {n2(fa['pts'])} points, or {n2(fa['pct'])}%, to close at {num(fa['value'], lang)} on {when}."
        summary = first + f" Turnover was {turn}."

    # ---- opening paragraphs
    p1, p2 = [], []
    if ne:
        if "advanced" in fa:
            p1.append(f"कारोबार भएका {whole(traded, lang)} कम्पनीमध्ये {whole(fa['advanced'], lang)} कम्पनीको भाउ बढ्यो, {whole(fa['declined'], lang)} कम्पनीको घट्यो र {whole(fa['unchanged'], lang)} कम्पनी अपरिवर्तित रहे।")
        bits = []
        if pc is not None:
            bits.append(f"अघिल्लो कारोबार दिनभन्दा {ne_digits(f'{abs(pc):.1f}')}% {'बढी' if pc > 0 else 'कम'}")
        if avg is not None:
            bits.append(f"पछिल्ला पाँच कारोबार दिनको औसतभन्दा {ne_digits(f'{abs(avg):.1f}')}% {'बढी' if avg > 0 else 'कम'}")
        if bits:
            p1.append("कारोबार रकम " + " र ".join(bits) + " रह्यो।")
        if fa.get("sectors"):
            (bn, bp), (wn, wp) = fa["sectors"][0], fa["sectors"][-1]
            p2.append(f"क्षेत्रगत रूपमा {sector_name(bn, lang)} क्षेत्र ({sg(bp)}) सबैभन्दा बलियो र {sector_name(wn, lang)} क्षेत्र ({sg(wp)}) सबैभन्दा कमजोर रह्यो।")
        if "week_pct" in fa:
            p2.append(f"पछिल्ला पाँच कारोबार दिनमा सूचकाङ्क {n2(fa['week_pct'])}% {'बढेको' if fa['week_pct'] >= 0 else 'घटेको'} छ।")
    else:
        if "advanced" in fa:
            p1.append(f"Of the {whole(traded, lang)} stocks that traded, {whole(fa['advanced'], lang)} advanced, {whole(fa['declined'], lang)} declined and {whole(fa['unchanged'], lang)} {'was' if fa['unchanged'] == 1 else 'were'} unchanged.")
        bits = []
        if pc is not None:
            bits.append(f"{abs(pc):.1f}% {'above' if pc > 0 else 'below'} the previous session")
        if avg is not None:
            bits.append(f"{abs(avg):.1f}% {'above' if avg > 0 else 'below'} the five-session average")
        if bits:
            p1.append("Turnover was " + " and ".join(bits) + ".")
        if fa.get("sectors"):
            (bn, bp), (wn, wp) = fa["sectors"][0], fa["sectors"][-1]
            p2.append(f"{bn} ({sg(bp)}) was the strongest sector and {wn} ({sg(wp)}) the weakest.")
        if "week_pct" in fa:
            p2.append(f"The index is {'up' if fa['week_pct'] >= 0 else 'down'} {n2(fa['week_pct'])}% over the last five sessions.")
    body = []
    if p1:
        body += [" ".join(p1), ""]
    if p2:
        body += [" ".join(p2), ""]

    # ---- at a glance: a row of boxes (the site draws "::: stats" blocks)
    boxes = [(L("Turnover", "कारोबार रकम"), turn, "")]
    if fa.get("volume"):
        boxes.append((L("Shares traded", "कारोबार भएका शेयर कित्ता"), shares(fa["volume"], lang), ""))
    if fa.get("trans"):
        boxes.append((L("Transactions", "कारोबार संख्या"), whole(fa["trans"], lang), ""))
    if fa.get("scrips"):
        boxes.append((L("Companies traded", "कारोबार भएका कम्पनी"), whole(fa["scrips"], lang), ""))
    if "advanced" in fa:
        boxes.append((L("Advanced", "बढे"), whole(fa["advanced"], lang), "up"))
        boxes.append((L("Declined", "घटे"), whole(fa["declined"], lang), "down"))
    body += ["::: stats"] + [f"{lab} | {val}" + (f" | {tone}" if tone else "") for lab, val, tone in boxes] + [":::", ""]

    # ---- sectors
    if fa.get("sectors"):
        body += ["", L("## Sectors", "## क्षेत्रगत अवस्था"), ""]
        body += table([L("Sector", "क्षेत्र"), L("Change", "परिवर्तन")], [(sector_name(n, lang), sg(p)) for n, p in fa["sectors"]])

    # ---- movers
    def movers(head_en, head_ne, items):
        if items:
            return ["", L(head_en, head_ne), ""] + table([L("Stock", "कम्पनी"), L("Price (Rs)", "भाउ (रु)"), L("Change", "परिवर्तन")], [(s_, num(p, lang), sg(c)) for s_, p, c in items])
        return []

    body += movers("## Top gainers", "## सबैभन्दा धेरै बढ्ने", fa.get("gainers"))
    body += movers("## Top losers", "## सबैभन्दा धेरै घट्ने", fa.get("losers"))
    if fa.get("busiest"):
        body += ["", L("## Most traded by turnover", "## सबैभन्दा धेरै कारोबार भएका"), ""] + table([L("Stock", "कम्पनी"), L("Turnover", "कारोबार रकम")], [(s_, money(t_, lang)) for s_, t_ in fa["busiest"]])

    # ---- brokers
    if fa.get("brokers"):
        def bro(items):
            return [(f"{no} {nm}".strip() if not ne else f"{ne_digits(no)} {nm}".strip(), money(a, lang)) for no, nm, a in items]

        body += ["", L("## Broker activity", "## ब्रोकर गतिविधि"), ""]
        body += table([L("Top net buyers", "सबैभन्दा धेरै खरिद गर्ने ब्रोकर"), L("Net bought", "खुद खरिद")], bro(fa["brokers"]["buyers"]))
        body += [""] + table([L("Top net sellers", "सबैभन्दा धेरै बिक्री गर्ने ब्रोकर"), L("Net sold", "खुद बिक्री")], bro(fa["brokers"]["sellers"]))

    # ---- disclosures
    if fa.get("disclosures"):
        body += ["", L("## Disclosures today", "## आजका सूचना"), ""]
        for sym, cat, divs in fa["disclosures"]:
            label = ANN_LABEL[cat][1 if ne else 0]
            extra = ""
            if divs:
                names = {"Cash": ("Cash", "नगद"), "Bonus": ("Bonus", "बोनस"), "Right": ("Right", "हकप्रद")}
                extra = ": " + ", ".join(f"{names[k][1 if ne else 0]} {(ne_digits if ne else str)('%g' % float(v))}%" for k, v in divs)
            body.append(f"- [{sym}](/announcements?symbol={sym}) - {label}{extra}")
        more = fa.get("disclosure_count", 0) - len(fa["disclosures"])
        tail = L("See all announcements", "सबै सूचना हेर्नुहोस्")
        body += ["", f"[{tail}](/announcements)" + ((f" (आज {whole(more, lang)} थप)" if ne else f" ({whole(more, lang)} more today)") if more > 0 else "")]

    body += ["", "::: note", L("Written automatically from NEPSE data.", "यो सारांश नेप्सेको तथ्याङ्कबाट स्वचालित रूपमा तयार गरिएको हो।"), ":::"]
    return title, summary, "\n".join(body)


# ---------------------------------------------------------------- saving
def save(sb, fa, publish, force):
    slug = f"market-summary-{fa['date']}"
    have = sb.table("articles").select("id,status").eq("slug", slug).limit(1).execute().data or []
    if have and not force:
        return f"{slug}: already exists ({have[0]['status']}), left alone"
    t, s, b = build(fa, "en")
    tn, sn, bn = build(fa, "ne")
    row = {"title": t, "summary": s[:400], "body": b, "title_ne": tn, "summary_ne": sn[:400], "body_ne": bn, "ne_status": "reviewed"}
    now = datetime.now(timezone.utc).isoformat()
    if have:
        sb.table("articles").update({**row, "updated_at": now}).eq("id", have[0]["id"]).execute()
        return f"{slug}: text rewritten ({have[0]['status']})"
    row.update({"slug": slug, "category": "market", "author": "Arthotix", "cover_url": f"{SITE}/news/cover/{fa['date']}",
                "status": "published" if publish else "draft", "published_at": now if publish else None, "updated_at": now})
    sb.table("articles").insert(row).execute()
    return f"{slug}: saved as {'PUBLISHED' if publish else 'a draft'}"


def main():
    args = sys.argv[1:]
    want = args[args.index("--date") + 1] if "--date" in args else None
    publish = "--publish" in args or os.environ.get("SUMMARY_AUTOPUBLISH", "").lower() == "true"
    from supabase import create_client

    missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not os.environ.get(k)]
    if missing:
        sys.exit("Missing " + ", ".join(missing) + ". Put them in the .env file next to this script.")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    facts, why = gather(sb, want)
    if not facts:
        print("No story today:", why)
        return
    if "--dry-run" in args:
        for lang in ("en", "ne"):
            t, s, b = build(facts, lang)
            print(f"\n===== {lang} =====\n{t}\n\n{s}\n\n{b}")
        return
    print(save(sb, facts, publish, "--force" in args))


if __name__ == "__main__":
    main()
