"""Quantitative Strategy Engines, Regime Router & Causal Shadow Evaluator.

Stateless, pure DataFrame-driven signal engines built without lookahead bias:
- Reuses `wilder_rsi`, `atr_wilder`, `drop_forming_bar` from `services.indicators_safe`.
- Reuses `HurstMigliorinoCycleService` from `services.hurst_migliorino_cycles`.
- Engines:
  1. TREND_PULLBACK_4H  (`engine_trend_pullback_4h1d`): Maker limit pullback on 4H/1H structure.
  2. LIQUIDITY_SWEEP_MR (`engine_liquidity_sweep_mr`): Contrarian Maker fade of trapped stops.
  3. INTRADAY_MOMENTUM  (`engine_intraday_momentum`): Filtered intraday breakout with shadow telemetry.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from services.hurst_migliorino_cycles import HurstMigliorinoCycleService
from services.indicators_safe import atr_wilder, drop_forming_bar, wilder_rsi

ENGINE_TREND_PULLBACK = "TREND_PULLBACK_4H"
ENGINE_LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP_MR"
ENGINE_INTRADAY_MOMENTUM = "INTRADAY_MOMENTUM"
ALL_ENGINES = [ENGINE_TREND_PULLBACK, ENGINE_LIQUIDITY_SWEEP, ENGINE_INTRADAY_MOMENTUM]


# ---------------------------------------------------------------------------
# Internal pure helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        val = float(value)
        return val if math.isfinite(val) else default
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _col_series(df: pd.DataFrame, names: Tuple[str, ...]) -> Optional[pd.Series]:
    col_map = {str(c).lower(): c for c in df.columns}
    for name in names:
        key = name.lower()
        if key in col_map:
            col = df[col_map[key]]
            if isinstance(col, pd.DataFrame):
                col = col.iloc[:, 0]
            return pd.to_numeric(col, errors="coerce").astype(float)
    return None


def _extract_ohlcv(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Normalize OHLCV columns case-insensitively without mutating caller DataFrame."""
    if df is None or not isinstance(df, pd.DataFrame) or len(df) == 0:
        return None
    close = _col_series(df, ("Close", "close"))
    if close is None:
        return None
    valid_mask = close.notna() & np.isfinite(close)
    if not valid_mask.any():
        return None

    high = _col_series(df, ("High", "high"))
    low = _col_series(df, ("Low", "low"))
    open_s = _col_series(df, ("Open", "open"))
    volume = _col_series(df, ("Volume", "volume"))

    out = pd.DataFrame(index=df.index)
    out["Close"] = close
    out["High"] = high.fillna(close) if high is not None else close
    out["Low"] = low.fillna(close) if low is not None else close
    out["Open"] = open_s.fillna(close) if open_s is not None else close
    out["Volume"] = volume.fillna(0.0) if volume is not None else pd.Series(0.0, index=df.index, dtype=float)
    return out.loc[valid_mask]


def prepare_closed_bars(
    df: Optional[pd.DataFrame],
    interval_minutes: Optional[float] = None,
    now: Any = None,
) -> Optional[pd.DataFrame]:
    """Strip an unclosed forming bar via `drop_forming_bar` when `interval_minutes` is provided."""
    norm = _extract_ohlcv(df)
    if norm is None or len(norm) == 0:
        return norm
    if interval_minutes is not None and interval_minutes > 0:
        norm = drop_forming_bar(norm, interval_minutes, now=now)
    return norm


def _resolve_cycle_data(close: pd.Series, cycle_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if cycle_data is not None:
        return dict(cycle_data)
    if len(close) >= 65:
        return HurstMigliorinoCycleService.calculate_cycle_metrics(pd.DataFrame({"Close": close}))
    return {}


# ---------------------------------------------------------------------------
# 1. Shared Microstructure & Indicator Utilities
# ---------------------------------------------------------------------------

def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's ADX (+DI / -DI / DX smoothed), NaN-safe with ~20.0 fallback for short series."""
    if close is None or len(close) == 0:
        return pd.Series(dtype=float)

    h = pd.to_numeric(high, errors="coerce").astype(float)
    l = pd.to_numeric(low, errors="coerce").astype(float)
    c = pd.to_numeric(close, errors="coerce").astype(float)

    if period <= 0 or len(c) < period * 2 or c.notna().sum() < period * 2:
        return pd.Series(20.0, index=c.index, dtype=float)

    up_move = h.diff()
    down_move = -l.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0.0), 0.0).where(up_move.notna())
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0.0), 0.0).where(down_move.notna())

    alpha = 1.0 / float(period)
    atr = atr_wilder(h, l, c, n=period)
    atr_safe = atr.where(atr > 1e-12, np.nan)

    plus_di = (100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_safe).fillna(0.0)
    minus_di = (100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_safe).fillna(0.0)

    di_sum = plus_di + minus_di
    # Guard against EWM decay ghost residuals in dead/inside-bar ranges where total DI < 1% of ATR
    dx = (100.0 * (plus_di - minus_di).abs() / di_sum).where(di_sum > 1.0, 0.0)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    adx = adx.replace([np.inf, -np.inf], np.nan).fillna(20.0).clip(lower=0.0, upper=100.0)
    return adx


