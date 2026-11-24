import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from quant.backtest import ExitRules
from quant.core import crypto_perp
from quant.data import generate_bars, generate_bars_with_signal
from quant.models import MetaModel, average_uniqueness, uniqueness_weights
from quant.research import NO_EDGE, build_event_dataset, run_walkforward, t1_series, verdict, write_report

RULES = ExitRules(sl_atr=3.0, tp_atr=3.0, max_hold_bars=24)
FAST = dict(max_iter=60, max_bins=32, n_estimators=100)


def prim(bars, spec, interval, ctx):
    """Primario casuale: un lato +-1 ogni 6 barre (nessuna informazione)."""
    rng = np.random.default_rng(len(bars))
    s = pd.Series(0, index=bars.index)
    i = np.arange(30, len(bars), 6)
    s.iloc[i] = rng.choice([-1, 1], len(i))
    return s


def universe(signal, n=8000, k=4):
    uni = {}
    for i in range(k):
        b = generate_bars_with_signal(n, seed=i, ic=0.20) if signal else generate_bars(n, seed=i)
        uni[f"S{i}USDT"] = (b, crypto_perp(f"S{i}USDT"))
    return uni


def split(ev):
    ts = ev.index.get_level_values("ts")
    cut = ts[int(len(ev) * 0.6)]
    tr = ev[ts < cut]
    return tr[tr.t1 < cut], ev[ts >= cut]


def fit_eval(kind, tr, te):
    w = uniqueness_weights(tr).to_numpy()
    m = MetaModel(kind, **FAST).fit(tr, tr["label"], t1_series(tr), w)
    return m, m.predict_proba(te)


@pytest.fixture(scope="module")
def sig():
    ev = build_event_dataset(universe(True), "1h", prim, RULES, hmm=False, extra_cols=("planted_signal",))
    return (ev,) + split(ev)


@pytest.fixture(scope="module")
def noise():
    ev = build_event_dataset(universe(False), "1h", prim, RULES, hmm=False)
    return (ev,) + split(ev)


def test_planted_signal_recovery(sig):
    _, tr, te = sig
    for kind in ("logit", "hgb"):
        _, p = fit_eval(kind, tr, te)
        assert roc_auc_score(te["label"], p) > 0.55, kind
        top = p >= np.median(p)
        assert te["ret_net"][top].mean() > te["ret_net"].mean()      # espettativa filtrata > non filtrata
    _, p0 = fit_eval("base_rate", tr, te)
    assert abs(roc_auc_score(te["label"], p0) - 0.5) < 1e-9


def test_noise_no_model_has_edge(noise):
    _, tr, te = noise
    for kind in ("logit", "hgb", "rf", "gbm_montecarlo", "base_rate"):
        _, p = fit_eval(kind, tr, te)
        assert roc_auc_score(te["label"], p) < 0.56, kind


def test_gbm_montecarlo_martingale_auc_half(noise):
    _, tr, te = noise
    _, p = fit_eval("gbm_montecarlo", tr, te)
    assert abs(roc_auc_score(te["label"], p) - 0.5) < 0.04
    assert ((p > 0) & (p < 1)).all()


def test_isotonic_calibration_monotone(sig):
    _, tr, te = sig
    m, _ = fit_eval("logit", tr, te)
    raw = np.sort(m.raw_score(te))
    cal = m.calibrate(raw)
    assert (np.diff(cal) >= -1e-12).all()
    assert cal.min() >= 0.0 and cal.max() <= 1.0


def test_uniqueness_weights_range(sig):
    ev, _, _ = sig
    t = ev.index.get_level_values("ts")
    u = average_uniqueness(t[:500], ev["t1"].to_numpy()[:500])
    assert ((u > 0) & (u <= 1)).all() and u.min() < 1
    assert np.allclose(average_uniqueness(pd.DatetimeIndex(["2024-01-01"] * 2),
                                          pd.DatetimeIndex(["2024-01-02"] * 2)), 0.5)
    w = uniqueness_weights(ev, normalize=False)
    assert ((w > 0) & (w <= 1)).all()


def test_noise_report_verdict_no_edge():
    uni = universe(False, n=5200, k=3)
    res = run_walkforward(uni, "1h", prim, RULES, kinds=("base_rate", "gbm_montecarlo", "logit"), train_bars=2500,
                          test_bars=1200, embargo_bars=48, ablation=False, importance=False,
                          hmm_kwargs=dict(n_init=1, n_iter=15), model_params=FAST)
    v = verdict({n: dict(r) for n, r in res.summary.to_dict("index").items()}, res.pbo)
    assert v["verdict"] == NO_EDGE and not v["deployable"]
