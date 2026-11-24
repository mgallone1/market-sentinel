"""Momentum cross-sectional (primario): rank di rendimento vol-scalato su lookback_h saltando skip_h.
Segnale di STATO, ribilanciato ogni rebalance_h ore; top-k long, bottom-k short, neutrale (k long = k short)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.core import AssetSpec, interval_to_hours


def xs_scores(universe: dict, interval: str, lookback_h: float = 168.0, skip_h: float = 24.0) -> pd.DataFrame:
    """Punteggio per simbolo (colonne) a ogni close t: log(c[t-skip]/c[t-L]) / (sd 1-barra * sqrt(L-skip)).
    Usa solo barre <= t per ogni simbolo (NaN se mancano)."""
    h = interval_to_hours(interval)
    L, S = max(2, int(round(lookback_h / h))), max(0, int(round(skip_h / h)))
    W = max(2, L - S)
    cols = {}
    for sym, b in universe.items():
        lc = np.log(b["close"].astype(float))
        r = lc.shift(S) - lc.shift(L)
        sd = lc.diff().shift(S).rolling(W).std() * np.sqrt(W)
        cols[sym] = r / sd
    return pd.concat(cols, axis=1)


def xs_state(universe: dict, interval: str, lookback_h: float = 168.0, skip_h: float = 24.0,
             rebalance_h: float = 24.0, k: int = 3, allow_short: bool = True) -> pd.DataFrame:
    """Posizioni di stato {-1,0,1} per simbolo sull'indice unione, tenute fino al prossimo ribilanciamento."""
    sc = xs_scores(universe, interval, lookback_h, skip_h)
    h = interval_to_hours(interval)
    step = max(1, int(round(rebalance_h / h)))
    epoch_bars = np.asarray((sc.index - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(hours=h), dtype=np.int64)
    is_reb = (epoch_bars % step) == 0
    pos = pd.DataFrame(np.nan, index=sc.index, columns=sc.columns)
    v = sc.to_numpy(float)
    out = np.full(v.shape, np.nan)
    for r in np.flatnonzero(is_reb):
        row = v[r]
        ok = np.flatnonzero(~np.isnan(row))
        p = np.zeros(len(row))
        if len(ok) >= 2 * k:
            order = ok[np.argsort(row[ok], kind="stable")]
            p[order[-k:]] = 1
            if allow_short:
                p[order[:k]] = -1
        out[r] = p
    pos[:] = out
    return pos.ffill().fillna(0).astype(int), is_reb


def xs_momentum(bars: pd.DataFrame, spec: AssetSpec, interval: str, context: dict | None = None,
                lookback_h: float = 168.0, skip_h: float = 24.0, rebalance_h: float = 24.0, k: int = 3,
                events_only: bool = False) -> pd.Series:
    """fn(bars, spec, interval, context): context['universe'] = {sym: bars}. events_only=True emette il lato solo
    sulle barre di ribilanciamento (per il backtester con max_hold_bars = rebalance)."""
    uni = dict((context or {}).get("universe") or {})
    uni[spec.symbol] = bars
    state, is_reb = xs_state(uni, interval, lookback_h, skip_h, rebalance_h, k, spec.allow_short)
    s = state[spec.symbol]
    if events_only:
        s = s.where(pd.Series(is_reb, index=s.index), 0)
    return s.reindex(bars.index).fillna(0).astype(int)
