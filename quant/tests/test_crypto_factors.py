import numpy as np
import pandas as pd

from quant.portfolio import crypto_factors as cf


def synth(n=200, k=15, seed=0, late=None):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-03", periods=n, freq="D", tz="UTC")
    cols = [f"S{i}USDT" for i in range(k)]
    cols[0] = "BTCUSDT"
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, (n, k)), 0)), index=idx, columns=cols)
    fund = pd.DataFrame(rng.normal(0, 1e-4, (n, k)), index=idx, columns=cols)
    if late:
        close.loc[: idx[late[1]], late[0]] = np.nan
    return close, fund


MON = pd.Timestamp("2022-05-02", tz="UTC")


def test_prefix_no_lookahead():
    close, fund = synth()
    for f in cf.FACTORS:
        a = cf.rebalance_weights(close, fund, MON, f)
        b = cf.rebalance_weights(close.loc[: MON - pd.Timedelta(days=1)], fund.loc[: MON - pd.Timedelta(days=1)], MON, f)
        pd.testing.assert_series_equal(a, b)
        c2 = close.copy()
        c2.loc[MON:] *= 7.0
        pd.testing.assert_series_equal(a, cf.rebalance_weights(c2, fund, MON, f))


def test_dollar_neutral_legs():
    close, fund = synth()
    for f in ("F1", "F2"):
        w = cf.rebalance_weights(close, fund, MON, f)
        assert abs(w.sum()) < 1e-12
        assert abs(w[w > 0].sum() - 0.5) < 1e-12 and abs(w[w < 0].sum() + 0.5) < 1e-12
    w3 = cf.rebalance_weights(close, fund, MON, "F3")
    assert abs(w3.abs().sum() - 1) < 1e-12 and w3[w3 > 0].sum() <= 0.75 + 1e-12 and -w3[w3 < 0].sum() <= 0.75 + 1e-12


def test_funding_sign_short_receives():
    idx = pd.date_range("2022-01-03", periods=14, freq="D", tz="UTC")
    close = pd.DataFrame(100.0, index=idx, columns=["AUSDT", "BUSDT"])
    fund = pd.DataFrame(0.0, index=idx, columns=close.columns)
    fund["AUSDT"] = 0.001
    W = pd.DataFrame({idx[7]: pd.Series({"AUSDT": -0.5, "BUSDT": 0.5})}).T
    r = cf.run_factor(close, fund, W, side_bps=0.0)
    assert r["funding"].iloc[0] > 0 and abs(r["funding"].iloc[0] - 0.5 * 0.001 * 7) < 1e-12
    W2 = pd.DataFrame({idx[7]: pd.Series({"AUSDT": 0.5, "BUSDT": -0.5})}).T
    assert cf.run_factor(close, fund, W2, side_bps=0.0)["funding"].iloc[0] < 0


def test_seasoning_exclusion():
    close, fund = synth(late=("S3USDT", 0))
    close.loc[:, "S3USDT"] = np.nan
    first = close.index[100]
    close.loc[first:, "S3USDT"] = 50.0 + np.arange(len(close) - 100)
    # barra 59 (indice 100+58) -> 59 osservazioni: escluso; 60 osservazioni: incluso
    assert "S3USDT" not in cf.eligible(close, close.index[100 + 58])
    assert "S3USDT" in cf.eligible(close, close.index[100 + 59])
