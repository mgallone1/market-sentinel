import numpy as np
import pandas as pd

from quant.portfolio.backtest import run_weights
from quant.portfolio.vrp import cash_index, v1_signal, v2_signal


def synth(n=2000, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2000-01-03", periods=n)
    spy = pd.Series(100 * np.cumprod(1 + rng.normal(3e-4, 0.01, n)), index=idx)
    vix = pd.Series(np.clip(18 + np.cumsum(rng.normal(0, 0.6, n)) * 0.2, 9, 60), index=idx)
    vix3m = vix * pd.Series(rng.uniform(0.9, 1.1, n), index=idx)
    return vix, vix3m, spy


def test_v1_prefix_and_cash_when_backwardation():
    vix, v3, _ = synth()
    full = v1_signal(vix, v3)
    cut = 1200
    pre = v1_signal(vix.iloc[:cut], v3.iloc[:cut])
    pd.testing.assert_series_equal(full.iloc[:cut], pre)
    assert (full[(vix / v3) >= 1.0] == 0).all() and (full[(vix / v3) < 1.0] == 1).all()
    eq = pd.Series([1.0, 1.0], index=pd.bdate_range("2020-01-01", periods=2))
    assert v1_signal(eq * 20, eq * 20).iloc[0] == 0  # ratio == 1 -> cash


def test_v2_prefix_and_month_end_only():
    vix, _, spy = synth()
    full = v2_signal(vix, spy)
    cut = 1700
    pre = v2_signal(vix.iloc[:cut], spy.iloc[:cut])
    d = pre.dropna().index[:-25]
    pd.testing.assert_series_equal(full.loc[d], pre.loc[d])
    f = full.dropna()
    chg = f.index[f.diff().fillna(0) != 0]
    month_ends = set(vix.groupby([vix.index.year, vix.index.month]).tail(1).index)
    assert len(chg) > 3 and all(t in month_ends for t in chg)
    assert full.first_valid_index() > vix.index[60 * 21 - 1]  # servono 60 mesi di storia


def test_tbill_accrual_on_cash():
    idx = pd.bdate_range("2020-01-01", periods=6)
    irx = pd.Series(2.52, index=idx)
    c = cash_index(irx)
    assert abs(c.iloc[2] / c.iloc[1] - 1 - 0.0252 / 252) < 1e-12
    P = pd.DataFrame({"CASH": c, "X": 100.0}, index=idx)
    w = pd.DataFrame({"CASH": 1.0, "X": 0.0}, index=idx)
    r = run_weights(P, w, pd.Series({"CASH": 0.0, "X": 5.0}), pd.Series({"CASH": 0.0, "X": 0.0})).net
    assert abs(r.iloc[3] - 0.0252 / 252) < 1e-12
