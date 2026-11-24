"""Replica fedele della logica di INGRESSO del bot live (telegram_bot.py).

Crypto: `_sync_crypto_risk_and_screening` + `_get_btc_macro_bias`; azioni: `_sync_alpaca_risk_and_screening`.
Interfaccia: fn(bars, spec, interval, context) -> Series int {-1,0,1}; segnale EVENTO (non nullo solo alla barra
di trigger), deciso alla chiusura della barra e eseguito dal backtester all'apertura successiva.

OMESSI (non ricostruibili storicamente): Order-Book Imbalance (OBI shield) e "Sentinella" news/sentiment.
Il CVD del bot (ultimi 50 trade pubblici) e' approssimato da ratio = taker_buy/(vol - taker_buy) della barra.
Il ranking Alpha-vs-BTC/SPY, il tetto 3 posizioni e il sizing non fanno parte del segnale.

Causalita': le barre HTF (1h/4h/1d) sono usate solo dopo la loro chiusura (`htf_align`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.core import AssetSpec, interval_to_hours
from quant.features import indicators as ind


def htf_align(bars: pd.DataFrame, rule: str, interval: str, fn=None, col: str = "close") -> pd.Series:
    """Resample causale: serie HTF (o fn(serie HTF)) riportata sull'indice base.
    La barra HTF [T, T+H) diventa disponibile alla chiusura dell'ultima barra base che la compone
    (apertura T+H-dt); la sua serie e' riportata con ffill solo da quel momento."""
    dt = pd.Timedelta(hours=interval_to_hours(interval))
    H = pd.Timedelta(rule)
    if H <= dt:
        s = bars[col]
        return (fn(s) if fn else s).copy()
    c = bars[col].resample(rule, label="left", closed="left").last().dropna()
    vals = fn(c) if fn else c
    vals = vals.copy()
    vals.index = c.index + H - dt
    return vals.reindex(bars.index, method="ffill")


def macro_bias(bench: pd.DataFrame, index: pd.DatetimeIndex, interval: str) -> pd.Series:
    """Bias macro crypto (+1 BULLISH, -1 BEARISH, 0 NEUTRAL) da benchmark 4h/1h."""
    b = bench
    c4 = htf_align(b, "4h", interval)
    e20, e50 = htf_align(b, "4h", interval, lambda s: ind.ema(s, 20)), htf_align(b, "4h", interval, lambda s: ind.ema(s, 50))
    c1 = htf_align(b, "1h", interval)
    f50 = htf_align(b, "1h", interval, lambda s: ind.ema(s, 50))
    bull = (c4 > e50) & (e20 >= e50)
    bear = (c4 < e50) & (c1 < f50) & ~bull
    out = pd.Series(0, index=b.index)
    out[bull] = 1
    out[bear] = -1
    return out.reindex(index, method="ffill").fillna(0).astype(int)


def cycle_features(bars: pd.DataFrame, interval: str) -> pd.DataFrame:
    """tempo (1..4, 0 se NaN), fld, ribassista (bool) sul ciclo 1h con semantica corretta (Phase-0 fix)."""
    def tempo(c: pd.Series) -> pd.Series:
        a = c.to_numpy(float)
        out = np.full(len(a), np.nan)
        if len(a) >= 32:
            w = np.lib.stride_tricks.sliding_window_view(a, 32)
            bs = np.argmin(w[:, ::-1], axis=1)  # barre trascorse dall'ultimo minimo a 32 barre
            out[31:] = bs
        return pd.Series(out, index=c.index)

    bs = htf_align(bars, "1h", interval, tempo)
    c1 = htf_align(bars, "1h", interval)
    fld = htf_align(bars, "1h", interval, lambda s: s.shift(10))
    m69 = htf_align(bars, "1h", interval, lambda s: s.shift(1).rolling(69).min())
    m31 = htf_align(bars, "1h", interval, lambda s: s.shift(1).rolling(31).min())
    ribass = ((c1 < m69) | ((bs > 16) & (c1 < m31))).fillna(False)
    tmp = pd.Series(np.select([bs <= 8, bs <= 16, bs <= 24, bs > 24], [1, 2, 3, 4], 0), index=bars.index)
    return pd.DataFrame({"tempo": tmp, "fld": fld, "ribassista": ribass.astype(bool)})


def rome_overnight(index: pd.DatetimeIndex, interval: str) -> pd.Series:
    """True se l'ora Europe/Rome (alla chiusura della barra, DST-aware) e' in [0,7)."""
    close_ts = index + pd.Timedelta(hours=interval_to_hours(interval))
    h = close_ts.tz_convert("Europe/Rome").hour
    return pd.Series((h >= 0) & (h < 7), index=index)


