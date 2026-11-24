"""Dati sintetici deterministici (GBM con regimi opzionali) conformi al contratto BARRE."""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.core import interval_to_hours


def _regime_path(rng, n, regimes):
    k = len(regimes)
    st = np.zeros(n, dtype=int)
    for i in range(1, n):
        if rng.random() < regimes[st[i - 1]][0] or k == 1:
            st[i] = st[i - 1]
        else:
            others = [j for j in range(k) if j != st[i - 1]]
            st[i] = others[rng.integers(len(others))]
    mu = np.array([r[1] for r in regimes])[st]
    sg = np.array([r[2] for r in regimes])[st]
    return mu, sg


def _build(rng, rets, sigma_t, n, interval, with_taker, with_funding, start):
    close = 100.0 * np.exp(np.cumsum(rets))
    prev = np.concatenate([[100.0], close[:-1]])
    open_ = prev * np.exp(rng.normal(0, 0.05, n) * sigma_t)
    hi = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.4, n)) * sigma_t)
    lo = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.4, n)) * sigma_t)
    vol = np.exp(rng.normal(5.0, 0.4, n)) * (1 + 20 * sigma_t * np.abs(rets / np.maximum(sigma_t, 1e-12)) / 10)
    idx = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=n, freq=pd.Timedelta(hours=interval_to_hours(interval)), name="ts")
    df = pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close, "volume": vol}, index=idx)
    if with_taker:
        frac = np.clip(0.5 + 0.08 * rng.standard_normal(n) + 5 * rets / np.maximum(sigma_t, 1e-12) * 0.01, 0.0, 1.0)
        df["taker_buy_volume"] = vol * frac
    if with_funding:
        f = np.full(n, np.nan)
        step = interval_to_hours(interval)
        if step >= 8:
            mask = np.ones(n, bool)
        else:
            mask = (idx.hour % 8 == 0) & (idx.minute == 0)
        f[mask] = rng.normal(1e-4, 1e-4, int(mask.sum()))
        df["funding_rate"] = f
    return df.astype("float64")


def generate_bars(n: int = 5000, interval: str = "1h", seed: int = 0, mu: float = 0.0, sigma: float = 0.007,
                  regimes=None, with_taker: bool = True, with_funding: bool = True,
                  start: str = "2024-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if regimes:
        mu_t, sigma_t = _regime_path(rng, n, regimes)
    else:
        mu_t, sigma_t = np.full(n, mu), np.full(n, sigma)
    rets = mu_t - 0.5 * sigma_t ** 2 + sigma_t * rng.standard_normal(n)
    return _build(rng, rets, sigma_t, n, interval, with_taker, with_funding, start)


def generate_bars_with_signal(n: int = 5000, interval: str = "1h", seed: int = 0, mu: float = 0.0,
                              sigma: float = 0.007, regimes=None, with_taker: bool = True,
                              with_funding: bool = True, start: str = "2024-01-01",
                              ic: float = 0.05, horizon: int = 24) -> pd.DataFrame:
    """Aggiunge `planted_signal` (N(0,1), nota al close di t) con corr ~ic rispetto al rendimento
    forward log(close[t+h]/close[t]). Costruzione: r_t += b * sum_{j=1..h} s_{t-j}."""
    rng = np.random.default_rng(seed)
    if regimes:
        mu_t, sigma_t = _regime_path(rng, n, regimes)
    else:
        mu_t, sigma_t = np.full(n, mu), np.full(n, sigma)
    h = int(horizon)
    V = float(sum((h - abs(d)) ** 2 for d in range(-(h - 1), h)))
    if h * h <= ic * ic * V:
        raise ValueError("ic troppo alto per questo horizon")
    sig0 = float(np.mean(sigma_t))
    b = abs(ic) * np.sqrt(h) * sig0 / np.sqrt(h * h - ic * ic * V) * np.sign(ic or 1)
    s = rng.standard_normal(n)
    drift = b * np.concatenate([[0.0], np.convolve(s, np.ones(h))[: n - 1]])  # somma s_{t-1..t-h}
    rets = mu_t - 0.5 * sigma_t ** 2 + sigma_t * rng.standard_normal(n) + drift
    df = _build(rng, rets, sigma_t, n, interval, with_taker, with_funding, start)
    df["planted_signal"] = s
    return df
