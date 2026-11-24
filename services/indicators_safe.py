"""Indicatori sicuri: RSI/ATR di Wilder e rimozione della barra in formazione."""
from datetime import datetime, timedelta, timezone

import pandas as pd


def wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    return 100 - (100 / (1 + rs))


def atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def drop_forming_bar(df: pd.DataFrame, interval_minutes: float, now=None) -> pd.DataFrame:
    """Rimuove l'ultima riga se open_time + intervallo > now (barra ancora aperta)."""
    if df is None or len(df) == 0:
        return df
    if now is None:
        now = datetime.now(timezone.utc)
    now = pd.Timestamp(now)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    last = pd.Timestamp(df.index[-1])
    last = last.tz_localize("UTC") if last.tzinfo is None else last.tz_convert("UTC")
    if last + timedelta(minutes=interval_minutes) > now:
        return df.iloc[:-1]
    return df
