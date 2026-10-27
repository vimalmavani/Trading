"""Broker interface. Add Upstox / Angel One by implementing these three methods."""
from abc import ABC, abstractmethod
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class Broker(ABC):
    name = "base"
    live = True   # False for mock data

    @abstractmethod
    def has(self, symbol: str) -> bool:
        """True if the symbol is tradable on NSE cash."""

    @abstractmethod
    def candles(self, symbol: str, start: datetime, end: datetime,
                interval: str = "5minute") -> pd.DataFrame:
        """OHLCV with a tz-aware IST 'date' column, oldest first."""

    @abstractmethod
    def ltp(self, symbols: list[str]) -> dict[str, float]:
        """Last traded price per symbol."""

    def names(self) -> dict[str, str]:
        """Optional symbol -> company name map (used for news search)."""
        return {}


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    df = df[CANDLE_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"])
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize(IST)
    else:
        df["date"] = df["date"].dt.tz_convert(IST)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df.sort_values("date").reset_index(drop=True)
