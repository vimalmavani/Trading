"""Stock universe. Download the official list from niftyindices.com
(Nifty LargeMidcap 250 -> 'Index constituents' CSV) and save it as data/nifty250.csv."""
import csv
from dataclasses import dataclass

import config

# Used only if data/nifty250.csv is missing. Symbols not found at the broker are skipped.
FALLBACK = """ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV
BEL BHARTIARTL CIPLA COALINDIA DRREDDY EICHERMOT GRASIM HCLTECH HDFCBANK HDFCLIFE HEROMOTOCO
HINDALCO HINDUNILVR ICICIBANK INDUSINDBK INFY ITC JSWSTEEL KOTAKBANK LT M&M MARUTI NESTLEIND
NTPC ONGC POWERGRID RELIANCE SBILIFE SBIN SHRIRAMFIN SUNPHARMA TATACONSUM TATASTEEL TCS TECHM
TITAN TRENT ULTRACEMCO WIPRO DLF VEDL TATAPOWER PNB BANKBARODA CANBK IOC GAIL HAL""".split()


@dataclass
class Stock:
    symbol: str
    name: str


def load_universe(path=None) -> list[Stock]:
    path = path or config.UNIVERSE_FILE
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        out = []
        for r in rows:
            keys = {k.strip().lower(): v for k, v in r.items() if k}
            sym = (keys.get("symbol") or "").strip()
            if sym:
                out.append(Stock(sym, (keys.get("company name") or sym).strip()))
        if out:
            return out
    return [Stock(s, s) for s in FALLBACK]
