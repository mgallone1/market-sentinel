"""Provider Yahoo Finance (yfinance): azioni, ETF, indici, crypto-USD."""
from __future__ import annotations

import logging
import warnings

import pandas as pd

from quant.core import interval_to_hours
from quant.data.cache import drop_forming

log = logging.getLogger(__name__)
MAX_DAYS = {"1m": 7, "5m": 59, "15m": 59, "30m": 59, "1h": 729, "4h": 729}


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def normalize(raw: pd.DataFrame, interval: str, now: pd.Timestamp | None = None) -> pd.DataFrame:
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].astype("float64").dropna(subset=["open", "close"])
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    df.index = idx.as_unit("ns")
    df.index.name = "ts"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    # coerenza OHLC (arrotondamenti Yahoo)
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"] = df[["low", "open", "close"]].min(axis=1)
    now = now or pd.Timestamp.now(tz="UTC")
    if interval == "1d":
        return df[df.index.normalize() < now.normalize()]
    return drop_forming(df, interval, now)


def get_bars(symbol: str, interval: str, start, end, now: pd.Timestamp | None = None) -> pd.DataFrame:
    import yfinance as yf
    now = now or pd.Timestamp.now(tz="UTC")
    start, end = _utc(start), _utc(end)
    lim = MAX_DAYS.get(interval)
    if lim is not None and start < now - pd.Timedelta(days=lim):
        new = (now - pd.Timedelta(days=lim)).normalize() + pd.Timedelta(days=1)
        warnings.warn(f"yahoo: intervallo {interval} limitato a {lim} giorni; start clippato a {new:%Y-%m-%d}")
        log.warning("yahoo start clippato a %s", new)
        start = new
    yf_int = "1h" if interval == "4h" else interval
    raw = yf.download(symbol, start=start.tz_localize(None), end=(end + pd.Timedelta(days=1)).tz_localize(None),
                      interval=yf_int, auto_adjust=True, progress=False, multi_level_index=False)
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = normalize(raw, yf_int, now)
    if interval == "4h" and not df.empty:
        df = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                    "volume": "sum"}).dropna(subset=["open"])
        df = drop_forming(df, "4h", now)
    return df.loc[(df.index >= start) & (df.index <= end)]
