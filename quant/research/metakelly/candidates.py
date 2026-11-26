"""Stage 1: point-in-time replay of the LIVE strategy engines to generate candidate trades.

The live functions of services/strategy_engines_service.py are called on windows of closed bars that
end at t, with `now` = end of bar t, so `prepare_closed_bars` drops forming bars exactly as in the bot.
Inputs with no reconstructible history are neutral (see PREREG §3). Cheap NECESSARY conditions of each
engine are checked first, so the (slow) engine is only called where it could trigger: this changes
speed, never the set of signals.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from services import market_calendar
from services.bybit_execution_service import classify_btc_bias, hysteresis_bias
from services.indicators_safe import atr_wilder, wilder_rsi
from services.strategy_engines_service import (
    ENGINE_INTRADAY_MOMENTUM,
    ENGINE_LIQUIDITY_SWEEP,
    ENGINE_TREND_PULLBACK,
    compute_adx,
    engine_intraday_momentum,
    engine_liquidity_sweep_mr,
    engine_trend_pullback_4h1d,
    regime_router,
    select_best_signal,
)

log = logging.getLogger(__name__)
ENGINES = (ENGINE_TREND_PULLBACK, ENGINE_LIQUIDITY_SWEEP, ENGINE_INTRADAY_MOMENTUM)


def to_live(df: pd.DataFrame) -> pd.DataFrame:
    """quant lower-case OHLCV -> live capitalised columns."""
    m = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    return df.rename(columns=m)[["Open", "High", "Low", "Close", "Volume"]]


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Same aggregation as telegram_bot._resample_ohlcv."""
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    return df.resample(rule).agg(agg).dropna(subset=["Close"])


def atr_pct_last(df: pd.DataFrame, fallback: float = 1.0) -> float:
    """telegram_bot._compute_closed_df_atr_pct."""
    if df is None or len(df) < 16:
        return fallback
    last_c = float(df["Close"].iloc[-1] or 0.0)
    if last_c <= 0:
        return fallback
    a = float(atr_wilder(df["High"], df["Low"], df["Close"], 14).iloc[-1] or 0.0)
    return (a / last_c) * 100.0 if a > 0 else fallback


def _vol_ratio(vol: np.ndarray, i: int) -> float:
    if i < 19:
        return 1.0
    avg = float(np.mean(vol[i - 19:i + 1]))
    return float(vol[i]) / (avg + 1e-5)


def _momentum_possible(h: np.ndarray, l: np.ndarray, c: np.ndarray, i: int) -> bool:
    """Necessary condition of engine_intraday_momentum: close beyond the previous 4 bars' extreme."""
    if i < 5:
        return False
    return bool(c[i] > h[i - 4:i].max() or c[i] < l[i - 4:i].min())


def _sweep_possible(h, l, c, i) -> bool:
    """Necessary condition of engine_liquidity_sweep_mr (wick sweep and reclaim of the 12-bar extreme)."""
    if i < 13:
        return False
    pl, ph = l[i - 12:i].min(), h[i - 12:i].max()
    rng = max(h[i] - l[i], 1e-9)
    long_ok = l[i] < pl and c[i] > pl and (c[i] - l[i]) / rng >= 0.45
    short_ok = h[i] > ph and c[i] < ph and (h[i] - c[i]) / rng >= 0.45
    return bool(long_ok or short_ok)


def _pullback_possible(c1: pd.Series, h1: pd.Series, l1: pd.Series) -> bool:
    """Necessary condition of engine_trend_pullback_4h1d with cycle_data = {} (no FLD path)."""
    if len(c1) < 20:
        return False
    last = float(c1.iloc[-1])
    ema20 = float(c1.ewm(span=20, adjust=False).mean().iloc[-1])
    atr = float(atr_wilder(h1, l1, c1, 14).iloc[-1] or 0.0) or last * 0.01
    rsi = float(wilder_rsi(c1, 14).iloc[-1])
    return bool(abs(last - ema20) <= 0.8 * atr and 38.0 <= rsi <= 62.0)


# ---------------------------------------------------------------------------
# US equities (Alpaca cycle, 1h)
# ---------------------------------------------------------------------------

