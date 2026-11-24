"""Feature di ciclo oneste (per TESTARE l'ipotesi dei cicli di Hurst). Tutto causale."""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


def rolling_dominant_cycle(close: pd.Series, window: int = 128, min_period: int = 8,
                           max_period: int = 64, step: int = 1, pad: int = 8,
                           chunk: int = 2000) -> pd.DataFrame:
    """Su ogni finestra di `window` barre terminante in t: detrend lineare del log-prezzo, taper di Hann,
    periodogramma (rfft con zero-padding x`pad`), picco nella banda [min_period, max_period].
    Colonne: cycle_period (barre), cycle_conc (potenza attorno al picco / potenza totale in banda),
    cycle_sin/cycle_cos (fase DFT della frequenza dominante valutata all'ULTIMA barra).
    Con step>1 si calcola solo dove indice_assoluto % step == 0 e si propaga (ffill, max step-1 barre)."""
    n = len(close)
    W = window
    nfft = W * pad
    logp = np.log(close.to_numpy(float))
    cols = ["cycle_period", "cycle_conc", "cycle_sin", "cycle_cos"]
    res = np.full((n, 4), np.nan)
    if n >= W:
        t = np.arange(W, dtype=float)
        A = np.stack([np.ones(W), t], axis=1)
        P = np.eye(W) - A @ np.linalg.pinv(A)
        hann = np.hanning(W + 2)[1:-1]
        Mt = P.T * hann[None, :]
        kmin = int(np.ceil(nfft / max_period))
        kmax = int(np.floor(nfft / min_period))
        nb = kmax - kmin + 1
        hw = 2 * pad
        views = sliding_window_view(logp, W)
        ends = np.arange(W - 1, n)
        ends = ends[ends % step == 0]
        for a in range(0, len(ends), chunk):
            e = ends[a:a + chunk]
            w = views[e - (W - 1)]
            ok = np.isfinite(w).all(axis=1)
            w = np.where(ok[:, None], w, 0.0)
            F = np.fft.rfft(w @ Mt, n=nfft, axis=1)
            pw = np.abs(F[:, kmin:kmax + 1]) ** 2
            j = pw.argmax(axis=1)
            k = kmin + j
            cs = np.concatenate([np.zeros((len(e), 1)), np.cumsum(pw, axis=1)], axis=1)
            r = np.arange(len(e))
            lo = np.maximum(j - hw, 0)
            hi = np.minimum(j + hw + 1, nb)
            tot = cs[:, -1]
            conc = (cs[r, hi] - cs[r, lo]) / np.where(tot > 0, tot, np.nan)
            ph = np.angle(F[r, k]) + 2 * np.pi * k / nfft * (W - 1) + np.pi / 2  # cycle_sin ~ oscillatore sin()
            blk = np.stack([nfft / k, conc, np.sin(ph), np.cos(ph)], axis=1)
            blk[~ok] = np.nan
            res[e] = blk
    df = pd.DataFrame(res, index=close.index, columns=cols)
    if step > 1:
        df = df.ffill(limit=step - 1)
    return df


def fld_momentum(close: pd.Series, period: int, atr: pd.Series) -> pd.DataFrame:
    """FLD di Hurst = prezzo spostato di period//2: distanza (in ATR) del close dal close di period//2 barre fa."""
    dist = (close - close.shift(max(period // 2, 1))) / atr.where(atr > 0)
    return pd.DataFrame({"fld_sign": np.sign(dist), "fld_dist": dist})
