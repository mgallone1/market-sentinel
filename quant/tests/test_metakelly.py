"""Deterministic tests of the meta-labeling + Kelly experiment (quant/research/metakelly)."""
import numpy as np
import pandas as pd
import pytest

from quant.research.metakelly import benchmark as bm
from quant.research.metakelly import candidates as cg
from quant.research.metakelly.cv import Fold, assert_no_overlap, purged_expanding_splits
from quant.research.metakelly.labels import equity_time_barrier, triple_barrier
from quant.research.metakelly.model import fit_predict, make_model
from quant.research.metakelly.sizing import kelly_fraction, kelly_weights, max_gross_exposure, simulate_portfolio


def _events(n=400, seed=0):
    rng = np.random.default_rng(seed)
    t0 = pd.date_range("2025-01-01", periods=n, freq="6h", tz="UTC")
    t1 = t0 + pd.to_timedelta(rng.integers(1, 48, n), unit="h")  # overlapping labels up to 2 days
    return t0, pd.DatetimeIndex(t1)


# ---------------------------------------------------------------- 1. no leakage
def test_scaler_and_model_fitted_on_train_only():
    rng = np.random.default_rng(1)
    Xtr = rng.normal(5.0, 2.0, (300, 4))
    ytr = (Xtr[:, 0] + rng.normal(0, 1, 300) > 5).astype(int)
    Xte = rng.normal(-50.0, 30.0, (100, 4))  # wildly different test distribution
    p1, m1 = fit_predict(Xtr, ytr, Xte, C=0.1)
    np.testing.assert_allclose(m1.named_steps["scale"].mean_, Xtr.mean(axis=0))
    np.testing.assert_allclose(m1.named_steps["impute"].statistics_, np.median(Xtr, axis=0))
    _, m2 = fit_predict(Xtr, ytr, Xte * 100 + 7, C=0.1)  # test data cannot influence the fit
    np.testing.assert_allclose(m1.named_steps["logit"].coef_, m2.named_steps["logit"].coef_)
    assert p1.shape == (100,) and ((p1 > 0) & (p1 < 1)).all()


def test_imputation_uses_train_medians():
    Xtr = np.array([[1.0, np.nan], [3.0, 2.0], [5.0, 4.0], [7.0, 6.0]])
    ytr = np.array([0, 1, 0, 1])
    Xte = np.array([[np.nan, np.nan]])
    _, m = fit_predict(Xtr, ytr, Xte, C=1.0)
    np.testing.assert_allclose(m.named_steps["impute"].statistics_, [4.0, 4.0])


def test_single_class_train_falls_back_to_base_rate():
    p, m = fit_predict(np.zeros((5, 2)), np.ones(5), np.zeros((3, 2)), C=1.0)
    assert m is None and np.allclose(p, 1.0)


def test_l2_regularisation_shrinks_coefficients():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(500, 3))
    y = (X[:, 0] > 0).astype(int)
    c_small = np.abs(make_model(0.01).fit(X, y).named_steps["logit"].coef_).sum()
    c_big = np.abs(make_model(1.0).fit(X, y).named_steps["logit"].coef_).sum()
    assert c_small < c_big


# ---------------------------------------------------------------- 2. purging / embargo
def test_purged_embargoed_expanding_folds():
    t0, t1 = _events()
    emb = pd.Timedelta(hours=24)
    folds = list(purged_expanding_splits(t0, t1, t0[100], pd.Timedelta(days=10), emb))
    assert len(folds) >= 5
    seen = np.concatenate([f.test_idx for f in folds])
    assert len(seen) == len(set(seen)) == (t0 >= t0[100]).sum()  # every OOS event tested exactly once
    prev_train = 0
    for f in folds:
        assert_no_overlap(t0, t1, f, emb)
        assert (t1[f.train_idx] < f.test_start).all()
        assert (t0[f.train_idx] <= f.test_start - emb).all()
        assert ((t0[f.test_idx] >= f.test_start) & (t0[f.test_idx] < f.test_end)).all()
        assert len(f.train_idx) >= prev_train  # expanding
        prev_train = len(f.train_idx)
        assert f.n_purged + f.n_embargoed > 0
    # purged events are exactly those straddling the boundary
    f = folds[0]
    before = np.flatnonzero(t0 < f.test_start)
    straddle = before[t1[before] >= f.test_start]
    assert not np.intersect1d(straddle, f.train_idx).size


def test_assert_no_overlap_detects_leakage():
    t0, t1 = _events(50)
    bad = Fold(np.arange(0, 30), np.arange(30, 50), t0[30], t0[49], 0, 0)
    with pytest.raises(AssertionError):
        assert_no_overlap(t0, t1, bad, pd.Timedelta(hours=24))


