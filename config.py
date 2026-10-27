"""Central settings. Override any value with an environment variable or a .env file."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _f(name, default):
    return float(os.getenv(name, default))


def _i(name, default):
    return int(os.getenv(name, default))


# --- Broker -----------------------------------------------------------------
BROKER = os.getenv("BROKER", "mock").lower()          # "kite", "yahoo" (free, no login) or "mock"
KITE_API_KEY = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET = os.getenv("KITE_API_SECRET", "")
KITE_ACCESS_TOKEN_FILE = DATA_DIR / "kite_access_token.txt"
KITE_RATE_LIMIT_PER_SEC = _f("KITE_RATE_LIMIT_PER_SEC", 2.8)   # historical API allows 3/sec
MOCK_BARS_TODAY = _i("MOCK_BARS_TODAY", 30)                     # mock "now" = 30 bars into session

# --- Universe ---------------------------------------------------------------
UNIVERSE_FILE = DATA_DIR / "nifty250.csv"       # NSE index constituents CSV (Symbol column)
LOW_PRICE_UNIVERSE_FILE = DATA_DIR / "nifty500.csv"   # wider list for the low-price tab
MIN_PRICE = _f("MIN_PRICE", 50)
MIN_AVG_TURNOVER_CR = _f("MIN_AVG_TURNOVER_CR", 20)   # avg daily turnover, Rs crore

# --- Data -------------------------------------------------------------------
INTERVAL = "5minute"
BAR_MINUTES = 5
HISTORY_DAYS = _i("HISTORY_DAYS", 35)          # calendar days of 5-min history (live + backtest)
MAX_WORKERS = _i("MAX_WORKERS", 8)

# --- Strategy ---------------------------------------------------------------
ORB_MINUTES = _i("ORB_MINUTES", 15)            # opening range
RISK_REWARD = _f("RISK_REWARD", 2.0)
SL_ATR_MIN = _f("SL_ATR_MIN", 0.75)
SL_ATR_MAX = _f("SL_ATR_MAX", 1.5)
MIN_RISK_PCT = _f("MIN_RISK_PCT", 0.3)         # stop at least 0.3% away
TRIGGER_BARS = _i("TRIGGER_BARS", 3)           # entry valid for 3 bars (15 min)
ENTRY_CUTOFF = os.getenv("ENTRY_CUTOFF", "14:30")
CHART_MIN = _f("CHART_MIN", 0.35)
IND_MIN = _f("IND_MIN", 0.60)
TICK = 0.05

# --- Ranking ----------------------------------------------------------------
TOP_N = _i("TOP_N", 5)
W_CHART = _f("W_CHART", 0.4)
W_IND = _f("W_IND", 0.4)
W_NEWS = _f("W_NEWS", 0.2)
MIN_BACKTEST_TRADES = _i("MIN_BACKTEST_TRADES", 5)

# --- News (Claude) ----------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
NEWS_ENABLED = os.getenv("NEWS_ENABLED", "1") == "1"
NEWS_BATCH_SIZE = _i("NEWS_BATCH_SIZE", 15)
NEWS_MAX_HEADLINES = _i("NEWS_MAX_HEADLINES", 6)
NEWS_LOOKBACK_HOURS = _i("NEWS_LOOKBACK_HOURS", 36)

# --- Server -----------------------------------------------------------------
APP_USER = os.getenv("APP_USER", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")   # set both to require a login
AUTO_SCAN_MINUTES = _i("AUTO_SCAN_MINUTES", 0) # 0 = only scan on demand