def compute_spread_bps(bid: float, ask: float) -> float:
    """Compute bid-ask spread in basis points safely; returns 0.0 if inputs are invalid."""
    b = _safe_float(bid, -1.0)
    a = _safe_float(ask, -1.0)
    if b <= 0.0 or a <= 0.0 or a < b:
        return 0.0
    mid = (b + a) * 0.5
    if mid <= 0.0 or not math.isfinite(mid):
        return 0.0
    spread = ((a - b) / mid) * 10000.0
    if not math.isfinite(spread):
        return 0.0
    return round(_clamp(spread, 0.0, 10000.0), 4)


def extract_normalized_features(
    df: pd.DataFrame,
    cycle_data: Optional[Dict[str, Any]] = None,
    cvd_info: Optional[Dict[str, Any]] = None,
    obi_info: Optional[Dict[str, Any]] = None,
    funding_rate: float = 0.0,
    vix_val: Optional[float] = None,
    spread_bps: float = 0.0,
    macro_bias: str = "NEUTRAL",
    interval_minutes: Optional[float] = None,
    now: Any = None,
) -> Dict[str, Any]:
    """Extract lookahead-free normalized numeric context from closed OHLCV bars."""
    bias = str(macro_bias or "NEUTRAL").upper()
    vix_clean: Optional[float] = None
    if vix_val is not None:
        vix_num = _safe_float(vix_val, float("nan"))
        if math.isfinite(vix_num):
            vix_clean = round(vix_num, 4)

    cvd_ratio = _safe_float((cvd_info or {}).get("ratio", 1.0), 1.0)
    obi_imbalance = _safe_float((obi_info or {}).get("imbalance", 0.0), 0.0)
    funding_clean = _safe_float(funding_rate, 0.0)
    spread_clean = max(0.0, _safe_float(spread_bps, 0.0))

    bars = prepare_closed_bars(df, interval_minutes=interval_minutes, now=now)
    if bars is None or len(bars) == 0:
        return {
            "last_price": 0.0,
            "rsi": 50.0,
            "atr_pct": 0.0,
            "adx": 20.0,
            "dist_ema20_atr": 0.0,
            "dist_ema50_atr": 0.0,
            "dist_fld_atr": 0.0,
            "vol_ratio": 1.0,
            "cvd_ratio": round(cvd_ratio, 4),
            "obi_imbalance": round(obi_imbalance, 4),
            "funding_rate": round(funding_clean, 6),
            "vix_val": vix_clean,
            "spread_bps": round(spread_clean, 4),
            "tempo_battleplan": str((cycle_data or {}).get("tempo_battleplan", "") or ""),
            "macro_bias": bias,
        }

    close = bars["Close"]
    high = bars["High"]
    low = bars["Low"]
    vol = bars["Volume"]

    last_price = _safe_float(close.iloc[-1], 0.0)
    rsi_val = _safe_float(wilder_rsi(close, 14).iloc[-1], 50.0) if len(close) >= 2 else 50.0
    atr_val = _safe_float(atr_wilder(high, low, close, 14).iloc[-1], 0.0)
    atr_pct = (atr_val / last_price * 100.0) if last_price > 0.0 else 0.0
    adx_val = _safe_float(compute_adx(high, low, close, 14).iloc[-1], 20.0)

    ema20 = _safe_float(close.ewm(span=20, adjust=False).mean().iloc[-1], last_price)
    ema50 = _safe_float(close.ewm(span=50, adjust=False).mean().iloc[-1], last_price)
    safe_atr = max(atr_val, last_price * 1e-4, 1e-9)

    dist_ema20_atr = (last_price - ema20) / safe_atr
    dist_ema50_atr = (last_price - ema50) / safe_atr

    resolved_cycle = _resolve_cycle_data(close, cycle_data)
    hurst_fld = _safe_float(resolved_cycle.get("hurst_fld_value", 0.0), 0.0)
    dist_fld_atr = ((last_price - hurst_fld) / safe_atr) if hurst_fld > 0.0 else 0.0
    tempo_battleplan = str(resolved_cycle.get("tempo_battleplan", "") or "")

    if len(vol) > 0 and (vol > 0).any():
        avg_vol = _safe_float(vol.rolling(20, min_periods=1).mean().iloc[-1], 0.0)
        last_vol = _safe_float(vol.iloc[-1], 0.0)
        vol_ratio = (last_vol / (avg_vol + 1e-9)) if avg_vol > 0.0 else 1.0
    else:
        vol_ratio = 1.0

    return {
        "last_price": round(last_price, 8),
        "rsi": round(rsi_val, 4),
        "atr_pct": round(atr_pct, 4),
        "adx": round(adx_val, 4),
        "dist_ema20_atr": round(dist_ema20_atr, 4),
        "dist_ema50_atr": round(dist_ema50_atr, 4),
        "dist_fld_atr": round(dist_fld_atr, 4),
        "vol_ratio": round(vol_ratio, 4),
        "cvd_ratio": round(cvd_ratio, 4),
        "obi_imbalance": round(obi_imbalance, 4),
        "funding_rate": round(funding_clean, 6),
        "vix_val": vix_clean,
        "spread_bps": round(spread_clean, 4),
        "tempo_battleplan": tempo_battleplan,
        "macro_bias": bias,
    }