def test_invalid_label_intervals_rejected():
    t0 = pd.date_range("2025-01-01", periods=3, freq="1h", tz="UTC")
    with pytest.raises(ValueError):
        list(purged_expanding_splits(t0, t0 - pd.Timedelta(hours=1), t0[1], pd.Timedelta(hours=1), pd.Timedelta(0)))


# ---------------------------------------------------------------- 3. Kelly + 70% cap
def test_kelly_formula_and_limits():
    np.testing.assert_allclose(kelly_fraction(0.5, 1.0), 0.0)
    np.testing.assert_allclose(kelly_fraction(0.4, 3.0), (0.4 * 3 - 0.6) / 3)
    np.testing.assert_allclose(kelly_fraction(1.0, 2.0), 1.0)
    np.testing.assert_allclose(kelly_fraction(0.3, 1e9), 0.3, atol=1e-8)  # R -> inf: f* -> p
    assert kelly_fraction(0.2, 2.0) < 0
    assert kelly_fraction(0.5, 0.0) == 0.0  # degenerate payoff
    w = kelly_weights(np.array([0.2, 0.4, 0.9]), np.array([2.0, 3.0, 3.0]), c=0.25, w_max=0.10)
    np.testing.assert_allclose(w, [0.0, 0.25 * (0.4 * 3 - 0.6) / 3, 0.10])
    assert (kelly_weights(np.random.default_rng(3).uniform(0, 1, 1000), 3.0, 0.15) <= 0.10).all()


def test_portfolio_cap_one_per_symbol_and_release():
    t = pd.Timestamp("2025-01-01", tz="UTC")
    ev = pd.DataFrame({
        "t0": [t] * 9 + [t + pd.Timedelta(hours=1), t + pd.Timedelta(hours=3)],
        "t1": [t + pd.Timedelta(hours=2)] * 9 + [t + pd.Timedelta(hours=2), t + pd.Timedelta(hours=4)],
        "symbol": [f"S{i}" for i in range(8)] + ["S0", "S9", "S0"],
        "ret": 0.01,
    })
    w = np.full(len(ev), 0.10)
    tr = simulate_portfolio(ev, w)
    # 8 distinct symbols at t: 7 x 0.10 fit, the 8th gets the 0.0 residual -> skipped; duplicate S0 skipped
    assert max_gross_exposure(tr) <= 0.70 + 1e-12
    assert (tr["t0"] == t).sum() == 7
    assert "S9" not in set(tr["symbol"])  # cap still full at t+1h
    late = tr[tr["t0"] == t + pd.Timedelta(hours=3)]
    assert len(late) == 1 and late["symbol"].iloc[0] == "S0"  # weight released after t1
    np.testing.assert_allclose(tr["pnl"], tr["w"] * tr["ret"])


def test_partial_allocation_and_min_alloc():
    t = pd.Timestamp("2025-01-01", tz="UTC")
    ev = pd.DataFrame({"t0": [t, t, t], "t1": [t + pd.Timedelta(hours=1)] * 3, "symbol": ["A", "B", "C"], "ret": 0.0})
    tr = simulate_portfolio(ev, np.array([0.40, 0.25, 0.10]))
    np.testing.assert_allclose(tr["w"].to_numpy(), [0.40, 0.25, 0.05])  # 0.05 = residual to the cap
    tr2 = simulate_portfolio(ev, np.array([0.40, 0.295, 0.10]))
    assert len(tr2) == 2  # residual 0.005 < 0.01 -> skipped
    assert len(simulate_portfolio(ev, np.zeros(3))) == 0  # f* <= 0 never traded


# ---------------------------------------------------------------- 4. beta-adjusted benchmark
def test_beta_adjusted_excess_removes_market_exposure():
    rng = np.random.default_rng(4)
    days = pd.date_range("2024-01-01", periods=600, freq="B")
    bench = pd.Series(rng.normal(0.0005, 0.01, len(days)), index=days)
    alpha = pd.Series(rng.normal(0.0002, 0.002, len(days)), index=days)
    strat = 1.5 * bench + alpha
    out = bm.beta_adjusted_excess(strat, bench, window=60, min_obs=20)
    assert abs(out["beta"].iloc[100:].mean() - 1.5) < 0.05
    tail = out.iloc[100:]
    np.testing.assert_allclose(tail["excess"], tail["strat"] - tail["beta"] * tail["bench"])
    assert np.corrcoef(tail["excess"], tail["bench"])[0, 1] < 0.1
    assert np.corrcoef(tail["excess"], alpha.iloc[100:])[0, 1] > 0.9
    # pure beta strategy: excess Sharpe ~ 0 while net Sharpe is the market's
    pure = bm.beta_adjusted_excess(1.5 * bench, bench)["excess"].iloc[100:]
    assert abs(pure.mean()) < 1e-5


