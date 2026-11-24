"""Statistiche di validazione (numpy puro): PSR/DSR, PBO (CSCV), IC, Brier, log-loss, calibrazione."""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np
import pandas as pd

EULER_GAMMA = 0.5772156649015329


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inversa della normale (Acklam) con un passo di raffinamento di Halley."""
    if not 0.0 < p < 1.0:
        if p == 0.0:
            return -math.inf
        if p == 1.0:
            return math.inf
        raise ValueError("p fuori da [0,1]")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    elif p <= 1 - pl:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    e = norm_cdf(x) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def probabilistic_sharpe_ratio(sr: float, n: int, skew: float = 0.0, kurt: float = 3.0,
                               sr_benchmark: float = 0.0) -> float:
    """PSR (Bailey & LdP 2012). sr per-periodo (non annualizzato); kurt = curtosi grezza (normale = 3)."""
    den = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if n < 2 or den <= 0:
        return float("nan")
    return norm_cdf((sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(den))


def expected_max_sharpe(var_sr_trials: float, n_trials: int) -> float:
    """Sharpe massimo atteso tra n_trials prove indipendenti a edge nullo."""
    if n_trials <= 1:
        return 0.0
    return math.sqrt(var_sr_trials) * ((1 - EULER_GAMMA) * norm_ppf(1 - 1.0 / n_trials)
                                       + EULER_GAMMA * norm_ppf(1 - 1.0 / (n_trials * math.e)))


def deflated_sharpe_ratio(returns, n_trials: int, var_sr_trials: float) -> float:
    """DSR (Bailey & LdP 2014): PSR rispetto al Sharpe massimo atteso da n_trials prove."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return float("nan")
    sd = r.std(ddof=1)
    sr = r.mean() / sd
    z = (r - r.mean()) / sd
    skew, kurt = float((z ** 3).mean()), float((z ** 4).mean())
    return probabilistic_sharpe_ratio(sr, n, skew, kurt, expected_max_sharpe(var_sr_trials, n_trials))


def pbo_cscv(perf_matrix, n_splits: int = 16):
    """Probability of Backtest Overfitting via CSCV. perf_matrix: T x N (rendimenti per periodo).
    Restituisce (pbo, logits)."""
    M = np.asarray(perf_matrix, dtype=float)
    T, N = M.shape
    S = n_splits
    if S % 2 or S < 2 or T < S or N < 2:
        raise ValueError("n_splits pari, T >= n_splits, N >= 2")
    L = T // S
    blocks = M[: L * S].reshape(S, L, N)
    s1, s2 = blocks.sum(1), (blocks ** 2).sum(1)

    def sharpe(idx):
        n = L * idx.shape[1]
        m = s1[idx].sum(1) / n
        v = np.maximum(s2[idx].sum(1) / n - m * m, 1e-18)
        return m / np.sqrt(v)

    combs = np.array(list(combinations(range(S), S // 2)))
    mask = np.zeros((len(combs), S), bool)
    np.put_along_axis(mask, combs, True, axis=1)
    comp = np.array([np.flatnonzero(~m) for m in mask])
    is_sr, oos_sr = sharpe(combs), sharpe(comp)
    best = is_sr.argmax(1)
    chosen = oos_sr[np.arange(len(combs)), best][:, None]
    rank = 1 + (oos_sr < chosen).sum(1) + 0.5 * ((oos_sr == chosen).sum(1) - 1)
    w = rank / (N + 1.0)
    logits = np.log(w / (1.0 - w))
    return float((logits <= 0).mean()), logits


def _rank(a: np.ndarray) -> np.ndarray:
    return pd.Series(a).rank(method="average").to_numpy()


def spearman_ic(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3:
        return float("nan")
    rx, ry = _rank(x[m]), _rank(y[m])
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def rolling_ic(x, y, window: int = 500, min_periods: int | None = None) -> pd.Series:
    idx = x.index if isinstance(x, pd.Series) else None
    xa, ya = np.asarray(x, float), np.asarray(y, float)
    mp = min_periods or max(10, window // 5)
    out = np.full(len(xa), np.nan)
    for i in range(mp - 1, len(xa)):
        lo = max(0, i - window + 1)
        out[i] = spearman_ic(xa[lo:i + 1], ya[lo:i + 1]) if i - lo + 1 >= mp else np.nan
    return pd.Series(out, index=idx)


def brier_score(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p, y, eps: float = 1e-15) -> float:
    p, y = np.clip(np.asarray(p, float), eps, 1 - eps), np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration_table(p, y, bins: int = 10) -> pd.DataFrame:
    p, y = np.asarray(p, float), np.asarray(y, float)
    b = np.minimum((p * bins).astype(int), bins - 1)
    rows = []
    for k in range(bins):
        m = b == k
        rows.append({"bin": k, "lo": k / bins, "hi": (k + 1) / bins, "n": int(m.sum()),
                     "mean_p": float(p[m].mean()) if m.any() else np.nan,
                     "frac_pos": float(y[m].mean()) if m.any() else np.nan})
    return pd.DataFrame(rows)