# ---------------------------------------------------------------------------
# 2. Regime Router
# ---------------------------------------------------------------------------

def regime_router(
    macro_bias: str,
    adx_1h: float,
    atr_pct: float,
    funding_rate: float = 0.0,
    vix_val: Optional[float] = None,
    spread_bps: float = 0.0,
) -> Dict[str, Any]:
    """Route active strategy engines and execution preference based on trend/squeeze regime."""
    bias = str(macro_bias or "NEUTRAL").upper()
    adx = _safe_float(adx_1h, 20.0)
    atr = _safe_float(atr_pct, 0.0)
    funding = _safe_float(funding_rate, 0.0)
    spread = max(0.0, _safe_float(spread_bps, 0.0))
    vix_num = _safe_float(vix_val, float("nan")) if vix_val is not None else float("nan")

    if adx < 18.0 or abs(funding) >= 0.025:
        regime = "RANGE_OR_SQUEEZE"
        allowed_engines = [ENGINE_LIQUIDITY_SWEEP]
        prefer_limit = True
    elif (bias in ("BULLISH", "BEARISH") and adx >= 24.0) or (adx >= 30.0 and atr >= 0.4):
        regime = "TREND_STRONG"
        allowed_engines = [ENGINE_TREND_PULLBACK, ENGINE_INTRADAY_MOMENTUM]
        prefer_limit = True  # Pullback Limit engine prioritized; also protective if spread wide
    else:
        regime = "TRANSITION_NEUTRAL"
        allowed_engines = [ENGINE_TREND_PULLBACK, ENGINE_LIQUIDITY_SWEEP, ENGINE_INTRADAY_MOMENTUM]
        prefer_limit = bool(
            spread >= 8.0 or (math.isfinite(vix_num) and vix_num >= 24.0)
        )

    return {
        "regime": regime,
        "allowed_engines": allowed_engines,
        "prefer_limit": prefer_limit,
    }


# ---------------------------------------------------------------------------
# 3. Engine 1 — TREND_PULLBACK_4H
# ---------------------------------------------------------------------------

