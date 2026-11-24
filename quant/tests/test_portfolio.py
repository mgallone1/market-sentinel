import numpy as np
import pandas as pd

from quant.portfolio import block_bootstrap_sharpe_diff, run_weights, tsmom_weights


def synth(n=1500, k=6, seed=0, drift=0.0003, vol=0.01):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n, tz="UTC")
    r = rng.normal(drift, vol, (n, k)) * rng.uniform(0.5, 2, k)
    return pd.DataFrame(100 * np.cumprod(1 + r, axis=0), index=idx, columns=[f"A{i}" for i in range(k)])


def test_prefix_no_lookahead():
    p = synth(900)
    full = tsmom_weights(p, freq="weekly")
    cut = p.index[700]
    pre = tsmom_weights(p.loc[:cut], freq="weekly")
    d = pre.index[-30]
    pd.testing.assert_series_equal(full.loc[d], pre.loc[d], check_names=False)


def test_constant_weights_hand_computed():
    idx = pd.bdate_range("2020-01-01", periods=4, tz="UTC")
    p = pd.DataFrame({"A": [100, 110, 99, 108.9], "B": [50, 50, 55, 55]}, index=idx)
    w = pd.DataFrame({"A": 0.5, "B": -0.5}, index=idx)
    res = run_weights(p, w, pd.Series({"A": 10, "B": 20}), pd.Series({"A": 0.0, "B": 0.252}))
    ra = p.A.pct_change().fillna(0); rb = p.B.pct_change().fillna(0)
    # w tenuto da t=1 (deciso a 0); costo ingresso al giorno 1: .5*10bp+.5*20bp ; borrow B .5*.252/252
    exp1 = 0.5 * ra.iloc[1] - 0.5 * rb.iloc[1] - (0.5 * 10 + 0.5 * 20) / 1e4 - 0.5 * 0.001
    assert abs(res.net.iloc[1] - exp1) < 1e-12
    exp2 = 0.5 * ra.iloc[2] - 0.5 * rb.iloc[2] - 0.5 * 0.001
    assert abs(res.net.iloc[2] - exp2) < 1e-12
    assert res.net.iloc[0] == 0


def test_vol_target_and_long_only():
    p = synth(2500, k=8, seed=3, drift=0.0)
    w = tsmom_weights(p, freq="monthly")
    assert w.abs().sum(axis=1).max() <= 2.0 + 1e-9
    res = run_weights(p, w, pd.Series(0.0, index=p.columns), pd.Series(0.0, index=p.columns))
    r = res.gross.iloc[400:]
    assert abs(r.std() * np.sqrt(252) - 0.10) < 0.02
    lo = tsmom_weights(p, freq="weekly", mode="long_only")
    assert (lo >= 0).all().all()


def test_no_weight_before_first_price():
    p = synth(800, k=4)
    p.iloc[:400, 3] = np.nan
    w = tsmom_weights(p, freq="weekly")
    assert (w["A3"].iloc[:400] == 0).all()
    w2 = pd.DataFrame(0.25, index=p.index, columns=p.columns)
    res = run_weights(p, w2, pd.Series(0.0, index=p.columns), pd.Series(0.0, index=p.columns))
    assert (res.weights["A3"].iloc[:401] == 0).all()


def test_bootstrap_ci_contains_zero():
    hits = 0
    for s in range(20):
        rng = np.random.default_rng(s)
        a = pd.Series(rng.normal(0, 0.01, 1000)); b = pd.Series(rng.normal(0, 0.01, 1000))
        _, lo, hi = block_bootstrap_sharpe_diff(a, b, block=20, n=300, seed=s)
        hits += lo <= 0 <= hi
    assert hits >= 16
