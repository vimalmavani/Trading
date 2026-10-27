"""Command-line scan: python run_scan.py"""
import json
import logging

from brokers.factory import get_broker
from pipeline import run_scan

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

if __name__ == "__main__":
    res = run_scan(get_broker(), lambda stage, n, total: None)
    print(f"\n{res['broker']} | data as of {res['data_as_of']} | {res['eligible']} eligible, "
          f"{res['signals']} signals, {res['seconds']}s")
    if res["note"]:
        print("Note:", res["note"])
    print(f"\n{'#':<3}{'Symbol':<12}{'Side':<7}{'LTP':>10}{'Entry':>10}{'Target':>10}{'Stop':>10}"
          f"{'Conf':>6}{'Hist win':>10}")
    for n, p in enumerate(res["top"], 1):
        bt = p["backtest"]
        hist = f"{bt['win_rate']*100:.0f}% /{bt['trades']}" if bt["win_rate"] is not None else "n/a"
        print(f"{n:<3}{p['symbol']:<12}{p['direction']:<7}{p['ltp']:>10}{p['entry']:>10}"
              f"{p['target']:>10}{p['stop_loss']:>10}{p['confidence']:>5}%{hist:>10}")
    with open("data/last_scan.json", "w") as fh:
        json.dump(res, fh, indent=2, default=str)
