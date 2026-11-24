"""Setup del pacchetto day-trader (day_trader/trader-scanner/scan.py e trader-entry/entry.py), portati come
strategie primarie long-only. Regole e soglie identiche agli originali; decisione a chiusura barra.

Daily (scan.find_setups, richiede >= 30 barre): breakout_20d_close_high, bull_flag, reclaim_20d_ma, oversold,
oversold_bounce. Su intervalli diversi da 1d le "barre" sono semplicemente le barre dell'intervallo.
Intraday: orb (opening range 15 min, ora US/Eastern con DST corretto, solo RTH, una volta per sessione)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.core import interval_to_hours

MIN_DAILY_BARS = 30


def wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI di Wilder come scan.rsi: seme = media semplice dei primi n delta, poi ricorsione. Causale
    (il valore a t dipende solo da close[:t+1]); NaN finche' non ci sono n+1 chiusure."""
    c = close.to_numpy(float)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return pd.Series(out, index=close.index)
    d = np.diff(c)
    g, lo = np.maximum(d, 0.0), np.maximum(-d, 0.0)
    ag, al = g[:n].mean(), lo[:n].mean()
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
        out[i + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return pd.Series(out, index=close.index)


def _sig(mask: pd.Series, bars: pd.DataFrame) -> pd.Series:
    ok = mask.fillna(False).to_numpy(bool).copy()
    ok[: MIN_DAILY_BARS - 1] = False
    return pd.Series(ok.astype(int), index=bars.index)


def breakout_20d_close_high(bars, spec, interval, context=None) -> pd.Series:
    c = bars["close"]
    return _sig(c > c.shift(1).rolling(20).max(), bars)


def bull_flag(bars, spec, interval, context=None) -> pd.Series:
    c = bars["close"]
    run = c.shift(5) / c.shift(15) - 1
    rng5 = (c.rolling(5).max() - c.rolling(5).min()) / c
    return _sig((run > 0.10) & (rng5 < 0.05), bars)


def reclaim_20d_ma(bars, spec, interval, context=None) -> pd.Series:
    c = bars["close"]
    ma20 = c.rolling(20).mean()
    return _sig((c.shift(1) < ma20.shift(1)) & (c > ma20), bars)


def oversold(bars, spec, interval, context=None) -> pd.Series:
    return _sig(wilder_rsi(bars["close"]) < 30, bars)


def oversold_bounce(bars, spec, interval, context=None) -> pd.Series:
    c = bars["close"]
    return _sig((wilder_rsi(c).shift(1) < 30) & (c > c.shift(1)), bars)


def orb(bars, spec, interval, context=None, or_minutes: int = 15, min_volume_x: float | None = None,
        no_entries_after: str = "15:30") -> pd.Series:
    """Opening range breakout (entry.evaluate, setup=orb): range = massimo delle barre che aprono tra 9:30 ET e
    9:30+or_minutes (devono esserci tutte); +1 sulla prima barra completata, che inizia dopo il range e chiude
    entro `no_entries_after` ET, con close > massimo del range (e, se richiesto, volume >= min_volume_x * volume
    medio delle barre del range). Al massimo un segnale per sessione; solo RTH; long-only."""
    step = int(round(interval_to_hours(interval) * 60))
    out = pd.Series(0, index=bars.index, dtype=int)
    if step <= 0 or or_minutes % step or interval.endswith("d"):
        return out
    n_or = or_minutes // step
    et = bars.index.tz_convert("America/New_York")
    mins = np.asarray(et.hour * 60 + et.minute)
    day = np.asarray(et.normalize().tz_localize(None).asi8)
    o_start = 9 * 60 + 30
    h, c = bars["high"].to_numpy(float), bars["close"].to_numpy(float)
    v = bars["volume"].to_numpy(float) if "volume" in bars else np.zeros(len(bars))
    a, b = (int(x) for x in no_entries_after.split(":"))
    cutoff = a * 60 + b
    sig = np.zeros(len(bars), dtype=int)
    for d in np.unique(day):
        idx = np.flatnonzero(day == d)
        m = mins[idx]
        in_or = (m >= o_start) & (m < o_start + or_minutes)
        if in_or.sum() != n_or:
            continue
        # le barre del range devono essere esattamente la griglia 9:30, 9:35, ...
        if not np.array_equal(np.sort(m[in_or]), o_start + step * np.arange(n_or)):
            continue
        hi = h[idx][in_or].max()
        avg_v = v[idx][in_or].mean()
        for j, i in enumerate(idx):
            if m[j] < o_start + or_minutes or m[j] + step > cutoff:
                continue
            if c[i] > hi:
                if min_volume_x and (avg_v <= 0 or v[i] / avg_v < min_volume_x):
                    continue
                sig[i] = 1
                break
    return pd.Series(sig, index=bars.index)
