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

    ms = sb.table("market_summary").select("business_date,total_turnover,total_traded_shares,total_transactions,total_scrips_traded").lte("business_date", d).order("business_date", desc=True).limit(2).execute().data or []
    if ms and str(ms[0]["business_date"]) == d:
        facts["turnover"] = f(ms[0].get("total_turnover"))
        facts["volume"] = f(ms[0].get("total_traded_shares"))
        facts["trans"] = f(ms[0].get("total_transactions"))
        facts["scrips"] = f(ms[0].get("total_scrips_traded"))
        facts["prev_turnover"] = f(ms[1].get("total_turnover")) if len(ms) > 1 else 0.0
    if not facts.get("turnover"):
        return None, "turnover for that day is not saved yet"

    lp = sb.table("live_prices").select("symbol,ltp,percent_change,volume,business_date").limit(1000).execute().data or []
    today = [r for r in lp if str(r.get("business_date")) == d and f(r.get("volume")) > 0]
    if today:
        up = sorted([r for r in today if f(r["percent_change"]) > 0], key=lambda r: -f(r["percent_change"]))
        dn = sorted([r for r in today if f(r["percent_change"]) < 0], key=lambda r: f(r["percent_change"]))
        facts["advanced"], facts["declined"] = len(up), len(dn)
        facts["unchanged"] = len(today) - len(up) - len(dn)
        facts["gainers"] = [(r["symbol"], f(r["ltp"]), f(r["percent_change"])) for r in up[:3]]
        facts["losers"] = [(r["symbol"], f(r["ltp"]), f(r["percent_change"])) for r in dn[:3]]

    try:
        sec = sb.table("nepse_sub_indices").select("index_name,percent_change,business_date").eq("business_date", d).execute().data or []
        sec = [(clean_sector(r["index_name"]), f(r["percent_change"])) for r in sec if r.get("index_name") and str(r["index_name"]).strip().lower() not in NOT_SECTORS]
        sec.sort(key=lambda x: -x[1])
        if len(sec) >= 2:
            facts["best_sector"], facts["worst_sector"] = sec[0], sec[-1]
    except Exception:
        pass

    try:
        tot = sb.rpc("symbol_day_totals", {"p_date": d}).execute().data or []
        tot = sorted(tot, key=lambda r: -f(r.get("turnover")))[:3]
        if tot and f(tot[0].get("turnover")) > 0:
            facts["busiest"] = [(r["symbol"], f(r["turnover"])) for r in tot]
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


