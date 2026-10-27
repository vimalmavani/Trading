"""Chart Agent: price action, volume, trend and breakout setups."""
from strategy import chart_eval


def run(prepared: dict) -> dict:
    out = {}
    for sym, p in prepared.items():
        res = chart_eval(p, p.today, p.last)
        if res:
            out[sym] = res
    return out
