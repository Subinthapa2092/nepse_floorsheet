"""Reads the key figures out of a quarterly financial result picture (.gif/.jpg/.png) of a bank.

    python report_reader.py picture.gif            prints what it found and the checks

Steps: enlarge the picture, OCR every word with its position, split the two page columns, rebuild text lines,
match line labels to measures, take the right column of numbers, and cross-check (EPS against profit / share capital).
Nothing here is saved anywhere: the caller decides what to do with the result.
"""
import csv
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

SCALE = 2
DARK = 150


def ocr_words(path):
    """[(left, top, width, height, text)] in original-picture pixels."""
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(int)
    # the grey/yellow watermark is lighter than the black text: keep only dark pixels
    im = Image.fromarray(np.where(rgb.min(axis=2) < DARK, 0, 255).astype("uint8"))
    im = im.resize((im.width * SCALE, im.height * SCALE), Image.LANCZOS)
    with tempfile.TemporaryDirectory() as d:
        png = Path(d) / "p.png"
        im.save(png)
        out = subprocess.run(["tesseract", str(png), "-", "--psm", "6", "tsv"], capture_output=True, text=True).stdout
    words = []
    for r in csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE):
        t = (r.get("text") or "").strip()
        if not t or float(r["conf"]) < 0:
            continue
        words.append((int(r["left"]) / SCALE, int(r["top"]) / SCALE, int(r["width"]) / SCALE, int(r["height"]) / SCALE, t))
    return words, im.width // SCALE


def heading_text(path):
    """The title band at the top of the picture. It is often white text on black, which the dark-pixel filter would erase,
    so it is read separately from the untouched picture (inverted when the band is dark)."""
    im = Image.open(path).convert("L")
    top = im.crop((0, 0, im.width, int(im.height * 0.14)))
    if np.asarray(top).mean() < 110:
        top = Image.fromarray(255 - np.asarray(top))
    top = top.resize((top.width * 2, top.height * 2), Image.LANCZOS)
    with tempfile.TemporaryDirectory() as d:
        png = Path(d) / "h.png"
        top.save(png)
        return subprocess.run(["tesseract", str(png), "-", "--psm", "6"], capture_output=True, text=True).stdout