def test_rolling_beta_is_point_in_time():
    rng = np.random.default_rng(5)
    days = pd.date_range("2024-01-01", periods=200, freq="B")
    bench = pd.Series(rng.normal(0, 0.01, 200), index=days)
    strat = 2.0 * bench + rng.normal(0, 0.003, 200)
    b1 = bm.rolling_beta(strat, bench)
    shocked = bench.copy()
    shocked.iloc[150] = 0.5  # a shock on day t must not change beta_t, only beta_{t+1}
    b2 = bm.rolling_beta(strat, shocked)
    assert b1.iloc[150] == pytest.approx(b2.iloc[150])
    assert b1.iloc[151] != pytest.approx(b2.iloc[151])


def test_trade_excess_and_profit_factor():
    ex = bm.trade_excess(np.array([0.02, -0.01]), np.array([1, -1]), np.array([1.2, 0.8]), np.array([0.01, -0.02]))
    np.testing.assert_allclose(ex, [0.02 - 1.2 * 0.01, -0.01 - (-1) * 0.8 * (-0.02)])
    assert bm.profit_factor(np.array([0.03, -0.01, -0.02])) == pytest.approx(1.0)
    days = pd.date_range("2025-01-01", periods=3, freq="D")
    tr = pd.DataFrame({"t1": pd.DatetimeIndex(["2025-01-02 10:00", "2025-01-02 23:00", "2025-01-03 01:00"], tz="UTC"),
                       "pnl": [0.01, 0.02, -0.005]})
    d = bm.daily_pnl(tr, days)
    np.testing.assert_allclose(d.to_numpy(), [0.0, 0.03, -0.005])


# ---------------------------------------------------------------- labels and stage-1 replay
def test_triple_barrier_sl_first_tp_and_time():
    h = np.array([100, 101.0, 103.5, 100.0])
    l = np.array([100, 98.5, 99.0, 99.0])
    c = np.array([100, 100.0, 103.0, 100.0])
    r = triple_barrier(h, l, c, 0, 1, 1.0, 3.0, 3, 0.001, 0.0003)
    assert r["outcome"] == "SL" and r["y"] == 0 and r["ret"] == pytest.approx(-0.01 - 0.0013)
    h2 = np.array([100, 100.5, 103.5, 100.0])
    l2 = np.array([100, 99.5, 99.5, 99.0])
    r2 = triple_barrier(h2, l2, c, 0, 1, 1.0, 3.0, 3, 0.001, 0.0)
    assert r2["outcome"] == "TP" and r2["y"] == 1 and r2["ret"] == pytest.approx(0.03 - 0.001)
    r3 = triple_barrier(h2, l2, c, 0, -1, 5.0, 5.0, 3, 0.001, 0.0)
    assert r3["outcome"] == "TIME" and r3["ret"] == pytest.approx(-0.001)
    assert triple_barrier(h, l, c, 3, 1, 1.0, 3.0, 3, 0.0, 0.0) is None


def test_equity_time_barrier_regular_and_early_close():
    reg = pd.date_range("2026-11-25 09:30", periods=7, freq="1h", tz="America/New_York").tz_convert("UTC")
    tb = equity_time_barrier(reg, 60)
    assert tb[0] == 5  # last bar ending by 15:52 ET is the 14:30 bar (ends 15:30)
    assert tb[6] == 6  # 15:30 bar: no forward bar
    early = pd.date_range("2026-11-27 09:30", periods=4, freq="1h", tz="America/New_York").tz_convert("UTC")
    tbe = equity_time_barrier(early, 60)
    assert tbe[0] == 2  # 11:30 bar ends 12:30 <= 12:52; 12:30 bar ends 13:00 > 12:52


def test_prefilters_are_necessary_conditions_of_live_engines():
    from services.strategy_engines_service import engine_intraday_momentum, engine_liquidity_sweep_mr

    rng = np.random.default_rng(6)
    n = 700
    c = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.006, n)))
    o = np.r_[100, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": rng.uniform(500, 3000, n)}, index=idx)
    cvd = {"ratio": 1.5, "bias": "NEUTRAL"}
    hits_m = hits_s = 0
    for i in range(60, n):
        win = df.iloc[i - 179 if i >= 179 else 0:i + 1]
        m = engine_intraday_momentum(win, "BULLISH", {}, cvd, None, 0.0, 2.0, False, interval_minutes=None)
        if m.get("triggered"):
            hits_m += 1
            assert cg._momentum_possible(h, l, c, i)
        s = engine_liquidity_sweep_mr(win, cvd, None, 0.0, "NEUTRAL", interval_minutes=None)
        if s:
            hits_s += 1
            assert cg._sweep_possible(h, l, c, i)
    assert hits_m > 0 and hits_s > 0
