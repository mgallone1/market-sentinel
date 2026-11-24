"""Provider Bybit (REST v5 pubblica, urllib): kline linear, funding history, open interest."""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

from quant.core import interval_to_hours
from quant.data.cache import cached_monthly, drop_forming

log = logging.getLogger(__name__)
BASE = "https://api.bybit.com"
INTERVAL_MAP = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
OI_MAP = {"1m": "5min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1d"}


def _http_get_json(path: str, params: dict, timeout: float = 20.0) -> dict:
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "quant-research"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    if data.get("retCode", 0) != 0:
        raise RuntimeError(f"bybit error {data.get('retCode')}: {data.get('retMsg')}")
    return data


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.value // 10**6)


def fetch_klines(symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    cur_end, s_ms, e_ms = _ms(end), _ms(start), _ms(end)
    while True:
        res = _http_get_json("/v5/market/kline", {"category": "linear", "symbol": symbol,
                             "interval": INTERVAL_MAP[interval], "end": cur_end, "limit": 1000})["result"]
        chunk = res.get("list") or []
        if not chunk:
            break
        rows.extend(chunk)
        oldest = min(int(r[0]) for r in chunk)
        if oldest <= s_ms or len(chunk) < 1000:
            break
        cur_end = oldest - 1
    rows = [r for r in rows if s_ms <= int(r[0]) <= e_ms]
    if not rows:
        return pd.DataFrame()
    a = np.array([[float(x) for x in r[:6]] for r in rows])
    df = pd.DataFrame(a[:, 1:6], columns=["open", "high", "low", "close", "volume"],
                      index=pd.DatetimeIndex(pd.to_datetime(a[:, 0].astype("int64"), unit="ms", utc=True)).as_unit("ns"))
    df.index.name = "ts"
    return df[~df.index.duplicated(keep="last")].sort_index()


def fetch_funding(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    rows, cur_end, s_ms = [], _ms(end), _ms(start)
    while True:
        res = _http_get_json("/v5/market/funding/history", {"category": "linear", "symbol": symbol,
                             "endTime": cur_end, "limit": 200})["result"]
        chunk = res.get("list") or []
        if not chunk:
            break
        rows.extend(chunk)
        oldest = min(int(r["fundingRateTimestamp"]) for r in chunk)
        if oldest <= s_ms or len(chunk) < 200:
            break
        cur_end = oldest - 1
    rows = [r for r in rows if s_ms <= int(r["fundingRateTimestamp"]) <= _ms(end)]
    if not rows:
        return pd.Series(dtype="float64")
    idx = pd.DatetimeIndex(pd.to_datetime([int(r["fundingRateTimestamp"]) for r in rows], unit="ms", utc=True)).as_unit("ns")
    return pd.Series([float(r["fundingRate"]) for r in rows], index=idx).sort_index()


def fetch_open_interest(symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    rows, cur_end, s_ms = [], _ms(end), _ms(start)
    while True:
        res = _http_get_json("/v5/market/open-interest", {"category": "linear", "symbol": symbol,
                             "intervalTime": OI_MAP[interval], "endTime": cur_end, "limit": 200})["result"]
        chunk = res.get("list") or []
        if not chunk:
            break
        rows.extend(chunk)
        oldest = min(int(r["timestamp"]) for r in chunk)
        if oldest <= s_ms or len(chunk) < 200:
            break
        cur_end = oldest - 1
    rows = [r for r in rows if s_ms <= int(r["timestamp"]) <= _ms(end)]
    if not rows:
        return pd.Series(dtype="float64")
    idx = pd.DatetimeIndex(pd.to_datetime([int(r["timestamp"]) for r in rows], unit="ms", utc=True)).as_unit("ns")
    s = pd.Series([float(r["openInterest"]) for r in rows], index=idx).sort_index()
    return s[~s.index.duplicated(keep="last")]


def _fetch_range(symbol: str, interval: str, t0: pd.Timestamp, t1: pd.Timestamp, include_oi: bool) -> pd.DataFrame:
    from quant.data.binance_vision import attach_funding, attach_oi
    bars = fetch_klines(symbol, interval, t0, t1)
    if bars.empty:
        return bars
    bars = attach_funding(bars, fetch_funding(symbol, t0, t1), interval)
    if include_oi:
        bars = attach_oi(bars, fetch_open_interest(symbol, interval, t0, t1), interval)
    return bars


class BybitProvider:
    name = "bybit"

    def get_bars(self, symbol: str, interval: str, start, end, include_oi: bool = False,
                 use_cache: bool = True, now: pd.Timestamp | None = None) -> pd.DataFrame:
        if interval not in INTERVAL_MAP:
            raise ValueError(f"intervallo non supportato: {interval}")
        now = now or pd.Timestamp.now(tz="UTC")
        df = cached_monthly("bybit", symbol, interval, start, end,
                            lambda m0, m1: _fetch_range(symbol, interval, m0, min(m1 - pd.Timedelta(milliseconds=1), now), include_oi),
                            use_cache=use_cache, tag="oi" if include_oi else "", now=now)
        if df.empty:
            return df
        df = drop_forming(df, interval, now)
        df.index.name = "ts"
        return df


def get_bars(symbol: str, interval: str, start, end, **kw) -> pd.DataFrame:
    return BybitProvider().get_bars(symbol, interval, start, end, **kw)
