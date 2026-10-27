"""Orchestrator: News runs from t=0 while candles download; then Chart + Indicator
run in parallel with it; the Master Agent ranks once all three report."""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import config
import market_data
from agents import chart_agent, indicator_agent, master_agent, news_agent
from brokers.base import IST
from strategy import CUTOFF_MIN, prepare
from universe import load_universe

log = logging.getLogger("pipeline")


def run_scan(broker, progress=None) -> dict:
    t0 = time.time()
    progress = progress or (lambda *a: None)
    stocks = [s for s in load_universe() if broker.has(s.symbol)]
    names = broker.names()
    for s in stocks:
        if s.name == s.symbol and s.symbol in names:
            s.name = names[s.symbol]

    with ThreadPoolExecutor(max_workers=3) as agents:
        news_f = agents.submit(news_agent.run, stocks, progress)

        candles = market_data.fetch_all(broker, stocks, progress)
        name_of = {s.symbol: s.name for s in stocks}
        prepared = {}
        for sym, df in candles.items():
            p = prepare(sym, name_of[sym], df)
            if p and p.a["close"][-1] >= config.MIN_PRICE and p.avg_turnover_cr >= config.MIN_AVG_TURNOVER_CR:
                prepared[sym] = p
        progress("Analysing charts and indicators", 0, len(prepared))

        chart_f = agents.submit(chart_agent.run, prepared)
        ind_f = agents.submit(indicator_agent.run, prepared)
        chart, ind = chart_f.result(), ind_f.result()
        progress("Waiting for news", 0, 1)
        news = news_f.result()

    progress("Ranking", 0, 1)
    ranked = master_agent.run(prepared, chart, ind, news)

    as_of = max((p.df["date"].iloc[-1] for p in prepared.values()), default=None)
    note = None
    if as_of is not None:
        if as_of.date() != datetime.now(IST).date():
            note = "Market is closed. Levels are from the last session and are for review only."
        elif as_of.hour * 60 + as_of.minute > CUTOFF_MIN:
            note = f"Past {config.ENTRY_CUTOFF}. Little time left for new intraday entries."
        elif len(prepared) and not chart:
            note = "Too early: picks start once the opening range is set (about 9:35)."

    return {
        "generated_at": datetime.now(IST).isoformat(),
        "data_as_of": as_of.isoformat() if as_of is not None else None,
        "broker": broker.name, "note": note,
        "scanned": len(stocks), "eligible": len(prepared), "signals": len(ranked),
        "news_scored": bool(config.ANTHROPIC_API_KEY),
        "seconds": round(time.time() - t0, 1),
        "top": ranked[:config.TOP_N], "watchlist": ranked[config.TOP_N:config.TOP_N + 5],
    }
