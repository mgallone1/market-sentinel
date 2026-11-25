"""Dati di mercato del laboratorio: live (Bybit -> Binance -> Yahoo, solo barre chiuse) e sintetico per test."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import zlib
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

from quant.core import interval_to_hours
from quant.data.cache import drop_forming

OHLCV = ["open", "high", "low", "close", "volume"]
BINANCE_HOSTS = ("https://data-api.binance.vision", "https://api.binance.com")


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _closed(df: pd.DataFrame, interval: str, now) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV)
    return drop_forming(df[df.index <= _utc(now)], interval, _utc(now))


def _get_json(url: str, timeout: float = 20.0):
    req = urllib.request.Request(url, headers={"User-Agent": "quant-lab"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def binance_klines(symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    last_err = None
    for host in BINANCE_HOSTS:
        try:
            rows, cur = [], int(start.value // 10**6)
            e_ms = int(end.value // 10**6)
            while cur < e_ms:
                q = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "startTime": cur,
                                            "endTime": e_ms, "limit": 1000})
                chunk = _get_json(f"{host}/api/v3/klines?{q}")
                if not chunk:
                    break
                rows.extend(chunk)
                cur = int(chunk[-1][0]) + 1
                if len(chunk) < 1000:
                    break
            if not rows:
                return pd.DataFrame(columns=OHLCV)
            a = np.array([[float(x) for x in r[:6]] for r in rows])
            idx = pd.DatetimeIndex(pd.to_datetime(a[:, 0].astype("int64"), unit="ms", utc=True)).as_unit("ns")
            df = pd.DataFrame(a[:, 1:6], columns=OHLCV, index=idx)
            df.index.name = "ts"
            return df[~df.index.duplicated(keep="last")].sort_index()
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"binance klines non disponibili: {last_err}")


def binance_funding(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    q = urllib.parse.urlencode({"symbol": symbol, "startTime": int(start.value // 10**6),
                                "endTime": int(end.value // 10**6), "limit": 1000})
    rows = _get_json(f"https://fapi.binance.com/fapi/v1/fundingRate?{q}")
    if not rows:
        return pd.Series(dtype="float64")
    idx = pd.DatetimeIndex(pd.to_datetime([int(r["fundingTime"]) for r in rows], unit="ms", utc=True)).as_unit("ns")
    return pd.Series([float(r["fundingRate"]) for r in rows], index=idx).sort_index()


class LiveMarketData:
    """MarketData reale (sola lettura). Cache in memoria con TTL di 5 minuti."""

    def __init__(self, ttl: float = 300.0):
        self.ttl = ttl
        self._cache: Dict[Tuple, Tuple[float, Any]] = {}

    def _cached(self, key, fn):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self.ttl:
            return hit[1]
        val = fn()
        self._cache[key] = (time.time(), val)
        return val

    # --- sorgenti ---
    def _crypto(self, source: str, symbol: str, interval: str, start, end) -> pd.DataFrame:
        if source == "bybit":
            try:
                from quant.data import bybit
                df = bybit.fetch_klines(symbol, interval, start, end)
                if not df.empty:
                    return df
            except Exception:  # noqa: BLE001 - geo-block ecc.: fallback Binance
                pass
        return binance_klines(symbol, interval, start, end)

    def _yahoo(self, symbol: str, interval: str, start, end, now) -> pd.DataFrame:
        from quant.data import yahoo
        return yahoo.get_bars(symbol, interval, start, end, now=now)

    def _spread(self, interval: str, start, end, now) -> pd.DataFrame:
        if interval != "1d":
            raise ValueError("sorgente 'spread' supporta solo 1d")
        b, w = self._yahoo("BZ=F", "1d", start, end, now), self._yahoo("CL=F", "1d", start, end, now)
        j = b.join(w, how="inner", lsuffix="_b", rsuffix="_w")
        out = pd.DataFrame({c: j[f"{c}_b"] - j[f"{c}_w"] for c in ("open", "high", "low", "close")})
        out["volume"] = 0.0
        out["high"] = out[["open", "high", "low", "close"]].max(axis=1)
        out["low"] = out[["open", "high", "low", "close"]].min(axis=1)
        out.index.name = "ts"
        return out

    def bars(self, source: str, symbol: str, interval: str, lookback_days: int, now_utc) -> pd.DataFrame:
        now = _utc(now_utc)
        start = (now - pd.Timedelta(days=lookback_days)).floor("D")

        def fetch():
            if source in ("bybit", "binance_proxy"):
                return self._crypto(source, symbol, interval, start, now)
            if source == "yahoo":
                return self._yahoo(symbol, interval, start, now, now)
            if source == "spread":
                return self._spread(interval, start, now, now)
            raise ValueError(f"sorgente sconosciuta: {source}")

        df = self._cached((source, symbol, interval, lookback_days, start), fetch)
        return _closed(df, interval, now)

    def last_price(self, source: str, symbol: str, now_utc) -> float:
        if source in ("bybit", "binance_proxy"):
            df = self.bars(source, symbol, "1m", 1, now_utc)
            if df.empty:
                df = self.bars(source, symbol, "1h", 3, now_utc)
        elif source == "yahoo":
            df = self.bars(source, symbol, "5m", 5, now_utc)
            if df.empty:
                df = self.bars(source, symbol, "1d", 10, now_utc)
        else:
            df = self.bars(source, symbol, "1d", 10, now_utc)
        if df.empty:
            raise RuntimeError(f"nessun prezzo per {source}:{symbol}")
        return float(df["close"].iloc[-1])

    def funding(self, symbol: str, lookback_days: int, now_utc) -> pd.Series:
        now = _utc(now_utc)
        start = (now - pd.Timedelta(days=lookback_days)).floor("D")

        def fetch():
            try:
                from quant.data import bybit
                s = bybit.fetch_funding(symbol, start, now)
                if len(s):
                    return s
            except Exception:  # noqa: BLE001
                pass
            return binance_funding(symbol, start, now)

        s = self._cached(("funding", symbol, lookback_days, start), fetch)
        return s[s.index <= now]


class SyntheticMarketData:
    """Percorsi orari deterministici (random walk) per ogni (source, symbol); funding ogni 8h (00/08/16 UTC)."""

    def __init__(self, seed: int = 0, base: float = 100.0, hourly_vol: float = 0.004, hourly_drift: float = 0.0,
                 funding_rate: float = 0.0001, start="2023-01-01", years: int = 4,
                 base_prices: Dict[str, float] | None = None):
        self.seed, self.base, self.vol, self.drift = seed, base, hourly_vol, hourly_drift
        self.funding_rate = funding_rate
        self.base_prices = base_prices or {}
        self.t0 = _utc(start)
        self.n = 24 * 365 * years
        self._paths: Dict[Tuple[str, str], pd.DataFrame] = {}

    def _hourly(self, source: str, symbol: str) -> pd.DataFrame:
        k = (source, symbol)
        if k not in self._paths:
            rng = np.random.default_rng(self.seed * 1_000_003 + zlib.crc32(f"{source}:{symbol}".encode()))
            r = rng.normal(self.drift, self.vol, self.n)
            close = self.base_prices.get(symbol, self.base) * np.exp(np.cumsum(r))
            open_ = np.concatenate([[close[0]], close[:-1]])
            wick = np.abs(rng.normal(0, self.vol / 2, self.n))
            idx = pd.date_range(self.t0, periods=self.n, freq="1h", tz="UTC").as_unit("ns")
            self._paths[k] = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * (1 + wick),
                                           "low": np.minimum(open_, close) * (1 - wick), "close": close,
                                           "volume": 1000.0}, index=idx)
            self._paths[k].index.name = "ts"
        return self._paths[k]

    def bars(self, source: str, symbol: str, interval: str, lookback_days: int, now_utc) -> pd.DataFrame:
        now = _utc(now_utc)
        h = self._hourly(source, symbol)
        h = h[(h.index >= now - pd.Timedelta(days=lookback_days) - pd.Timedelta(days=1)) & (h.index <= now)]
        if interval != "1h":
            rule = f"{int(interval_to_hours(interval))}h" if interval_to_hours(interval) < 24 else "1D"
            h = h.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                      "volume": "sum"}).dropna(subset=["open"])
        h = _closed(h, interval, now)
        return h[h.index >= now - pd.Timedelta(days=lookback_days)]

    def last_price(self, source: str, symbol: str, now_utc) -> float:
        df = self.bars(source, symbol, "1h", 2, now_utc)
        if df.empty:
            raise RuntimeError("nessun prezzo sintetico")
        return float(df["close"].iloc[-1])

    def funding(self, symbol: str, lookback_days: int, now_utc) -> pd.Series:
        now = _utc(now_utc)
        idx = pd.date_range((now - pd.Timedelta(days=lookback_days)).ceil("8h"), now, freq="8h", tz="UTC")
        return pd.Series(self.funding_rate, index=idx.as_unit("ns"), dtype="float64")
