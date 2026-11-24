import numpy as np
import pandas as pd

from quant.research import oil_grid
from quant.research.oil_grid_regime import daily_params, params_for_sessions, simulate_regime


def _bars(prices, per_day=10, lo=55.0, hi=65.0, step=0.5, on=True):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="h")
    sess = pd.DatetimeIndex(pd.Timestamp("2024-01-01") + pd.to_timedelta(np.arange(len(prices)) // per_day, unit="D"))
    bp = pd.DataFrame({"on": on, "lo": lo, "hi": hi, "step": step}, index=range(len(prices)))
    return pd.Series(prices, index=idx), bp, sess


def _daily(n=400, seed=1):
    r = np.random.default_rng(seed)
    return pd.Series(60 * np.exp(np.cumsum(r.normal(0, 0.015, n))), index=pd.bdate_range("2020-01-01", periods=n))


def test_params_causal_prefix():
    c = _daily()
    full = daily_params(c)
    for k in (100, 250, 399):
        pre = daily_params(c.iloc[:k]).iloc[-1]
        pd.testing.assert_series_equal(pre, full.iloc[k - 1], check_names=False)
    # parametri della sessione t usano solo il giorno t-1
    sess = c.index[100:110]
    ps = params_for_sessions(full, sess)
    assert np.allclose(ps["hi"].to_numpy(), full["hi"].shift(1).loc[sess].to_numpy())
    c2 = c.copy(); c2.iloc[105:] *= 3  # modificare il futuro non cambia i parametri passati
    ps2 = params_for_sessions(daily_params(c2), sess)
    assert np.allclose(ps["hi"].iloc[:6], ps2["hi"].iloc[:6]) and np.array_equal(ps["on"].iloc[:6], ps2["on"].iloc[:6])


def test_kill_switch_flattens():
    x = list(60 + np.sin(np.arange(60) / 2) * 3) + [70.0] * 20
    p, bp, sess = _bars(x)
    r = simulate_regime(p, bp, sess, spread=0.04, fin_annual=0.0)
    assert r["n_kills"] >= 1 and r["open_positions_end"] == 0
    assert abs(r["equity"].iloc[-1] - r["realized"]) < 1e-9


def test_inventory_cap():
    x = 60 + np.linspace(0, 4.9, 80)  # trend dentro al range: l'inventario netto tenderebbe a crescere
    p, bp, sess = _bars(x, lo=50, hi=70, step=0.1)
    r = simulate_regime(p, bp, sess, fin_annual=0.0, cap=3)
    assert r["max_abs_net_inventory"] <= 3


def test_ou_profitable_and_trend_loses_less_than_g0():
    rng = np.random.default_rng(0)
    x = np.empty(1500); x[0] = 60
    for i in range(1, len(x)):
        x[i] = x[i - 1] + 0.5 * (60 - x[i - 1]) + rng.normal(0, 0.6)
    p, bp, sess = _bars(x, per_day=30, lo=55, hi=65, step=0.5)
    r = simulate_regime(p, bp, sess, fin_annual=0.0)
    assert r["equity"].iloc[-1] > 0
    t = 60 + np.linspace(0, 40, 600) + np.random.default_rng(1).normal(0, 0.3, 600)
    p, bp, sess = _bars(t, per_day=30, lo=55, hi=65, step=0.5)
    g1 = simulate_regime(p, bp, sess, fin_annual=0.0)
    g0 = oil_grid.simulate(p, 0.5, 0.04, 0.0, "hold")
    assert g1["equity"].iloc[-1] > g0["final_equity"]
