"""Indicator Agent: VWAP, RSI, MACD, Supertrend, ATR -> bias plus Entry / Target / Stop-loss."""
import numpy as np

from strategy import ind_eval, levels


def run(prepared: dict) -> dict:
    out = {}
    for sym, p in prepared.items():
        res = ind_eval(p, p.last)
        direction = int(np.sign(res["score"]))
        if direction:
            res["levels"] = levels(p, p.last, direction)
        out[sym] = res
    return out
