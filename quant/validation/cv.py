"""Cross-validation senza leakage: PurgedKFold (LdP) e walk-forward."""
from __future__ import annotations

from typing import Iterator, Tuple

import numpy as np
import pandas as pd


class PurgedKFold:
    """K-fold contiguo con purge (eventi di train sovrapposti alla finestra di test) ed embargo."""

    def __init__(self, n_splits: int = 5, embargo_frac: float = 0.01):
        if n_splits < 2:
            raise ValueError("n_splits >= 2")
        self.n_splits, self.embargo_frac = n_splits, embargo_frac

    def get_n_splits(self, *a, **k) -> int:
        return self.n_splits

    def split(self, X, t1: pd.Series) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        n = len(t1)
        if len(X) != n:
            raise ValueError("X e t1 devono avere la stessa lunghezza")
        starts = t1.index.asi8
        ends = pd.DatetimeIndex(t1.values).asi8
        emb = int(np.ceil(n * self.embargo_frac))
        pos = np.arange(n)
        for test in np.array_split(pos, self.n_splits):
            if len(test) == 0:
                continue
            t_start, t_end = starts[test[0]], ends[test].max()
            overlap = (starts <= t_end) & (ends >= t_start)
            train_mask = ~overlap
            train_mask[test] = False
            train_mask[test[-1] + 1: test[-1] + 1 + emb] = False
            yield pos[train_mask], test


def walk_forward_splits(index, train_bars: int, test_bars: int, step_bars: int | None = None,
                        embargo_bars: int = 0, expanding: bool = False) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
    """(train_idx, test_idx) interi; tra fine train e inizio test ci sono embargo_bars barre."""
    n = len(index)
    step = step_bars or test_bars
    t0 = train_bars + embargo_bars
    while t0 + test_bars <= n:
        tr_end = t0 - embargo_bars
        tr_start = 0 if expanding else tr_end - train_bars
        yield np.arange(tr_start, tr_end), np.arange(t0, t0 + test_bars)
        t0 += step
