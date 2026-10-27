"""Web backend.  Run:  uvicorn server:app --host 0.0.0.0 --port 8000"""
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

import charts
import config
import next_day
from brokers.base import IST
from brokers.factory import get_broker
from pipeline import run_scan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("server")
LAST_SCAN = config.DATA_DIR / "last_scan.json"

# ------------------------------------------------------------------- auth
_basic = HTTPBasic(auto_error=False)


def require_login(creds: Optional[HTTPBasicCredentials] = Depends(_basic)):
    if not (config.APP_USER and config.APP_PASSWORD):
        return
    ok = creds and secrets.compare_digest(creds.username, config.APP_USER) \
        and secrets.compare_digest(creds.password, config.APP_PASSWORD)
    if not ok:
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": "Basic"})


app = FastAPI(title="Intraday Top 5", dependencies=[Depends(require_login)])
app.mount("/static", StaticFiles(directory=config.BASE_DIR / "static"), name="static")


# ------------------------------------------------------------------ state
class State:
    lock = threading.Lock()
    broker = None
    broker_error = None
    scanning = False
    stage, done, total = "", 0, 0
    error = None
    result = json.loads(LAST_SCAN.read_text()) if LAST_SCAN.exists() else None


S = State()


def broker():
    if S.broker is None:
        try:
            S.broker = get_broker()
            S.broker_error = None
        except Exception as e:
            S.broker_error = str(e)
            raise HTTPException(503, S.broker_error)
    return S.broker


def _progress(stage, done, total):
    S.stage, S.done, S.total = stage, done, total


def _scan_job():
    try:
        res = run_scan(broker(), _progress)
        S.result = res
        LAST_SCAN.write_text(json.dumps(res, default=str))
        S.error = None
    except Exception as e:
        log.exception("scan failed")
        S.error = str(getattr(e, "detail", e))
    finally:
        S.scanning = False
        S.stage = ""


def start_scan() -> bool:
    with S.lock:
        if S.scanning:
            return False
        S.scanning, S.error = True, None
    threading.Thread(target=_scan_job, daemon=True).start()
    return True


def _auto_scan_loop():
    while True:
        time.sleep(30)
        now = datetime.now(IST)
        mins = now.hour * 60 + now.minute
        if now.weekday() >= 5 or not (9 * 60 + 35 <= mins <= 15 * 60):
            continue
        last = S.result and datetime.fromisoformat(S.result["generated_at"])
        if not last or now - last >= timedelta(minutes=config.AUTO_SCAN_MINUTES):
            start_scan()


if config.AUTO_SCAN_MINUTES > 0:
    threading.Thread(target=_auto_scan_loop, daemon=True).start()


# ------------------------------------------------------------------ routes
@app.get("/")
def index():
    return FileResponse(config.BASE_DIR / "static" / "index.html")


@app.get("/api/status")
def status():
    ready = True
    try:
        broker()
    except HTTPException:
        ready = False
    return {"broker": config.BROKER, "broker_ready": ready, "broker_error": S.broker_error,
            "scanning": S.scanning, "stage": S.stage, "done": S.done, "total": S.total,
            "error": S.error, "has_result": S.result is not None,
            "auto_scan_minutes": config.AUTO_SCAN_MINUTES}


@app.post("/api/scan")
def scan():
    broker()
    return {"started": start_scan()}


@app.get("/api/results")
def results():
    if not S.result:
        raise HTTPException(404, "No scan yet")
    return S.result


NEXT_DAY_MAX_AGE = timedelta(minutes=10)
NEXT_DAY_LISTS = {"main": None, "low": config.LOW_PRICE_UNIVERSE_FILE}   # list -> universe file
_next_lock = threading.Lock()
_next_scans = {}   # list -> next_day.scan() result


@app.get("/api/nextday")
def next_day_list(which: str = Query("main", alias="list", pattern="^(main|low)$"),
                  max_price: Optional[float] = Query(None, gt=0), refresh: bool = False):
    b = broker()
    with _next_lock:   # one build at a time; a second caller gets the fresh result
        sc = _next_scans.get(which)
        stale = not sc or datetime.now(IST) - sc["generated_at"] >= NEXT_DAY_MAX_AGE or sc["broker"] != b.name
        if refresh or stale:
            sc = _next_scans[which] = next_day.scan(b, NEXT_DAY_LISTS[which])
    return next_day.summarize(sc, max_price)


@app.get("/api/daily/{symbol}")
def daily(symbol: str, days: int = Query(130, ge=20, le=400)):
    bars = charts.daily_bars(broker(), symbol, days)
    if not bars:
        raise HTTPException(404, "No candles")
    return {"symbol": symbol, "bars": bars}


@app.get("/api/candles/{symbol}")
def candles(symbol: str, sessions: int = Query(2, ge=1, le=5)):
    b = broker()
    if not b.has(symbol):
        raise HTTPException(404, f"{symbol} not found on NSE")
    bars = charts.candle_bars(b, symbol, sessions)
    if not bars:
        raise HTTPException(404, "No candles")
    return {"symbol": symbol, "bars": bars}


@app.get("/api/ltp")
def ltp(symbols: str):
    syms = [s for s in symbols.split(",") if s][:50]
    return {"time": datetime.now(IST).isoformat(), "prices": broker().ltp(syms)}


@app.get("/kite/login")
def kite_login():
    from brokers.kite import make_client
    return RedirectResponse(make_client().login_url())


@app.get("/kite/callback")
def kite_callback(request_token: str = "", status: str = ""):
    if status != "success" or not request_token:
        raise HTTPException(400, "Kite login was cancelled or failed. Try again from the home page.")
    from brokers.kite import save_session
    save_session(request_token)
    S.broker = None          # reconnect with the fresh token
    return RedirectResponse("/")
