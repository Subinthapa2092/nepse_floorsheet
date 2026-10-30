"""
STEP 2: uploads the small summaries made by archive_summarize.py to Supabase.

WHERE TO RUN: in your nepse_floorsheet folder (next to the .env that has
SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY). First copy data/archive_summaries.db there.
Never put the service-role key in the arthotix website folder.

  python upload_archive_summaries.py            -> checks only, prints what it WOULD send
  python upload_archive_summaries.py --go       -> really uploads

SAFE TO RE-RUN: days / months that already exist in Supabase are skipped, so nothing
is ever counted twice. It only INSERTS. It never updates or deletes anything.
"""
import os, sys, sqlite3
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
GO = "--go" in sys.argv
FILE = next((a for a in sys.argv[1:] if not a.startswith("--")), "data/archive_summaries.db")
DAILY_BEFORE, MONTHLY_BEFORE = "2026-08-03", "2026-02-01"
BATCH = 1000

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
db = sqlite3.connect("file:" + FILE + "?mode=ro", uri=True)

def existing_days():
    seen, start = set(), 0
    while True:
        r = sb.table("floorsheet_daily_broker").select("business_date").lt("business_date", DAILY_BEFORE) \
              .order("business_date").range(start, start + 999).execute().data
        seen.update(x["business_date"] for x in r)
        if len(r) < 1000: return seen
        start += 1000

def existing_months():
    r = sb.rpc("distinct_monthly_summary_months").execute().data
    out = set()
    for x in r:
        out.add(x if isinstance(x, str) else list(x.values())[0])
    return {str(m)[:10] for m in out}

def send(table, cols, rows, label):
    print(f"  {label}: {len(rows)} rows to send")
    if not GO: return
    for i in range(0, len(rows), BATCH):
        part = [dict(zip(cols, r)) for r in rows[i:i + BATCH]]
        sb.table(table).insert(part).execute()
        print(f"    sent {min(i + BATCH, len(rows))}/{len(rows)}", end="\r", flush=True)
    print()

# ---- daily per broker
dcols = ["business_date", "broker", "buy_qty", "buy_amt", "buy_trans", "sell_qty", "sell_amt", "sell_trans"]
have = existing_days()
rows = [r for r in db.execute(f"select {','.join(dcols)} from daily_broker where business_date < ? order by 1,2", (DAILY_BEFORE,))
        if r[0] not in have]
print("Daily broker totals: already in Supabase:", len(have), "days")
send("floorsheet_daily_broker", dcols, rows, "daily_broker")

# ---- monthly per stock and broker
mcols = ["month_start", "symbol", "broker", "buy_qty", "buy_amt", "buy_trans", "sell_qty", "sell_amt", "sell_trans"]
haveM = existing_months()
print("Monthly totals: months already in Supabase:", sorted(haveM))
rows = [r for r in db.execute(f"select {','.join(mcols)} from monthly_broker where month_start < ? order by 1,2,3", (MONTHLY_BEFORE,))
        if r[0] not in haveM]
send("floorsheet_monthly_summary", mcols, rows, "monthly_broker")

print("\nDONE (uploaded)." if GO else "\nDRY RUN ONLY. Nothing was sent. Run again with --go to upload.")