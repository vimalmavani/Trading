"""Technical indicators on 5-minute candles. VWAP resets each session; the rest run continuously."""
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    # the overnight gap is not intraday range; let the first bar of each session use high-low only
    pc = df["close"].shift().where(df["date"].dt.date == df["date"].dt.date.shift())
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = df["date"].dt.date
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vol = df["volume"].groupby(day).cumsum().replace(0, np.nan)
    return (pv / vol).fillna(tp)


def supertrend(df: pd.DataFrame, atr_s: pd.Series, mult: float = 3.0):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    a = atr_s.values
    hl2 = (h + l) / 2
    bu, bl = hl2 + mult * a, hl2 - mult * a
    fu, fl = bu.copy(), bl.copy()
    n = len(c)
    direction = np.ones(n, dtype=int)
    line = np.full(n, np.nan)
    if n:
        line[0] = fl[0]
    for i in range(1, n):
        fu[i] = bu[i] if (bu[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = bl[i] if (bl[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        if direction[i - 1] == 1:
            direction[i] = -1 if c[i] < fl[i] else 1
        else:
            direction[i] = 1 if c[i] > fu[i] else -1
        line[i] = fl[i] if direction[i] == 1 else fu[i]
    return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["vwap"] = vwap(df)
    df["rsi"] = rsi(df["close"])
    macd = ema(df["close"], 12) - ema(df["close"], 26)
    df["macd_hist"] = macd - ema(macd, 9)
    df["atr"] = atr(df)
    df["st"], df["st_dir"] = supertrend(df, atr(df, 10), 3.0)
    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    return df