def equities_macro_bias(spy_1h: pd.DataFrame, vix_daily: pd.Series) -> pd.DataFrame:
    """Replica of telegram_bot._get_equities_macro_bias at each SPY 1h bar END (point-in-time).

    SPY daily EMA20/50 on previous daily closes + current price as today's close; SPY 1h EMA20;
    VIX = yesterday's close and yesterday's % change (PREREG §3: used from the next day).
    """
    c = spy_1h["Close"]
    ny = pd.DatetimeIndex(c.index).tz_convert("America/New_York")
    day = pd.Series(ny.normalize().tz_localize(None), index=c.index)
    daily_close = c.groupby(day.to_numpy()).last()
    a20, a50 = 2 / 21, 2 / 51
    e20d = daily_close.ewm(span=20, adjust=False).mean()
    e50d = daily_close.ewm(span=50, adjust=False).mean()
    prev_e20 = e20d.shift(1).reindex(day.to_numpy()).to_numpy()
    prev_e50 = e50d.shift(1).reindex(day.to_numpy()).to_numpy()
    px = c.to_numpy()
    ema20_1d = np.where(np.isfinite(prev_e20), a20 * px + (1 - a20) * prev_e20, px)
    ema50_1d = np.where(np.isfinite(prev_e50), a50 * px + (1 - a50) * prev_e50, px)
    ema20_1h = c.ewm(span=20, adjust=False).mean().to_numpy()

    v = vix_daily.dropna()
    v.index = pd.DatetimeIndex(v.index).tz_localize(None).normalize() if pd.DatetimeIndex(v.index).tz is not None \
        else pd.DatetimeIndex(v.index).normalize()
    vd = v.pct_change() * 100.0
    # value known on day D = close of the last trading day strictly before D
    vix_y = pd.Series(v.to_numpy(), index=v.index + pd.Timedelta(days=1)).reindex(day.to_numpy(), method="ffill").to_numpy()
    vdel_y = pd.Series(vd.to_numpy(), index=v.index + pd.Timedelta(days=1)).reindex(day.to_numpy(), method="ffill").to_numpy()
    vix_y = np.where(np.isfinite(vix_y), vix_y, 20.0)
    vdel_y = np.where(np.isfinite(vdel_y), vdel_y, 0.0)

    bias = []
    for i in range(len(c)):
        vix, dv = vix_y[i], vdel_y[i]
        last_1d = px[i]
        rising = (dv >= 3.0) or (vix >= 24.0 and dv > 0.0)
        shock = (vix >= 26.0 and dv > 0.0) or (dv >= 8.0) or (vix > 35.0)
        cooling = (dv <= -3.0 and vix < 26.0) or (vix < 19.0)
        if shock or (rising and (px[i] < ema20_1h[i] or last_1d < ema50_1d[i])):
            b = "BEARISH"
        elif last_1d > ema50_1d[i] and ema20_1d[i] >= ema50_1d[i] and px[i] > ema20_1h[i] and not rising and not shock:
            b = "BULLISH"
        elif px[i] > ema20_1h[i] and cooling and not rising:
            b = "NEUTRAL"
        elif last_1d < ema50_1d[i] or px[i] < ema20_1h[i] or rising:
            b = "BEARISH"
        else:
            b = "NEUTRAL"
        bias.append(b)
    unfav = (vdel_y > 2.0) | ((vix_y >= 24.0) & (vdel_y >= 0.0)) | (vix_y >= 28.0)
    return pd.DataFrame({"bias": bias, "vix": vix_y, "vix_unfav": unfav}, index=c.index)


