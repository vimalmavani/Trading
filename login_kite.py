"""Daily Kite login (tokens expire every morning). Or use the 'Connect Kite' button in the web app."""
import urllib.parse

from brokers.kite import make_client, save_session

kite = make_client()
print("1. Open and log in:\n  ", kite.login_url())
raw = input("2. Paste the full redirect URL (or just the request_token): ").strip()
token = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query).get("request_token", [raw])[0]
save_session(token)
print("Saved. Kite session is ready for today.")
