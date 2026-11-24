"""
Crowding-Conditioned Trend (CCT) e segnali singoli di confronto, per perpetual crypto.

Ipotesi (pre-registrata): la continuazione di un trend dipende dall'INTERAZIONE tra
  - T   : trend vol-scalato a 7 giorni,
  - F   : affollamento della leva (funding cumulato 24h, z-score 30g),
  - Phi : flusso aggressivo (taker imbalance 24h, z-score 30g).
Trend con flusso concorde e leva non affollata -> continua; trend con funding estremo
nella sua direzione -> fragile (carry + rischio di liquidazioni a cascata).

Tutte le grandezze alla barra t usano solo barre <= t (chiuse). Richiede le colonne
taker_buy_volume e funding_rate (NaN tra un print e l'altro).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.core import interval_to_hours


def cct_features(bars: pd.DataFrame, interval: str, trend_days: float = 7, z_days: float = 30,
                 flow_hours: float = 24) -> pd.DataFrame:
    bh = interval_to_hours(interval)
    n_tr = max(2, int(round(trend_days * 24 / bh)))
    n_z = max(10, int(round(z_days * 24 / bh)))
    n_fl = max(1, int(round(flow_hours / bh)))
    lr = np.log(bars["close"]).diff()
    sig = lr.rolling(n_z, min_periods=n_z // 2).std()
    T = lr.rolling(n_tr).sum() / (sig * np.sqrt(n_tr))
    fund = bars["funding_rate"].fillna(0.0) if "funding_rate" in bars else pd.Series(0.0, index=bars.index)
    f24 = fund.rolling(n_fl, min_periods=1).sum()
    F = (f24 - f24.rolling(n_z, min_periods=n_z // 2).mean()) / f24.rolling(n_z, min_periods=n_z // 2).std()
    if "taker_buy_volume" in bars:
        imb = (2 * bars["taker_buy_volume"] - bars["volume"]).rolling(n_fl).sum() / bars["volume"].rolling(n_fl).sum()
        Phi = (imb - imb.rolling(n_z, min_periods=n_z // 2).mean()) / imb.rolling(n_z, min_periods=n_z // 2).std()
    else:
        Phi = pd.Series(np.nan, index=bars.index)
    rv_s = lr.rolling(n_fl).std()
    V = rv_s / sig
    out = pd.DataFrame({"T": T, "F": F, "Phi": Phi, "V": V}, index=bars.index)
    return out.replace([np.inf, -np.inf], np.nan)


def _side(long_mask, short_mask, idx, allow_short=True):
    s = pd.Series(0, index=idx, dtype=int)
    s[long_mask.fillna(False)] = 1
    if allow_short:
        s[short_mask.fillna(False)] = -1
    return s


def cct(bars, spec, interval, context=None, tau: float = 0.5, f_max: float = 1.0, phi_min: float = 0.0):
    """Regola CCT: trend AND leva non affollata AND flusso concorde."""
    x = cct_features(bars, interval)
    lo = (x["T"] > tau) & (x["F"] < f_max) & (x["Phi"] > phi_min)
    sh = (x["T"] < -tau) & (x["F"] > -f_max) & (x["Phi"] < -phi_min)
    return _side(lo, sh, bars.index, spec.allow_short)


def trend_only(bars, spec, interval, context=None, tau: float = 0.5):
    x = cct_features(bars, interval)
    return _side(x["T"] > tau, x["T"] < -tau, bars.index, spec.allow_short)


def funding_contrarian(bars, spec, interval, context=None, k: float = 1.5):
    x = cct_features(bars, interval)
    return _side(x["F"] < -k, x["F"] > k, bars.index, spec.allow_short)


def flow_only(bars, spec, interval, context=None, k: float = 1.0):
    x = cct_features(bars, interval)
    return _side(x["Phi"] > k, x["Phi"] < -k, bars.index, spec.allow_short)
