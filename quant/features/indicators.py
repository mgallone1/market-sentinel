"""Indicatori puri e causali: il valore alla riga t usa solo dati <= t."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


def _mask_warmup(s: pd.Series, n: int) -> pd.Series:
    """NaN finche' non ci sono almeno n osservazioni valide (seed mal convergenti)."""
    return s.where(s.notna().cumsum() >= n)


def ema(x: pd.Series, span: int) -> pd.Series:
    out = x.ewm(span=span, adjust=False).mean()
    return _mask_warmup(out, span)


def wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    ag = d.clip(lower=0).where(d.notna()).ewm(alpha=1 / n, adjust=False).mean()
    al = (-d).clip(lower=0).where(d.notna()).ewm(alpha=1 / n, adjust=False).mean()
    den = ag + al
    rsi = (100 * ag / den).where(den > 0, 50.0)
    return _mask_warmup(rsi.where(ag.notna()), n)


def true_range(bars: pd.DataFrame) -> pd.Series:
    pc = bars["close"].shift(1)
    parts = pd.concat([bars["high"] - bars["low"], (bars["high"] - pc).abs(), (bars["low"] - pc).abs()], axis=1)
    return parts.max(axis=1)


def atr_wilder(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    return _mask_warmup(true_range(bars).ewm(alpha=1 / n, adjust=False).mean(), n)


def realized_vol(logret: pd.Series, window: int) -> pd.Series:
    return logret.rolling(window).std()


def rolling_zscore(x: pd.Series, window: int) -> pd.Series:
    m = x.rolling(window).mean()
    s = x.rolling(window).std()
    return (x - m) / s.where(s > 0)


def donchian(high: pd.Series, low: pd.Series, n: int) -> pd.DataFrame:
    return pd.DataFrame({"high": high.rolling(n).max(), "low": low.rolling(n).min()})


def aroon_position(close: pd.Series, n: int) -> pd.Series:
    """Barre trascorse dal minimo delle ultime n+1 barre, divise per n (0 = minimo ora, 1 = minimo n barre fa)."""
    v = close.to_numpy(float)
    if len(v) < n + 1:
        return pd.Series(np.nan, index=close.index)
    w = sliding_window_view(v, n + 1)[:, ::-1]  # colonna 0 = barra corrente
    bad = ~np.isfinite(w).all(axis=1)
    pos = np.argmin(np.where(np.isfinite(w), w, np.inf), axis=1).astype(float) / n
    pos[bad] = np.nan
    out = np.full(len(v), np.nan)
    out[n:] = pos
    return pd.Series(out, index=close.index)


def roc(close: pd.Series, n: int) -> pd.Series:
    return close / close.shift(n) - 1


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line.dropna(), signal).reindex(close.index)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger_pctb(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.Series:
    m = close.rolling(n).mean()
    s = close.rolling(n).std()
    width = 2 * k * s
    return (close - (m - k * s)) / width.where(width > 0)


def adx(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    up = bars["high"].diff()
    dn = -bars["low"].diff()
    pdm = up.where((up > dn) & (up > 0), 0.0).where(up.notna())
    mdm = dn.where((dn > up) & (dn > 0), 0.0).where(dn.notna())
    a = 1 / n
    atr = true_range(bars).ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=a, adjust=False).mean() / atr
    mdi = 100 * mdm.ewm(alpha=a, adjust=False).mean() / atr
    den = (pdi + mdi)
    dx = (100 * (pdi - mdi).abs() / den).where(den > 0, 0.0).where(pdi.notna())
    return _mask_warmup(dx.ewm(alpha=a, adjust=False).mean(), 2 * n)


def variance_ratio(logp: pd.Series, q: int, window: int) -> pd.Series:
    """Lo-MacKinlay: Var(r_q) / (q Var(r_1)) su finestra mobile (>1 trend, <1 mean reversion)."""
    r1 = logp.diff()
    rq = logp.diff(q)
    v1 = r1.rolling(window).var()
    vq = rq.rolling(window).var()
    return vq / (q * v1.where(v1 > 0))


def hurst_exponent_rs(returns: pd.Series, window: int = 256, chunk: int = 4000) -> pd.Series:
    """Hurst rolling via R/S multi-scala (pendenza log R/S vs log s, s = window/2^k, s>=16).
    Stimatore grezzo: per rumore bianco tende a ~0.55-0.6 (bias di piccolo campione)."""
    r = returns.to_numpy(float)
    n = len(r)
    sizes = []
    s = window
    while s >= 16 and window % s == 0:
        sizes.append(s)
        s //= 2
    if len(sizes) < 3:
        raise ValueError("window deve essere multiplo di 16 con almeno 3 scale")
    out = np.full(n, np.nan)
    if n < window:
        return pd.Series(out, index=returns.index)
    W = sliding_window_view(r, window)
    ls = np.log(np.array(sizes, float))
    lsc = ls - ls.mean()
    for a in range(0, W.shape[0], chunk):
        w = W[a:a + chunk]
        ok = np.isfinite(w).all(axis=1)
        w = np.where(ok[:, None], w, 0.0)
        lrs = []
        for s in sizes:
            b = w.reshape(w.shape[0], window // s, s)
            dev = b - b.mean(axis=2, keepdims=True)
            cum = np.cumsum(dev, axis=2)
            rng = cum.max(axis=2) - cum.min(axis=2)
            sd = b.std(axis=2)
            rs = np.where(sd > 0, rng / np.where(sd > 0, sd, 1), np.nan)
            with np.errstate(all="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                lrs.append(np.log(np.nanmean(np.where(np.isfinite(rs), rs, np.nan), axis=1)))
        Y = np.stack(lrs, axis=1)
        h = (Y * lsc).sum(axis=1) / (lsc ** 2).sum()
        h[~ok] = np.nan
        out[window - 1 + a: window - 1 + a + len(h)] = h
    return pd.Series(out, index=returns.index)


def kaufman_efficiency_ratio(close: pd.Series, n: int) -> pd.Series:
    path = close.diff().abs().rolling(n).sum()
    return (close - close.shift(n)).abs() / path.where(path > 0)
