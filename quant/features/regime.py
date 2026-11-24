"""Regimi: HMM gaussiano (solo filtraggio causale) e TrendRegime con isteresi."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind


class GaussianHMM:
    """HMM a covarianze diagonali, Baum-Welch con scaling, piu' inizializzazioni casuali.
    Stati ordinati per media della prima colonna (stato 0 = piu' ribassista).
    fit() va chiamato SOLO su una fetta di training; filter_proba e' causale (forward, mai smoothing)."""

    def __init__(self, n_states: int = 2, n_init: int = 5, n_iter: int = 60, tol: float = 1e-4,
                 var_floor: float = 1e-4, seed: int = 0):
        if not 2 <= n_states <= 3:
            raise ValueError("n_states in {2,3}")
        self.K, self.n_init, self.n_iter, self.tol = n_states, n_init, n_iter, tol
        self.var_floor, self.seed = var_floor, seed
        self.fitted = False

    # -- helpers
    def _logB(self, Z, mu, var):
        ll = -0.5 * (np.log(2 * np.pi * var)[None] + (Z[:, None, :] - mu[None]) ** 2 / var[None]).sum(axis=2)
        ll[~np.isfinite(Z).all(axis=1)] = 0.0  # osservazione mancante: emissione non informativa
        return ll

    @staticmethod
    def _forward(logB, pi, A):
        T, K = logB.shape
        m = logB.max(axis=1, keepdims=True)
        B = np.exp(logB - m)
        alpha = np.empty((T, K))
        c = np.empty(T)
        a = pi * B[0]
        c[0] = a.sum()
        alpha[0] = a / c[0]
        for t in range(1, T):
            a = (alpha[t - 1] @ A) * B[t]
            c[t] = a.sum()
            alpha[t] = a / c[t]
        return alpha, c, B, float((np.log(c) + m[:, 0]).sum())

    def _em(self, Z, mu, var, A, pi):
        prev = -np.inf
        for _ in range(self.n_iter):
            logB = self._logB(Z, mu, var)
            alpha, c, B, ll = self._forward(logB, pi, A)
            T, K = alpha.shape
            beta = np.empty((T, K))
            beta[-1] = 1.0
            for t in range(T - 2, -1, -1):
                beta[t] = (A @ (B[t + 1] * beta[t + 1])) / c[t + 1]
            gamma = alpha * beta
            gamma /= gamma.sum(axis=1, keepdims=True)
            xi = (alpha[:-1, :, None] * A[None] * (B[1:] * beta[1:] / c[1:, None])[:, None, :]).sum(axis=0)
            A = xi / xi.sum(axis=1, keepdims=True)
            pi = gamma[0]
            w = gamma.sum(axis=0)
            mu = (gamma.T @ Z) / w[:, None]
            var = np.maximum((gamma.T @ Z ** 2) / w[:, None] - mu ** 2, self.var_floor)
            if abs(ll - prev) < self.tol * max(1.0, abs(ll)) * 1e-2:
                break
            prev = ll
        _, _, _, ll = self._forward(self._logB(Z, mu, var), pi, A)
        return ll, mu, var, A, pi

    def fit(self, X) -> "GaussianHMM":
        X = np.asarray(X, float)
        if X.ndim == 1:
            X = X[:, None]
        X = X[np.isfinite(X).all(axis=1)]
        self.mean_, self.std_ = X.mean(axis=0), X.std(axis=0)
        self.std_ = np.where(self.std_ > 0, self.std_, 1.0)
        Z = (X - self.mean_) / self.std_
        rng = np.random.default_rng(self.seed)
        best = None
        for _ in range(self.n_init):
            mu = Z[rng.choice(len(Z), self.K, replace=False)]
            var = np.ones((self.K, Z.shape[1]))
            A = np.full((self.K, self.K), 0.1 / (self.K - 1))
            np.fill_diagonal(A, 0.9)
            res = self._em(Z, mu, var, A, np.full(self.K, 1 / self.K))
            if best is None or res[0] > best[0]:
                best = res
        self.loglik_, mu, var, A, pi = best
        o = np.argsort(mu[:, 0])
        self.mu_, self.var_ = mu[o], var[o]
        self.A_, self.pi_ = A[np.ix_(o, o)], pi[o]
        self.fitted = True
        return self

    def filter_proba(self, X) -> np.ndarray:
        """P(stato_t | X_0..t): forward filtering, causale. Shape (T, K)."""
        if not self.fitted:
            raise RuntimeError("fit() prima")
        X = np.asarray(X, float)
        if X.ndim == 1:
            X = X[:, None]
        Z = (X - self.mean_) / self.std_
        return self._forward(self._logB(Z, self.mu_, self.var_), self.pi_, self.A_)[0]


class TrendRegime:
    """Regime di trend {-1,0,1}: EMA(fast) vs EMA(slow) e prezzo vs EMA(slow), con isteresi:
    il candidato (+1 se ema_f-ema_s > band_atr*ATR e close>ema_s; -1 speculare; altrimenti 0)
    diventa stato solo dopo `confirm` barre consecutive concordi."""

    def __init__(self, fast: int = 24, slow: int = 96, confirm: int = 3, band_atr: float = 0.5, atr_n: int = 14):
        self.fast, self.slow, self.confirm, self.band_atr, self.atr_n = fast, slow, confirm, band_atr, atr_n

    def classify(self, close_or_bars) -> pd.Series:
        if isinstance(close_or_bars, pd.DataFrame):
            close = close_or_bars["close"]
            atr = ind.atr_wilder(close_or_bars, self.atr_n)
        else:
            close = close_or_bars
            atr = close.diff().abs().ewm(alpha=1 / self.atr_n, adjust=False).mean()
        ef, es = ind.ema(close, self.fast), ind.ema(close, self.slow)
        band = self.band_atr * atr
        cand = pd.Series(0, index=close.index)
        cand[(ef - es > band) & (close > es)] = 1
        cand[(es - ef > band) & (close < es)] = -1
        cv = cand.to_numpy()
        out = np.zeros(len(cv), dtype=int)
        state, run, runval = 0, 0, 0
        for i, x in enumerate(cv):
            if x != state:
                if x == runval:
                    run += 1
                else:
                    runval, run = x, 1
                if run >= self.confirm:
                    state, run = x, 0
            else:
                run = 0
            out[i] = state
        return pd.Series(out, index=close.index, name="reg_trend")


def hmm_inputs(bars: pd.DataFrame, vol_window: int = 24) -> pd.DataFrame:
    """Osservazioni per l'HMM: rendimento log 1 barra (prima colonna) e log vol realizzata rolling."""
    lr = np.log(bars["close"]).diff()
    rv = lr.rolling(vol_window).std()
    return pd.DataFrame({"ret": lr, "logvol": np.log(rv.where(rv > 0))})


def regime_features(bars: pd.DataFrame, hmm_fitted: GaussianHMM, trend: TrendRegime | None = None,
                    X: pd.DataFrame | None = None) -> pd.DataFrame:
    X = hmm_inputs(bars) if X is None else X
    p = hmm_fitted.filter_proba(X.to_numpy(float))
    out = pd.DataFrame(p, index=bars.index, columns=[f"reg_p_state{i}" for i in range(p.shape[1])])
    out.loc[X.isna().any(axis=1).to_numpy(), :] = np.nan
    out["reg_trend"] = (trend or TrendRegime()).classify(bars).astype(float)
    return out
