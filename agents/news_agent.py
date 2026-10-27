"""News Agent: pulls recent headlines (Google News RSS) and has Claude score sentiment.

Claude only reads headlines here; it never touches prices or levels."""
import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import config

log = logging.getLogger("news_agent")
NEUTRAL = {"sentiment": "neutral", "score": 0.0, "summary": "No recent news found.", "headlines": []}

SYSTEM = """You score short-term (same-day) sentiment for Indian NSE stocks from news headlines.
For each stock return: sentiment ("positive" | "negative" | "neutral"), score from -1.0 to 1.0
(strength of the likely intraday effect on price), and a one-sentence summary.
Ignore generic market commentary and old news. If headlines are irrelevant or mixed, use neutral near 0.
Reply with JSON only, no prose and no code fences:
{"SYMBOL": {"sentiment": "...", "score": 0.0, "summary": "..."}, ...}"""


def _headlines(symbol: str, name: str) -> list[dict]:
    q = f'"{name}" stock' if name and name != symbol else f"{symbol} NSE share"
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
           + "&hl=en-IN&gl=IN&ceid=IN:en")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        root = ET.fromstring(r.read())
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.NEWS_LOOKBACK_HOURS)
    items = []
    for it in root.iter("item"):
        try:
            when = parsedate_to_datetime(it.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        if when < cutoff:
            continue
        items.append({"title": it.findtext("title") or "", "link": it.findtext("link") or "",
                      "source": it.findtext("source") or "", "time": when.isoformat()})
    items.sort(key=lambda x: x["time"], reverse=True)
    return items[:config.NEWS_MAX_HEADLINES]


def _score_batch(client, batch: dict) -> dict:
    lines = []
    for sym, items in batch.items():
        lines.append(f"## {sym}")
        lines += [f"- {h['title']} ({h['source']}, {h['time'][:16]})" for h in items]
    msg = client.messages.create(model=config.CLAUDE_MODEL, max_tokens=2000, system=SYSTEM,
                                 messages=[{"role": "user", "content": "\n".join(lines)}])
    text = "".join(b.text for b in msg.content if b.type == "text")
    text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    return json.loads(text)


def run(stocks, progress=None) -> dict:
    if not config.NEWS_ENABLED:
        return {}
    news = {}
    with ThreadPoolExecutor(config.MAX_WORKERS) as pool:
        def safe(s):
            try:
                return s.symbol, _headlines(s.symbol, s.name)
            except Exception as e:
                log.debug("rss failed for %s: %s", s.symbol, e)
                return s.symbol, []
        for n, (sym, items) in enumerate(pool.map(safe, stocks), 1):
            news[sym] = items
            if progress and n % 10 == 0:
                progress("Reading news", n, len(stocks))

    out = {sym: {**NEUTRAL} for sym in news}
    with_news = {s: h for s, h in news.items() if h}
    for sym, h in with_news.items():
        out[sym]["headlines"] = h
        out[sym]["summary"] = "Headlines found; sentiment not scored."

    if not with_news or not config.ANTHROPIC_API_KEY:
        return out
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    except ImportError:
        log.warning("anthropic package not installed; news left unscored")
        return out

    syms = list(with_news)
    batches = [syms[i:i + config.NEWS_BATCH_SIZE] for i in range(0, len(syms), config.NEWS_BATCH_SIZE)]

    def score(b):
        try:
            return _score_batch(client, {s: with_news[s] for s in b})
        except Exception as e:
            log.warning("Claude scoring failed for a batch: %s", e)
            return {}

    with ThreadPoolExecutor(4) as pool:
        for res in pool.map(score, batches):
            for sym, v in res.items():
                if sym in out and isinstance(v, dict):
                    sc = float(max(-1.0, min(1.0, float(v.get("score", 0)))))
                    out[sym].update(sentiment=v.get("sentiment", "neutral"), score=sc,
                                    summary=v.get("summary", ""))
    if progress:
        progress("News scored", len(stocks), len(stocks))
    return out