def engine_trend_pullback_4h1d(
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    macro_bias: str,
    cycle_data: Optional[Dict[str, Any]] = None,
    funding_rate: float = 0.0,
    interval_minutes_4h: Optional[float] = None,
    interval_minutes_1h: Optional[float] = None,
    now: Any = None,
) -> Optional[Dict[str, Any]]:
    """Multi-timeframe 4H structure + 1H EMA20/FLD pullback Maker Limit engine."""
    bars_4h = prepare_closed_bars(df_4h, interval_minutes=interval_minutes_4h, now=now)
    bars_1h = prepare_closed_bars(df_1h, interval_minutes=interval_minutes_1h, now=now)
    if bars_4h is None or bars_1h is None or len(bars_4h) < 20 or len(bars_1h) < 20:
        return None

    bias = str(macro_bias or "NEUTRAL").upper()
    funding = _safe_float(funding_rate, 0.0)

    c4 = bars_4h["Close"]
    last_4h = _safe_float(c4.iloc[-1], 0.0)
    ema20_4h = _safe_float(c4.ewm(span=20, adjust=False).mean().iloc[-1], last_4h)
    ema50_4h = _safe_float(c4.ewm(span=50, adjust=False).mean().iloc[-1], last_4h)
    if last_4h <= 0.0:
        return None

    struct_4h_up = (last_4h > ema50_4h) or (ema20_4h > ema50_4h)
    struct_4h_down = (last_4h < ema50_4h) or (ema20_4h < ema50_4h)

    c1 = bars_1h["Close"]
    h1 = bars_1h["High"]
    l1 = bars_1h["Low"]
    last_1h = _safe_float(c1.iloc[-1], 0.0)
    if last_1h <= 0.0:
        return None

    ema20_1h = _safe_float(c1.ewm(span=20, adjust=False).mean().iloc[-1], last_1h)
    ema50_1h = _safe_float(c1.ewm(span=50, adjust=False).mean().iloc[-1], last_1h)

    rsi_series = wilder_rsi(c1, 14)
    rsi_1h = _safe_float(rsi_series.iloc[-1], 50.0)
    prev_rsi_1h = _safe_float(rsi_series.iloc[-2], rsi_1h)

    atr_1h = _safe_float(atr_wilder(h1, l1, c1, 14).iloc[-1], 0.0)
    if atr_1h <= 0.0:
        atr_1h = last_1h * 0.01
    atr_pct = (atr_1h / last_1h) * 100.0

    resolved_cycle = _resolve_cycle_data(c1, cycle_data)
    vincolo_up = str(resolved_cycle.get("vincolo_migliorino", "LIBERO") or "LIBERO").upper()
    tempo_up = str(resolved_cycle.get("tempo_battleplan", "") or "").upper()
    hurst_fld = _safe_float(resolved_cycle.get("hurst_fld_value", 0.0), 0.0)

    diff_ema20 = last_1h - ema20_1h
    diff_fld = (last_1h - hurst_fld) if hurst_fld > 0.0 else None

    near_long = (-0.8 * atr_1h <= diff_ema20 <= 0.6 * atr_1h) or (
        diff_fld is not None and (-0.8 * atr_1h <= diff_fld <= 0.6 * atr_1h)
    )
    near_short = (-0.6 * atr_1h <= diff_ema20 <= 0.8 * atr_1h) or (
        diff_fld is not None and (-0.6 * atr_1h <= diff_fld <= 0.8 * atr_1h)
    )

    long_ok = (
        bias in ("BULLISH", "NEUTRAL")
        and struct_4h_up
        and last_1h > ema50_1h
        and near_long
        and (42.0 <= rsi_1h <= 62.0)
        and (rsi_1h >= prev_rsi_1h)
        and ("RIBASSISTA" not in vincolo_up)
        and (funding <= 0.035)
    )

    short_ok = (
        bias in ("BEARISH", "NEUTRAL")
        and struct_4h_down
        and last_1h < ema50_1h
        and near_short
        and (38.0 <= rsi_1h <= 58.0)
        and (rsi_1h <= prev_rsi_1h)
        and ("1° TEMPO" not in tempo_up)
        and ("RIALZISTA FORZATO" not in vincolo_up)
        and (funding >= -0.030)
    )

    if not long_ok and not short_ok:
        return None

    side = "LONG" if long_ok else "SHORT"
    if side == "LONG":
        limit_price = min(last_1h, max(ema20_1h, last_1h * 0.9985))
    else:
        limit_price = max(last_1h, min(ema20_1h, last_1h * 1.0015))

    sl_pct = round(_clamp(atr_pct * 1.35, 1.00, 2.40), 2)
    tp_pct = round(sl_pct * 3.0, 2)

    features = extract_normalized_features(
        bars_1h,
        cycle_data=resolved_cycle,
        funding_rate=funding,
        macro_bias=bias,
    )

    # Deterministic quality score (0..100)
    score = 65.0
    if (side == "LONG" and bias == "BULLISH") or (side == "SHORT" and bias == "BEARISH"):
        score += 15.0
    else:
        score += 5.0
    dist_ema = abs(features["dist_ema20_atr"])
    score += 10.0 * max(0.0, 1.0 - dist_ema)
    if hurst_fld > 0.0:
        if (side == "LONG" and last_1h > hurst_fld) or (side == "SHORT" and last_1h < hurst_fld):
            score += 5.0
    if (side == "LONG" and ("1° TEMPO" in tempo_up or "2° TEMPO" in tempo_up)) or (
        side == "SHORT" and ("3° TEMPO" in tempo_up or "4° TEMPO" in tempo_up)
    ):
        score += 5.0
    score = round(_clamp(score, 0.0, 100.0), 2)

    reason = (
        f"4H_{side}_PULLBACK near 1H EMA20 ({ema20_1h:.4f}), "
        f"RSI={rsi_1h:.1f} (prev={prev_rsi_1h:.1f}), bias={bias}"
    )

    return {
        "triggered": True,
        "side": side,
        "engine": ENGINE_TREND_PULLBACK,
        "reject_reason": "",
        "order_type": "Limit",
        "limit_price": round(limit_price, 8),
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "score": score,
        "reason": reason,
        "features": features,
    }


