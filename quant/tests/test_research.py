import json

import numpy as np
import pandas as pd
import pytest

from quant.backtest import ExitRules
from quant.core import crypto_perp
from quant.data import generate_bars_with_signal
from quant.features import GaussianHMM
from quant.live import MetaGate, train_gate
from quant.research import build_event_dataset, run_walkforward, write_report

RULES = ExitRules(sl_atr=3.0, tp_atr=3.0, max_hold_bars=24)
TRAIN, TEST, EMB = 2500, 1200, 5
FAST = dict(max_iter=40, max_bins=32, n_estimators=50)


def prim(bars, spec, interval, ctx):
    """Primario banale: segno del rendimento a 24 barre, valutato ogni 6 barre."""
    r = bars["close"].pct_change(24)
    s = np.sign(r).fillna(0).astype(int)
    keep = np.zeros(len(s), bool)
    keep[30::6] = True
    return s.where(keep, 0)


def uni3():
    return {f"S{i}USDT": (generate_bars_with_signal(5200, seed=i, ic=0.2), crypto_perp(f"S{i}USDT")) for i in range(3)}


@pytest.fixture(scope="module")
def wf(tmp_path_factory):
    calls = []
    orig = GaussianHMM.fit

    def rec(self, X):
        calls.append(len(np.asarray(X)))
        return orig(self, X)

    GaussianHMM.fit = rec
    try:
        uni = uni3()
        res = run_walkforward(uni, "1h", prim, RULES, kinds=("base_rate", "gbm_montecarlo", "logit"),
                              train_bars=TRAIN, test_bars=TEST, embargo_bars=EMB, ablation=True, importance=True,
                              hmm_kwargs=dict(n_init=1, n_iter=15), model_params=FAST, extra_cols=("planted_signal",))
    finally:
        GaussianHMM.fit = orig
    return uni, res, calls, tmp_path_factory.mktemp("rep")


def test_no_leakage_and_purge(wf):
    uni, res, calls, _ = wf
    ev = build_event_dataset(uni, "1h", prim, RULES, hmm=False)
    ts, t1 = ev.index.get_level_values("ts"), pd.DatetimeIndex(ev["t1"])
    assert len(res.folds) >= 2
    for _, f in res.folds.iterrows():
        assert f.max_train_t1 < f.test_start                  # nessun train t1 dentro il test
        assert f.train_end < f.test_start
        in_train = (ts >= f.train_start) & (ts <= f.train_end)
        assert int((in_train & (t1 >= f.test_start)).sum()) == f.n_purged   # eventi sovrapposti rimossi
        assert f.n_train == int((in_train & (t1 < f.test_start)).sum())
    assert res.folds.n_purged.sum() > 0


def test_hmm_fitted_on_train_only(wf):
    uni, res, calls, _ = wf
    assert len(calls) == len(res.folds)
    for n, (_, f) in zip(calls, res.folds.iterrows()):
        # righe usate <= barre di train di tutti i simboli (3 x TRAIN), mai quelle di test
        assert n <= 3 * TRAIN
        assert n < 3 * (TRAIN + TEST)


def test_walkforward_end_to_end_and_report(wf):
    _, res, _, tmp = wf
    for n in ("primary_only", "random@logit", "logit", "base_rate", "gbm_montecarlo"):
        assert n in res.summary.index
    assert res.summary.loc["primary_only", "n_trades"] > 0
    assert {"auc", "oos_logloss", "dsr", "expectancy_ret"} <= set(res.summary.columns)
    assert len(res.ablation) > 0
    d = write_report(res, tmp / "r", "test")
    j = json.loads((tmp / "r" / "report.json").read_text())
    assert j["verdict"] == d["verdict"] and "summary" in j
    md = (tmp / "r" / "report.md").read_text()
    assert "Verdetto" in md and "primary_only" in md


def test_metagate_roundtrip_and_refusal(tmp_path):
    uni = uni3()
    bars, spec = uni["S0USDT"]
    nd = {"verdict": "NO EDGE — do not deploy", "deployable": False, "deployable_kinds": []}
    g = train_gate(uni, "1h", prim, RULES, "logit", None, nd, hmm_kwargs=dict(n_init=1, n_iter=10))
    side = int(prim(bars, spec, "1h", {}).iloc[-60:].replace(0, np.nan).dropna().iloc[-1])
    out = g.decide(bars, spec, "1h", side)
    assert out["allow"] is False and out["reason"] == "model not deployable"
    f = g.decide(bars, spec, "1h", side, force=True)
    assert 0 < f["p"] < 1 and set(out) == {"allow", "p", "p_star", "size_frac", "reason"}
    path = tmp_path / "g.pkl"
    g.save(path)
    g2 = MetaGate.load(path)
    assert g2.meta["verdict"] == nd["verdict"] and g2.columns == g.columns
    assert g2.decide(bars, spec, "1h", side, force=True)["p"] == pytest.approx(f["p"])
    # deployable: decisione basata solo su p vs p*, barre chiuse
    ok = {"verdict": "DEPLOYABLE: logit", "deployable": True, "deployable_kinds": ["logit"]}
    g3 = train_gate(uni, "1h", prim, RULES, "logit", None, ok, hmm_kwargs=dict(n_init=1, n_iter=10))
    r = g3.decide(bars, spec, "1h", side)
    assert r["reason"] != "model not deployable"
    assert r["allow"] == (r["p"] > r["p_star"]) and (r["size_frac"] > 0) == r["allow"]
