"""
Prints the SHAPE of the intraday graph endpoints (NEPSE index, two sector indices, one stock),
so we can see the real field names, how many points there are and what the times look like.
Read only. No keys, nothing is saved anywhere.

Run it from GitHub: Actions -> "Inspect graphs" -> Run workflow, then open the log.
"""
import json
import traceback

from nepse import Nepse


def show(label, fn):
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    try:
        v = fn()
    except Exception:
        traceback.print_exc()
        return
    if v is None:
        print("(None returned)")
        return
    print("type:", type(v).__name__)
    if isinstance(v, dict):
        print("keys:", list(v.keys())[:20])
        for k, x in v.items():
            if isinstance(x, list):
                print(f"key '{k}' is a list of {len(x)}")
                v = x
                break
    if isinstance(v, list):
        print("items:", len(v))
        for name, i in (("first", 0), ("second", 1), ("middle", len(v) // 2), ("last", -1)):
            if v:
                print(f"{name}:", json.dumps(v[i], default=str)[:300])
    else:
        print(json.dumps(v, default=str)[:500])


def main():
    n = Nepse()
    n.setTLSVerification(False)
    show("getDailyNepseIndexGraph()", n.getDailyNepseIndexGraph)
    show("getDailyBankSubindexGraph()", n.getDailyBankSubindexGraph)
    show("getDailyHydroSubindexGraph()", n.getDailyHydroSubindexGraph)
    try:
        import asyncio
        # the stock graph is an async call in this library
        from nepse import AsyncNepse  # noqa: F401
    except Exception:
        pass
    show("getDailyScripPriceGraph('NABIL')", lambda: n.getDailyScripPriceGraph("NABIL"))


if __name__ == "__main__":
    main()