# ---------------------------------------------------------------------------
# 4. Engine 2 — LIQUIDITY_SWEEP_MR
# ---------------------------------------------------------------------------

def engine_liquidity_sweep_mr(
    df_15m: pd.DataFrame,
    cvd_info: Optional[Dict[str, Any]],
    obi_info: Optional[Dict[str, Any]],
    funding_rate: float,
    macro_bias: str,
    interval_minutes: Optional[float] = None,
    now: Any = None,
) -> Optional[Dict[str, Any]]:
    """Contrarian Maker Limit engine fading liquidity stop-sweeps confirmed by orderflow/funding."""
    bars = prepare_closed_bars(df_15m, interval_minutes=interval_minutes, now=now)
    if bars is None or len(bars) < 15:
        return None

    bias = str(macro_bias or "NEUTRAL").upper()
    funding = _safe_float(funding_rate, 0.0)
    cvd_ratio = _safe_float((cvd_info or {}).get("ratio", 1.0), 1.0)
    obi_imbalance = _safe_float((obi_info or {}).get("imbalance", 0.0), 0.0)

    high = bars["High"]
    low = bars["Low"]
    close = bars["Close"]

    prior_low = _safe_float(low.iloc[-13:-1].min(), 0.0)
    prior_high = _safe_float(high.iloc[-13:-1].max(), 0.0)

    bar_high = _safe_float(high.iloc[-1], 0.0)
    bar_low = _safe_float(low.iloc[-1], 0.0)
    bar_close = _safe_float(close.iloc[-1], 0.0)
    if bar_close <= 0.0:
        return None

    bar_range = max(bar_high - bar_low, 1e-9)
    lower_wick_ratio = (bar_close - bar_low) / bar_range
    upper_wick_ratio = (bar_high - bar_close) / bar_range

    rsi_15m = _safe_float(wilder_rsi(close, 14).iloc[-1], 50.0)
    atr_15m = _safe_float(atr_wilder(high, low, close, 14).iloc[-1], 0.0)
    atr_pct = (atr_15m / bar_close * 100.0) if atr_15m > 0.0 else 0.0

    long_confirmations = [
        ("CVD", cvd_ratio >= 1.10),
        ("OBI", obi_imbalance >= 0.25),
        ("FUNDING", funding <= -0.015),
    ]
    long_hits = [name for name, ok in long_confirmations if ok]

    short_confirmations = [
        ("CVD", cvd_ratio <= 0.92),
        ("OBI", obi_imbalance <= -0.25),
        ("FUNDING", funding >= 0.025),
    ]
    short_hits = [name for name, ok in short_confirmations if ok]

    long_sweep = (
        (bar_low < prior_low)
        and (bar_close > prior_low)
        and (lower_wick_ratio >= 0.45)
        and (len(long_hits) >= 1)
        and not (bias == "BEARISH" and rsi_15m < 25.0)
    )

    short_sweep = (
        (bar_high > prior_high)
        and (bar_close < prior_high)
        and (upper_wick_ratio >= 0.45)
        and (len(short_hits) >= 1)
        and not (bias == "BULLISH" and rsi_15m > 75.0)
    )

    if not long_sweep and not short_sweep:
        return None

    # Disambiguate rare outside bar sweeping both sides by stronger rejection + confirmation count
    if long_sweep and short_sweep:
        choose_long = (len(long_hits), lower_wick_ratio) >= (len(short_hits), upper_wick_ratio)
    else:
        choose_long = long_sweep

    if choose_long:
        side = "LONG"
        hits = long_hits
        wick_ratio = lower_wick_ratio
        limit_price = min(bar_close, max(prior_low, bar_close * 0.999))
        level_ref = prior_low
    else:
        side = "SHORT"
        hits = short_hits
        wick_ratio = upper_wick_ratio
        limit_price = max(bar_close, min(prior_high, bar_close * 1.001))
        level_ref = prior_high

    sl_pct = round(_clamp(atr_pct * 1.1, 0.75, 1.60), 2)
    tp_pct = round(sl_pct * 3.0, 2)

    features = extract_normalized_features(
        bars,
        cvd_info=cvd_info,
        obi_info=obi_info,
        funding_rate=funding,
        macro_bias=bias,
    )

    score = 60.0 + 10.0 * min(3, len(hits)) + 10.0 * _clamp(wick_ratio, 0.0, 1.0)
    score = round(_clamp(score, 0.0, 100.0), 2)
    reason = (
        f"{side}_SWEEP level={level_ref:.4f} reclaimed={bar_close:.4f} "
        f"(wick={wick_ratio:.2f}, confirms={','.join(hits)})"
    )

    return {
        "triggered": True,
        "side": side,
        "engine": ENGINE_LIQUIDITY_SWEEP,
        "reject_reason": "",
        "order_type": "Limit",
        "limit_price": round(limit_price, 8),
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "score": score,
        "reason": reason,
        "features": features,
    }


