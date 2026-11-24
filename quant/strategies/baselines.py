"""Modelli primari semplici, utilizzabili su qualsiasi asset. Long-only se spec.allow_short e' False.
Segnali di STATO (tsmom, ema_cross, always_long) o di EVENTO (donchian, meanrev_z, random)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.core import AssetSpec, interval_to_hours
from quant.features import TrendRegime
from quant.features import indicators as ind


def _fin(sig: pd.Series, spec: AssetSpec) -> pd.Series:
    sig = sig.fillna(0).astype(int)
    return sig if spec.allow_short else sig.clip(lower=0)


def tsmom(bars, spec, interval, context=None, lookback_h: float = 168.0, deadband: float = 0.5) -> pd.Series:
    """Segno del rendimento log su `lookback_h` ore, scalato per la vol (std ritorni a 1 barra * sqrt(L) sulla
    stessa finestra); posizione 0 se |z| < deadband."""
    L = max(2, int(round(lookback_h / interval_to_hours(interval))))
    lc = np.log(bars["close"])
    r = lc.diff(L)
    sd = lc.diff().rolling(L).std() * np.sqrt(L)
    z = r / sd
    sig = pd.Series(np.where(z > deadband, 1, np.where(z < -deadband, -1, 0)), index=bars.index)
    sig[z.isna()] = 0
    return _fin(sig, spec)


def donchian_breakout(bars, spec, interval, context=None, n: int = 96) -> pd.Series:
    """Evento: close rompe il massimo (minimo) delle n barre precedenti -> +1 (-1)."""
    hi = bars["high"].shift(1).rolling(n).max()
    lo = bars["low"].shift(1).rolling(n).min()
    c = bars["close"]
    sig = pd.Series(np.where(c > hi, 1, np.where(c < lo, -1, 0)), index=bars.index)
    return _fin(sig, spec)


def meanrev_z(bars, spec, interval, context=None, k: float = 2.0, n: int = 4, z_window: int = 96,
              adx_max: float = 20.0) -> pd.Series:
    """Evento: z del rendimento a n barre (std rolling z_window) con |z|>k e ADX(14)<adx_max -> posizione contraria."""
    r = bars["close"].pct_change(n)
    z = r / r.rolling(z_window).std()
    low_adx = ind.adx(bars, 14) < adx_max
    sig = pd.Series(np.where((z > k) & low_adx, -1, np.where((z < -k) & low_adx, 1, 0)), index=bars.index)
    return _fin(sig, spec)


def ema_cross(bars, spec, interval, context=None, fast: int = 24, slow: int = 96, confirm: int = 3,
              band_atr: float = 0.5) -> pd.Series:
    """Stato: regime TrendRegime(fast, slow, confirm, band_atr) con isteresi."""
    return _fin(TrendRegime(fast, slow, confirm, band_atr).classify(bars), spec)


def always_long(bars, spec, interval, context=None) -> pd.Series:
    """Benchmark buy&hold: +1 ovunque."""
    return pd.Series(1, index=bars.index, dtype=int)


def random(bars, spec, interval, context=None, p: float = 0.02, seed: int = 0) -> pd.Series:
    """Evento casuale (null test): con prob. p per barra, lato +-1 equiprobabile. Seed fisso, indipendente dalla
    lunghezza (un draw per timestamp) cosi' resta causale."""
    n = len(bars)
    rng = np.random.default_rng(seed)
    u = rng.random(n)
    s = np.where(np.random.default_rng(seed + 1).random(n) < 0.5, -1, 1)
    return _fin(pd.Series(np.where(u < p, s, 0), index=bars.index), spec)
