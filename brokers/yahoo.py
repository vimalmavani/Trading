"""Yahoo Finance adapter. Free, no login; NSE quotes may lag the exchange by a minute or two.
Calls the public chart API directly: it needs no cookie, so it also works behind TLS-inspecting proxies."""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from .base import Broker, normalize

log = logging.getLogger("yahoo")
URL = "https://query2.finance.yahoo.com/v8/finance/chart/{}"
HEADERS = {"User-Agent": "Mozilla/5.0"}
INTERVALS = {"minute": "1m", "5minute": "5m", "15minute": "15m", "day": "1d"}
LTP_CACHE_SECONDS = 10


def _chart(symbol: str, **params) -> dict:
    r = requests.get(URL.format(requests.utils.quote(f"{symbol}.NS")), params=params,
                     headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()["chart"]["result"][0]


class YahooBroker(Broker):
    name = "yahoo"
    live = True

    def __init__(self):
        self._ltp = {}
        self._ltp_at = 0.0
        self._lock = threading.Lock()

    def has(self, symbol):
        return True   # unknown symbols fail to fetch and are skipped

    def candles(self, symbol, start, end, interval="5minute"):
        res = _chart(symbol, interval=INTERVALS[interval],
                     period1=int(start.timestamp()), period2=int(end.timestamp()))
        if not res.get("timestamp"):
            return normalize(None)
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame({"date": pd.to_datetime(res["timestamp"], unit="s", utc=True),
                           **{k: q[k] for k in ["open", "high", "low", "close", "volume"]}})
        df = df.dropna(subset=["open", "high", "low", "close"]).fillna({"volume": 0})
        if interval != "day":
            # a point off the bar grid (e.g. 15:14:59) is a live quote, not a candle
            df = df[df["date"] == df["date"].dt.floor(f"{INTERVALS[interval][:-1]}min")]
            # the newest bar is often a zero-volume placeholder (open = high = low = close)
            while len(df) and df["volume"].iloc[-1] == 0:
                df = df.iloc[:-1]
        return normalize(df)

    def _price(self, symbol):
        return symbol, float(_chart(symbol, interval="1m", range="1d")["meta"]["regularMarketPrice"])

    def ltp(self, symbols):
        if not symbols:
            return {}
        with self._lock:
            if time.time() - self._ltp_at < LTP_CACHE_SECONDS and all(s in self._ltp for s in symbols):
                return {s: self._ltp[s] for s in symbols}
            with ThreadPoolExecutor(8) as pool:
                futures = [pool.submit(self._price, s) for s in symbols]
            for f in futures:
                try:
                    sym, price = f.result()
                    self._ltp[sym] = price
                except Exception as e:
                    log.warning("no quote: %s", e)
            self._ltp_at = time.time()
            return {s: self._ltp[s] for s in symbols if s in self._ltp}