def equity_candidates(sym: str, df_1h: pd.DataFrame, macro: pd.DataFrame, window: int = 147) -> List[Dict]:
    """All triggered best-score signals of the Alpaca cycle on one symbol (1h bars, live engines)."""
    df = df_1h.sort_index()
    idx = df.index
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    ends = idx + pd.Timedelta(hours=1)
    out: List[Dict] = []
    for i in range(60, len(df)):
        t = idx[i]
        tny = t.tz_convert("America/New_York")
        b = market_calendar.session_bounds(tny.date())
        if b is None:
            continue
        end = min(ends[i], pd.Timestamp(b[1]).tz_convert("UTC"))
        mtc = (pd.Timestamp(b[1]).tz_convert("UTC") - end).total_seconds() / 60.0
        if mtc < 30.0:
            continue  # live: no entry in the last 30 minutes
        mom = _momentum_possible(h, l, c, i)
        win = df.iloc[max(0, i - window + 1):i + 1]
        pb = _pullback_possible(win["Close"], win["High"], win["Low"])
        if not (mom or pb):
            continue
        if t not in macro.index:
            continue
        mb = macro.loc[t]
        bias, vix, unfav = str(mb["bias"]), float(mb["vix"]), bool(mb["vix_unfav"])
        adx = float(compute_adx(win["High"], win["Low"], win["Close"], 14).iloc[-1] or 20.0)
        atrp = atr_pct_last(win, 1.2)
        route = regime_router(bias, adx, atrp, funding_rate=0.0, vix_val=vix, spread_bps=0.0, is_equities=True)
        allowed = set(route.get("allowed_engines") or [])
        cands = []
        if pb and ENGINE_TREND_PULLBACK in allowed:
            w4 = resample(win, "4h")
            if len(w4) >= 20:
                s = engine_trend_pullback_4h1d(w4, win, bias, cycle_data={}, funding_rate=0.0,
                                               interval_minutes_4h=240, interval_minutes_1h=60, now=end)
                if s:
                    cands.append(s)
        if mom and ENGINE_INTRADAY_MOMENTUM in allowed:
            s = engine_intraday_momentum(win, bias, {}, None, None, 0.0, _vol_ratio(v, i), is_overnight=False,
                                         is_equities=True, vix_unfavorable=unfav, adx_min=16.0,
                                         interval_minutes=60, now=end)
            if s.get("triggered"):
                cands.append(s)
        best = select_best_signal(cands)
        if best:
            out.append({"symbol": sym, "pos": i, "t0": end, "side": 1 if best["side"] == "LONG" else -1,
                        "engine": best["engine"], "sl_pct": float(best["sl_pct"]), "tp_pct": float(best["tp_pct"]),
                        "score": float(best.get("score") or 0.0), "minutes_to_close": mtc, "bias": bias})
    return out


# ---------------------------------------------------------------------------
# Crypto perpetuals (Bybit cycle, 15m)
# ---------------------------------------------------------------------------

def btc_bias_series(btc_15m: pd.DataFrame) -> pd.Series:
    """Replica of telegram_bot._get_btc_macro_bias (4h/1h EMAs + hysteresis) at each 15m bar END."""
    h1 = resample(btc_15m, "1h")
    h4 = resample(btc_15m, "4h")
    c1, c4 = h1["Close"], h4["Close"]
    t1_end = h1.index + pd.Timedelta(hours=1)
    t4_end = h4.index + pd.Timedelta(hours=4)
    cache: Dict[int, str] = {}

    def at_hour(k: int) -> str:  # bias using 1h bars [..k] closed and 4h bars closed by their end
        if k in cache:
            return cache[k]
        if k < 2:
            cache[k] = "NEUTRAL"
            return "NEUTRAL"
        cut = t1_end[k]
        n4 = int((t4_end <= cut).sum())
        cut_prev = t1_end[k - 1]
        n4p = int((t4_end <= cut_prev).sum())
        if n4 < 30 or n4p < 30:
            cache[k] = "NEUTRAL"
            return "NEUTRAL"
        cur = classify_btc_bias(list(c4.iloc[max(0, n4 - 199):n4]), list(c1.iloc[max(0, k - 198):k + 1]))
        prev = classify_btc_bias(list(c4.iloc[max(0, n4p - 199):n4p]), list(c1.iloc[max(0, k - 199):k]))
        cache[k] = hysteresis_bias(cur, prev)
        return cache[k]

    ends15 = btc_15m.index + pd.Timedelta(minutes=15)
    k_idx = np.searchsorted(t1_end.to_numpy(), ends15.to_numpy(), side="right") - 1
    return pd.Series([at_hour(int(k)) if k >= 0 else "NEUTRAL" for k in k_idx], index=btc_15m.index)