# ---------------------------------------------------------------------------
# 5. Engine 3 — INTRADAY_MOMENTUM
# ---------------------------------------------------------------------------

def engine_intraday_momentum(
    df_15m: pd.DataFrame,
    macro_bias: str,
    cycle_data: Optional[Dict[str, Any]],
    cvd_info: Optional[Dict[str, Any]],
    obi_info: Optional[Dict[str, Any]],
    funding_rate: float,
    vol_ratio: float,
    is_overnight: bool,
    is_equities: bool = False,
    vix_unfavorable: bool = False,
    adx_min: float = 16.0,
    interval_minutes: Optional[float] = None,
    now: Any = None,
) -> Dict[str, Any]:
    """Momentum breakout engine with full regime/microstructure shields and shadow reject logging."""
    bars = prepare_closed_bars(df_15m, interval_minutes=interval_minutes, now=now)
    bias = str(macro_bias or "NEUTRAL").upper()
    funding = _safe_float(funding_rate, 0.0)

    def _result(
        triggered: bool,
        side: Optional[str],
        reject_reason: str,
        sl_pct: float,
        tp_pct: float,
        score: float,
        features: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "triggered": triggered,
            "side": side,
            "engine": ENGINE_INTRADAY_MOMENTUM,
            "reject_reason": reject_reason,
            "order_type": "Market",
            "limit_price": None,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "score": score,
            "features": features,
        }

    if bars is None or len(bars) < 20:
        empty_feats = extract_normalized_features(
            bars if bars is not None else pd.DataFrame(),
            cycle_data=cycle_data,
            cvd_info=cvd_info,
            obi_info=obi_info,
            funding_rate=funding,
            macro_bias=bias,
        )
        return _result(False, None, "INSUFFICIENT_DATA", 1.0, 3.0, 0.0, empty_feats)

    close = bars["Close"]
    high = bars["High"]
    low = bars["Low"]
    resolved_cycle = _resolve_cycle_data(close, cycle_data)

    features = extract_normalized_features(
        bars,
        cycle_data=resolved_cycle,
        cvd_info=cvd_info,
        obi_info=obi_info,
        funding_rate=funding,
        macro_bias=bias,
    )

    last_c = _safe_float(close.iloc[-1], 0.0)
    ema20 = _safe_float(close.ewm(span=20, adjust=False).mean().iloc[-1], last_c)
    ema50 = _safe_float(close.ewm(span=50, adjust=False).mean().iloc[-1], last_c)
    rsi = features["rsi"]
    adx = features["adx"]
    atr_pct = features["atr_pct"]
    eff_vol_ratio = _safe_float(vol_ratio, features["vol_ratio"])
    features["vol_ratio"] = round(eff_vol_ratio, 4)

    max_sl = 2.50 if is_equities else 1.80
    sl_pct = round(_clamp(atr_pct * 1.4, 0.90, max_sl), 2)
    tp_pct = round(sl_pct * 3.0, 2)

    or_high = _safe_float(high.iloc[-5:-1].max(), last_c)
    or_low = _safe_float(low.iloc[-5:-1].min(), last_c)

    # Chop ADX guard (captures both breakout fakeouts in chop and low-ADX chop regimes)
    if adx < adx_min:
        chop_side = "LONG" if last_c > or_high else ("SHORT" if last_c < or_low else None)
        return _result(False, chop_side, "LOW_ADX_CHOP", sl_pct, tp_pct, 0.0, features)

    cand_long = (last_c > or_high) and (last_c > ema20 > ema50) and (rsi > 52.0)
    cand_short = (last_c < or_low) and (last_c < ema20 < ema50) and (rsi < 48.0)

    if not cand_long and not cand_short:
        return _result(False, None, "NO_SIGNAL", sl_pct, tp_pct, 0.0, features)

    side = "LONG" if cand_long else "SHORT"

    if side == "LONG" and vix_unfavorable:
        return _result(False, side, "VIX_SHIELD", sl_pct, tp_pct, 0.0, features)

    min_vol_required = 1.70 if is_overnight else 1.10
    if eff_vol_ratio < min_vol_required:
        rej = "LOW_VOLUME_OVERNIGHT" if is_overnight else "LOW_VOLUME"
        return _result(False, side, rej, sl_pct, tp_pct, 0.0, features)

    tempo_up = str(resolved_cycle.get("tempo_battleplan", "") or "").upper()
    vincolo_up = str(resolved_cycle.get("vincolo_migliorino", "LIBERO") or "LIBERO").upper()
    hurst_fld = _safe_float(resolved_cycle.get("hurst_fld_value", 0.0), 0.0)

    if side == "LONG":
        allow_long = (bias == "BULLISH") or (
            bias == "NEUTRAL"
            and ("1° TEMPO" in tempo_up or "2° TEMPO" in tempo_up)
            and (hurst_fld <= 0.0 or last_c > hurst_fld)
        )
        if not allow_long or "RIBASSISTA" in vincolo_up:
            return _result(False, side, "CYCLE_CONFLICT", sl_pct, tp_pct, 0.0, features)
    else:
        allow_short = (bias == "BEARISH") or (
            bias == "NEUTRAL"
            and ("3° TEMPO" in tempo_up or "4° TEMPO" in tempo_up)
            and (hurst_fld <= 0.0 or last_c < hurst_fld)
        )
        if not allow_short or "RIALZISTA FORZATO" in vincolo_up or "1° TEMPO" in tempo_up:
            return _result(False, side, "CYCLE_CONFLICT", sl_pct, tp_pct, 0.0, features)

    cvd_bias = str((cvd_info or {}).get("bias", "NEUTRAL") or "NEUTRAL").upper()
    cvd_ratio = features["cvd_ratio"]
    if side == "LONG":
        min_cvd = 1.15 if is_overnight else 0.75
        if cvd_bias == "BEARISH" or cvd_ratio < min_cvd:
            return _result(False, side, "CVD_SHIELD", sl_pct, tp_pct, 0.0, features)
        if funding > 0.035:
            return _result(False, side, "FUNDING_SQUEEZE", sl_pct, tp_pct, 0.0, features)
    else:
        max_cvd = 1.05 if is_overnight else 1.25
        if cvd_bias == "BULLISH" or cvd_ratio > max_cvd:
            return _result(False, side, "CVD_SHIELD", sl_pct, tp_pct, 0.0, features)
        if funding < -0.030:
            return _result(False, side, "FUNDING_SQUEEZE", sl_pct, tp_pct, 0.0, features)

    obi_bias = str((obi_info or {}).get("bias", "BALANCED") or "BALANCED").upper()
    obi_imb = features["obi_imbalance"]
    if side == "LONG" and ((obi_bias == "SELL_WALL" and obi_imb < -0.40) or obi_imb <= -0.45):
        return _result(False, side, "OBI_WALL", sl_pct, tp_pct, 0.0, features)
    if side == "SHORT" and ((obi_bias == "BUY_WALL" and obi_imb > 0.40) or obi_imb >= 0.45):
        return _result(False, side, "OBI_WALL", sl_pct, tp_pct, 0.0, features)

    # Triggered: compute quality score
    score = 58.0
    if (side == "LONG" and bias == "BULLISH") or (side == "SHORT" and bias == "BEARISH"):
        score += 12.0
    score += min(10.0, max(0.0, (adx - adx_min) * 0.5))
    score += min(10.0, max(0.0, (eff_vol_ratio - min_vol_required) * 10.0))
    if (side == "LONG" and cvd_ratio >= 1.2) or (side == "SHORT" and cvd_ratio <= 0.8):
        score += 10.0
    score = round(_clamp(score, 0.0, 100.0), 2)

    return _result(True, side, "", sl_pct, tp_pct, score, features)


