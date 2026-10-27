"""Shared signal logic. The live agents and the backtest call the same functions,
so the backtest hit rate measures exactly the rules that produce today's picks."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config
from indicators import add_indicators

ORB_BARS = max(1, config.ORB_MINUTES // config.BAR_MINUTES)
_h, _m = map(int, config.ENTRY_CUTOFF.split(":"))
CUTOFF_MIN = _h * 60 + _m


def rtick(x: float) -> float:
    return round(round(x / config.TICK) * config.TICK, 2)


@dataclass
class Prepared:
    symbol: str
    name: str
    df: pd.DataFrame
    a: dict = field(repr=False)          # numpy arrays
    starts: list = field(repr=False)
    ends: list = field(repr=False)
    cumvol: list = field(repr=False)
    avg_turnover_cr: float = 0.0

    @property
    def last(self) -> int:
        return len(self.df) - 1

    @property
    def today(self) -> int:
        return len(self.starts) - 1


def prepare(symbol: str, name: str, df: pd.DataFrame) -> Prepared | None:
    if df is None or len(df) < 60:
        return None
    df = add_indicators(df)
    days = df["date"].dt.date.values
    cut = list(np.flatnonzero(days[1:] != days[:-1]) + 1)
    starts, ends = [0] + cut, cut + [len(df)]
    a = {c: df[c].to_numpy(dtype=float) for c in
         ["open", "high", "low", "close", "volume", "vwap", "rsi", "macd_hist",
          "atr", "st", "ema9", "ema21"]}
    a["st_dir"] = df["st_dir"].to_numpy()
    a["tmin"] = (df["date"].dt.hour * 60 + df["date"].dt.minute).to_numpy()
    cumvol = [np.cumsum(a["volume"][s:e]) for s, e in zip(starts, ends)]
    full = [(s, e) for s, e in zip(starts[:-1], ends[:-1])][-10:]
    turnover = [float((a["close"][s:e] * a["volume"][s:e]).sum()) / 1e7 for s, e in full]
    return Prepared(symbol, name, df, a, starts, ends, cumvol,
                    float(np.mean(turnover)) if turnover else 0.0)


# --------------------------------------------------------------------------- chart
def chart_eval(p: Prepared, d: int, i: int) -> dict | None:
    """Price action, volume and pattern read at bar i of session d. Score in [-1, 1]."""
    a, s = p.a, p.starts[d]
    k = i - s
    if d == 0 or k < ORB_BARS:
        return None
    ps, pe = p.starts[d - 1], p.ends[d - 1]
    pdh, pdl, pdc = a["high"][ps:pe].max(), a["low"][ps:pe].min(), a["close"][pe - 1]
    orh, orl = a["high"][s:s + ORB_BARS].max(), a["low"][s:s + ORB_BARS].min()
    price = a["close"][i]
    dh, dl = a["high"][s:i + 1].max(), a["low"][s:i + 1].min()
    change = (price / pdc - 1) * 100
    gap = (a["open"][s] / pdc - 1) * 100

    prior = [p.cumvol[j][k] for j in range(max(0, d - 10), d) if len(p.cumvol[j]) > k]
    base = float(np.mean(prior)) if prior else 0.0
    rel_vol = float(p.cumvol[d][k] / base) if base > 0 else 1.0

    orb = 1 if price > orh else -1 if price < orl else 0
    pdb = 1 if price > pdh else -1 if price < pdl else 0
    up = a["ema9"][i] > a["ema21"][i]
    trend = 1 if (up and price > a["ema9"][i]) else -1 if (not up and price < a["ema9"][i]) else 0
    mom = float(np.clip(change / 2, -1, 1))
    pos = (price - dl) / (dh - dl) if dh > dl else 0.5
    raw = 0.30 * orb + 0.20 * pdb + 0.20 * trend + 0.15 * mom + 0.15 * (pos - 0.5) * 2
    vol_factor = float(np.clip((rel_vol - 0.5) / 1.5, 0, 1))
    score = float(np.clip(raw * (0.6 + 0.4 * vol_factor), -1, 1))

    flags = []
    if orb:
        flags.append("Opening-range breakout" if orb > 0 else "Opening-range breakdown")
    if pdb:
        flags.append("Above previous day high" if pdb > 0 else "Below previous day low")
    if trend:
        flags.append("EMA 9/21 uptrend" if trend > 0 else "EMA 9/21 downtrend")
    if rel_vol >= 1.5:
        flags.append(f"Volume {rel_vol:.1f}x normal")
    if abs(gap) >= 1:
        flags.append(f"Gap {'up' if gap > 0 else 'down'} {abs(gap):.1f}%")
    return {"score": round(score, 3), "change_pct": round(change, 2), "gap_pct": round(gap, 2),
            "rel_vol": round(rel_vol, 2), "orh": rtick(orh), "orl": rtick(orl),
            "pdh": rtick(pdh), "pdl": rtick(pdl), "flags": flags}


# ---------------------------------------------------------------------- indicators
def ind_eval(p: Prepared, i: int) -> dict:
    a = p.a
    price, r = a["close"][i], a["rsi"][i]
    v_vwap = 1 if price > a["vwap"][i] else -1
    v_st = int(a["st_dir"][i])
    v_macd = 1 if a["macd_hist"][i] > 0 else -1
    if 55 <= r <= 72:
        v_rsi = 1
    elif 28 <= r <= 45:
        v_rsi = -1
    elif r > 75:
        v_rsi = -0.5          # stretched, fade risk for longs
    elif r < 25:
        v_rsi = 0.5
    else:
        v_rsi = 0
    score = 0.3 * v_vwap + 0.3 * v_st + 0.2 * v_macd + 0.2 * v_rsi
    return {"score": round(float(score), 3), "rsi": round(float(r), 1),
            "vwap": rtick(a["vwap"][i]), "macd_hist": round(float(a["macd_hist"][i]), 3),
            "supertrend": rtick(a["st"][i]), "supertrend_dir": "up" if v_st > 0 else "down",
            "atr": round(float(a["atr"][i]), 2)}


def levels(p: Prepared, i: int, direction: int) -> dict:
    """Entry on a break of the signal candle; stop at Supertrend, clamped by ATR."""
    a = p.a
    atr_v = a["atr"][i]
    if direction > 0:
        entry = a["high"][i] + config.TICK
        st_gap = entry - a["st"][i] if a["st_dir"][i] > 0 else atr_v
    else:
        entry = a["low"][i] - config.TICK
        st_gap = a["st"][i] - entry if a["st_dir"][i] < 0 else atr_v
    risk = float(np.clip(st_gap, config.SL_ATR_MIN * atr_v, config.SL_ATR_MAX * atr_v))
    risk = max(risk, entry * config.MIN_RISK_PCT / 100)
    entry = rtick(entry)
    return {"entry": entry, "stop_loss": rtick(entry - direction * risk),
            "target": rtick(entry + direction * config.RISK_REWARD * risk),
            "risk_per_share": round(risk, 2)}


def gate(chart: dict | None, ind: dict) -> int:
    """Direction (+1 long, -1 short) when chart and indicators agree strongly enough."""
    if not chart:
        return 0
    cd, idr = np.sign(chart["score"]), np.sign(ind["score"])
    if cd == 0 or cd != idr:
        return 0
    if abs(chart["score"]) < config.CHART_MIN or abs(ind["score"]) < config.IND_MIN:
        return 0
    return int(cd)


# ------------------------------------------------------------------------ backtest
def simulate(p: Prepared, i: int, end: int, lv: dict, direction: int) -> dict | None:
    a = p.a
    entry, sl, tgt = lv["entry"], lv["stop_loss"], lv["target"]
    risk = abs(entry - sl)
    j_trig = None
    for j in range(i + 1, min(i + 1 + config.TRIGGER_BARS, end)):
        if (direction > 0 and a["high"][j] >= entry) or (direction < 0 and a["low"][j] <= entry):
            j_trig = j
            break
    if j_trig is None:
        return None
    for j in range(j_trig, end):
        hit_sl = a["low"][j] <= sl if direction > 0 else a["high"][j] >= sl
        hit_tg = a["high"][j] >= tgt if direction > 0 else a["low"][j] <= tgt
        if hit_sl:                       # same-bar ambiguity counted as a loss
            return {"result": "loss", "r": -1.0}
        if hit_tg:
            return {"result": "win", "r": config.RISK_REWARD}
    exit_px = a["close"][end - 1]
    return {"result": "time", "r": round((exit_px - entry) * direction / risk, 2)}


def backtest(p: Prepared, direction: int) -> dict:
    """First same-direction signal per past session, traded with the same rules."""
    trades = []
    for d in range(1, p.today):
        s, e = p.starts[d], p.ends[d]
        for i in range(s + ORB_BARS, e - 3):
            if p.a["tmin"][i] > CUTOFF_MIN:
                break
            ch = chart_eval(p, d, i)
            ind = ind_eval(p, i)
            if gate(ch, ind) != direction:
                continue
            out = simulate(p, i, e, levels(p, i, direction), direction)
            if out:
                trades.append(out)
            break
    n = len(trades)
    wins = sum(t["result"] == "win" for t in trades)
    return {"trades": n, "wins": wins,
            "losses": sum(t["result"] == "loss" for t in trades),
            "win_rate": round(wins / n, 3) if n else None,
            "avg_r": round(float(np.mean([t["r"] for t in trades])), 2) if n else None,
            "sessions": p.today}
