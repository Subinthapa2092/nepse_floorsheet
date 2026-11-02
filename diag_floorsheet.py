"""
Prints what the NEPSE site answers (status code and the start of the reply) for a few floorsheet requests.
Read only. Saves nothing. Run in the nepse_floorsheet folder:   python diag_floorsheet.py
"""
import fetch_all as fa
from nepse import NepseLib

_orig = NepseLib._Nepse.handle_response


def _spy(self, response):
    print(f"     HTTP {response.status_code}  {(response.text or '')[:200]!r}")
    return _orig(self, response)


NepseLib._Nepse.handle_response = _spy


def attempt(label, fn):
    print(f"\n{label}")
    try:
        r = fn()
        n = len(r) if hasattr(r, "__len__") else r
        print("   result:", type(r).__name__, n)
        if isinstance(r, list) and r:
            print("   first row:", {k: r[0][k] for k in list(r[0])[:12]})
        if isinstance(r, dict):
            print("   keys:", list(r)[:12])
    except Exception as e:  # noqa: BLE001
        print(f"   FAILED: {type(e).__name__}: {e}")


def market_wide(n, d):
    """The market-wide floorsheet (what live_loop.py uses), asked for a given date. One page only."""
    url = f"{n.api_end_points['floor_sheet']}?&size=500&businessDate={d}&sort=contractId,desc"
    sheet = n.requestPOSTAPI(url=url, payload_generator=n.getPOSTPayloadIDForFloorSheet)
    fs = (sheet or {}).get("floorsheets", {})
    rows = fs.get("content", [])
    times = sorted(str(r.get("tradeTime")) for r in rows)
    return {"rows_on_page": len(rows), "totalPages": fs.get("totalPages"), "totalElements": fs.get("totalElements"),
            "first_time": times[0] if times else None, "last_time": times[-1] if times else None,
            "dates_seen": sorted({str(r.get("businessDate")) for r in rows})[:3]}


n = fa.get_nepse_client()
attempt("1) all-stocks prices for 2026-10-29", lambda: n.getPriceVolumeHistory(business_date="2026-10-29"))
attempt("2) NABIL floorsheet, latest session (2026-11-02)", lambda: n.getFloorSheetOf("NABIL", "2026-11-02"))
attempt("3) NABIL floorsheet, 2026-10-29", lambda: n.getFloorSheetOf("NABIL", "2026-10-29"))
attempt("4) NABIL floorsheet, 2026-09-02", lambda: n.getFloorSheetOf("NABIL", "2026-09-02"))
attempt("5) MARKET-WIDE floorsheet, no date (what the live loop uses)", lambda: market_wide(n, ""))
attempt("6) MARKET-WIDE floorsheet for 2026-10-29", lambda: market_wide(n, "2026-10-29"))
attempt("7) MARKET-WIDE floorsheet for 2026-09-02", lambda: market_wide(n, "2026-09-02"))
