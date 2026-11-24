"""Pesi di unicita' media delle etichette (Lopez de Prado, AFML cap. 4)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def average_uniqueness(t0, t1) -> np.ndarray:
    """t0: inizio evento (array-like di timestamp), t1: fine evento. Restituisce, per evento, la media di
    1/concorrenza sui punti-griglia (unione di t0 e t1) coperti dall'evento. Valori in (0, 1]."""
    s = pd.DatetimeIndex(t0).asi8
    e = pd.DatetimeIndex(t1).asi8
    n = len(s)
    if n == 0:
        return np.array([])
    e = np.maximum(e, s)
    grid = np.unique(np.concatenate([s, e]))
    i0, i1 = np.searchsorted(grid, s), np.searchsorted(grid, e)          # indici inclusivi
    diff = np.zeros(len(grid) + 1)
    np.add.at(diff, i0, 1.0)
    np.add.at(diff, i1 + 1, -1.0)
    conc = np.cumsum(diff)[:-1]
    inv = np.cumsum(1.0 / np.maximum(conc, 1.0))
    inv = np.concatenate([[0.0], inv])
    u = (inv[i1 + 1] - inv[i0]) / (i1 - i0 + 1)
    return np.clip(u, 1e-12, 1.0)


def uniqueness_weights(events: pd.DataFrame, t1_col: str = "t1", symbol_level: str = "symbol",
                       normalize: bool = True) -> pd.Series:
    """Pesi per un dataset di eventi (MultiIndex (symbol, ts) o indice ts). Concorrenza calcolata per simbolo.
    Con normalize=True i pesi hanno media 1 (utile per i fit); i valori grezzi sono comunque in (0,1]."""
    idx = events.index
    ts = idx.get_level_values(-1)
    out = np.empty(len(events))
    if isinstance(idx, pd.MultiIndex) and symbol_level in idx.names:
        sym = np.asarray(idx.get_level_values(symbol_level))
        for s in np.unique(sym):
            m = sym == s
            out[m] = average_uniqueness(ts[m], events[t1_col].to_numpy()[m])
    else:
        out[:] = average_uniqueness(ts, events[t1_col].to_numpy())
    w = pd.Series(out, index=idx, name="uniqueness")
    return w / w.mean() if normalize and len(w) else w
