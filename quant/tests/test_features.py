import time

import numpy as np
import pandas as pd
import pytest

from quant.core import crypto_perp, equity
from quant.features import GaussianHMM, TrendRegime, build_features
from quant.features import indicators as ind
from quant.features.cycles import rolling_dominant_cycle
from quant.features.regime import regime_features


def make_bars(n, seed=0, with_deriv=True):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-04", periods=n, freq="1h", tz="UTC", name="ts")
    r = rng.normal(0, 0.006, n)
    close = 100 * np.exp(np.cumsum(r))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.003, n)))
    vol = np.exp(rng.normal(8, 0.5, n))
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)
    if with_deriv:
        df["taker_buy_volume"] = vol * rng.uniform(0.3, 0.7, n)
        fr = np.full(n, np.nan)
        fr[::8] = rng.normal(1e-4, 5e-5, len(fr[::8]))
        df["funding_rate"] = fr
        df["open_interest"] = 1e6 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return df


@pytest.mark.parametrize("spec", [crypto_perp("BTCUSDT"), equity("AAPL")])
def test_causality_all_columns(spec):
    bars = make_bars(3000, seed=1)
    bench = make_bars(3000, seed=2, with_deriv=False)
    full = build_features(bars, spec, "1h", benchmark=bench)
    assert full.shape[1] > 30 and (full.dtypes == "float64").all()
    assert not np.isinf(full.to_numpy()).any()
    for k in (2300, 2600, 2999):
        part = build_features(bars.iloc[:k], spec, "1h", benchmark=bench.iloc[:k])
        assert list(part.columns) == list(full.columns)
        a, b = part.iloc[k - 1], full.iloc[k - 1]
        for col in full.columns:
            assert (np.isnan(a[col]) and np.isnan(b[col])) or np.isclose(a[col], b[col], rtol=1e-8, atol=1e-10), (k, col)
        pd.testing.assert_frame_equal(part.iloc[-50:], full.iloc[k - 50:k], rtol=1e-8, atol=1e-10)


def test_wilder_rsi_reference():
    c = make_bars(500, seed=3)["close"]
    n = 14
    d = np.diff(c.to_numpy())
    ag = al = None
    ref = [np.nan]
    for x in d:
        g, l = max(x, 0), max(-x, 0)
        ag = g if ag is None else (1 - 1 / n) * ag + g / n
        al = l if al is None else (1 - 1 / n) * al + l / n
        ref.append(100 * ag / (ag + al))
    got = ind.wilder_rsi(c, n).to_numpy()
    assert np.isnan(got[:n]).all()
    np.testing.assert_allclose(got[n:], np.array(ref)[n:], rtol=1e-9)


def test_atr_reference():
    b = make_bars(500, seed=4)
    n = 14
    h, l, c = b["high"].to_numpy(), b["low"].to_numpy(), b["close"].to_numpy()
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    a = [tr[0]]
    for x in tr[1:]:
        a.append((1 - 1 / n) * a[-1] + x / n)
    got = ind.atr_wilder(b, n).to_numpy()
    np.testing.assert_allclose(got[n:], np.array(a)[n:], rtol=1e-9)


def test_cycle_recovers_sinusoid_and_noise_low():
    n = 1500
    rng = np.random.default_rng(5)
    t = np.arange(n)
    idx = pd.date_range("2022-01-01", periods=n, freq="1h", tz="UTC")
    sin = pd.Series(np.exp(0.05 * np.sin(2 * np.pi * t / 24) + 0.0002 * t + rng.normal(0, 0.003, n).cumsum()), index=idx)
    cs = rolling_dominant_cycle(sin)
    tail = cs.iloc[200:]
    assert abs(tail["cycle_period"].median() - 24) <= 2
    assert (np.abs(tail["cycle_period"] - 24) <= 2).mean() > 0.9
    noise = pd.Series(np.exp(rng.normal(0, 0.01, n)), index=idx)
    cn = rolling_dominant_cycle(noise).iloc[200:]
    assert cn["cycle_conc"].median() < 0.5 * tail["cycle_conc"].median()
    rw = pd.Series(np.exp(rng.normal(0, 0.01, n).cumsum()), index=idx)  # red spectrum: concentrato ma meno del ciclo vero
    assert rolling_dominant_cycle(rw).iloc[200:]["cycle_conc"].median() < tail["cycle_conc"].median()
    # fase: sin^2+cos^2 = 1 e step>1 coerente con step=1 sui punti calcolati
    np.testing.assert_allclose(tail["cycle_sin"] ** 2 + tail["cycle_cos"] ** 2, 1.0)
    c4 = rolling_dominant_cycle(sin, step=4)
    m = np.arange(n) % 4 == 0
    pd.testing.assert_frame_equal(c4[m].dropna(), cs[m].dropna())


def test_cycle_phase_tracks_sinusoid():
    n = 600
    t = np.arange(n)
    s = pd.Series(np.exp(0.05 * np.sin(2 * np.pi * t / 24 + 0.7)), index=pd.date_range("2022-01-01", periods=n, freq="1h", tz="UTC"))
    c = rolling_dominant_cycle(s).iloc[200:]
    exp = np.sin(2 * np.pi * t[200:] / 24 + 0.7)
    assert np.corrcoef(c["cycle_sin"], exp)[0, 1] > 0.9


def test_hmm_recovers_regimes_and_filter_causal():
    rng = np.random.default_rng(7)
    T = 3000
    z = np.zeros(T, int)
    for t in range(1, T):
        z[t] = z[t - 1] if rng.random() < 0.98 else 1 - z[t - 1]
    X = np.column_stack([rng.normal(np.where(z == 0, -1.0, 1.0), 1.0),
                         rng.normal(0, np.where(z == 0, 1.5, 0.6))])
    h = GaussianHMM(2, n_init=4, seed=1).fit(X)
    p = h.filter_proba(X)
    assert (p.argmax(1) == z).mean() > 0.8
    np.testing.assert_allclose(p.sum(1), 1.0)
    for k in (100, 1000, 2500):
        np.testing.assert_allclose(h.filter_proba(X[:k]), p[:k], atol=1e-12)
    h3 = GaussianHMM(3, n_init=2).fit(X)
    assert h3.mu_[0, 0] < h3.mu_[1, 0] < h3.mu_[2, 0]


def test_regime_features_columns():
    b = make_bars(1500, seed=8, with_deriv=False)
    from quant.features.regime import hmm_inputs
    X = hmm_inputs(b)
    h = GaussianHMM(2, n_init=2).fit(X.iloc[:800].dropna().to_numpy())
    rf = regime_features(b, h)
    assert list(rf.columns) == ["reg_p_state0", "reg_p_state1", "reg_trend"]
    assert set(rf["reg_trend"].unique()) <= {-1.0, 0.0, 1.0}


def test_trend_regime_hysteresis():
    b = make_bars(4000, seed=9, with_deriv=False)
    s = TrendRegime(confirm=3).classify(b)
    chg = np.flatnonzero(np.diff(s.to_numpy()) != 0) + 1
    assert len(chg) > 3
    assert (np.diff(chg) >= 3).all()
    assert set(s.unique()) <= {-1, 0, 1}


def test_build_features_runtime_20k():
    bars = make_bars(20000, seed=10)
    bench = make_bars(20000, seed=11, with_deriv=False)
    t0 = time.time()
    f = build_features(bars, crypto_perp("BTCUSDT"), "1h", benchmark=bench)
    dt = time.time() - t0
    print("runtime", dt, f.shape)
    assert dt < 20
