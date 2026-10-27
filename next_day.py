"""Next-day watchlist: stocks that closed strong today, with a plan to buy tomorrow above today's high.
Works on daily candles. The backtest replays the same rule on the past year of this stock, so the
win rate measures exactly the plan that is shown."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import config
from brokers.base import IST
from indicators import ema, rsi
from strategy import rtick
from universe import load_universe

log = logging.getLogger("next_day")

HISTORY_DAYS = 400          # calendar days of daily candles (about a year of sessions + warm-up)
MIN_BARS = 22
MIN_CLV = 0.6               # close in the top 40% of the day's range
MIN_CHANGE_PCT = 0.3
MIN_REL_VOL = 1.0           # stricter filters gave fewer picks with the same result over 250 stocks
RSI_LO, RSI_HI = 50, 75
RISK_ATR_MIN, RISK_ATR_MAX = 0.5, 1.0   # stop distance in daily ATRs (tighter stops tested worse)
NO_HISTORY_PRIOR = 0.35
MARKET_CLOSE_MIN = 15 * 60 + 30


def to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """One row per session. Accepts daily or intraday candles."""
    if df is None or df.empty:
        return pd.DataFrame()
    g = df.groupby(df["date"].dt.date)
    d = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                      "close": g["close"].last(), "volume": g["volume"].sum()})
    d.index = pd.to_datetime(d.index)
    return d


def add_daily_indicators(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    pc = d["close"].shift()
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d["ema20"], d["ema50"] = ema(d["close"], 20), ema(d["close"], 50)
    d["rsi"] = rsi(d["close"])
    d["avg_vol"] = d["volume"].shift().rolling(20, min_periods=5).mean()
    d["hi20"] = d["high"].shift().rolling(20, min_periods=5).max()
    d["change_pct"] = (d["close"] / pc - 1) * 100
    return d


def setup(d: pd.DataFrame, i: int):
    """Strong-close buy setup at session i. Returns (score, reasons) or None."""
    r = d.iloc[i]
    rng = r["high"] - r["low"]
    if rng <= 0 or not r["avg_vol"]:
        return None
    clv = (r["close"] - r["low"]) / rng
    rel_vol = r["volume"] / r["avg_vol"]
    if not (r["close"] > r["ema20"] > r["ema50"] and clv >= MIN_CLV and r["change_pct"] >= MIN_CHANGE_PCT
            and rel_vol >= MIN_REL_VOL and RSI_LO <= r["rsi"] <= RSI_HI):
        return None
    breakout = r["close"] > r["hi20"]
    score = (0.3 * clv + 0.25 * min(rel_vol / 3, 1) + 0.2 * min(r["change_pct"] / 4, 1)
             + 0.25 * (1 if breakout else 0))
    reasons = [f"Closed near the day's high ({clv * 100:.0f}% of the range)",
               f"Up {r['change_pct']:.1f}% on {rel_vol:.1f}x normal volume",
               "Uptrend: price above 20-day and 50-day averages",
               f"RSI {r['rsi']:.0f}: strong but not overbought"]
    if breakout:
        reasons.insert(0, "Closed above its 20-day high (breakout)")
    return float(score), reasons


def levels(d: pd.DataFrame, i: int) -> dict:
    r = d.iloc[i]
    entry = r["high"] + config.TICK
    risk = float(np.clip(entry - r["low"], RISK_ATR_MIN * r["atr"], RISK_ATR_MAX * r["atr"]))
    risk = max(risk, entry * config.MIN_RISK_PCT / 100)
    return {"entry": rtick(entry), "stop_loss": rtick(entry - risk),
            "target": rtick(entry + config.RISK_REWARD * risk),
            "skip_above": rtick(entry + risk),     # opening this far up means the move already happened
            "risk_per_share": round(risk, 2)}


def simulate(d: pd.DataFrame, j: int, lv: dict):
    """Next session j on daily candles. Same-day stop and target both touched counts as a loss."""
    r = d.iloc[j]
    if r["open"] > lv["skip_above"] or r["high"] < lv["entry"]:
        return None
    fill = max(lv["entry"], r["open"])
    risk = lv["risk_per_share"]
    if r["low"] <= lv["stop_loss"]:
        return {"result": "loss", "r": round((lv["stop_loss"] - fill) / risk, 2)}
    if r["high"] >= lv["target"]:
        return {"result": "win", "r": round((lv["target"] - fill) / risk, 2)}
    return {"result": "time", "r": round((r["close"] - fill) / risk, 2)}


def backtest(d: pd.DataFrame) -> dict:
    trades = []
    for i in range(MIN_BARS, len(d) - 1):
        if setup(d, i):
            out = simulate(d, i + 1, levels(d, i))
            if out:
                trades.append(out)
    n = len(trades)
    wins = sum(t["result"] == "win" for t in trades)
    return {"trades": n, "wins": wins, "losses": sum(t["result"] == "loss" for t in trades),
            "sum_r": round(float(sum(t["r"] for t in trades)), 2),
            "win_rate": round(wins / n, 3) if n else None,
            "avg_r": round(float(np.mean([t["r"] for t in trades])), 2) if n else None,
            "sessions": len(d)}


def analyse(symbol: str, name: str, raw: pd.DataFrame):
    """(pick or None, backtest, last close). The backtest is returned for every eligible stock, pick or not."""
    d = to_daily(raw)
    if len(d) < MIN_BARS:
        return None, None, None
    d = add_daily_indicators(d)
    last = d.iloc[-10:]
    turnover_cr = float((last["close"] * last["volume"]).mean()) / 1e7
    close = float(d["close"].iloc[-1])
    if close < config.MIN_PRICE or turnover_cr < config.MIN_AVG_TURNOVER_CR:
        return None, None, None
    i = len(d) - 1
    bt = backtest(d)
    hit = setup(d, i)
    if not hit:
        return None, bt, close
    score, reasons = hit
    enough = bt["trades"] >= config.MIN_BACKTEST_TRADES
    hist = bt["win_rate"] if enough else NO_HISTORY_PRIOR
    r = d.iloc[i]
    return {"symbol": symbol, "name": name, "direction": "LONG",
            "ltp": round(float(r["close"]), 2), **levels(d, i),
            "risk_reward": config.RISK_REWARD,
            "confidence": round(score * 100), "rank_score": round(0.6 * score + 0.4 * hist, 4),
            "backtest": {**bt, "reliable": enough},
            "today": {"date": d.index[i].date().isoformat(), "open": rtick(r["open"]), "high": rtick(r["high"]),
                      "low": rtick(r["low"]), "close": rtick(r["close"]),
                      "change_pct": round(float(r["change_pct"]), 2),
                      "rel_vol": round(float(r["volume"] / r["avg_vol"]), 2),
                      "rsi": round(float(r["rsi"]), 1), "atr": round(float(r["atr"]), 2)},
            "reasons": reasons, "avg_turnover_cr": round(turnover_cr, 1)}, bt, close


def scan(broker, universe_file=None) -> dict:
    """Analyse every stock once. summarize() then cuts lists from this, e.g. by price."""
    now = datetime.now(IST)
    stocks = [st for st in load_universe(universe_file) if broker.has(st.symbol)]
    names = broker.names()

    def one(st):
        try:
            raw = broker.candles(st.symbol, now - timedelta(days=HISTORY_DAYS), now, "day")
            pick, bt, close = analyse(st.symbol, names.get(st.symbol, st.name), raw)
            last = raw["date"].iloc[-1] if not raw.empty else None
            return {"pick": pick, "bt": bt, "close": close, "last": last}
        except Exception as e:   # one bad symbol must not stop the list
            log.warning("next-day %s failed: %s", st.symbol, e)
            return {"pick": None, "bt": None, "close": None, "last": None}

    with ThreadPoolExecutor(config.MAX_WORKERS) as pool:
        rows = list(pool.map(one, stocks))
    return {"generated_at": now, "broker": broker.name, "scanned": len(stocks), "rows": rows}


def summarize(scanned: dict, max_price: float = None) -> dict:
    now = datetime.now(IST)
    rows = [r for r in scanned["rows"] if r["close"] is not None
            and (max_price is None or r["close"] <= max_price)]
    picks = sorted((r["pick"] for r in rows if r["pick"]), key=lambda p: p["rank_score"], reverse=True)
    # how this rule has done across the same stocks, so a single list is never read as proof
    bts = [r["bt"] for r in rows if r["bt"]]
    n = sum(bt["trades"] for bt in bts)
    overall = {"stocks": len(bts), "trades": n, "wins": sum(bt["wins"] for bt in bts),
               "losses": sum(bt["losses"] for bt in bts),
               "avg_r": round(sum(bt["sum_r"] for bt in bts) / n, 2) if n else None}
    dates = [r["last"] for r in scanned["rows"] if r["last"] is not None]
    as_of = max(dates).date() if dates else None

    note = None
    if as_of == now.date() and now.weekday() < 5 and now.hour * 60 + now.minute < MARKET_CLOSE_MIN:
        note = "Market is still open, so today's candle is not final. Check this list again after 3:30 pm."
    return {"generated_at": scanned["generated_at"].isoformat(), "as_of": as_of.isoformat() if as_of else None,
            "broker": scanned["broker"], "note": note, "scanned": scanned["scanned"], "eligible": len(rows),
            "max_price": max_price, "signals": len(picks), "overall": overall, "risk_reward": config.RISK_REWARD,
            "top": picks[:config.TOP_N], "watchlist": picks[config.TOP_N:config.TOP_N + 10]}