def build(fa, lang):
    """(title, summary, body) in 'en' or 'ne'."""
    ne = lang == "ne"
    n2 = lambda v: num(abs(v), lang)
    up = fa["pts"] >= 0
    flat = abs(fa["pts"]) < 0.005
    when = long_date(fa["date"], lang)
    turn = money(fa["turnover"], lang)
    cmp_en = cmp_ne = ""
    if fa.get("prev_turnover"):
        ch = (fa["turnover"] - fa["prev_turnover"]) / fa["prev_turnover"] * 100
        if abs(ch) >= 0.5:
            cmp_en = f", {'up' if ch > 0 else 'down'} {abs(ch):.1f}% from the previous session"
            cmp_ne = f", अघिल्लो कारोबार दिनभन्दा {ne_digits(f'{abs(ch):.1f}')}% {'बढी' if ch > 0 else 'कम'}"

    if ne:
        verb = "अपरिवर्तित" if flat else ("बढेर" if up else "घटेर")
        title = f"नेप्से सूचकाङ्क {num(fa['value'], lang)} मा बन्द; कारोबार {turn}" if flat else f"नेप्से {n2(fa['pts'])} अङ्कले {'बढेर' if up else 'घटेर'} {num(fa['value'], lang)} मा बन्द; कारोबार {turn}"
        parts = [f"{when} मा नेप्से सूचकाङ्क {num(fa['value'], lang)} मा बन्द भयो।" if flat else f"{when} मा नेप्से सूचकाङ्क {n2(fa['pts'])} अङ्कले ({n2(fa['pct'])}%) {'बढेर' if up else 'घटेर'} {num(fa['value'], lang)} मा बन्द भयो।"]
        parts.append(f"कारोबार रकम {turn} रह्यो{cmp_ne}।")
        summary = parts[0] + (f" {whole(fa['advanced'], lang)} कम्पनीको भाउ बढ्यो र {whole(fa['declined'], lang)} कम्पनीको घट्यो।" if "advanced" in fa else "")
    else:
        title = f"NEPSE ends flat at {num(fa['value'], lang)}; turnover {turn}" if flat else f"NEPSE {'rises' if up else 'falls'} {n2(fa['pts'])} points to {num(fa['value'], lang)}; turnover {turn}"
        parts = [f"The NEPSE index closed flat at {num(fa['value'], lang)} on {when}." if flat else f"The NEPSE index {'rose' if up else 'fell'} {n2(fa['pts'])} points, or {n2(fa['pct'])}%, to close at {num(fa['value'], lang)} on {when}."]
        parts.append(f"Turnover was {turn}{cmp_en}.")
        summary = parts[0] + (f" {whole(fa['advanced'], lang)} {'stock' if fa['advanced'] == 1 else 'stocks'} rose and {whole(fa['declined'], lang)} fell." if "advanced" in fa else "")

    L = lambda en, nep: nep if ne else en
    body = [parts[1], ""]
    body.extend([L("## Market at a glance", "## बजार एक नजरमा"), ""])
    body.append(f"- {L('NEPSE index', 'नेप्से सूचकाङ्क')}: {num(fa['value'], lang)} ({'+' if up else '-'}{n2(fa['pts'])}, {'+' if up else '-'}{n2(fa['pct'])}%)")
    body.append(f"- {L('Turnover', 'कारोबार रकम')}: {turn}")
    if fa.get("volume"):
        body.append(f"- {L('Shares traded', 'कारोबार भएका शेयर कित्ता')}: {shares(fa['volume'], lang)}")
    if fa.get("trans"):
        body.append(f"- {L('Transactions', 'कारोबार संख्या')}: {whole(fa['trans'], lang)}")
    if fa.get("scrips"):
        body.append(f"- {L('Companies traded', 'कारोबार भएका कम्पनी')}: {whole(fa['scrips'], lang)}")
    if "advanced" in fa:
        body.append(f"- {L('Advanced / declined / unchanged', 'बढे / घटे / अपरिवर्तित')}: {whole(fa['advanced'], lang)} / {whole(fa['declined'], lang)} / {whole(fa['unchanged'], lang)}")

    def lst(head_en, head_ne, items):
        if items:
            body.extend(["", L(head_en, head_ne), ""] + [f"- {s}: {L('Rs', 'रु')} {num(p, lang)} ({'+' if c > 0 else '-'}{n2(c)}%)" for s, p, c in items])

    lst("## Top gainers", "## सबैभन्दा धेरै बढ्ने", fa.get("gainers"))
    lst("## Top losers", "## सबैभन्दा धेरै घट्ने", fa.get("losers"))
    if fa.get("busiest"):
        body.extend(["", L("## Most traded by turnover", "## सबैभन्दा धेरै कारोबार हुने"), ""] + [f"- {s}: {money(t, lang)}" for s, t in fa["busiest"]])
    if fa.get("best_sector"):
        (bn, bp), (wn, wp) = fa["best_sector"], fa["worst_sector"]
        sg = lambda p: ("+" if p > 0 else "-" if p < 0 else "") + n2(p) + "%"
        body.extend(["", L("## Sectors", "## क्षेत्रगत अवस्था"), "", f"- {L('Strongest', 'सबैभन्दा बलियो')}: {sector_name(bn, lang)} ({sg(bp)})", f"- {L('Weakest', 'सबैभन्दा कमजोर')}: {sector_name(wn, lang)} ({sg(wp)})"])
    body.extend(["", L("This summary is written automatically from NEPSE data. It is for information and is not investment advice.", "यो सारांश नेप्सेको तथ्याङ्कबाट स्वचालित रूपमा तयार गरिएको हो। यो जानकारीका लागि हो, लगानी सल्लाह होइन।")])
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
