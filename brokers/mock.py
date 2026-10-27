"""Synthetic NSE-like 5-minute data so the whole system runs without a broker account."""
import time
import zlib
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import config
from .base import IST, Broker, normalize

BARS_PER_DAY = 75   # 09:15 .. 15:25


def _sessions(end: datetime, days: int):
    d = end.date()
    out = []
    while len(out) < days:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class MockBroker(Broker):
    name = "mock"
    live = False

    def __init__(self):
        self._cache = {}

    def has(self, symbol):
        return True

    def _series(self, symbol):
        if symbol in self._cache:
            return self._cache[symbol]
        rng = np.random.default_rng(zlib.crc32(symbol.encode()) + datetime.now(IST).toordinal())
        price = float(rng.uniform(150, 4000))
        base_vol = float(rng.uniform(2e4, 4e5))
        frames = []
        days = _sessions(datetime.now(IST), 25)
        for n, day in enumerate(days):
            bars = config.MOCK_BARS_TODAY if n == len(days) - 1 else BARS_PER_DAY
            drift = rng.normal(0, 0.012) / BARS_PER_DAY
            vol = rng.uniform(0.010, 0.022) / np.sqrt(BARS_PER_DAY)
            price *= 1 + rng.normal(0, 0.006)                       # overnight gap
            rets = rng.normal(drift, vol, BARS_PER_DAY)[:bars]
            closes = price * np.cumprod(1 + rets)
            opens = np.concatenate([[price], closes[:-1]])
            spread = np.abs(rng.normal(0, vol, bars)) * closes
            highs = np.maximum(opens, closes) + spread
            lows = np.minimum(opens, closes) - spread
            ushape = 1 + 1.8 * np.abs(np.linspace(-1, 1, BARS_PER_DAY))[:bars] ** 2
            volume = base_vol * ushape * (1 + 40 * np.abs(rets)) * rng.uniform(0.6, 1.4, bars)
            start = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)
            dates = [start + timedelta(minutes=5 * i) for i in range(bars)]
            frames.append(pd.DataFrame({"date": dates, "open": opens, "high": highs,
                                        "low": lows, "close": closes, "volume": volume.round()}))
            price = float(closes[-1])
        df = normalize(pd.concat(frames, ignore_index=True))
        self._cache[symbol] = df
        return df

    def candles(self, symbol, start, end, interval="5minute"):
        df = self._series(symbol)
        return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)

    def ltp(self, symbols):
        out = {}
        for s in symbols:
            last = float(self._series(s)["close"].iloc[-1])
            wiggle = np.sin(time.time() / 7 + zlib.crc32(s.encode())) * 0.002
            out[s] = round(last * (1 + wiggle) / config.TICK) * config.TICK
        return out
