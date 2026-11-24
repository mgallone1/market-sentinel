"""Provider Binance Vision (dati bulk pubblici USD-M perp): klines + taker_buy_volume, funding, open interest."""
from __future__ import annotations

import io
import logging
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from quant.core import interval_to_hours
from quant.data.cache import cached_monthly, drop_forming

log = logging.getLogger(__name__)
BASE = "https://data.binance.vision/data/futures/um"
BASE_SPOT = "https://data.binance.vision/data/spot"
_KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
               "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def _fetch(url: str, timeout: float = 60.0) -> bytes | None:
    """Scarica url; None su 404."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _read_zip_csv(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        with z.open(z.namelist()[0]) as f:
            raw = f.read().decode()
    first = raw.split("\n", 1)[0].split(",")[0].strip()
    header = 0 if not first.lstrip("-").isdigit() and not first[:1].isdigit() else None
    return pd.read_csv(io.StringIO(raw), header=header)


def _to_ts(s: pd.Series) -> pd.DatetimeIndex:
    """Epoch ms o µs -> DatetimeIndex UTC."""
    v = s.astype("int64")
    unit = "us" if v.abs().max() > 10**14 else "ms"
    return pd.DatetimeIndex(pd.to_datetime(v, unit=unit, utc=True))


def parse_klines(blob: bytes) -> pd.DataFrame:
    df = _read_zip_csv(blob)
    if all(isinstance(c, (int, np.integer)) for c in df.columns):
        df.columns = _KLINE_COLS[: df.shape[1]]
    if df.empty:
        return pd.DataFrame()
    out = pd.DataFrame({c: df[c].astype("float64") for c in
                        ["open", "high", "low", "close", "volume", "taker_buy_volume"]})
    out.index = _to_ts(df["open_time"]).as_unit("ns")
    out.index.name = "ts"
    return out


def parse_funding(blob: bytes) -> pd.Series:
    df = _read_zip_csv(blob)
    if all(isinstance(c, (int, np.integer)) for c in df.columns):
        df.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"][: df.shape[1]]
    if df.empty:
        return pd.Series(dtype="float64")
    return pd.Series(df["last_funding_rate"].astype("float64").values, index=_to_ts(df["calc_time"]).as_unit("ns"))


def parse_metrics(blob: bytes) -> pd.Series:
    df = _read_zip_csv(blob)
    if df.empty:
        return pd.Series(dtype="float64")
    idx = pd.DatetimeIndex(pd.to_datetime(df["create_time"], utc=True)).as_unit("ns")
    return pd.Series(df["sum_open_interest"].astype("float64").values, index=idx)


def attach_funding(bars: pd.DataFrame, events: pd.Series, interval: str) -> pd.DataFrame:
    """Ogni evento di funding sulla barra il cui [open, open+interval) lo contiene (somma se piu' eventi)."""
    freq = pd.Timedelta(hours=interval_to_hours(interval))
    bars = bars.copy()
    bars["funding_rate"] = np.nan
    if len(events):
        per_bar = events.groupby(events.index.floor(freq)).sum()
        per_bar = per_bar[per_bar.index.isin(bars.index)]
        bars.loc[per_bar.index, "funding_rate"] = per_bar.values
    return bars


def attach_oi(bars: pd.DataFrame, oi: pd.Series, interval: str) -> pd.DataFrame:
    freq = pd.Timedelta(hours=interval_to_hours(interval))
    bars = bars.copy()
    if len(oi):
        oi = oi.sort_index()
        last = oi.groupby(oi.index.floor(freq)).last()
        bars["open_interest"] = last.reindex(bars.index).ffill(limit=1)
    else:
        bars["open_interest"] = np.nan
    return bars


def _fetch_month(symbol: str, interval: str, m0: pd.Timestamp, m1: pd.Timestamp, include_oi: bool,
                 now: pd.Timestamp, market: str = "um") -> pd.DataFrame:
    spot = market == "spot"
    base = BASE_SPOT if spot else BASE
    cur = pd.Timestamp(now.year, now.month, 1, tz="UTC")
    if m0 < cur:
        blob = _fetch(f"{base}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{m0:%Y-%m}.zip")
        bars = parse_klines(blob) if blob else pd.DataFrame()
        days = pd.date_range(m0, m1 - pd.Timedelta(days=1), freq="D")
    else:
        days = pd.date_range(m0, now.normalize() - pd.Timedelta(days=1), freq="D")
        urls = [f"{base}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{d:%Y-%m-%d}.zip" for d in days]
        with ThreadPoolExecutor(8) as ex:
            blobs = list(ex.map(_fetch, urls))
        parts = [parse_klines(b) for b in blobs if b]
        bars = pd.concat(parts) if parts else pd.DataFrame()
    if bars.empty:
        log.warning("binance_vision: nessun dato %s %s %s", symbol, interval, m0.strftime("%Y-%m"))
        return bars
    bars = bars[~bars.index.duplicated(keep="last")].sort_index()
    if spot:
        return bars
    fblob = _fetch(f"{BASE}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{m0:%Y-%m}.zip") if m0 < cur else None
    bars = attach_funding(bars, parse_funding(fblob) if fblob else pd.Series(dtype="float64"), interval)
    if include_oi:
        urls = [f"{BASE}/daily/metrics/{symbol}/{symbol}-metrics-{d:%Y-%m-%d}.zip" for d in days]
        with ThreadPoolExecutor(8) as ex:
            blobs = list(ex.map(_fetch, urls))
        parts = [parse_metrics(b) for b in blobs if b]
        bars = attach_oi(bars, pd.concat(parts) if parts else pd.Series(dtype="float64"), interval)
    return bars


def get_bars(symbol: str, interval: str, start, end, include_oi: bool = False, use_cache: bool = True,
             now: pd.Timestamp | None = None, market: str = "um") -> pd.DataFrame:
    """market: 'um' (USD-M perp, default; con funding) | 'spot'. Cache key distinta per mercato."""
    if market not in ("um", "spot"):
        raise ValueError(f"market sconosciuto: {market}")
    now = now or pd.Timestamp.now(tz="UTC")
    provider = "binance" if market == "um" else "binance_spot"
    df = cached_monthly(provider, symbol, interval, start, end,
                        lambda m0, m1: _fetch_month(symbol, interval, m0, m1, include_oi and market == "um", now,
                                                    market),
                        use_cache=use_cache, tag="oi" if include_oi and market == "um" else "", now=now)
    if df.empty:
        return df
    df = drop_forming(df, interval, now)
    df.index.name = "ts"
    return df
