"""Costruzione feature scale-free e causali. Riga t usa solo barre chiuse <= t."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import AssetSpec, interval_to_hours
from . import indicators as ind
from .cycles import fld_momentum, rolling_dominant_cycle

FEATURE_FAMILIES = {
    "trend_": "rendimenti log scalati per vol su 4h..720h, distanza EMA in ATR, ADX, efficiency ratio",
    "rev_": "z-score rendimento 1/4 barre, RSI Wilder centrato, %b Bollinger",
    "vol_": "vol realizzata annualizzata 24h/168h, rapporto, componenti HAR, ATR%",
    "volu_": "z-score log-volume, rapporto volume, sbilanciamento taker",
    "deriv_": "funding (ultimo, z-score, cumulato 24h), variazione e z-score open interest",
    "xs_": "rendimento in eccesso, beta e correlazione rolling vs benchmark",
    "cal_": "stagionalita' ora/giorno (sin/cos), ore al prossimo funding",
    "struct_": "distanza Donchian in ATR, aroon, FLD, variance ratio, Hurst R/S, cicli dominanti",
    "phys_": "(opzionale, physics=True) numero di Peclet multi-scala, P(TP prima di SL) Fokker-Planck "
             "in forma chiusa (senza drift e delta del drift), drift a ritardo compensato DEMA+minmod",
}


def _fp_ptp(nu, s2, a, b, T, n_terms: int = 60):
    """P(TP before SL within T) for drifted BM, vectorised over bars (closed form, see
    services.strategy_engines_service.first_passage_probabilities). nu, s2, a, b: arrays."""
    nu, s2, a, b = (np.asarray(x, float) for x in (nu, s2, a, b))
    L = a + b
    with np.errstate(all="ignore"):
        k = 2.0 * nu / s2
        kl = np.clip(k * L, -700.0, 700.0)
        ka = np.clip(k * a, -700.0, 700.0)
        p_inf = np.where(np.abs(kl) < 1e-9, a / L, np.expm1(-ka) / np.expm1(-kl))
        n = np.arange(1, n_terms + 1, dtype=float)[None, :]
        lam = (nu * nu / (2.0 * s2))[:, None] + (n * np.pi) ** 2 * (s2 / (2.0 * L * L))[:, None]
        c = (2.0 / L)[:, None] * np.sin(n * np.pi * (a / L)[:, None]) * (n * np.pi / L[:, None]) * (s2 / 2.0)[:, None]
        sgn = np.where(n % 2 == 0, 1.0, -1.0)
        res = np.sum(c * (-sgn) * np.exp(-lam * T) / lam, axis=1) * np.exp(np.clip(nu * b / s2, -700.0, 700.0))
        out = np.clip(p_inf - res, 0.0, 1.0)
    bad = ~(np.isfinite(out) & (s2 > 0) & (a > 0) & (b > 0))
    out[bad] = np.nan
    return out


def physics_features(bars: pd.DataFrame, interval: str, sl_atr: float = 1.5, tp_atr: float = 3.0,
                     horizon_bars: int = 48) -> pd.DataFrame:
    """Famiglia phys_ (causale): grandezze "fluidodinamiche" del processo di prezzo.

    - phys_pe_<h>h: numero di Peclet 2*nu*dx/s2 del movimento verso un target dx = tp_atr*ATR/close,
      con drift nu e varianza s2 per barra stimati su h ore. Pe = z_drift * 2dx/(sigma*sqrt(n)).
    - phys_fp_ptp0: P(TP prima di SL entro horizon_bars) senza drift (Fokker-Planck in forma chiusa,
      SL = sl_atr*ATR, TP = tp_atr*ATR, varianza su 168 h): raggiungibilita' da sola volatilita'.
    - phys_fp_edge: P(TP) con drift (168 h) per un LONG meno phys_fp_ptp0 (direzionale).
    - phys_drift_tvd_<span>: drift a ritardo compensato, minmod(dlog EMA, dlog DEMA) / sigma.
    """
    ih = interval_to_hours(interval)
    n = len(bars)
    c = bars["close"]
    lr = np.log(c).diff()
    sig = lr.ewm(span=200, min_periods=50).std()
    atr = ind.atr_wilder(bars, 14)
    dx = (tp_atr * atr / c).where(atr > 0)
    F: dict[str, pd.Series] = {}

    def hb(h: float):
        nb = int(round(h / ih))
        return nb if 2 <= nb <= n // 3 else None

    for h in (24, 72, 168):
        nb = hb(h)
        if nb:
            nu = lr.rolling(nb).mean()
            s2 = lr.rolling(nb).var()
            F[f"phys_pe_{h}h"] = 2.0 * nu * dx / s2.where(s2 > 0)
    nb = hb(168)
    if nb:
        nu = lr.rolling(nb).mean().to_numpy(float)
        s2 = lr.rolling(nb).var().to_numpy(float)
        a = np.log1p(sl_atr * (atr / c).to_numpy(float))
        b = np.log1p(tp_atr * (atr / c).to_numpy(float))
        p0 = _fp_ptp(np.zeros(n), s2, a, b, horizon_bars)
        p1 = _fp_ptp(nu, s2, a, b, horizon_bars)
        F["phys_fp_ptp0"] = pd.Series(p0, index=bars.index)
        F["phys_fp_edge"] = pd.Series(p1 - p0, index=bars.index)
    for span in (12, 48):
        nb = hb(span)
        if nb:
            e = ind.ema(c, nb)
            dema = 2.0 * e - ind.ema(e, nb)
            d1 = np.log(e).diff()
            d2 = np.log(dema.where(dema > 0)).diff()
            mm = np.where(np.sign(d1) == np.sign(d2), np.sign(d1) * np.minimum(d1.abs(), d2.abs()), 0.0)
            F[f"phys_drift_tvd_{span}"] = pd.Series(mm, index=bars.index).where(d1.notna() & d2.notna()) / sig
    out = pd.DataFrame(F, index=bars.index).astype("float64")
    return out.replace([np.inf, -np.inf], np.nan)


def build_features(bars: pd.DataFrame, spec: AssetSpec, interval: str,
                   benchmark: pd.DataFrame | None = None, cycle_step: int = 2,
                   physics: bool = False) -> pd.DataFrame:
    n = len(bars)
    ih = interval_to_hours(interval)
    idx = bars.index
    F: dict[str, pd.Series] = {}

    def hb(h: float):
        nb = int(round(h / ih))
        return nb if 1 <= nb <= n // 3 else None

    if spec.session == "rth" and ih >= 24:
        bpy = 252.0 / (ih / 24)
    else:
        bpy = spec.bars_per_year_factor / ih
    ann = np.sqrt(bpy)

    c = bars["close"]
    logp = np.log(c)
    lr = logp.diff()
    sig = lr.ewm(span=200, min_periods=50).std()
    atr = ind.atr_wilder(bars, 14)
    atr_safe = atr.where(atr > 0)

    # ---- trend
    for h in (4, 24, 72, 168, 720):
        nb = hb(h)
        if nb:
            F[f"trend_ret_{h}h"] = logp.diff(nb) / (sig * np.sqrt(nb))
    nf, ns = hb(12), hb(48)
    if nf and ns and nf < ns:
        F["trend_ema_dist_atr"] = (ind.ema(c, nf) - ind.ema(c, ns)) / atr_safe
    F["trend_adx"] = ind.adx(bars, 14) / 100
    ner = hb(24)
    if ner:
        F["trend_er"] = ind.kaufman_efficiency_ratio(c, ner)

    # ---- reversion
    F["rev_z1"] = lr / sig
    F["rev_z4"] = logp.diff(4) / (sig * 2)
    F["rev_rsi"] = (ind.wilder_rsi(c, 14) - 50) / 50
    F["rev_bb_pctb"] = ind.bollinger_pctb(c, 20)

    # ---- volatilita
    n24, n168, n720 = hb(24), hb(168), hb(720)
    if n24 and n168:
        rv_s = ind.realized_vol(lr, n24) * ann
        rv_l = ind.realized_vol(lr, n168) * ann
        F["vol_rv_24h"] = rv_s
        F["vol_rv_168h"] = rv_l
        F["vol_ratio"] = np.log(rv_s / rv_l.where(rv_l > 0)).where(rv_s > 0)
    for tag, nb in (("d", n24), ("w", n168), ("m", n720)):
        if nb:
            rms = np.sqrt((lr ** 2).rolling(nb).mean()) * ann
            F[f"vol_har_{tag}"] = np.log(rms.where(rms > 0))
    F["vol_atr_pct"] = atr / c

    # ---- volume
    v = bars["volume"]
    if n24:
        F["volu_logvol_z"] = ind.rolling_zscore(np.log1p(v), n24)
        m = v.rolling(n24).mean()
        F["volu_ratio"] = np.log((v / m.where(m > 0)).where(v > 0))
    if "taker_buy_volume" in bars:
        tb = bars["taker_buy_volume"]
        for k in (1, 4, 24):
            sv, st = v.rolling(k).sum(), tb.rolling(k).sum()
            F[f"volu_taker_imb_{k}"] = 2 * st / sv.where(sv > 0) - 1

    # ---- derivati
    if "funding_rate" in bars:
        fr = bars["funding_rate"]
        ff = fr.ffill()
        F["deriv_funding"] = ff
        if n720:
            F["deriv_funding_z"] = ind.rolling_zscore(ff, n720)
        if n24:
            F["deriv_funding_cum24"] = fr.fillna(0.0).rolling(n24).sum().where(ff.notna())
    if "open_interest" in bars:
        oi = bars["open_interest"].ffill()
        F["deriv_oi_chg_4"] = oi.pct_change(4, fill_method=None)
        F["deriv_oi_chg_24"] = oi.pct_change(24, fill_method=None)
        if n168:
            F["deriv_oi_z"] = ind.rolling_zscore(np.log(oi.where(oi > 0)), n168)

    # ---- cross-sectional vs benchmark
    if benchmark is not None:
        bc = benchmark["close"]
        bc = bc[~bc.index.duplicated()].reindex(bc.index.union(idx)).ffill().reindex(idx)
        blp = np.log(bc)
        blr = blp.diff()
        for h in (24, 168):
            nb = hb(h)
            if nb:
                F[f"xs_excess_{h}h"] = (logp.diff(nb) - blp.diff(nb)) / (sig * np.sqrt(nb))
        if n168:
            cov = lr.rolling(n168).cov(blr)
            var = blr.rolling(n168).var()
            F["xs_beta_168h"] = cov / var.where(var > 0)
            F["xs_corr_168h"] = lr.rolling(n168).corr(blr)

    # ---- calendario
    hod = idx.hour + idx.minute / 60.0
    if ih < 24:
        F["cal_hour_sin"] = pd.Series(np.sin(2 * np.pi * hod / 24), index=idx)
        F["cal_hour_cos"] = pd.Series(np.cos(2 * np.pi * hod / 24), index=idx)
    F["cal_dow_sin"] = pd.Series(np.sin(2 * np.pi * idx.dayofweek / 7), index=idx)
    F["cal_dow_cos"] = pd.Series(np.cos(2 * np.pi * idx.dayofweek / 7), index=idx)
    if spec.asset_class == "crypto_perp":
        close_h = np.asarray((hod + ih) % 24)
        F["cal_hours_to_funding"] = pd.Series(((8 - close_h % 8) % 8) / 8, index=idx)

    # ---- struttura
    n72 = hb(72)
    if n72:
        dc = ind.donchian(bars["high"], bars["low"], n72)
        F["struct_dc_high_atr"] = (dc["high"] - c) / atr_safe
        F["struct_dc_low_atr"] = (c - dc["low"]) / atr_safe
    F["struct_aroon_32"] = ind.aroon_position(c, 32)
    fld = fld_momentum(c, 20, atr)
    F["struct_fld_sign"] = fld["fld_sign"]
    F["struct_fld_dist"] = fld["fld_dist"]
    F["struct_vr_4"] = ind.variance_ratio(logp, 4, 256)
    F["struct_hurst_256"] = ind.hurst_exponent_rs(lr, 256)
    cyc = rolling_dominant_cycle(c, window=128, min_period=8, max_period=64, step=cycle_step)
    F["struct_cycle_period"] = cyc["cycle_period"] / 64
    F["struct_cycle_conc"] = cyc["cycle_conc"]
    F["struct_cycle_sin"] = cyc["cycle_sin"]
    F["struct_cycle_cos"] = cyc["cycle_cos"]

    out = pd.DataFrame(F, index=idx).astype("float64")
    if physics:
        out = out.join(physics_features(bars, interval))
    return out.replace([np.inf, -np.inf], np.nan)
