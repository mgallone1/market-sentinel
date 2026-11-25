"""Helper comuni alle strategie del lab: solo dati CHIUSI fino a `now`."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd

try:  # calendario festivi NYSE gia' mantenuto per il risk manager del bot
    from services.risk_limits import NYSE_HOLIDAYS
except Exception:  # noqa: BLE001
    NYSE_HOLIDAYS = {}


def utc(now) -> pd.Timestamp:
    t = pd.Timestamp(now)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _idx_utc(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    df = df.sort_index()
    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")
    return df


def closed_bars(df, now, interval_hours: float, same_day_after_hour: Optional[int] = None) -> pd.DataFrame:
    """Tiene solo le barre chiuse a `now`. Intraday: open + intervallo <= now. Giornaliere (24h): open_date < oggi,
    oppure oggi se `same_day_after_hour` e now >= quell'ora UTC (azioni/ETF a mercato chiuso)."""
    df = _idx_utc(df)
    if df.empty:
        return df
    now = utc(now)
    if interval_hours >= 24:
        d = df.index.normalize()
        keep = d < now.normalize()
        if same_day_after_hour is not None and now.hour >= same_day_after_hour:
            keep = keep | (d == now.normalize())
        return df[keep]
    return df[df.index + pd.Timedelta(hours=interval_hours) <= now]


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS


def is_last_trading_day_of_month(d: date) -> bool:
    if not is_trading_day(d):
        return False
    nxt = d + timedelta(days=1)
    while nxt.month == d.month:
        if is_trading_day(nxt):
            return False
        nxt += timedelta(days=1)
    return True


def funding_series(f, now) -> pd.Series:
    """Normalizza l'output di MarketData.funding in Series (indice UTC, tasso per print) con print <= now."""
    if f is None or len(f) == 0:
        return pd.Series(dtype=float)
    if isinstance(f, pd.DataFrame):
        col = "funding_rate" if "funding_rate" in f.columns else f.columns[0]
        f = f[col]
    s = f.dropna().sort_index().astype(float)
    if s.index.tz is None:
        s.index = s.index.tz_localize("UTC")
    return s[s.index <= utc(now)]
