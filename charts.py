"""Chart data for the web page. Shared by the live server and the static GitHub Pages build."""
from datetime import datetime, timedelta

import config
import next_day
from brokers.base import IST
from indicators import add_indicators

IST_OFFSET = 19800  # chart library shows UTC; shift so the axis reads IST


def candle_bars(broker, symbol: str, sessions: int = 2) -> list:
    """5-minute candles with VWAP and Supertrend for the last few sessions. Empty if none."""
    now = datetime.now(IST)
    df = broker.candles(symbol, now - timedelta(days=7 + sessions), now, config.INTERVAL)
    if df.empty:
        return []
    df = add_indicators(df)
    keep = sorted(df["date"].dt.date.unique())[-sessions:]
    df = df[df["date"].dt.date.isin(keep)]
    epoch = [int(d.timestamp()) + IST_OFFSET for d in df["date"]]
    return [{"time": t, "open": r.open, "high": r.high, "low": r.low, "close": r.close,
             "volume": r.volume, "vwap": round(r.vwap, 2), "st": round(r.st, 2), "st_dir": int(r.st_dir)}
            for t, r in zip(epoch, df.itertuples())]


def daily_bars(broker, symbol: str, days: int = 130) -> list:
    """Daily candles with 20 and 50-day EMAs. Empty if none."""
    now = datetime.now(IST)
    d = next_day.to_daily(broker.candles(symbol, now - timedelta(days=days + 80), now, "day"))
    if d.empty:
        return []
    d = next_day.add_daily_indicators(d).iloc[-days:]
    return [{"time": t.date().isoformat(), "open": r.open, "high": r.high, "low": r.low, "close": r.close,
             "volume": r.volume, "ema20": round(r.ema20, 2), "ema50": round(r.ema50, 2)}
            for t, r in zip(d.index, d.itertuples())]
