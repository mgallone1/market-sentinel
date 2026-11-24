import numpy as np
import pandas as pd

from quant.research.overnight import apply_costs, decompose, effective_splits, metrics


def _px(n=30, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    c = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, n)), index=idx)
    o = c.shift(1) * (1 + rng.normal(0, 0.004, n))
    o.iloc[0] = 100.0
    return o, c


def test_identity_with_dividends():
    o, c = _px()
    div = pd.Series(0.0, index=o.index)
    div.iloc[[5, 17]] = [0.8, 1.1]
    d = decompose(o, c, div)
    assert np.allclose((1 + d["on"]) * (1 + d["id"]), 1 + d["cc"])
    # dividendo accreditato alla gamba overnight che termina all'open ex-date
    assert np.isclose(d["on"].iloc[4], (o.iloc[5] + 0.8) / c.iloc[4] - 1)
    assert np.isclose(d["id"].iloc[4], c.iloc[5] / o.iloc[5] - 1)
    nodiv = decompose(o, c)
    assert np.allclose(nodiv["id"], d["id"]) and (d["on"] >= nodiv["on"] - 1e-15).all()


def test_cost_per_round_trip():
    c = 1.0 / 1e4
    r = apply_costs(pd.Series([0.0, 0.01]), 1.0)
    assert np.isclose(r.iloc[0], (1 - c) ** 2 - 1)           # ~ -2 bp per giro completo
    assert np.isclose(r.iloc[1], 1.01 * (1 - c) ** 2 - 1)
    assert np.isclose(r.iloc[0], -2e-4, atol=1e-8)
    assert (apply_costs(pd.Series([0.0]), 0.0) == 0).all()


def test_split_handling_synthetic():
    idx = pd.bdate_range("2021-01-04", periods=4)
    close = pd.Series([100.0, 100.0, 51.0, 52.0], index=idx)   # split 2:1 non aggiustato
    open_ = pd.Series([100.0, 100.0, 50.0, 51.0], index=idx)
    split = pd.Series([0.0, 0.0, 2.0, 0.0], index=idx)
    s = effective_splits(open_, close, split)
    assert list(s.index) == [idx[2]]
    d = decompose(open_, close, None, s)
    assert np.isclose(d["on"].loc[idx[2]], 50 * 2 / 100 - 1)   # +0%: lo split non e' un rendimento
    assert np.isclose(d["id"].loc[idx[2]], 51 / 50 - 1)
    assert np.allclose((1 + d["on"]) * (1 + d["id"]), 1 + d["cc"])
    assert abs(decompose(open_, close)["on"].loc[idx[2]]) > 0.4  # senza fattore: errore -50%
    # prezzi gia' aggiustati (nessun salto): lo split non viene applicato
    adj = pd.Series([50.0, 50.0, 51.0, 52.0], index=idx)
    assert effective_splits(adj, adj, split).empty


def test_metrics_basic():
    r = pd.Series(0.001, index=pd.bdate_range("2020-01-01", periods=252))
    m = metrics(r)
    assert m["maxdd"] == 0 and m["cagr"] > 0.25
