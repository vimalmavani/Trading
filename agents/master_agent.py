"""Master Agent: merges the three agents, backtests the candidates, ranks the Top N."""
import numpy as np

import config
from agents.news_agent import NEUTRAL
from strategy import backtest, gate

NO_HISTORY_PRIOR = 0.35   # assumed win rate when the backtest has too few trades


def run(prepared: dict, chart: dict, ind: dict, news: dict) -> list[dict]:
    picks = []
    for sym, p in prepared.items():
        ch, ix = chart.get(sym), ind.get(sym)
        if not ch or not ix:
            continue
        direction = gate(ch, ix)
        if not direction or "levels" not in ix:
            continue
        nw = news.get(sym, NEUTRAL)
        news_aligned = nw["score"] * direction
        combined = (config.W_CHART * abs(ch["score"]) + config.W_IND * abs(ix["score"])
                    + config.W_NEWS * news_aligned)
        confidence = float(np.clip(combined / (config.W_CHART + config.W_IND + config.W_NEWS), 0, 1))

        bt = backtest(p, direction)
        enough = bt["trades"] >= config.MIN_BACKTEST_TRADES
        hist = bt["win_rate"] if enough else NO_HISTORY_PRIOR
        rank = 0.7 * confidence + 0.3 * hist

        reasons = list(ch["flags"])
        reasons.append(f"Price {'above' if ix['score'] > 0 else 'below'} VWAP {ix['vwap']}, "
                       f"Supertrend {ix['supertrend_dir']}, RSI {ix['rsi']}")
        if nw["score"] * direction < -0.3:
            reasons.append("Warning: news leans against this trade")
        elif nw["score"] * direction > 0.3:
            reasons.append("News supports the move")

        last = p.df.iloc[-1]
        picks.append({
            "symbol": sym, "name": p.name,
            "direction": "LONG" if direction > 0 else "SHORT",
            "ltp": round(float(last["close"]), 2),
            **ix["levels"], "risk_reward": config.RISK_REWARD,
            "confidence": round(confidence * 100),
            "backtest": {**bt, "reliable": enough},
            "rank_score": round(rank, 4),
            "signal_time": last["date"].isoformat(),
            "valid_bars": config.TRIGGER_BARS,
            "chart": ch, "indicators": {k: v for k, v in ix.items() if k != "levels"},
            "news": nw, "reasons": reasons,
            "avg_turnover_cr": round(p.avg_turnover_cr, 1),
        })
    picks.sort(key=lambda x: x["rank_score"], reverse=True)
    return picks
