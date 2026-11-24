import math

import numpy as np
import pandas as pd

from quant.validation import (PurgedKFold, brier_score, calibration_table, deflated_sharpe_ratio,
                              expected_max_sharpe, log_loss, norm_ppf, pbo_cscv, probabilistic_sharpe_ratio,
                              rolling_ic, spearman_ic, walk_forward_splits)


def test_norm_ppf():
    assert abs(norm_ppf(0.975) - 1.959964) < 1e-5
    assert abs(norm_ppf(0.001) + 3.090232) < 1e-5


def test_psr_half_at_zero():
    assert abs(probabilistic_sharpe_ratio(0.0, 1000) - 0.5) < 1e-9
    assert probabilistic_sharpe_ratio(0.1, 1000) > 0.95


def test_dsr_decreases_with_trials():
    r = np.random.default_rng(1).normal(0.0006, 0.01, 2000)
    d = [deflated_sharpe_ratio(r, n, 0.0004) for n in (1, 10, 100, 1000)]
    assert all(a > b for a, b in zip(d, d[1:]))
    assert expected_max_sharpe(0.0004, 100) > expected_max_sharpe(0.0004, 10) > 0


def test_pbo_noise_and_dominant():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.01, (1600, 20))
    pbo, logits = pbo_cscv(noise, 16)
    assert 0.35 < pbo < 0.65 and len(logits) == 12870
    dom = noise.copy()
    dom[:, 3] += 0.01
    assert pbo_cscv(dom, 16)[0] < 0.2


def test_ic_and_probs():
    rng = np.random.default_rng(0)
    x = rng.normal(size=3000)
    y = x + rng.normal(size=3000)
    assert spearman_ic(x, y) > 0.6
    assert abs(spearman_ic(x, rng.normal(size=3000))) < 0.1
    assert rolling_ic(pd.Series(x), pd.Series(y), 200).iloc[200:].min() > 0.3
    p = rng.uniform(size=5000)
    yb = (rng.uniform(size=5000) < p).astype(float)
    assert abs(brier_score(p, yb) - 1 / 6) < 0.02
    assert log_loss(np.full(10, 0.5), np.ones(10)) - math.log(2) < 1e-9
    t = calibration_table(p, yb, 10)
    assert (t["mean_p"] - t["frac_pos"]).abs().max() < 0.1


def test_purged_kfold_no_overlap():
    n, h = 500, 10
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    t1 = pd.Series(idx + pd.Timedelta(hours=h), index=idx)
    X = np.zeros((n, 2))
    folds = list(PurgedKFold(5, 0.02).split(X, t1))
    assert len(folds) == 5
    for tr, te in folds:
        assert len(tr) and len(te) and not set(tr) & set(te)
        t_start, t_end = t1.index[te[0]], t1.iloc[te].max()
        s, e = t1.index[tr], pd.DatetimeIndex(t1.iloc[tr])
        assert not ((s <= t_end) & (e >= t_start)).any()
        # embargo dopo il test
        after = tr[tr > te[-1]]
        if len(after):
            assert after.min() - te[-1] > math.ceil(n * 0.02)


def test_walk_forward_no_leakage():
    idx = pd.RangeIndex(1000)
    sp = list(walk_forward_splits(idx, 300, 100, embargo_bars=5))
    assert len(sp) == 6
    for tr, te in sp:
        assert tr.max() + 5 < te.min() and len(tr) == 300 and len(te) == 100
    tests = np.concatenate([te for _, te in sp])
    assert len(set(tests)) == len(tests)
    ex = list(walk_forward_splits(idx, 300, 100, expanding=True))
    assert ex[-1][0][0] == 0 and len(ex[-1][0]) > 300
