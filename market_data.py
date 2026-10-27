"""Fetch 5-minute history for the whole universe once; every agent reads from it."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import config
from brokers.base import IST

log = logging.getLogger("market_data")


def fetch_all(broker, stocks, progress=None) -> dict:
    now = datetime.now(IST)
    start = now - timedelta(days=config.HISTORY_DAYS)
    out, done = {}, 0

    def one(stock):
        df = broker.candles(stock.symbol, start, now, config.INTERVAL)
        if broker.live and not df.empty:
            # drop the candle that is still forming
            if df["date"].iloc[-1] + timedelta(minutes=config.BAR_MINUTES) > now:
                df = df.iloc[:-1]
        return stock.symbol, df

    with ThreadPoolExecutor(config.MAX_WORKERS) as pool:
        futures = [pool.submit(one, s) for s in stocks]
        for f in as_completed(futures):
            done += 1
            try:
                sym, df = f.result()
                out[sym] = df
            except Exception as e:  # one bad symbol must not stop the scan
                log.warning("candles failed: %s", e)
            if progress:
                progress("Fetching candles", done, len(stocks))
    return out
