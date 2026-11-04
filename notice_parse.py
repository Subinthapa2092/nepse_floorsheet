"""
Reads the text OCR got from a company's lock-in notice and works out which shares, and the first day they can trade.
Pure functions, no network. A date is only trusted when the Nepali (BS) date, converted with a calendar library,
equals the English date printed next to it in the same notice. Anything else goes to "check by hand".
"""
import re
from datetime import date, timedelta

import nepali_datetime as nd

DEV = str.maketrans("०१२३४५६७८९", "0123456789")

MONTHS = {
    "जनवरी": 1, "फेब्रुअरी": 2, "फेब्रुवरी": 2, "मार्च": 3, "अप्रिल": 4, "अप्रील": 4, "मे": 5, "जुन": 6, "जून": 6,
    "जुलाई": 7, "अगस्ट": 8, "अगष्ट": 8, "सेप्टेम्बर": 9, "सेप्टेम्वर": 9, "अक्टोबर": 10, "अक्टुबर": 10,
    "नोभेम्बर": 11, "नोभेम्वर": 11, "डिसेम्बर": 12, "डिसेम्वर": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# a Nepali year such as 2083, then month and day, with OCR-friendly separators
BS_RE = re.compile(r"(20[6-9]\d)\s*[/:\-.]\s*(\d{1,2})\s*[/:\-.]\s*(\d{1,2})")
# "सन् २०२६ डिसेम्बर ४"  and  "November 20, 2026"
AD_DEV = re.compile(r"सन[्‌‍]?\W{0,4}(20\d\d)\W{0,3}([ऀ-ॿ]+)\W{0,3}(\d{1,2})")
AD_EN = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d\d)")


def norm(text: str) -> str:
    return text.translate(DEV)


def bs_to_ad(y: int, m: int, d: int):
    try:
        return nd.date(y, m, d).to_datetime_date()
    except Exception:
        return None


def ad_dates(flat: str):
    out = set()
    for m in AD_DEV.finditer(flat):
        mon = MONTHS.get(m.group(2))
        if mon:
            try:
                out.add(date(int(m.group(1)), mon, int(m.group(3))))
            except ValueError:
                pass
    for m in AD_EN.finditer(flat):
        mon = MONTHS.get(m.group(1).lower())
        if mon:
            try:
                out.add(date(int(m.group(3)), mon, int(m.group(2))))
            except ValueError:
                pass
    return out


def share_type(title: str, flat_raw: str) -> str:
    t = (title + " " + flat_raw).lower()
    if "mutual fund" in t or "म्युचुअल" in t or "म्यूचुअल" in t:
        return "Mutual fund"
    if "संस्थापक" in flat_raw or "promoter" in t:
        return "Promoter"
    return "Other"


def parse(title: str, ocr_text: str, today: date | None = None):
    """Returns dict: status 'publish' or 'review', plus symbol, share_type, unlock (first free day), why."""
    today = today or date.today()
    flat = norm(ocr_text)
    sym = re.search(r"\[([A-Z0-9]{2,12})\]", title or "")
    res = {"symbol": sym.group(1) if sym else None, "share_type": share_type(title or "", ocr_text), "unlock": None, "why": ""}

    ads = ad_dates(flat)
    pairs = []  # BS dates that convert to a date also printed in English
    all_bs = []
    for m in BS_RE.finditer(flat):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 32):
            continue
        conv = bs_to_ad(y, mo, d)
        if conv:
            all_bs.append(conv)
            if conv in ads:
                pairs.append(conv)
    pairs = sorted(set(pairs))

    if not res["symbol"]:
        res.update(status="review", why="no company symbol in the title")
        return res
    if len(pairs) != 1:
        res.update(status="review", why=f"{len(pairs)} matching date pairs (needs exactly 1); read dates: {sorted(set(map(str, all_bs)))}")
        return res

    last = pairs[0]
    # "...until DATE and ends after that" (सम्म / पश्चात्) means the last locked day is DATE; first free day is the next day
    if "पश्चात" in flat or "पश्चात्" in ocr_text:
        first_free = last + timedelta(days=1)
    else:
        res.update(status="review", why="could not tell whether the date is the last locked day or the first free day")
        return res

    if first_free < today - timedelta(days=30) or first_free > today + timedelta(days=365 * 4):
        res.update(status="review", unlock=first_free.isoformat(), why="date is outside the expected range")
        return res

    res.update(status="publish", unlock=first_free.isoformat(), why=f"BS date matches the printed English date ({last})")
    return res
