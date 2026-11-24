"""Meta-labeling: modello secondario p = P(trade profittevole al netto dei costi | feature)."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from scipy.special import ndtr
from threadpoolctl import threadpool_limits
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from quant.features import FEATURE_FAMILIES
from quant.validation import PurgedKFold, log_loss

KINDS = ("logit", "hgb", "rf", "ensemble", "gbm_montecarlo", "base_rate")
MC_COLS = ("aux_mc_mu", "aux_mc_sigma", "aux_mc_h", "side")
P_LO, P_HI = 0.01, 0.99
FAMILIES = tuple(FEATURE_FAMILIES) + ("reg_", "meta_", "ext_")


def feature_columns(df: pd.DataFrame) -> list[str]:
    """Colonne-feature di un dataset di eventi: esclude etichette (side, ret_net, ...) e colonne aux_*."""
    lab = {"side", "ret_net", "label", "t1", "exit_reason", "R"}
    return [c for c in df.columns if c not in lab and not str(c).startswith("aux_")]


def _cols(X) -> list[str]:
    return feature_columns(X)


def family_of(col: str) -> str:
    for f in FAMILIES:
        if str(col).startswith(f):
            return f
    return "other_"


def family_columns(cols) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in cols:
        out.setdefault(family_of(c), []).append(c)
    return out


def _ll(p, y, w=None):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    v = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    return float(np.average(v, weights=w))


class MetaModel:
    def __init__(self, kind: str, n_splits: int = 4, embargo_frac: float = 0.01, seed: int = 0,
                 C_grid=(0.003, 0.03, 0.3, 3.0), **params):
        if kind not in KINDS:
            raise ValueError(f"kind sconosciuto: {kind}")
        self.kind, self.n_splits, self.embargo_frac, self.seed = kind, n_splits, embargo_frac, seed
        self.C_grid, self.params = tuple(C_grid), params
        self.fitted = False

    # ------------------------------------------------------------------ basi
    def _base(self, kind: str, n: int, C: float = 0.1):
        msl = max(5, min(int(self.params.get("min_samples_leaf", 100 if kind == "hgb" else 200)), n // 8))
        if kind == "logit":
            return Pipeline([("imp", SimpleImputer(strategy="median", keep_empty_features=True)),
                             ("sc", StandardScaler()),
                             ("clf", LogisticRegression(C=C, max_iter=500))])
        if kind == "hgb":
            kw = dict(max_depth=3, learning_rate=0.05, max_iter=300, l2_regularization=0.1,
                      early_stopping=False, random_state=self.seed, max_bins=255)
            kw.update({k: v for k, v in self.params.items() if k in kw})
            return HistGradientBoostingClassifier(min_samples_leaf=msl, **kw)
        if kind == "rf":
            return Pipeline([("imp", SimpleImputer(strategy="median", keep_empty_features=True)),
                             ("clf", ExtraTreesClassifier(n_estimators=int(self.params.get("n_estimators", 200)),
                                                          min_samples_leaf=msl, max_features="sqrt",
                                                          n_jobs=-1, random_state=self.seed))])
        raise ValueError(kind)

    @staticmethod
    def _fit_base(est, X, y, w):
        with threadpool_limits(limits=1):      # l'OpenMP multi-thread di HGB e' molto piu' lento su dataset piccoli
            if isinstance(est, Pipeline):
                est.fit(X, y, clf__sample_weight=w)
            else:
                est.fit(X, y, sample_weight=w)
        return est

    @staticmethod
    def _proba(est, X) -> np.ndarray:
        return est.predict_proba(X)[:, 1]

    # ------------------------------------------------------------------ fit
    def fit(self, X: pd.DataFrame, y, t1, sample_weight=None) -> "MetaModel":
        y = np.asarray(y, float)
        w = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)
        self.base_rate_ = float(np.average(y, weights=w)) if len(y) else 0.5
        self.fitted = True
        self.degenerate_ = False
        if self.kind in ("base_rate", "gbm_montecarlo"):
            self.columns_ = []
            return self
        if self.kind == "ensemble":
            self.columns_ = _cols(X)
            self.subs_ = [MetaModel(k, self.n_splits, self.embargo_frac, self.seed, C_grid=self.C_grid,
                                    **self.params).fit(X, y, t1, w) for k in ("logit", "hgb")]
            return self
        cols = _cols(X)
        self.columns_ = cols
        order = np.argsort(pd.DatetimeIndex(t1.index).asi8, kind="stable")
        Xs = X[cols].to_numpy(float)[order]
        ys, ws = y[order], w[order]
        t1s = pd.Series(np.asarray(t1.values)[order], index=pd.DatetimeIndex(t1.index)[order])
        n = len(ys)
        if n < 60 or len(np.unique(ys)) < 2:
            self.degenerate_ = True
            return self
        folds = list(PurgedKFold(self.n_splits, self.embargo_frac).split(Xs, t1s))
        Cs = self.C_grid if self.kind == "logit" else (None,)
        best = None
        for C in Cs:
            oof = np.full(n, np.nan)
            for tr, te in folds:
                if len(np.unique(ys[tr])) < 2:
                    oof[te] = np.average(ys[tr], weights=ws[tr]) if len(tr) else self.base_rate_
                    continue
                est = self._fit_base(self._base(self.kind, len(tr), C or 0.1), Xs[tr], ys[tr], ws[tr])
                oof[te] = self._proba(est, Xs[te])
            m = np.isfinite(oof)
            sc = _ll(oof[m], ys[m], ws[m])
            if best is None or sc < best[0]:
                best = (sc, C, oof, m)
        _, self.C_, oof, m = best
        self.oof_raw_, self.oof_y_ = oof[m], ys[m]
        self.iso_ = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
        self.iso_.fit(oof[m], ys[m], sample_weight=ws[m])
        self.est_ = self._fit_base(self._base(self.kind, n, self.C_ or 0.1), Xs, ys, ws)
        return self

    # --------------------------------------------------------------- predict
    def raw_score(self, X: pd.DataFrame) -> np.ndarray:
        Xa = X.reindex(columns=self.columns_).to_numpy(float)
        return self._proba(self.est_, Xa)

    def calibrate(self, raw) -> np.ndarray:
        return np.clip(self.iso_.predict(np.asarray(raw, float)), P_LO, P_HI)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("fit() prima")
        n = len(X)
        if self.kind == "base_rate" or (self.kind not in ("gbm_montecarlo", "ensemble") and self.degenerate_):
            return np.full(n, float(np.clip(self.base_rate_, P_LO, P_HI)))
        if self.kind == "gbm_montecarlo":
            return self.gbm_p(X)
        if self.kind == "ensemble":
            return np.mean([s.predict_proba(X) for s in self.subs_], axis=0)
        return self.calibrate(self.raw_score(X))

    @staticmethod
    def gbm_p(X: pd.DataFrame) -> np.ndarray:
        """P(GBM termina sopra l'entry in h barre) = Phi(mu sqrt(h)/sigma), aggiustata per il lato.
        Forma chiusa equivalente al Monte Carlo a 5000 percorsi del vecchio bot."""
        mu, sg = X["aux_mc_mu"].to_numpy(float), X["aux_mc_sigma"].to_numpy(float)
        h, side = X["aux_mc_h"].to_numpy(float), X["side"].to_numpy(float)
        z = np.where(sg > 0, mu * np.sqrt(h) / np.where(sg > 0, sg, 1.0), 0.0)
        p = ndtr(np.where(side >= 0, z, -z))
        return np.clip(np.nan_to_num(p, nan=0.5), P_LO, P_HI)

    # ------------------------------------------------------------ importanza
    def family_importance(self, X: pd.DataFrame, y, t1, sample_weight=None, n_splits: int = 3,
                          seed: int = 0) -> pd.Series:
        """Permutation importance su log-loss OOF (PurgedKFold), aggregata per famiglia (prefisso colonna).
        Valore = aumento medio di log-loss quando le colonne della famiglia sono permutate (>0 = utile)."""
        kind = "hgb" if self.kind == "ensemble" else self.kind
        if kind not in ("logit", "hgb", "rf"):
            return pd.Series(dtype=float)
        y = np.asarray(y, float)
        w = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)
        cols = _cols(X)
        order = np.argsort(pd.DatetimeIndex(t1.index).asi8, kind="stable")
        Xs, ys, ws = X[cols].to_numpy(float)[order], y[order], w[order]
        t1s = pd.Series(t1.values[order], index=pd.DatetimeIndex(t1.index)[order])
        fam = family_columns(cols)
        rng = np.random.default_rng(seed)
        acc = {f: [] for f in fam}
        C = getattr(self, "C_", None) or 0.1
        for tr, te in PurgedKFold(n_splits, self.embargo_frac).split(Xs, t1s):
            if len(np.unique(ys[tr])) < 2:
                continue
            est = self._fit_base(self._base(kind, len(tr), C), Xs[tr], ys[tr], ws[tr])
            base = _ll(self._proba(est, Xs[te]), ys[te], ws[te])
            for f, fc in fam.items():
                ii = [cols.index(c) for c in fc]
                Xp = Xs[te].copy()
                Xp[:, ii] = Xp[rng.permutation(len(te))][:, ii]
                acc[f].append(_ll(self._proba(est, Xp), ys[te], ws[te]) - base)
        return pd.Series({f: float(np.mean(v)) if v else np.nan for f, v in acc.items()}).sort_values(ascending=False)