# ---------------------------------------------------------------------------
# 6. Signal Selector & Causal Shadow Forward Simulator
# ---------------------------------------------------------------------------

def select_best_signal(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the highest-scoring triggered candidate signal, or None if none fired."""
    valid = [
        c for c in (candidates or [])
        if isinstance(c, dict)
        and bool(c.get("triggered", True))
        and c.get("side") in ("LONG", "SHORT")
    ]
    if not valid:
        return None
    return max(valid, key=lambda c: _safe_float(c.get("score", 0.0), 0.0))


def evaluate_shadow_bars(
    side: str,
    signal_price: float,
    sl_pct: float,
    tp_pct: float,
    future_ohlcv_df: pd.DataFrame,
    fee_rt_pct: float = 0.12,
    min_bars_for_time_exit: int = 6,
    interval_minutes: Optional[float] = None,
    now: Any = None,
) -> Dict[str, Any]:
    """Strictly forward bar-by-bar outcome simulation for triggered or rejected shadow signals.

    Tie-breaking rule: if both `sl_price` and `tp_price` lie inside a single bar's [Low, High],
    `SL` is conservatively triggered first. Round-trip `fee_rt_pct` is always deducted.
    """
    side_u = str(side or "").upper()
    if side_u == "BUY":
        side_u = "LONG"
    elif side_u == "SELL":
        side_u = "SHORT"

    sig_p = _safe_float(signal_price, -1.0)
    sl_p_pct = _safe_float(sl_pct, -1.0)
    tp_p_pct = _safe_float(tp_pct, -1.0)
    fee = max(0.0, _safe_float(fee_rt_pct, 0.12))

    def _insufficient(mfe: float = 0.0, mae: float = 0.0, bars_held: int = 0) -> Dict[str, Any]:
        return {
            "status": "INSUFFICIENT",
            "virtual_pnl_pct": 0.0,
            "virtual_r": 0.0,
            "mfe_pct": round(mfe, 4),
            "mae_pct": round(mae, 4),
            "hit_outcome": "INSUFFICIENT",
            "bars_held": bars_held,
        }

    bars = prepare_closed_bars(future_ohlcv_df, interval_minutes=interval_minutes, now=now)
    if (
        side_u not in ("LONG", "SHORT")
        or sig_p <= 0.0
        or sl_p_pct <= 0.0
        or tp_p_pct <= 0.0
        or bars is None
        or len(bars) == 0
    ):
        return _insufficient()

    if side_u == "LONG":
        sl_price = sig_p * (1.0 - sl_p_pct / 100.0)
        tp_price = sig_p * (1.0 + tp_p_pct / 100.0)
    else:
        sl_price = sig_p * (1.0 + sl_p_pct / 100.0)
        tp_price = sig_p * (1.0 - tp_p_pct / 100.0)

    highs = bars["High"].to_numpy(dtype=float)
    lows = bars["Low"].to_numpy(dtype=float)
    closes = bars["Close"].to_numpy(dtype=float)

    mfe_pct = 0.0
    mae_pct = 0.0
    denom_r = max(sl_p_pct, 0.1)

    for idx in range(len(bars)):
        h = float(highs[idx])
        l = float(lows[idx])
        c = float(closes[idx])
        bars_held = idx + 1

        if side_u == "LONG":
            fav_pct = ((h - sig_p) / sig_p) * 100.0
            adv_pct = ((l - sig_p) / sig_p) * 100.0
            hit_sl = l <= sl_price
            hit_tp = h >= tp_price
        else:
            fav_pct = ((sig_p - l) / sig_p) * 100.0
            adv_pct = ((sig_p - h) / sig_p) * 100.0
            hit_sl = h >= sl_price
            hit_tp = l <= tp_price

        if fav_pct > mfe_pct:
            mfe_pct = fav_pct
        if adv_pct < mae_pct:
            mae_pct = adv_pct

        # Ambiguity safety rule: SL ALWAYS checked before TP on the same bar
        if hit_sl:
            virtual_pnl = round(-sl_p_pct - fee, 4)
            return {
                "status": "EVALUATED",
                "virtual_pnl_pct": virtual_pnl,
                "virtual_r": round(virtual_pnl / denom_r, 3),
                "mfe_pct": round(mfe_pct, 4),
                "mae_pct": round(mae_pct, 4),
                "hit_outcome": "SL",
                "bars_held": bars_held,
            }
        if hit_tp:
            virtual_pnl = round(tp_p_pct - fee, 4)
            return {
                "status": "EVALUATED",
                "virtual_pnl_pct": virtual_pnl,
                "virtual_r": round(virtual_pnl / denom_r, 3),
                "mfe_pct": round(mfe_pct, 4),
                "mae_pct": round(mae_pct, 4),
                "hit_outcome": "TP",
                "bars_held": bars_held,
            }

    total_bars = len(bars)
    if total_bars < min_bars_for_time_exit:
        return _insufficient(mfe=mfe_pct, mae=mae_pct, bars_held=total_bars)

    final_close = float(closes[-1])
    if side_u == "LONG":
        raw_ret = ((final_close - sig_p) / sig_p) * 100.0
    else:
        raw_ret = ((sig_p - final_close) / sig_p) * 100.0

    virtual_pnl = round(raw_ret - fee, 4)
    return {
        "status": "EVALUATED",
        "virtual_pnl_pct": virtual_pnl,
        "virtual_r": round(virtual_pnl / denom_r, 3),
        "mfe_pct": round(mfe_pct, 4),
        "mae_pct": round(mae_pct, 4),
        "hit_outcome": "TIME_EXIT",
        "bars_held": total_bars,
    }