def crypto_candidates(sym: str, df_15m: pd.DataFrame, taker_buy: Optional[pd.Series], funding_pct: pd.Series,
                      btc_bias: pd.Series, window: int = 180) -> List[Dict]:
    """All triggered best-score signals of the Bybit cycle on one symbol (15m bars, live engines)."""
    df = df_15m.sort_index()
    idx = df.index
    h, l, c, v = (df[k].to_numpy(float) for k in ("High", "Low", "Close", "Volume"))
    tb = taker_buy.reindex(idx).to_numpy(float) if taker_buy is not None else np.full(len(df), np.nan)
    fund = funding_pct.reindex(idx).ffill().fillna(0.0).to_numpy(float)
    h1_all = resample(df, "1h")
    h4_all = resample(df, "4h")
    h1_end = (h1_all.index + pd.Timedelta(hours=1)).to_numpy()
    h4_end = (h4_all.index + pd.Timedelta(hours=4)).to_numpy()
    ends = idx + pd.Timedelta(minutes=15)
    out: List[Dict] = []
    for i in range(60, len(df)):
        end = ends[i]
        mom = _momentum_possible(h, l, c, i)
        sw = _sweep_possible(h, l, c, i)
        hourly = (end.minute == 0)
        n1 = int(np.searchsorted(h1_end, end.to_datetime64(), side="right"))
        n4 = int(np.searchsorted(h4_end, end.to_datetime64(), side="right"))
        w1 = h1_all.iloc[max(0, n1 - 120):n1]
        w4 = h4_all.iloc[max(0, n4 - 100):n4]
        pb = hourly and _pullback_possible(w1["Close"], w1["High"], w1["Low"]) if len(w1) >= 20 else False
        if not (mom or sw or pb):
            continue
        win = df.iloc[max(0, i - window + 1):i + 1]
        bias = str(btc_bias.iloc[i]) if i < len(btc_bias) else "NEUTRAL"
        f = float(fund[i])
        adx_src = w1 if len(w1) >= 28 else win
        adx = float(compute_adx(adx_src["High"], adx_src["Low"], adx_src["Close"], 14).iloc[-1] or 20.0)
        atrp = atr_pct_last(win, 1.0)
        route = regime_router(bias, adx, atrp, funding_rate=f, spread_bps=1.0)
        allowed = set(route.get("allowed_engines") or [])
        buy = tb[i]
        sell = v[i] - buy if np.isfinite(buy) else np.nan
        ratio = float(buy / (sell + 1e-6)) if (np.isfinite(buy) and v[i] > 0) else 1.0
        cvd = {"ratio": round(ratio, 2), "bias": "BULLISH" if ratio > 1.35 else ("BEARISH" if ratio < 0.70 else "NEUTRAL")}
        obi = {"bias": "BALANCED", "imbalance": 0.0}
        rome_h = end.tz_convert("Europe/Rome").hour
        cands = []
        if pb and ENGINE_TREND_PULLBACK in allowed and len(w4) >= 20:
            s = engine_trend_pullback_4h1d(w4, w1, bias, cycle_data={}, funding_rate=f,
                                           interval_minutes_4h=240, interval_minutes_1h=60, now=end)
            if s:
                cands.append(s)
        if sw and ENGINE_LIQUIDITY_SWEEP in allowed:
            s = engine_liquidity_sweep_mr(win, cvd, obi, f, bias, interval_minutes=15, now=end)
            if s:
                cands.append(s)
        if mom and ENGINE_INTRADAY_MOMENTUM in allowed:
            s = engine_intraday_momentum(win, bias, {}, cvd, obi, f, _vol_ratio(v, i), is_overnight=(0 <= rome_h < 7),
                                         is_equities=False, adx_min=16.0, interval_minutes=15, now=end)
            if s.get("triggered"):
                cands.append(s)
        best = select_best_signal(cands)
        if best:
            out.append({"symbol": sym, "pos": i, "t0": end, "side": 1 if best["side"] == "LONG" else -1,
                        "engine": best["engine"], "sl_pct": float(best["sl_pct"]), "tp_pct": float(best["tp_pct"]),
                        "score": float(best.get("score") or 0.0), "minutes_to_close": np.nan, "bias": bias})
    return out
