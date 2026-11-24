import numpy as np
import pandas as pd

from quant.research import spreads as sp


def _ou_pair(n=1500, seed=0, theta=0.15, sig=1.0):
    r = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-02", periods=n)
    b = 100 + np.cumsum(r.normal(0, 0.5, n))
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = x[t - 1] * (1 - theta) + r.normal(0, sig)
    return pd.Series(b + x + 50, index=idx), pd.Series(b + 50, index=idx)


def _rw_pair(seed, n=1500):
    r = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-02", periods=n)
    return (pd.Series(100 + np.cumsum(r.normal(0, 1, n)), index=idx),
            pd.Series(100 + np.cumsum(r.normal(0, 1, n)), index=idx))


def test_zscore_causal_prefix():
    a, _ = _ou_pair(400)
    full = sp.zscore(a)
    for k in (100, 250, 399):
        assert np.isclose(sp.zscore(a.iloc[:k]).iloc[-1], full.iloc[k - 1])
    a2 = a.copy(); a2.iloc[300:] += 50
    pd.testing.assert_series_equal(sp.zscore(a2).iloc[:300], full.iloc[:300])


def test_s3_z_causal():
    a, b = _ou_pair(700)
    full = sp.s3_pair(a, b)["z"]
    pre = sp.s3_pair(a.iloc[:500], b.iloc[:500])["z"]
    pd.testing.assert_series_equal(pre.iloc[:480], full.iloc[:480])


def test_ou_pair_profitable_gross_s1_s3():
    tot1 = tot3 = 0.0
    for seed in range(3):
        a, b = _ou_pair(seed=seed)
        tot1 += sp.s1_run(a, b, costs=False)["pnl"].sum()
        tot3 += sp.s3_pair(a, b, costs=False)["pnl"].sum()
    assert tot1 > 0 and tot3 > 0


def test_random_walks_no_edge_gross():
    for fn in (lambda a, b: sp.s1_run(a, b, costs=False)["pnl"].sum() / 100,
               lambda a, b: sp.s3_pair(a, b, costs=False)["pnl"].sum()):
        v = np.array([fn(*_rw_pair(s)) for s in range(30)])
        assert abs(v.mean()) < 2.5 * v.std(ddof=1) / np.sqrt(len(v))


def test_costs_per_leg_per_side_abs():
    idx = pd.bdate_range("2020-01-01", periods=5)
    a = np.array([100.0] * 5); b = np.array([100.0] * 5)
    z = np.array([np.nan, 3.0, 0.0, 0.0, 0.0])      # segnale short spread a i=1 -> entry i=2; exit al i=4 (max_hold=2)
    r = sp.run_pairs(a, b, z, np.ones(5), idx, dict(kind="abs", v=0.03, fin=0.0), max_hold=2)
    assert len(r["trades"]) == 1
    assert np.isclose(r["trades"][0]["pnl"], -0.03 * 2 * 2)   # 2 gambe x 2 lati


def test_costs_bps_and_borrow():
    idx = pd.bdate_range("2020-01-01", periods=5)
    a = np.array([100.0] * 5); b = np.array([50.0] * 5)
    z = np.array([np.nan, -3.0, 0.0, 0.0, 0.0])
    r = sp.run_pairs(a, b, z, np.ones(5), idx, dict(kind="bps", v=5e-4, borrow=0.0), max_hold=2, gross=1.0, dollar=True)
    assert np.isclose(r["trades"][0]["pnl"], -5e-4 * 1.0 * 2)   # gross 1 (due gambe da 0.5) x 2 lati
    # long spread = long A, short B: 
    r2 = sp.run_pairs(a, b, z, np.ones(5), idx, dict(kind="bps", v=0.0, borrow=0.01), max_hold=2, gross=1.0, dollar=True)
    assert r2["trades"][0]["pnl"] < 0


def test_grid_runs_and_costs_reduce_pnl():
    a, b = _ou_pair(800)
    g0 = sp.s1_grid(a, b, costs=False)["pnl"].sum(); g1 = sp.s1_grid(a, b, costs=True)["pnl"].sum()
    assert g1 < g0
