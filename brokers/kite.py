"""Zerodha Kite Connect adapter."""
import threading
import time
from datetime import datetime

import pandas as pd
from kiteconnect import KiteConnect

import config
from .base import Broker, normalize


class _RateLimiter:
    def __init__(self, per_sec: float):
        self.gap = 1.0 / per_sec
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            sleep_for = self.next_at - now
            self.next_at = max(now, self.next_at) + self.gap
        if sleep_for > 0:
            time.sleep(sleep_for)


def make_client() -> KiteConnect:
    if not config.KITE_API_KEY:
        raise RuntimeError("KITE_API_KEY is not set in .env")
    return KiteConnect(api_key=config.KITE_API_KEY)


def save_session(request_token: str) -> str:
    kite = make_client()
    session = kite.generate_session(request_token, api_secret=config.KITE_API_SECRET)
    token = session["access_token"]
    config.KITE_ACCESS_TOKEN_FILE.write_text(token)
    return token


class KiteBroker(Broker):
    name = "kite"
    live = True

    def __init__(self):
        if not config.KITE_ACCESS_TOKEN_FILE.exists():
            raise RuntimeError("No Kite session. Log in at /kite/login or run: python login_kite.py")
        self.kite = make_client()
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN_FILE.read_text().strip())
        rows = self.kite.instruments("NSE")
        eq = [r for r in rows if r.get("instrument_type") == "EQ" and r.get("segment") == "NSE"]
        self._tokens = {r["tradingsymbol"]: r["instrument_token"] for r in eq}
        self._names = {r["tradingsymbol"]: r.get("name") or r["tradingsymbol"] for r in eq}
        self._limiter = _RateLimiter(config.KITE_RATE_LIMIT_PER_SEC)

    def has(self, symbol):
        return symbol in self._tokens

    def names(self):
        return self._names

    def candles(self, symbol, start: datetime, end: datetime, interval="5minute"):
        token = self._tokens[symbol]
        self._limiter.wait()
        rows = self.kite.historical_data(token, start.replace(tzinfo=None),
                                         end.replace(tzinfo=None), interval)
        return normalize(pd.DataFrame(rows))

    def ltp(self, symbols):
        if not symbols:
            return {}
        data = self.kite.ltp([f"NSE:{s}" for s in symbols])
        return {k.split(":", 1)[1]: v["last_price"] for k, v in data.items()}
