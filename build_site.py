"""Static build for GitHub Pages:  python build_site.py  ->  site/
Runs the same scans as the server and writes each API answer as a JSON file, so the web page
works with no server. GitHub Actions runs this every few minutes (.github/workflows/scan.yml)."""
import json
import logging
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import charts
import config
import next_day
from brokers.base import IST
from brokers.factory import get_broker
from pipeline import run_scan

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("build_site")

OUT = config.BASE_DIR / "site"
API = OUT / "api"
LOW_CAPS = [200, 500, 1000]    # keep in step with LOW_CAPS in static/index.html


def key(symbol: str) -> str:
    """File-safe name for a symbol (M&M -> M_M). Same rule as fileKey() in index.html."""
    return re.sub(r"[^A-Za-z0-9-]", "_", symbol)


def write(path: str, obj) -> None:
    f = API / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(obj, default=str))


def symbols(*lists) -> list:
    return sorted({p["symbol"] for res in lists if res for p in res["top"] + res.get("watchlist", [])})


def charts_for(b, syms, fn, folder) -> None:
    def one(sym):
        try:
            bars = fn(b, sym)
            if bars:
                write(f"{folder}/{key(sym)}.json", {"symbol": sym, "bars": bars})
        except Exception as e:   # a missing chart must not stop the build
            log.warning("%s %s failed: %s", folder, sym, e)
    with ThreadPoolExecutor(config.MAX_WORKERS) as pool:
        list(pool.map(one, syms))


if __name__ == "__main__":
    t0 = time.time()
    b = get_broker()
    shutil.rmtree(OUT, ignore_errors=True)
    API.mkdir(parents=True)

    today = run_scan(b)            # if this fails the job fails and the last good site stays up
    write("results.json", today)

    nexts = {}
    for name, universe, caps in [("main", None, [None]), ("low", config.LOW_PRICE_UNIVERSE_FILE, LOW_CAPS)]:
        try:
            scanned = next_day.scan(b, universe)
            for cap in caps:
                res = nexts[f"{name}-{cap}" if cap else name] = next_day.summarize(scanned, cap)
                write(f"nextday-{name}{f'-{cap}' if cap else ''}.json", res)
        except Exception as e:
            log.warning("next-day %s list failed: %s", name, e)

    charts_for(b, symbols(today), charts.candle_bars, "candles")
    charts_for(b, symbols(*nexts.values()), charts.daily_bars, "daily")
    write("ltp.json", {"time": datetime.now(IST).isoformat(),
                       "prices": b.ltp(symbols(today, *nexts.values()))})
    write("status.json", {"broker": b.name, "broker_ready": True, "scanning": False, "error": None,
                          "has_result": True, "generated_at": today["generated_at"],
                          "repo": os.getenv("GITHUB_REPOSITORY", "")})

    page = (config.BASE_DIR / "static" / "index.html").read_text()
    (OUT / "index.html").write_text(page.replace("<script>\n", "<script>\nwindow.STATIC_SITE = true;\n", 1))
    (OUT / ".nojekyll").touch()
    log.info("site/ built in %.0fs: %d today picks, next-day lists %s",
             time.time() - t0, len(today["top"]), sorted(nexts))
