"""Point-in-time meta-features (same definitions as the live telemetry v2)."""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from services.strategy_engines_service import first_passage_probabilities

SR0 = 0.4
POOL_BARS = 500


def _gap_mask(idx: pd.DatetimeIndex, interval_min: float) -> np.ndarray:
    d = np.r_[np.inf, (idx[1:] - idx[:-1]).total_seconds().to_numpy(float) / 60.0]
    return d > 1.5 * interval_min


def variance_inputs(o, h, l, c, idx, interval_min, pos: int) -> Tuple[float, float, Optional[float], int]:
    """(nu, s2_cc, s2_rs, n) from the POOL_BARS bars ending at pos (inclusive), gaps excluded for cc."""
    a = max(0, pos - POOL_BARS + 1)
    cs = c[a:pos + 1]
    lr = np.diff(np.log(cs))
    gm = _gap_mask(idx[a:pos + 1], interval_min)[1:]
    lr = lr[~gm & np.isfinite(lr)]
    if len(lr) < 20:
        return float("nan"), float("nan"), None, len(lr)
    nu, s2 = float(lr.mean()), float(lr.var(ddof=1))
    oo, hh, ll, cc = o[a:pos + 1], h[a:pos + 1], l[a:pos + 1], c[a:pos + 1]
    ok = (oo > 0) & (hh > 0) & (ll > 0) & (cc > 0) & (hh >= np.maximum(oo, cc)) & (ll <= np.minimum(oo, cc))
    rs = None
    if ok.sum() >= 20:
        v = float(np.mean(np.log(hh[ok] / cc[ok]) * np.log(hh[ok] / oo[ok]) + np.log(ll[ok] / cc[ok]) * np.log(ll[ok] / oo[ok])))
        rs = v if v > 0 else None
    return nu, s2, rs, len(lr)


def fp_features(nu: float, s2: float, s2_rs: Optional[float], n: int, side: int, sl_pct: float, tp_pct: float,
                horizon: int, bars_per_year: float) -> Dict[str, float]:
    out = {k: np.nan for k in ("fp_p_tp", "fp_p_tp_zero_drift", "fp_p_tp_rs_zero_drift", "fp_p_tp_bayes")}
    if not (s2 > 0 and horizon >= 1):
        return out
    if side > 0:
        a, b = -math.log(1 - sl_pct / 100.0), math.log(1 + tp_pct / 100.0)
    else:
        a, b = math.log(1 + sl_pct / 100.0), -math.log(1 - tp_pct / 100.0)
    nu_s = side * nu
    out["fp_p_tp"] = first_passage_probabilities(nu_s, s2, a, b, horizon)["p_tp"]
    out["fp_p_tp_zero_drift"] = first_passage_probabilities(0.0, s2, a, b, horizon)["p_tp"]
    out["fp_p_tp_rs_zero_drift"] = first_passage_probabilities(0.0, s2_rs if s2_rs else s2, a, b, horizon)["p_tp"]
    w = (SR0 ** 2 * n) / (SR0 ** 2 * n + bars_per_year)
    out["fp_p_tp_bayes"] = first_passage_probabilities(w * nu_s, s2, a, b, horizon)["p_tp"]
    return out


def ofi_series(df: pd.DataFrame, short: int = 15, med: int = 60, sigma_window: int = 60) -> pd.DataFrame:
    """Bulk Volume Classification, vectorised and causal (sigma from bars < t)."""
    dp = df["close"] - df["open"]
    sig = dp.rolling(sigma_window, min_periods=max(10, sigma_window // 3)).std().shift(1)
    z = dp / sig.where(sig > 0)
    ofi = z.apply(lambda x: math.erf(x / math.sqrt(2.0)) if np.isfinite(x) else np.nan)
    v = df["volume"].where(df["volume"] > 0)
    out = {}
    for name, k in (("ofi_bvc_short", short), ("ofi_bvc_med", med)):
        num = (ofi * v).rolling(k, min_periods=max(3, k // 3)).sum()
        den = v.where(ofi.notna()).rolling(k, min_periods=max(3, k // 3)).sum()
        out[name] = (num / den.where(den > 0)).clip(-1, 1)
    return pd.DataFrame(out, index=df.index)


def idio_panel(closes: Dict[str, pd.Series], bench: pd.Series, window: int = 140, min_obs: int = 30) -> Dict[str, pd.DataFrame]:
    """Rolling beta, residual sum and z-score vs the benchmark (window ending at t), plus CS rank."""
    bl = np.log(bench).diff()
    res = {}
    for sym, c in closes.items():
        r = np.log(c).diff()
        j = pd.concat([r.rename("r"), bl.rename("m")], axis=1, join="inner").dropna()
        cov = j["r"].rolling(window, min_periods=min_obs).cov(j["m"])
        var_m = j["m"].rolling(window, min_periods=min_obs).var()
        beta = cov / var_m.where(var_m > 0)
        n = j["r"].rolling(window, min_periods=min_obs).count()
        s_r = j["r"].rolling(window, min_periods=min_obs).sum()
        s_m = j["m"].rolling(window, min_periods=min_obs).sum()
        eps_sum = s_r - beta * s_m
        var_r = j["r"].rolling(window, min_periods=min_obs).var()
        var_eps = (var_r - beta ** 2 * var_m).clip(lower=0)
        z = (eps_sum / n) / (np.sqrt(var_eps) / np.sqrt(n)).where(var_eps > 0)
        res[sym] = pd.DataFrame({"spy_beta": beta, "idio_ret_window": eps_sum, "idio_z_drift": z})
    panel = pd.DataFrame({s: d["idio_ret_window"] for s, d in res.items()})
    others = panel.notna().sum(axis=1) - 1
    for sym in res:
        me = panel[sym]
        below = panel.drop(columns=[sym]).lt(me, axis=0).sum(axis=1) + 0.5 * panel.drop(columns=[sym]).eq(me, axis=0).sum(axis=1)
        res[sym]["idio_cs_rank"] = (below / others.where(others > 0)).where(me.notna())
    return res


def realized_vol_5d(spy: pd.DataFrame) -> pd.Series:
    """At each SPY bar: sqrt(sum r^2 over the bars of the last 5 NY sessions up to t * 252/5)."""
    c = spy["close"]
    r2 = np.log(c).diff() ** 2
    ny = pd.DatetimeIndex(c.index).tz_convert("America/New_York")
    dates = pd.Series(ny.date, index=c.index)
    uniq = sorted(set(dates))
    pos = {d: i for i, d in enumerate(uniq)}
    di = dates.map(pos).to_numpy()
    out = np.full(len(c), np.nan)
    r2v = r2.to_numpy()
    for i in range(len(c)):
        if di[i] < 4:
            continue
        m = (di >= di[i] - 4) & (np.arange(len(c)) <= i)
        out[i] = math.sqrt(np.nansum(r2v[m]) * 252.0 / 5.0)
    return pd.Series(out, index=c.index)