def split_columns(words, width):
    """One or two page columns. Find the widest empty vertical strip in the middle of the page and cut there.
    If there is no real empty strip, the page is read as one block."""
    step = 4
    n = int(width // step) + 1
    cover = [0] * n
    for l, t, w, h, _ in words:
        for i in range(int(l // step), min(n - 1, int((l + w) // step)) + 1):
            cover[i] += 1
    lo, hi = int(n * 0.33), int(n * 0.67)
    best_len, best_mid, run_start = 0, None, None
    for i in range(lo, hi + 1):
        empty = i < hi and cover[i] <= 2
        if empty and run_start is None:
            run_start = i
        if not empty and run_start is not None:
            if i - run_start > best_len:
                best_len, best_mid = i - run_start, (run_start + i) // 2
            run_start = None
    if best_mid is None or best_len * step < 14:
        return [list(words)]
    cut = best_mid * step
    return [[w for w in words if w[0] + w[2] / 2 < cut], [w for w in words if w[0] + w[2] / 2 >= cut]]


def to_lines(words):
    words = sorted(words, key=lambda w: w[1] + w[3] / 2)
    if not words:
        return []
    med = sorted(w[3] for w in words)[len(words) // 2]
    lines, cur, cy = [], [], None
    for w in words:
        y = w[1] + w[3] / 2
        if cy is None or abs(y - cy) <= med * 0.6:
            cur.append(w)
            cy = y if cy is None else (cy * (len(cur) - 1) + y) / len(cur)
        else:
            lines.append(sorted(cur, key=lambda a: a[0]))
            cur, cy = [w], y
    if cur:
        lines.append(sorted(cur, key=lambda a: a[0]))
    return lines


NUM = re.compile(r"^\(?-?\d[\d,.)]*\)?%?$|^-$")


def parse_num(tok):
    """'(62,136,469)' -> -62136469.0, '4.31' -> 4.31, '-' -> 0.0, junk -> None"""
    s = re.sub(r"^[\s|~_=\u2014\u2013.:;*'\"\u2018\u2019]+|[\s|~_=:;*'\"\u2018\u2019]+$", "", tok)
    s = re.sub(r"^[\u2014\u2013]+(?=\d)", "", s)
    if s in ("-", "–"):
        return 0.0
    neg = s.startswith("(") or s.startswith("-")
    s = re.sub(r"[^\d.,)]", "", s)
    s = s.replace(")", ",") if re.search(r"\)\d", s) else s.replace(")", "")
    if "," in s and not re.fullmatch(r"\d{1,3}(,\d{3})*(\.\d+)?", s):
        return None  # a broken thousands group such as 1,611,45: better unknown than wrong
    s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    v = float(s)
    return -v if neg else v


def glue(line):
    """OCR sometimes splits '27 056,997' into two words: join a short number to a following ',ddd' number."""
    out = []
    for w in line:
        if out and re.fullmatch(r"\d{1,3}", out[-1][4]) and re.fullmatch(r"\d{3}(,\d{3})+", w[4]):
            l, t, ww, h, txt = out[-1]
            out[-1] = (l, t, w[0] + w[2] - l, h, txt + "," + w[4])
        else:
            out.append(w)
    return out


def line_parts(line):
    line = glue(line)
    """label text and the numbers that follow it (numbers start at the first numeric token that is not part of the label)."""
    label, nums = [], []
    for _, _, _, _, t in line:
        if NUM.match(re.sub(r"^[\s|~_=\u2014\u2013.:;*'\"\u2018\u2019]+|[\s|~_=:;*|'\"\u2018\u2019]+$", "", t)):
            v = parse_num(t)
            if label or nums:
                nums.append(v)  # None keeps the column position when one number is unreadable
                continue
        if nums:  # text after the numbers (OCR noise from the next column) is ignored
            continue
        label.append(t)
    return " ".join(label), nums


# label pattern -> (measure, which statement it belongs to)
RULES = [
    ("net_profit", re.compile(r"profit\s*/?\s*\(?\s*loss\)?\s*(i\s*)?for\s*the\s*(period|quarter)", re.I), "pl"),
    ("operating_profit", re.compile(r"^operating profit", re.I), "pl"),
    ("interest_income", re.compile(r"^interest income", re.I), "pl"),
    ("net_interest_income", re.compile(r"^net interest income", re.I), "pl"),
    ("eps_annualized", re.compile(r"^(basic|diluted) earnings? per share", re.I), "eps"),
    ("paid_up_capital", re.compile(r"^share capit\w*", re.I), "bs"),
    ("retained_earnings", re.compile(r"^retained earnings?", re.I), "bs"),
    ("reserves", re.compile(r"^reserves?$", re.I), "bs"),
    ("net_worth", re.compile(r"^total equity$", re.I), "bs"),
    ("total_assets", re.compile(r"^total assets", re.I), "bs"),
    ("deposits", re.compile(r"^deposits from customers", re.I), "bs"),
    ("loans", re.compile(r"^loans and advances to customers", re.I), "bs"),
    ("npl_gross", re.compile(r"^(gross )?non[- ]?performing loan.*total loan|^gross non", re.I), "ratio"),
    ("cd_ratio", re.compile(r"^credit to deposit", re.I), "ratio"),
    ("roe", re.compile(r"^return on equity", re.I), "ratio"),
    ("roa", re.compile(r"^return on assets?", re.I), "ratio"),
    ("cost_of_funds", re.compile(r"^costs? of funds", re.I), "ratio"),
    ("capital_adequacy", re.compile(r"^capital fund to rwa", re.I), "ratio"),
]


def first_ok(nums, order):
    for i in order:
        if i < len(nums) and nums[i] is not None:
            return nums[i]
    return None


def pick(nums, kind, has_bank):
    """Choose the right number. Statements with a Group and a Bank block carry 4+4 numbers (or 2+2 for the balance sheet)."""
    n = len(nums)
    if kind == "bs":
        if n >= 4:
            return first_ok(nums, (2,) if has_bank else (0,))  # this quarter ending: bank block, else the only block
        return first_ok(nums, (0,))
    if kind == "pl":
        if n >= 8:
            return first_ok(nums, (5, 4))  # bank, current year: this quarter and year-to-date are equal in Q1, so one may cover for the other
        if n >= 4:
            return first_ok(nums, (1, 0))
        return first_ok(nums, range(n - 1, -1, -1))
    if kind == "eps":
        if n >= 4:
            return first_ok(nums, (2,))  # bank, current year
        return first_ok(nums, (0,))
    if kind == "ratio":
        if n >= 8:
            return first_ok(nums, (5, 4))
        if n >= 4:
            return first_ok(nums, (1, 0))
        return first_ok(nums, (0,))
    return None


def read(path):
    words, width = ocr_words(path)
    text_all = " ".join(w[4] for w in words)
    unit = 1000.0 if re.search(r"NPR\s*in\s*['’`]?\s*000|in\s*['’`]000", text_all, re.I) else 1.0
    found, lines_seen = {}, 0
    cols = split_columns(words, width)
    has_bank = bool(re.search(r"\bBank\b", " ".join(w[4] for w in words if w[1] < 1700)) and re.search(r"\bGroup\b", text_all))
    for col in cols:
        for line in to_lines(col):
            lines_seen += 1
            label, nums = line_parts(line)
            if not nums:
                continue
            label = re.sub(r"\s+", " ", label).strip()
            label = label.translate(str.maketrans("{}[]", "()()"))
            label = re.sub(r"\b(\w+) / \1\b", r"\1", label)
            for measure, rx, kind in RULES:
                if rx.search(label):
                    v = pick(nums, kind, has_bank)
                    if v is None:
                        continue
                    if kind in ("pl", "bs"):
                        v = v * unit
                    old = found.get(measure)
                    if old is None or sum(x is not None for x in nums) > sum(x is not None for x in old["numbers"]):  # the full table row has the most numbers
                        found[measure] = {"value": v, "label": label, "numbers": nums}
    return {"unit": unit, "has_group_and_bank": has_bank, "lines": lines_seen, "found": found, "text": text_all, "heading": heading_text(path)}


VARIANTS = [(90, 2), (150, 2), (120, 3)]  # (darkness cut-off, enlargement): scans differ, so no single setting suits all


def read_multi(path, variants=VARIANTS):
    """Reads the picture several ways and keeps, for each figure, the value most passes agree on.
    Two independent passes giving the same number is strong evidence; a lone value stays 'single'."""
    global DARK, SCALE
    saved = (DARK, SCALE)
    runs = []
    try:
        for dark, scale in variants:
            DARK, SCALE = dark, scale
            runs.append(read(path))
    finally:
        DARK, SCALE = saved
    merged = {}
    metrics = {m for r in runs for m in r["found"]}
    for m in metrics:
        votes = {}
        for r in runs:
            if m in r["found"]:
                v = round(r["found"][m]["value"], 4)
                votes.setdefault(v, []).append(r["found"][m])
        best = max(votes.items(), key=lambda kv: (len(kv[1]), len(kv[1][0]["numbers"])))
        item = dict(best[1][0])
        item["agree"] = len(best[1])
        item["passes"] = len(runs)
        item["others"] = [v for v in votes if v != best[0]]
        merged[m] = item
    first = max(runs, key=lambda r: len(r["found"]))
    return {
        "unit": first["unit"], "has_group_and_bank": first["has_group_and_bank"], "lines": first["lines"], "found": merged,
        "text": " ".join(r["text"] for r in runs), "heading": " ".join(r["heading"] for r in runs[:1]),
    }


def checks(res):
    """Cross-checks. Each is (name, ok, detail). A figure with a failed check goes to review, never straight to the site."""
    f = {k: v["value"] for k, v in res["found"].items()}
    out = []
    if all(k in f for k in ("net_profit", "paid_up_capital", "eps_annualized")) and f["paid_up_capital"]:
        shares = f["paid_up_capital"] / 100.0  # face value Rs 100
        calc = f["net_profit"] * 4 / shares
        rep = f["eps_annualized"]
        ok = abs(calc - rep) <= max(abs(rep) * 0.06, 0.5)
        out.append(("EPS = 4 x profit / shares", ok, f"calculated {calc:.2f}, reported {rep:.2f}"))
        res["calc_eps"] = round(calc, 2)
    if f.get("net_profit") is not None and f.get("roe") is not None and f["net_profit"] < 0 < f["roe"]:
        res["found"]["roe"]["value"] = -f["roe"]  # the minus sign is often lost; profit is negative so ROE must be
        out.append(("ROE sign follows profit", True, "sign restored"))
    if all(k in f for k in ("total_assets", "net_worth")):
        out.append(("net worth below total assets", f["net_worth"] < f["total_assets"], f"{f['net_worth']:,.0f} < {f['total_assets']:,.0f}"))
    if all(k in f for k in ("net_interest_income", "interest_income")):
        out.append(("net interest income below interest income", f["net_interest_income"] <= f["interest_income"], ""))
    return out


if __name__ == "__main__":
    r = read(sys.argv[1])
    print(f"unit x{r['unit']:g}  group+bank layout: {r['has_group_and_bank']}  lines read: {r['lines']}")
    for k, v in r["found"].items():
        print(f"  {k:22s} {v['value']:>22,.2f}   <- {v['label'][:48]!r} {v['numbers']}")
    for name, ok, detail in checks(r):
        print(("  OK    " if ok else "  FAIL  ") + name, detail)
