"""Event-based expanding walk-forward with purging and embargo."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Fold:
    train_idx: np.ndarray
    test_idx: np.ndarray
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    n_purged: int
    n_embargoed: int


def purged_expanding_splits(
    t0: pd.DatetimeIndex,
    t1: pd.DatetimeIndex,
    first_test_start: pd.Timestamp,
    test_len: pd.Timedelta,
    embargo: pd.Timedelta,
    end: pd.Timestamp | None = None,
) -> Iterator[Fold]:
    """Yield expanding folds over events with label interval [t0, t1].

    Test block k: events with test_start <= t0 < test_end. Train: every earlier event whose label
    ends strictly before the test block (purging: t1 < test_start) and whose start is not inside
    the embargo window before the test block (t0 <= test_start - embargo).
    """
    t0 = pd.DatetimeIndex(t0)
    t1 = pd.DatetimeIndex(t1)
    if len(t0) != len(t1):
        raise ValueError("t0 e t1 di lunghezza diversa")
    if (t1 < t0).any():
        raise ValueError("t1 < t0")
    end = pd.Timestamp(end) if end is not None else (t0.max() + pd.Timedelta(seconds=1))
    start = pd.Timestamp(first_test_start)
    while start < end:
        stop = min(start + test_len, end)
        test = (t0 >= start) & (t0 < stop)
        before = t0 < start
        purged = before & (t1 >= start)
        embargoed = before & ~purged & (t0 > start - embargo)
        train = before & ~purged & ~embargoed
        if test.any():
            yield Fold(np.flatnonzero(train), np.flatnonzero(test), start, stop, int(purged.sum()), int(embargoed.sum()))
        start = stop


def assert_no_overlap(t0: pd.DatetimeIndex, t1: pd.DatetimeIndex, fold: Fold, embargo: pd.Timedelta) -> None:
    """Raise if any train label overlaps the test block or falls inside the embargo."""
    t0 = pd.DatetimeIndex(t0)
    t1 = pd.DatetimeIndex(t1)
    tr = fold.train_idx
    if len(tr) == 0:
        return
    if (t1[tr] >= fold.test_start).any():
        raise AssertionError("leakage: label di train dentro il test")
    if (t0[tr] > fold.test_start - embargo).any():
        raise AssertionError("leakage: evento di train dentro l'embargo")
    if len(np.intersect1d(tr, fold.test_idx)):
        raise AssertionError("eventi condivisi tra train e test")


def fold_list(*args, **kwargs) -> List[Fold]:
    return list(purged_expanding_splits(*args, **kwargs))
