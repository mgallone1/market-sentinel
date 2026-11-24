"""TSMOM multi-asset: segnale, sizing e vol targeting (specifica fissa pre-registrata)."""
from __future__ import annotations

import numpy as np
import pandas as pd

TARGET_PORT_VOL = 0.10
ASSET_VOL_TARGET = 0.40
MAX_GROSS = 2.0
LOOKBACKS = (21, 63, 252)
BAND = 0.10


def signals(prices: pd.DataFrame) -> pd.DataFrame:
    """Media dei segni dei rendimenti 21/63/252g; NaN se meno di 252g di storia (poi trattato come 0)."""
    p = prices.ffill()
    s = sum(np.sign(p / p.shift(k) - 1) for k in LOOKBACKS) / len(LOOKBACKS)
    return s.where(p.shift(252).notna())


def asset_vol(prices: pd.DataFrame, crypto: set[str]) -> pd.DataFrame:
    r = prices.ffill().pct_change(fill_method=None)
    v = r.ewm(com=60, min_periods=60).std()
    ann = pd.Series([np.sqrt(365) if c in crypto else np.sqrt(252) for c in prices.columns], index=prices.columns)
    return v * ann


def rebalance_dates(index: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    naive = index.tz_localize(None) if index.tz is not None else index
    key = naive.to_period("W" if freq == "weekly" else "M").astype(str)
    s = pd.Series(np.arange(len(index)), index=index)
    return index[s.groupby(np.asarray(key)).max().values]


def tsmom_weights(prices: pd.DataFrame, crypto: set[str] = frozenset(), freq: str = "weekly",
                  mode: str = "long_short") -> pd.DataFrame:
    """mode: long_short | long_only | risk_parity. Pesi target alle date di ribilanciamento (ffill tra le date)."""
    prices = prices.sort_index()
    sig = signals(prices)
    if mode == "risk_parity":
        sig = sig.where(sig.isna(), 1.0)
    elif mode == "long_only":
        sig = sig.clip(lower=0)
    vol = asset_vol(prices, crypto)
    rets = prices.ffill().pct_change(fill_method=None)
    cols = prices.columns
    out = pd.DataFrame(np.nan, index=prices.index, columns=cols)
    cur = pd.Series(0.0, index=cols)
    for d in rebalance_dates(prices.index, freq):
        i = prices.index.get_loc(d)
        act = sig.loc[d].notna() & vol.loc[d].notna() & (vol.loc[d] > 0)
        new = pd.Series(0.0, index=cols)
        if act.sum() > 0 and i >= 252:
            raw = sig.loc[d][act] * (ASSET_VOL_TARGET / vol.loc[d][act]) / act.sum()
            win = rets.iloc[i - 251:i + 1][raw.index]
            cov = win.cov().values * 252
            pv = float(np.sqrt(max(raw.values @ cov @ raw.values, 0.0)))
            if pv > 0:
                raw = raw * (TARGET_PORT_VOL / pv)
            g = raw.abs().sum()
            if g > MAX_GROSS:
                raw = raw * (MAX_GROSS / g)
            new[raw.index] = raw
        trade = (new - cur).abs() >= BAND * new.abs()
        trade &= ~((new == 0) & (cur == 0))
        cur = cur.where(~trade, new)
        out.loc[d] = cur
    # prima della prima data di ribilanciamento: pesi 0
    return out.ffill().fillna(0.0)


def n_active(prices: pd.DataFrame) -> pd.Series:
    return signals(prices).notna().sum(axis=1)
