"""Walk-forward OOS del meta-labeling: primario -> filtro p>p* -> backtest sulla sola finestra di test."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from quant.backtest import (ExitRules, breakeven_probability, fractional_kelly, run_portfolio,
                            vol_target_fraction)
from quant.core import interval_to_hours
from quant.models import MetaModel, family_columns, feature_columns, uniqueness_weights
from quant.research.dataset import (add_regime_features, build_event_dataset, fit_hmm, t1_series)
from quant.validation import (brier_score, calibration_table, deflated_sharpe_ratio, log_loss, pbo_cscv,
                              spearman_ic, walk_forward_splits)

log = logging.getLogger(__name__)
DEFAULT_KINDS = ("base_rate", "gbm_montecarlo", "logit", "hgb", "rf", "ensemble")
ML_KINDS = ("logit", "hgb", "rf", "ensemble")
MIN_FRAC = 0.01


def size_fractions(p, payoff: float, sigma_ann, sizing: str = "kelly", lam: float = 0.25, cap: float = 0.25,
                   vol_target: float = 0.30, fixed: float = 0.10) -> np.ndarray:
    """Frazione di equity per trade: Kelly frazionale (capped) x vol targeting; oppure fissa."""
    p = np.atleast_1d(np.asarray(p, float))
    if sizing == "fixed":
        return np.full(len(p), float(fixed))
    sg = np.nan_to_num(np.broadcast_to(np.asarray(sigma_ann, float), p.shape), nan=0.0)
    k = np.array([fractional_kelly(float(x), payoff, lam, cap) for x in p])
    v = np.array([vol_target_fraction(float(s), vol_target, 1.0) for s in sg])
    return np.maximum(k * v, MIN_FRAC)


def payoff_stats(ret_net) -> dict:
    r = np.asarray(ret_net, float)
    w, lo = r[r > 0], r[r <= 0]
    aw = float(w.mean()) if len(w) else 0.0
    al = float(-lo.mean()) if len(lo) else 0.0
    if aw <= 0 or al <= 0:
        return dict(avg_win=aw, avg_loss=al, payoff=1.0, p_star=0.5)
    return dict(avg_win=aw, avg_loss=al, payoff=aw / al, p_star=breakeven_probability(aw, al, 0.0))


@dataclass
class WalkForwardResult:
    config: dict
    summary: pd.DataFrame
    folds: pd.DataFrame
    returns: pd.DataFrame
    details: dict
    pbo: float
    n_trials: int
    best_kind: str | None = None
    ablation: pd.DataFrame = field(default_factory=pd.DataFrame)
    importance: pd.Series = field(default_factory=pd.Series)
    predictions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        def clean(o):
            if isinstance(o, dict):
                return {str(k): clean(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [clean(v) for v in o]
            if isinstance(o, (np.floating, float)):
                return None if not math.isfinite(float(o)) else float(o)
            if isinstance(o, np.integer):
                return int(o)
            if isinstance(o, (pd.Timestamp,)):
                return o.isoformat()
            return o
        return clean(dict(
            config=self.config, pbo=self.pbo, n_trials=self.n_trials, best_kind=self.best_kind,
            summary=self.summary.reset_index().to_dict("records"),
            folds=self.folds.astype(str).to_dict("records"),
            ablation=self.ablation.reset_index().to_dict("records") if len(self.ablation) else [],
            importance=self.importance.to_dict(), details=self.details))


def _cfg_name(kind, thr, multi):
    return f"{kind}@{thr}" if multi else kind


def _daily(eq: pd.Series, a, b) -> pd.Series:
    e = eq.loc[a:b]
    return e.resample("1D").last().ffill().pct_change().dropna()


def _agg_trades(tr: pd.DataFrame) -> dict:
    nan = float("nan")
    if tr is None or not len(tr):
        return dict(n_trades=0, win_rate=nan, expectancy_ret=nan, profit_factor=nan, avg_win=nan, avg_loss=nan)
    r = tr["ret_net"].astype(float)
    w, lo = r[r > 0], r[r <= 0]
    return dict(n_trades=int(len(r)), win_rate=float(len(w) / len(r)), expectancy_ret=float(r.mean()),
                profit_factor=float(w.sum() / -lo.sum()) if lo.sum() < 0 else nan,
                avg_win=float(w.mean()) if len(w) else nan, avg_loss=float(-lo.mean()) if len(lo) else nan)


def _ret_stats(r: pd.Series, days_per_year: float) -> dict:
    if len(r) < 2:
        return dict(sharpe=float("nan"), max_dd=float("nan"), total_return=float("nan"))
    sd = r.std()
    eq = (1 + r).cumprod()
    return dict(sharpe=float(r.mean() / sd * math.sqrt(days_per_year)) if sd > 0 else float("nan"),
                max_dd=float((eq / eq.cummax() - 1).min()), total_return=float(eq.iloc[-1] - 1))


def run_walkforward(universe: dict, interval: str, primary, rules: ExitRules, kinds=DEFAULT_KINDS,
                    train_bars: int = 2000, test_bars: int = 500, embargo_bars: int = 48,
                    threshold="breakeven", sizing: str = "kelly", benchmark=None, expanding: bool = False,
                    step_bars: int | None = None, hmm_kwargs: dict | None = None, extra_cols=(),
                    min_gap_bars: int = 0, kelly_lam: float = 0.25, kelly_cap: float = 0.25,
                    vol_target: float = 0.30, fixed_frac: float = 0.10, seed: int = 0, ablation: bool = True,
                    importance: bool = True, min_train_events: int = 150, model_params: dict | None = None,
                    ) -> WalkForwardResult:
    rng = np.random.default_rng(seed)
    thresholds = list(threshold) if isinstance(threshold, (list, tuple)) else [threshold]
    multi = len(thresholds) > 1
    kinds = tuple(kinds)
    mp = model_params or {}
    events = build_event_dataset(universe, interval, primary, rules, benchmark, hmm=False, extra_cols=extra_cols,
                                 min_gap_bars=min_gap_bars)
    ts_all = events.index.get_level_values("ts")
    sym_all = np.asarray(events.index.get_level_values("symbol"))
    union = None
    for bars, _ in universe.values():
        union = bars.index if union is None else union.union(bars.index)
    spec0 = next(iter(universe.values()))[1]
    dpy = 365.0 if spec0.session == "24/7" else 252.0
    hold = int(rules.max_hold_bars)

    names_cfg = {}                                  # nome -> (kind, thr, role)
    for k in kinds:
        for t in thresholds:
            names_cfg[_cfg_name(k, t, multi)] = (k, t, "model")
    names_cfg["primary_only"] = ("primary_only", None, "control")
    for k in kinds:
        for t in thresholds:
            names_cfg["random@" + _cfg_name(k, t, multi)] = (k, t, "control")
    trades = {n: [] for n in names_cfg}
    rets = {n: [] for n in names_cfg}
    accepted = {n: [0, 0] for n in names_cfg}
    preds = {k: [] for k in kinds}                  # DataFrame(p, y, ret_net)
    fold_rows, fold_cache = [], []

    for tr_i, te_i in walk_forward_splits(union, train_bars, test_bars, step_bars, embargo_bars, expanding):
        tr_s, tr_e = union[tr_i[0]], union[tr_i[-1]]
        te_s, te_e = union[te_i[0]], union[te_i[-1]]
        t1v = pd.DatetimeIndex(events["t1"].to_numpy())
        in_train = (ts_all >= tr_s) & (ts_all <= tr_e)
        tr_mask = in_train & (t1v < te_s)
        n_purged = int((in_train & ~(t1v < te_s)).sum())
        te_mask = (ts_all >= te_s) & (ts_all <= te_e)
        if tr_mask.sum() < min_train_events or te_mask.sum() == 0:
            log.warning("fold saltato: train=%d test=%d", tr_mask.sum(), te_mask.sum())
            continue
        h = fit_hmm(universe, until=tr_e, since=tr_s, **(hmm_kwargs or {}))
        sub = add_regime_features(events[tr_mask | te_mask], universe, h)
        sub_ts = sub.index.get_level_values("ts")
        trn, tst = sub[sub_ts <= tr_e], sub[sub_ts >= te_s]
        assert trn["t1"].max() < te_s, "leakage: t1 di train dentro il test"
        y_tr, y_te = trn["label"].to_numpy(float), tst["label"].to_numpy(float)
        w = uniqueness_weights(trn).to_numpy()
        t1tr = t1_series(trn)
        ps = payoff_stats(trn["ret_net"])
        fold_rows.append(dict(train_start=tr_s, train_end=tr_e, test_start=te_s, test_end=te_e,
                              n_train=len(trn), n_test=len(tst), n_purged=n_purged,
                              max_train_t1=trn["t1"].max(), p_star=ps["p_star"], payoff=ps["payoff"]))
        fold_cache.append((trn, tst, y_tr, y_te, w, t1tr))
        sig_ann = tst["aux_sigma_ann"].to_numpy(float)
        tsym = np.asarray(tst.index.get_level_values("symbol"))
        tts = tst.index.get_level_values("ts")

        # backtest helper sulla sola finestra di test (barre estese per far chiudere i trade)
        def backtest(accept: np.ndarray, size: np.ndarray):
            uni = {}
            for sym, (bars, spec) in universe.items():
                e_pos = min(bars.index.searchsorted(te_e, side="right") - 1 + hold + 2, len(bars) - 1)
                b = bars.loc[te_s:bars.index[max(e_pos, 0)]]
                sig = pd.DataFrame({"side": 0.0, "size_frac": np.nan}, index=b.index)
                m = accept & (tsym == sym)
                if m.any():
                    sig.loc[tts[m], "side"] = tst["side"].to_numpy()[m].astype(float)
                    sig.loc[tts[m], "size_frac"] = size[m]
                uni[sym] = (b, sig, spec)
            res = run_portfolio(uni, rules, interval, size_frac=fixed_frac, max_gross_exposure=0.7)
            return res.trades, _daily(res.equity, te_s, te_e)

        def record(name, accept, size):
            tr_, dr_ = backtest(accept, size)
            trades[name].append(tr_)
            rets[name].append(dr_)
            accepted[name][0] += int(accept.sum())
            accepted[name][1] += len(accept)

        allm = np.ones(len(tst), bool)
        record("primary_only", allm, np.full(len(tst), fixed_frac))
        for kind in kinds:
            m = MetaModel(kind, seed=seed, **mp).fit(trn, y_tr, t1tr, w)
            p = m.predict_proba(tst)
            preds[kind].append(pd.DataFrame({"p": p, "y": y_te, "ret_net": tst["ret_net"].to_numpy(float)}))
            for thr in thresholds:
                pstar = ps["p_star"] if thr == "breakeven" else float(thr)
                acc = p > pstar
                size = size_fractions(p, ps["payoff"], sig_ann, sizing, kelly_lam, kelly_cap, vol_target, fixed_frac)
                nm = _cfg_name(kind, thr, multi)
                record(nm, acc, size)
                k = int(acc.sum())                      # controllo casuale: stessa acceptance rate e stessi size
                racc = np.zeros(len(tst), bool)
                rsize = np.full(len(tst), fixed_frac)
                if k:
                    pick = rng.choice(len(tst), k, replace=False)
                    racc[pick] = True
                    rsize[pick] = rng.permutation(size[acc])
                record("random@" + nm, racc, rsize)

    if not fold_rows:
        raise ValueError("nessun fold valido: riduci train_bars/min_train_events o allunga lo storico")

    # ------------------------------------------------------------ aggregazione
    ret_df = {}
    for n in names_cfg:
        s = pd.concat(rets[n]) if rets[n] else pd.Series(dtype=float)
        ret_df[n] = s[~s.index.duplicated()]
    returns = pd.DataFrame(ret_df).sort_index().fillna(0.0)
    pred_all = {k: pd.concat(v, ignore_index=True) for k, v in preds.items() if v}
    base_ll = log_loss(pred_all["base_rate"]["p"], pred_all["base_rate"]["y"]) if "base_rate" in pred_all else float("nan")
    pred_metrics = {}
    for k, d in pred_all.items():
        yy = d["y"].to_numpy()
        auc = float(roc_auc_score(yy, d["p"])) if len(np.unique(yy)) > 1 else float("nan")
        ll = log_loss(d["p"], d["y"])
        pred_metrics[k] = dict(oos_logloss=ll, logloss_vs_base=ll - base_ll, brier=brier_score(d["p"], d["y"]),
                               auc=auc, ic=spearman_ic(d["p"], d["ret_net"]),
                               calibration=calibration_table(d["p"], d["y"]).to_dict("records"),
                               n_events=int(len(d)))
    model_names = [n for n, v in names_cfg.items() if v[2] == "model"]
    sharpes = np.array([_ret_stats(returns[n], 1.0)["sharpe"] for n in model_names], float)
    var_sr = float(np.nanvar(sharpes)) if np.isfinite(sharpes).sum() > 1 else 0.0
    n_trials = len(model_names)
    details, rows = {}, []
    for n, (k, t, role) in names_cfg.items():
        tr = pd.concat([x for x in trades[n] if len(x)]) if any(len(x) for x in trades[n]) else pd.DataFrame()
        d = dict(kind=k, threshold=t, role=role, **_agg_trades(tr), **_ret_stats(returns[n], dpy),
                 acceptance_rate=accepted[n][0] / max(accepted[n][1], 1))
        r1 = returns[n]
        d["sr_daily"] = float(r1.mean() / r1.std()) if r1.std() > 0 else float("nan")
        d["dsr"] = deflated_sharpe_ratio(r1.to_numpy(), n_trials, var_sr) if role == "model" else float("nan")
        pm = pred_metrics.get(k, {}) if role == "model" else {}
        d.update({a: pm.get(a, float("nan")) for a in ("oos_logloss", "logloss_vs_base", "brier", "auc", "ic")})
        d["calibration"] = pm.get("calibration", [])
        details[n] = d
        rows.append({"config": n, **{a: v for a, v in d.items() if a != "calibration"}})
    summary = pd.DataFrame(rows).set_index("config")

    cols = model_names + ["primary_only"]
    M = returns[cols].to_numpy()
    S = 16
    while S > 2 and M.shape[0] < S:
        S -= 2
    try:
        pbo = pbo_cscv(M, n_splits=S)[0] if len(cols) >= 2 and M.shape[0] >= S >= 2 else float("nan")
    except Exception:  # noqa: BLE001
        pbo = float("nan")

    # --------------------------------------------- ablazione per famiglia di feature
    best = None
    ml = [k for k in kinds if k in ML_KINDS and k in pred_metrics]
    if ml:
        best = min(ml, key=lambda k: pred_metrics[k]["oos_logloss"])
    abl, imp = pd.DataFrame(), pd.Series(dtype=float)
    if best and (ablation or importance):
        cols0 = feature_columns(fold_cache[0][0])
        fams = family_columns(cols0)
        if ablation:
            full = pred_metrics[best]["oos_logloss"]
            out = {}
            for f, fc in fams.items():
                P, Y = [], []
                for trn, tst, y_tr, y_te, w, t1tr in fold_cache:
                    mm = MetaModel(best, seed=seed, n_splits=3, **mp).fit(trn.drop(columns=fc), y_tr, t1tr, w)
                    P.append(mm.predict_proba(tst.drop(columns=fc)))
                    Y.append(y_te)
                ll = log_loss(np.concatenate(P), np.concatenate(Y))
                out[f] = dict(n_cols=len(fc), logloss_without=ll, delta_logloss=ll - full)
            abl = pd.DataFrame(out).T.sort_values("delta_logloss", ascending=False)
            abl.index.name = "family_dropped"
        if importance:
            trn, tst, y_tr, y_te, w, t1tr = fold_cache[-1]
            imp = MetaModel(best, seed=seed, **mp).family_importance(trn, y_tr, t1tr, w, seed=seed)

    cfg = dict(interval=interval, kinds=list(kinds), thresholds=[str(t) for t in thresholds], sizing=sizing,
               train_bars=train_bars, test_bars=test_bars, embargo_bars=embargo_bars, expanding=expanding,
               symbols=list(universe), rules=repr(rules), n_events=int(len(events)),
               n_folds=len(fold_rows), kelly_lam=kelly_lam, kelly_cap=kelly_cap, vol_target=vol_target,
               data_start=str(min(b.index[0] for b, _ in universe.values())),
               data_end=str(max(b.index[-1] for b, _ in universe.values())), seed=seed)
    return WalkForwardResult(cfg, summary, pd.DataFrame(fold_rows), returns, details, pbo, n_trials, best, abl, imp,
                             pred_all)
