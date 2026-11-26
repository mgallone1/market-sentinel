"""Binance Vision USD-M futures `metrics` (5-minute open interest snapshots), cached per day.

Research proxy for Bybit open interest (Bybit public API is geo-blocked from the research container).
Columns: sum_open_interest (contracts), sum_open_interest_value (USD). Index: snapshot time (UTC).
"""
from __future__ import annotations

import io
import logging
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
BASE = "https://data.binance.vision/data/futures/um/daily/metrics"
CACHE = Path("data/cache/binance_metrics")


def _day(symbol: str, day: str) -> pd.DataFrame | None:
    p = CACHE / symbol / f"{day}.pkl.gz"
    if p.exists():
        return pd.read_pickle(p)
    url = f"{BASE}/{symbol}/{symbol}-metrics-{day}.zip"
    try:
        raw = urllib.request.urlopen(url, timeout=30).read()
    except Exception as e:  # noqa: BLE001  (missing day / network)
        log.debug("metrics %s %s: %s", symbol, day, e)
        return None
    z = zipfile.ZipFile(io.BytesIO(raw))
    df = pd.read_csv(z.open(z.namelist()[0]))
    df["create_time"] = pd.to_datetime(df["create_time"], utc=True)
    df = df.set_index("create_time")[["sum_open_interest", "sum_open_interest_value"]].astype(float)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(p)
    return df


def get_open_interest(symbol: str, start, end, workers: int = 8) -> pd.DataFrame:
    days = [d.strftime("%Y-%m-%d") for d in pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="D")]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        parts = [p for p in ex.map(lambda d: _day(symbol, d), days) if p is not None and len(p)]
    if not parts:
        return pd.DataFrame(columns=["sum_open_interest", "sum_open_interest_value"])
    df = pd.concat(parts).sort_index()
    return df[~df.index.duplicated(keep="last")]


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    syms = sys.argv[1].split(",")
    for s in syms:
        d = get_open_interest(s, sys.argv[2], sys.argv[3])
        print(s, len(d), d.index.min(), d.index.max(), flush=True)