def legacy_crypto(bars: pd.DataFrame, spec: AssetSpec, interval: str = "15m", context: dict | None = None) -> pd.Series:
    context = context or {}
    bench = context.get("benchmark")
    if bench is None and spec.symbol == "BTCUSDT":
        bench = bars
    bias = macro_bias(bench, bars.index, interval) if bench is not None else pd.Series(0, index=bars.index)
    cy = cycle_features(bars, interval)
    c, h, l, v = bars["close"], bars["high"], bars["low"], bars["volume"]
    rsi, e20, e50 = ind.wilder_rsi(c, 14), ind.ema(c, 20), ind.ema(c, 50)
    or_high, or_low = h.shift(1).rolling(4).max(), l.shift(1).rolling(4).min()
    vr = v / (v.rolling(20).mean() + 1e-5)
    night = rome_overnight(bars.index, interval)
    min_vol = pd.Series(np.where(night, 1.70, 1.10), index=bars.index)
    vol_ok = vr >= min_vol

    t_ok_short = cy["tempo"].isin([3, 4]) & (c < cy["fld"])
    t_ok_long = cy["tempo"].isin([1, 2]) & (c > cy["fld"])
    allow_short = (bias == -1) | ((bias == 0) & t_ok_short)
    allow_long = (bias == 1) | ((bias == 0) & t_ok_long)

    short = allow_short & (c < or_low) & (c < e20) & (e20 < e50) & (rsi < 48) & vol_ok
    long_ = allow_long & (c > or_high) & (c > e20) & (e20 > e50) & (rsi > 52) & vol_ok

    if "taker_buy_volume" in bars:
        tbv = bars["taker_buy_volume"]
        ratio = tbv / (v - tbv).replace(0, np.nan)
        max_s = pd.Series(np.where(night, 1.05, 1.25), index=bars.index)
        min_l = pd.Series(np.where(night, 1.15, 0.75), index=bars.index)
        short &= ~((ratio > 1.35) | (ratio > max_s)).fillna(False)
        long_ &= ~((ratio < 0.70) | (ratio < min_l)).fillna(False)
    if "funding_rate" in bars:
        f = bars["funding_rate"].ffill() * 100.0
        short &= ~(f < -0.030).fillna(False)
        long_ &= ~(f > 0.035).fillna(False)
    short &= ~(cy["tempo"] == 1)          # veto 1 tempo
    long_ &= ~cy["ribassista"]            # veto vincolo RIBASSISTA

    sig = pd.Series(0, index=bars.index, dtype=int)
    sig[long_.fillna(False)] = 1
    sig[short.fillna(False)] = -1         # nel bot lo short ha priorita' (mutuamente esclusivi in pratica)
    if not spec.allow_short:
        sig = sig.clip(lower=0)
    return sig


def legacy_equity(bars: pd.DataFrame, spec: AssetSpec, interval: str = "1h", context: dict | None = None) -> pd.Series:
    """Replica long-only del ciclo Alpaca (bias SPY daily+1h, filtro VIX shock se context['vix'] disponibile).
    context['vix']: Series/DataFrame (colonna close) giornaliera; usabile dal giorno successivo."""
    context = context or {}
    bench = context.get("benchmark")
    if bench is None:
        bench = bars
    b = bench
    # bias: daily (EMA20/50) + 1h (EMA20)
    d_c = htf_align(b, "1D", interval)
    d_c = d_c.reindex(bars.index, method='ffill')
    d20 = htf_align(b, "1D", interval, lambda s: ind.ema(s, 20))
    d20 = d20.reindex(bars.index, method='ffill')
    d50 = htf_align(b, "1D", interval, lambda s: ind.ema(s, 50))
    d50 = d50.reindex(bars.index, method='ffill')
    h_c = htf_align(b, "1h", interval)
    h_c = h_c.reindex(bars.index, method='ffill')
    h20 = htf_align(b, "1h", interval, lambda s: ind.ema(s, 20))
    h20 = h20.reindex(bars.index, method='ffill')

    vix = context.get("vix")
    if vix is not None:
        vs = vix["close"] if isinstance(vix, pd.DataFrame) else vix
        vs = vs.dropna()
        vdelta = vs.pct_change() * 100.0
        avail = lambda s: pd.Series(s.to_numpy(), index=s.index + pd.Timedelta(days=1)).reindex(bars.index, method="ffill")
        vval, vdel = avail(vs), avail(vdelta)
        shock = ((vdel > 12.0) & (vval > 28.0)) | (vval > 40.0)
        shock = shock.fillna(False)
        cooling = ((vdel < -5.0) | (vval < 22.0)).fillna(False)
        vdel0 = vdel.fillna(0.0)
    else:
        shock = pd.Series(False, index=bars.index)
        cooling = pd.Series(False, index=bars.index)
        vdel0 = pd.Series(0.0, index=bars.index)
    bull = (d_c > d50) & (d20 >= d50) & ~shock
    neut = (h_c > h20) & (cooling | ~shock)
    bear = (d_c < d50) & (h_c < h20) & (shock | (vdel0 >= 0))
    bias = pd.Series(0, index=bars.index)       # NEUTRAL
    bias[bear & ~bull & ~neut] = -1
    bias[bull] = 1

    cy = cycle_features(bars, interval)
    c = bars["close"]
    rsi, e20, e50 = ind.wilder_rsi(c, 14), ind.ema(c, 20), ind.ema(c, 50)
    allow_long = (bias == 1) | ((bias == 0) & (cy["tempo"].isin([1, 2]) | (c > cy["fld"])))
    up = ((c > e20) & (c > e50)) | ((c > e20) & (e20 > e50))
    long_ = allow_long & ~shock & up & (rsi > 50) & ~cy["ribassista"]
    sig = pd.Series(0, index=bars.index, dtype=int)
    sig[long_.fillna(False)] = 1
    return sig
