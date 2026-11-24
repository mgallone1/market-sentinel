"""Cache su disco (pickle gzip) sotto <repo>/data/cache/. Mesi chiusi: permanenti; mese corrente: TTL breve."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import pandas as pd

from quant.core import interval_to_hours

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
CURRENT_MONTH_TTL = 1800.0


def cache_path(provider: str, symbol: str, interval: str, month: str, tag: str = "") -> Path:
    name = "_".join(p for p in (provider, symbol, interval, month, tag) if p)
    safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in name)
    return CACHE_DIR / f"{safe}.pkl.gz"


def read_cache(path: Path, max_age: float | None = None) -> pd.DataFrame | None:
    try:
        if not path.exists():
            return None
        if max_age is not None and time.time() - path.stat().st_mtime > max_age:
            return None
        return pd.read_pickle(path, compression="gzip")
    except Exception:
        return None


def write_cache(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_pickle(tmp, compression="gzip")
    tmp.replace(path)


def month_starts(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    s = pd.Timestamp(start.year, start.month, 1, tz="UTC")
    return list(pd.date_range(s, end, freq="MS", tz="UTC"))


def cached_monthly(provider: str, symbol: str, interval: str, start, end,
                   fetch_month: Callable[[pd.Timestamp, pd.Timestamp], pd.DataFrame],
                   use_cache: bool = True, tag: str = "", now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Concatena i mesi in [start, end]; fetch_month(m0, m1) con m1 = inizio mese successivo (escluso)."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    now = now or pd.Timestamp.now(tz="UTC")
    cur = pd.Timestamp(now.year, now.month, 1, tz="UTC")
    parts = []
    for m0 in month_starts(start, end):
        m1 = m0 + pd.offsets.MonthBegin(1)
        path = cache_path(provider, symbol, interval, m0.strftime("%Y-%m"), tag)
        df = read_cache(path, None if m0 < cur else CURRENT_MONTH_TTL) if use_cache else None
        if df is None:
            df = fetch_month(m0, m1)
            if use_cache and df is not None and len(df):
                write_cache(path, df)
        if df is not None and len(df):
            parts.append(df)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.loc[(out.index >= start) & (out.index <= end)]


def drop_forming(df: pd.DataFrame, interval: str, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Scarta le barre la cui chiusura (open + intervallo) e' nel futuro."""
    if df.empty:
        return df
    now = now or pd.Timestamp.now(tz="UTC")
    return df[df.index + pd.Timedelta(hours=interval_to_hours(interval)) <= now]
