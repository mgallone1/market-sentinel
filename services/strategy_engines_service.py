"""Quantitative Strategy Engines, Regime Router & Causal Shadow Evaluator.

Stateless, pure DataFrame-driven signal engines built without lookahead bias:
- Reuses `wilder_rsi`, `atr_wilder`, `drop_forming_bar` from `services.indicators_safe`.
- Reuses `HurstMigliorinoCycleService` from `services.hurst_migliorino_cycles`.
- Engines:
  1. TREND_PULLBACK_4H  (`engine_trend_pullback_4h1d`): Maker limit pullback on 4H/1H structure.
  2. LIQUIDITY_SWEEP_MR (`engine_liquidity_sweep_mr`): Contrarian Maker fade of trapped stops.
  3. INTRADAY_MOMENTUM  (`engine_intraday_momentum`): Filtered intraday breakout with shadow telemetry.
  4. ORB_BREAKOUT_15M   (`engine_orb_breakout_15m`): NY 15-minute Opening Range Breakout for equities.
  5. Time Machine Gate  (`evaluate_timemachine_gate`): Bootstrap Monte Carlo adverse-drift veto.
  6. Same-rule replay   (`replay_signal_history`): real-path replay of past triggers (telemetry).
  7. Late-session gate  (`late_session_entry_check`): no weak entries close to the equity flatten.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from services import market_calendar
from services.hurst_migliorino_cycles import HurstMigliorinoCycleService
from services.indicators_safe import atr_wilder, drop_forming_bar, wilder_rsi

ENGINE_TREND_PULLBACK = "TREND_PULLBACK_4H"
ENGINE_LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP_MR"
ENGINE_INTRADAY_MOMENTUM = "INTRADAY_MOMENTUM"
ENGINE_ORB_BREAKOUT = "ORB_BREAKOUT_15M"

# Version tag of the live rule set, stored with every journal entry and shadow signal so that
# outcomes can be grouped by rule version (ADX 21 trend routing, Anti-Chase 68/32/2.2 ATR,
# ORB 15m, Time Machine rev. 2026-11-26, late-session gate 30/90 min).
STRATEGY_RULESET_VERSION = "2026-11-26.1"
ALL_ENGINES = [
    ENGINE_TREND_PULLBACK,
    ENGINE_LIQUIDITY_SWEEP,
    ENGINE_INTRADAY_MOMENTUM,
    ENGINE_ORB_BREAKOUT,
]


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
    is_equities: bool = False,
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
    elif (bias in ("BULLISH", "BEARISH") and adx >= 21.0) or (adx >= 30.0 and atr >= 0.4):
        regime = "TREND_STRONG"
        allowed_engines = [ENGINE_TREND_PULLBACK, ENGINE_INTRADAY_MOMENTUM]
        if is_equities:
            allowed_engines.append(ENGINE_ORB_BREAKOUT)
        prefer_limit = True  # Pullback Limit engine prioritized; also protective if spread wide
    else:
        regime = "TRANSITION_NEUTRAL"
        allowed_engines = [ENGINE_TREND_PULLBACK, ENGINE_LIQUIDITY_SWEEP, ENGINE_INTRADAY_MOMENTUM]
        if is_equities:
            allowed_engines.append(ENGINE_ORB_BREAKOUT)
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

def _is_cycle_aligned(
    side: str,
    bias: str,
    last_c: float,
    resolved_cycle: Dict[str, Any],
) -> bool:
    """Shared Hurst/Migliorino cycle alignment guard for breakout engines."""
    tempo_up = str(resolved_cycle.get("tempo_battleplan", "") or "").upper()
    vincolo_up = str(resolved_cycle.get("vincolo_migliorino", "LIBERO") or "LIBERO").upper()
    hurst_fld = _safe_float(resolved_cycle.get("hurst_fld_value", 0.0), 0.0)

    if side == "LONG":
        allow_long = (bias == "BULLISH") or (
            bias == "NEUTRAL"
            and ("1° TEMPO" in tempo_up or "2° TEMPO" in tempo_up)
            and (hurst_fld <= 0.0 or last_c > hurst_fld)
        )
        return bool(allow_long and "RIBASSISTA" not in vincolo_up)

    allow_short = (bias == "BEARISH") or (
        bias == "NEUTRAL"
        and ("3° TEMPO" in tempo_up or "4° TEMPO" in tempo_up)
        and (hurst_fld <= 0.0 or last_c < hurst_fld)
    )
    return bool(allow_short and "RIALZISTA FORZATO" not in vincolo_up and "1° TEMPO" not in tempo_up)


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

    atr_abs = (atr_pct / 100.0) * last_c if (atr_pct > 0.0 and last_c > 0.0) else 0.0
    ema20_dist_atr = (abs(last_c - ema20) / atr_abs) if atr_abs > 0.0 else 0.0
    features["ema20_dist_atr"] = round(ema20_dist_atr, 3)

    # Anti-Chase guard: prevent entering late after an impulse is already overextended
    if side == "LONG" and (rsi > 68.0 or ema20_dist_atr > 2.2):
        return _result(False, side, "OVEREXTENDED_CHASE", sl_pct, tp_pct, 0.0, features)
    if side == "SHORT" and (rsi < 32.0 or ema20_dist_atr > 2.2):
        return _result(False, side, "OVEREXTENDED_CHASE", sl_pct, tp_pct, 0.0, features)

    if side == "LONG" and vix_unfavorable:
        return _result(False, side, "VIX_SHIELD", sl_pct, tp_pct, 0.0, features)

    min_vol_required = 1.70 if is_overnight else 1.10
    if eff_vol_ratio < min_vol_required:
        rej = "LOW_VOLUME_OVERNIGHT" if is_overnight else "LOW_VOLUME"
        return _result(False, side, rej, sl_pct, tp_pct, 0.0, features)

    if not _is_cycle_aligned(side, bias, last_c, resolved_cycle):
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


def engine_orb_breakout_15m(
    df_5m: pd.DataFrame,
    macro_bias: str,
    cycle_data: Optional[Dict[str, Any]] = None,
    vix_unfavorable: bool = False,
    or_minutes: int = 15,
    min_vol_x: float = 1.10,
    interval_minutes: Optional[float] = 5,
    now: Any = None,
    late_cutoff_minutes: float = 30.0,
) -> Dict[str, Any]:
    """NY 15-minute Opening Range Breakout (ORB) engine on closed 5m bars."""
    bars = prepare_closed_bars(df_5m, interval_minutes=interval_minutes, now=now)
    bias = str(macro_bias or "NEUTRAL").upper()

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
            "engine": ENGINE_ORB_BREAKOUT,
            "reject_reason": reject_reason,
            "order_type": "Market",
            "limit_price": None,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "score": score,
            "features": features,
        }

    if bars is None or len(bars) < 6 or not isinstance(bars.index, pd.DatetimeIndex):
        empty_feats = extract_normalized_features(
            bars if bars is not None else pd.DataFrame(),
            cycle_data=cycle_data,
            macro_bias=bias,
        )
        return _result(False, None, "INSUFFICIENT_DATA", 1.2, 3.0, 0.0, empty_feats)

    # Timezone-naive input: NY local if market-hour timestamps exist directly, otherwise UTC
    idx_ny = _to_ny_index(bars.index)

    bars_ny = bars.copy()
    bars_ny.index = idx_ny
    last_date = idx_ny[-1].date()
    session_bars = bars_ny[bars_ny.index.date == last_date]
    # Session close from the NYSE calendar: 16:00 ET, or 13:00 ET on early-close days
    close_ts = _session_close_ny(last_date) or pd.Timestamp(datetime_combine_ny(last_date, 16, 0))
    open_ts = pd.Timestamp(datetime_combine_ny(last_date, 9, 30))
    rth_bars = session_bars[(session_bars.index >= open_ts) & (session_bars.index < close_ts)]

    or_bars_count = max(1, int(or_minutes // 5))
    if len(rth_bars) <= or_bars_count:
        feats = extract_normalized_features(bars, cycle_data=cycle_data, macro_bias=bias)
        return _result(False, None, "INSUFFICIENT_DATA", 1.2, 3.0, 0.0, feats)
    if rth_bars.index[0] != open_ts:
        # Opening bars missing: the range would be computed on the wrong bars
        feats = extract_normalized_features(bars, cycle_data=cycle_data, macro_bias=bias)
        return _result(False, None, "OR_INCOMPLETE", 1.2, 3.0, 0.0, feats)

    # Entry window: from the end of the opening range to `late_cutoff_minutes` before the close
    # (bar is complete at last_ts + 5m). Late entries are additionally screened by the bot's
    # late-session gate.
    last_ts = rth_bars.index[-1]
    window_start = open_ts + pd.Timedelta(minutes=or_minutes)
    window_end = close_ts - pd.Timedelta(minutes=late_cutoff_minutes)
    if last_ts < window_start or (last_ts + pd.Timedelta(minutes=5)) > window_end:
        feats = extract_normalized_features(bars, cycle_data=cycle_data, macro_bias=bias)
        return _result(False, None, "OUTSIDE_ORB_WINDOW", 1.2, 3.0, 0.0, feats)

    or_slice = rth_bars.iloc[:or_bars_count]
    or_high = _safe_float(or_slice["High"].max(), 0.0)
    or_low = _safe_float(or_slice["Low"].min(), 0.0)
    or_mid = (or_high + or_low) / 2.0
    or_avg_vol = _safe_float(or_slice["Volume"].mean(), 0.0)

    last_bar = rth_bars.iloc[-1]
    prev_bar = rth_bars.iloc[-2]
    last_c = _safe_float(last_bar["Close"], 0.0)
    prev_c = _safe_float(prev_bar["Close"], last_c)
    last_vol = _safe_float(last_bar["Volume"], 0.0)

    if last_c <= 0.0 or or_high <= 0.0 or or_low <= 0.0 or or_high <= or_low:
        feats = extract_normalized_features(bars, cycle_data=cycle_data, macro_bias=bias)
        return _result(False, None, "INSUFFICIENT_DATA", 1.2, 3.0, 0.0, feats)

    resolved_cycle = _resolve_cycle_data(bars["Close"], cycle_data)
    features = extract_normalized_features(bars, cycle_data=resolved_cycle, macro_bias=bias)
    vol_ratio = (last_vol / or_avg_vol) if or_avg_vol > 0.0 else features.get("vol_ratio", 1.0)
    features["vol_ratio"] = round(vol_ratio, 4)
    features["or_high"] = round(or_high, 4)
    features["or_low"] = round(or_low, 4)

    cand_long = (last_c > or_high) and (prev_c <= or_high * 1.002) and (((last_c - or_high) / or_high) * 100.0 <= 1.50)
    cand_short = (last_c < or_low) and (prev_c >= or_low * 0.998) and (((or_low - last_c) / or_low) * 100.0 <= 1.50)

    if not cand_long and not cand_short:
        return _result(False, None, "NO_SIGNAL", 1.2, 3.0, 0.0, features)

    side = "LONG" if cand_long else "SHORT"
    raw_sl_dist = abs((last_c - or_mid) / last_c) * 100.0
    sl_pct = round(_clamp(raw_sl_dist, 0.80, 2.50), 2)
    tp_pct = round(sl_pct * 2.5, 2)

    if side == "LONG" and vix_unfavorable:
        return _result(False, side, "VIX_SHIELD", sl_pct, tp_pct, 0.0, features)

    if or_avg_vol > 0.0 and vol_ratio < min_vol_x:
        return _result(False, side, "LOW_VOLUME", sl_pct, tp_pct, 0.0, features)

    if not _is_cycle_aligned(side, bias, last_c, resolved_cycle):
        return _result(False, side, "CYCLE_CONFLICT", sl_pct, tp_pct, 0.0, features)

    breakout_ext = abs((last_c - (or_high if side == "LONG" else or_low)) / last_c) * 100.0
    score = 62.0
    if (side == "LONG" and bias == "BULLISH") or (side == "SHORT" and bias == "BEARISH"):
        score += 12.0
    score += min(10.0, max(0.0, (vol_ratio - min_vol_x) * 12.0))
    score += min(8.0, breakout_ext * 10.0)
    score = round(_clamp(score, 0.0, 100.0), 2)

    return _result(True, side, "", sl_pct, tp_pct, score, features)


# Time Machine gate parameters (rev. 2026-11-26). Decision is taken on GROSS expectancy AND on the
# statistical significance of the adverse drift, never on the win-rate among resolved paths
# (that statistic is biased towards the nearer barrier on a finite horizon: with SL 1.2% /
# TP 3.6% / 24 bars on a driftless walk it reads ~0.08 against a 0.25 break-even).
TM_MIN_EXPECTED_R_GROSS = -0.10
TM_ADVERSE_DRIFT_Z = -1.0


def _bootstrap_pool(
    bars: pd.DataFrame,
    interval_minutes: Optional[float],
    max_bars: int = 500,
) -> Tuple[np.ndarray, int]:
    """Per-bar (High/prevC, Low/prevC, Close/prevC) ratios of the last `max_bars` closed bars.

    Bars that follow a time gap larger than 1.5x the bar interval (overnight / weekend /
    missing data) are excluded: intraday positions are flattened before the close, so a
    session gap is not a move an intraday trade can experience.
    """
    tail = bars.tail(max_bars)
    highs = tail["High"].to_numpy(dtype=float)
    lows = tail["Low"].to_numpy(dtype=float)
    closes = tail["Close"].to_numpy(dtype=float)

    gap_mask = np.zeros(len(tail), dtype=bool)
    if isinstance(tail.index, pd.DatetimeIndex) and len(tail) >= 3:
        dt_min = (tail.index[1:] - tail.index[:-1]).total_seconds().to_numpy(dtype=float) / 60.0
        step = float(interval_minutes) if interval_minutes else float(np.median(dt_min))
        if step > 0.0:
            gap_mask[1:] = dt_min > (1.5 * step)

    rows: List[Tuple[float, float, float]] = []
    gaps = 0
    for i in range(1, len(tail)):
        if gap_mask[i]:
            gaps += 1
            continue
        prev_c = closes[i - 1]
        if prev_c <= 0.0 or not math.isfinite(prev_c):
            continue
        hr, lr, cr = highs[i] / prev_c, lows[i] / prev_c, closes[i] / prev_c
        if min(hr, lr, cr) > 0.0 and all(math.isfinite(v) for v in (hr, lr, cr)):
            rows.append((hr, lr, cr))
    return np.asarray(rows, dtype=float).reshape(-1, 3), gaps


def evaluate_timemachine_gate(
    df_bars: pd.DataFrame,
    side: str,
    sl_pct: float,
    tp_pct: float,
    n_replays: int = 1200,
    horizon_bars: int = 24,
    fee_rt_pct: float = 0.12,
    min_expected_r: float = TM_MIN_EXPECTED_R_GROSS,
    adverse_drift_z: float = TM_ADVERSE_DRIFT_Z,
    seed: int = 19,
    interval_minutes: Optional[float] = None,
    now: Any = None,
    max_horizon_bars: Optional[int] = None,
    wr_tolerance: Optional[float] = None,  # deprecated, ignored (kept for call compatibility)
) -> Dict[str, Any]:
    """Empirical bootstrap Monte Carlo pre-entry check (rev. 2026-11-26).

    Rebuilds `n_replays` synthetic paths of `horizon_bars` (capped by `max_horizon_bars`,
    e.g. the bars left before the forced equity flatten) from recent closed-bar ratios.
    SL is checked before TP inside each bar. Paths that touch neither barrier are marked to
    market at the horizon, so E[R] accounts for every path (no conditioning on resolution).

    Blocks (TIMEMACHINE_NEG_EXPECTANCY) only when BOTH hold:
      * gross E[R] (before fees) < `min_expected_r`, and
      * the drift of the sampled bars, signed in the trade direction, has z-score <= `adverse_drift_z`.
    The unconditional bootstrap measures the recent drift/volatility regime, not the edge of the
    setup: it is used as a "don't fight a significant adverse drift" veto. Fees are reported in
    the net `expected_r` but do not trigger the veto (otherwise every tight-stop plan is vetoed).
    `resolved_win_rate` is reported for information only.
    """
    side_u = str(side or "").upper()
    if side_u == "BUY":
        side_u = "LONG"
    elif side_u == "SELL":
        side_u = "SHORT"

    sl_p = _safe_float(sl_pct, -1.0)
    tp_p = _safe_float(tp_pct, -1.0)
    fee = max(0.0, _safe_float(fee_rt_pct, 0.12))

    if side_u not in ("LONG", "SHORT") or sl_p <= 0.0 or tp_p <= 0.0:
        return {"passed": False, "reason": "INVALID_PLAN", "replays": 0, "expected_r": 0.0}

    h_bars = max(1, int(horizon_bars))
    if max_horizon_bars is not None:
        h_bars = max(1, min(h_bars, int(max_horizon_bars)))
    breakeven_wr = round(1.0 / (1.0 + (tp_p / sl_p)), 4)

    def _insufficient() -> Dict[str, Any]:
        return {
            "passed": True,
            "reason": "INSUFFICIENT_HISTORY",
            "replays": 0,
            "horizon_bars": h_bars,
            "expected_r": 0.0,
            "expected_r_gross": 0.0,
            "p_tp_first": 0.0,
            "p_sl_first": 0.0,
            "p_neither": 1.0,
            "resolved_win_rate": 0.0,
            "breakeven_wr": breakeven_wr,
            "drift_z": 0.0,
            "pool_size": 0,
        }

    bars = prepare_closed_bars(df_bars, interval_minutes=interval_minutes, now=now)
    if bars is None or len(bars) < 22:
        return _insufficient()

    pool, gaps = _bootstrap_pool(bars, interval_minutes)
    if len(pool) < 20:
        return _insufficient()

    direction = 1.0 if side_u == "LONG" else -1.0
    rets = pool[:, 2] - 1.0
    sd = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    mean_ret = float(np.mean(rets))
    if sd > 0.0:
        drift_z = direction * mean_ret / (sd / math.sqrt(len(rets)))
    else:
        drift_z = 0.0 if mean_ret == 0.0 else direction * math.copysign(99.0, mean_ret)

    n_rep = max(100, int(n_replays))
    rng = np.random.default_rng(seed)
    draws = pool[rng.integers(0, len(pool), size=(n_rep, h_bars))]  # (n, h, 3)
    cum_c = np.cumprod(draws[:, :, 2], axis=1)
    px_prev = np.concatenate([np.ones((n_rep, 1)), cum_c[:, :-1]], axis=1)
    bar_h = px_prev * draws[:, :, 0]
    bar_l = px_prev * draws[:, :, 1]

    if side_u == "LONG":
        sl_hit = bar_l <= (1.0 - sl_p / 100.0)
        tp_hit = bar_h >= (1.0 + tp_p / 100.0)
    else:
        sl_hit = bar_h >= (1.0 + sl_p / 100.0)
        tp_hit = bar_l <= (1.0 - tp_p / 100.0)

    big = h_bars + 1
    sl_first = np.where(sl_hit.any(axis=1), sl_hit.argmax(axis=1), big)
    tp_first = np.where(tp_hit.any(axis=1), tp_hit.argmax(axis=1), big)
    is_sl = (sl_first < big) & (sl_first <= tp_first)  # SL wins ties inside the same bar
    is_tp = (tp_first < big) & ~is_sl

    end_ret_pct = direction * (cum_c[:, -1] - 1.0) * 100.0
    gross_pct = np.where(is_sl, -sl_p, np.where(is_tp, tp_p, end_ret_pct))
    gross_r = gross_pct / sl_p
    net_r = (gross_pct - fee) / sl_p

    p_tp = float(is_tp.mean())
    p_sl = float(is_sl.mean())
    resolved = p_tp + p_sl
    expected_r = float(net_r.mean())
    expected_r_gross = float(gross_r.mean())

    passed = True
    reason = "TIMEMACHINE_OK"
    if expected_r_gross < float(min_expected_r) and drift_z <= float(adverse_drift_z):
        passed = False
        reason = "TIMEMACHINE_NEG_EXPECTANCY"

    return {
        "passed": passed,
        "reason": reason,
        "replays": n_rep,
        "horizon_bars": h_bars,
        "expected_r": round(expected_r, 3),
        "expected_r_gross": round(expected_r_gross, 3),
        "p_tp_first": round(p_tp, 4),
        "p_sl_first": round(p_sl, 4),
        "p_neither": round(max(0.0, 1.0 - resolved), 4),
        "resolved_win_rate": round((p_tp / resolved) if resolved > 0.0 else 0.0, 4),
        "breakeven_wr": breakeven_wr,
        "drift_z": round(float(drift_z), 3),
        "pool_size": int(len(pool)),
        "gaps_skipped": int(gaps),
    }


# ---------------------------------------------------------------------------
# 5c. Same-rule historical replay (real paths, informational telemetry)
# ---------------------------------------------------------------------------

def _to_ny_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    ny_tz = ZoneInfo("America/New_York")
    if idx.tz is None:
        has_ny_morning = any((t.hour == 9 and t.minute >= 30) for t in idx[-min(len(idx), 120):])
        return idx.tz_localize(ny_tz if has_ny_morning else "UTC").tz_convert(ny_tz)
    return idx.tz_convert(ny_tz)


def _session_close_ny(day: Any) -> Optional[pd.Timestamp]:
    bounds = market_calendar.session_bounds(day)
    return pd.Timestamp(bounds[1]) if bounds else None


def momentum_signal_positions(bars: pd.DataFrame, side: str, adx_min: float = 16.0) -> List[int]:
    """Bar positions where the INTRADAY_MOMENTUM price rules fired (vectorised, no lookahead).

    Mirrors breakout over the previous 4 bars, EMA20/EMA50 stack, RSI 52/48, ADX floor and the
    Anti-Chase guard (RSI 68/32, |C-EMA20| <= 2.2 ATR). Microstructure/cycle/VIX shields are not
    replayed (their history is not stored), so this is an upper bound of the live trigger set.
    """
    if bars is None or len(bars) < 60:
        return []
    c, h, l = bars["Close"], bars["High"], bars["Low"]
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    rsi = wilder_rsi(c, 14)
    adx = compute_adx(h, l, c, 14)
    atr = atr_wilder(h, l, c, 14)
    dist = (c - ema20).abs() / atr.replace(0.0, np.nan)
    if str(side).upper() == "LONG":
        prior_hi = h.shift(1).rolling(4).max()
        cond = (c > prior_hi) & (c > ema20) & (ema20 > ema50) & (rsi > 52.0) & (rsi <= 68.0)
    else:
        prior_lo = l.shift(1).rolling(4).min()
        cond = (c < prior_lo) & (c < ema20) & (ema20 < ema50) & (rsi < 48.0) & (rsi >= 32.0)
    cond = cond & (adx >= adx_min) & (dist <= 2.2)
    arr = cond.fillna(False).to_numpy(dtype=bool)
    arr[:50] = False
    return [int(i) for i in np.flatnonzero(arr)]


def orb_signal_positions(
    bars: pd.DataFrame,
    side: str,
    or_minutes: int = 15,
    min_vol_x: float = 1.10,
    late_cutoff_minutes: float = 30.0,
) -> List[int]:
    """Bar positions where the ORB_BREAKOUT_15M price/volume rules fired in each NY session."""
    if bars is None or len(bars) < 6 or not isinstance(bars.index, pd.DatetimeIndex):
        return []
    idx_ny = _to_ny_index(bars.index)
    side_u = str(side).upper()
    or_n = max(1, int(or_minutes // 5))
    out: List[int] = []
    pos_all = np.arange(len(bars))
    dates = np.array([t.date() for t in idx_ny])
    for day in sorted(set(dates)):
        close_ts = _session_close_ny(day)
        if close_ts is None:
            continue
        sel = pos_all[dates == day]
        times = idx_ny[sel]
        open_ts = pd.Timestamp(datetime_combine_ny(day, 9, 30))
        rth = [(p, t) for p, t in zip(sel, times) if open_ts <= t < close_ts]
        if len(rth) <= or_n or rth[0][1] != open_ts:
            continue
        or_pos = [p for p, _ in rth[:or_n]]
        or_high = float(bars["High"].iloc[or_pos].max())
        or_low = float(bars["Low"].iloc[or_pos].min())
        or_vol = float(bars["Volume"].iloc[or_pos].mean())
        if or_high <= or_low or or_low <= 0.0:
            continue
        last_entry_ts = close_ts - pd.Timedelta(minutes=late_cutoff_minutes)
        for k in range(or_n, len(rth)):
            p, t = rth[k]
            if t + pd.Timedelta(minutes=5) > last_entry_ts:
                break
            c = float(bars["Close"].iloc[p])
            pc = float(bars["Close"].iloc[rth[k - 1][0]])
            v = float(bars["Volume"].iloc[p])
            if or_vol > 0.0 and v < min_vol_x * or_vol:
                continue
            if side_u == "LONG":
                ok = c > or_high and pc <= or_high * 1.002 and (c - or_high) / or_high * 100.0 <= 1.5
            else:
                ok = c < or_low and pc >= or_low * 0.998 and (or_low - c) / or_low * 100.0 <= 1.5
            if ok:
                out.append(int(p))
    return out


def datetime_combine_ny(day: Any, hour: int, minute: int) -> Any:
    import datetime as _dt
    return _dt.datetime.combine(day, _dt.time(hour, minute), tzinfo=ZoneInfo("America/New_York"))


def replay_signal_history(
    df_bars: pd.DataFrame,
    engine: str,
    side: str,
    sl_pct: float,
    tp_pct: float,
    fee_rt_pct: float = 0.12,
    max_bars: int = 24,
    interval_minutes: Optional[float] = None,
    session_bound: bool = False,
    flatten_lead_minutes: float = 8.0,
    now: Any = None,
) -> Dict[str, Any]:
    """Replay the SAME entry rule on past bars of the same symbol, on the real price paths.

    Each past trigger enters at its bar close with the live SL/TP percentages; SL is checked
    before TP inside each bar; open trades are marked to market after `max_bars` or, when
    `session_bound` (US equities), at the last bar before the forced flatten of that session.
    Trades never overlap (a new trigger is ignored while a replayed trade is open), so the
    outcomes are closer to independent. The current (last) bar is excluded.
    Informational only: with a handful of past events it cannot support a decision.
    """
    side_u = str(side or "").upper()
    engine_u = str(engine or "").upper()
    out: Dict[str, Any] = {"engine": engine_u, "n": 0, "mean_r": None, "win_rate": None,
                           "tp_rate": None, "sl_rate": None, "t_stat": None}
    sl_p = _safe_float(sl_pct, -1.0)
    tp_p = _safe_float(tp_pct, -1.0)
    if side_u not in ("LONG", "SHORT") or sl_p <= 0.0 or tp_p <= 0.0:
        return out
    bars = prepare_closed_bars(df_bars, interval_minutes=interval_minutes, now=now)
    if bars is None or len(bars) < 10:
        return out

    if engine_u == ENGINE_INTRADAY_MOMENTUM:
        entries = momentum_signal_positions(bars, side_u)
    elif engine_u == ENGINE_ORB_BREAKOUT:
        entries = orb_signal_positions(bars, side_u)
    else:
        out["note"] = "NO_REPLAY_RULE"
        return out
    entries = [p for p in entries if p < len(bars) - 1]

    closes = bars["Close"].to_numpy(dtype=float)
    highs = bars["High"].to_numpy(dtype=float)
    lows = bars["Low"].to_numpy(dtype=float)
    fee = max(0.0, _safe_float(fee_rt_pct, 0.12))
    step = float(interval_minutes) if interval_minutes else 0.0
    idx_ny = _to_ny_index(bars.index) if (session_bound and isinstance(bars.index, pd.DatetimeIndex)) else None

    results: List[float] = []
    outcomes: List[str] = []
    busy_until = -1
    for p in entries:
        if p <= busy_until:
            continue
        entry = closes[p]
        if entry <= 0.0:
            continue
        sl_px = entry * (1.0 - sl_p / 100.0) if side_u == "LONG" else entry * (1.0 + sl_p / 100.0)
        tp_px = entry * (1.0 + tp_p / 100.0) if side_u == "LONG" else entry * (1.0 - tp_p / 100.0)
        cutoff_ts = None
        if idx_ny is not None:
            close_ts = _session_close_ny(idx_ny[p].date())
            if close_ts is not None:
                cutoff_ts = close_ts - pd.Timedelta(minutes=flatten_lead_minutes)
        gross: Optional[float] = None
        last_j = p
        for j in range(p + 1, min(len(bars), p + 1 + int(max_bars))):
            if idx_ny is not None:
                if idx_ny[j].date() != idx_ny[p].date():
                    break
                if cutoff_ts is not None and idx_ny[j] + pd.Timedelta(minutes=step) > cutoff_ts:
                    break
            last_j = j
            hit_sl = lows[j] <= sl_px if side_u == "LONG" else highs[j] >= sl_px
            hit_tp = highs[j] >= tp_px if side_u == "LONG" else lows[j] <= tp_px
            if hit_sl:
                gross, tag = -sl_p, "SL"
                break
            if hit_tp:
                gross, tag = tp_p, "TP"
                break
        if last_j == p:
            continue  # no forward bar inside the session: nothing to learn
        if gross is None:
            move = (closes[last_j] - entry) / entry * 100.0
            gross, tag = (move if side_u == "LONG" else -move), "TIME"
        results.append((gross - fee) / sl_p)
        outcomes.append(tag)
        busy_until = last_j

    n = len(results)
    out["n"] = n
    if n == 0:
        return out
    arr = np.asarray(results, dtype=float)
    out["mean_r"] = round(float(arr.mean()), 3)
    out["win_rate"] = round(float((arr > 0.0).mean()), 3)
    out["tp_rate"] = round(outcomes.count("TP") / n, 3)
    out["sl_rate"] = round(outcomes.count("SL") / n, 3)
    if n >= 3 and float(arr.std(ddof=1)) > 0.0:
        out["t_stat"] = round(float(arr.mean() / (arr.std(ddof=1) / math.sqrt(n))), 2)
    return out


# ---------------------------------------------------------------------------
# 5d. Late-session entry gate (US equities, forced flatten before the close)
# ---------------------------------------------------------------------------

LATE_SESSION_NO_ENTRY_MINUTES = 30.0
LATE_SESSION_ZONE_MINUTES = 90.0
LATE_SESSION_MIN_SCORE = 75.0
LATE_SESSION_MIN_P_TP = 0.25
LATE_SESSION_MIN_EXPECTED_R = 0.0


def late_session_entry_check(
    minutes_to_close: Optional[float],
    score: float,
    tm_res: Optional[Dict[str, Any]],
    no_entry_minutes: float = LATE_SESSION_NO_ENTRY_MINUTES,
    late_zone_minutes: float = LATE_SESSION_ZONE_MINUTES,
    min_score: float = LATE_SESSION_MIN_SCORE,
    min_p_tp: float = LATE_SESSION_MIN_P_TP,
    min_expected_r: float = LATE_SESSION_MIN_EXPECTED_R,
) -> Dict[str, Any]:
    """Decide whether a new equity entry still has time to work before the forced flatten.

    * `minutes_to_close` None (crypto / session unknown): no restriction.
    * < `no_entry_minutes`: never enter (LATE_SESSION_NO_TIME).
    * < `late_zone_minutes`: enter only on a strong setup, all required:
        - engine score >= `min_score`                                  (else LATE_SESSION_WEAK_SETUP)
        - Time Machine evidence available, with horizon cut at the flatten (else LATE_SESSION_NO_EVIDENCE)
        - P(TP touched before the flatten) >= `min_p_tp`              (else LATE_SESSION_TP_UNREACHABLE)
        - net E[R], open paths valued at the flatten, >= `min_expected_r` (else LATE_SESSION_NEG_EXPECTANCY)
    """
    if minutes_to_close is None:
        return {"allowed": True, "zone": "NO_SESSION_LIMIT", "reason": ""}
    mtc = float(minutes_to_close)
    if mtc < no_entry_minutes:
        return {"allowed": False, "zone": "CLOSING", "reason": "LATE_SESSION_NO_TIME"}
    if mtc >= late_zone_minutes:
        return {"allowed": True, "zone": "NORMAL", "reason": ""}

    tm = tm_res or {}
    if _safe_float(score, 0.0) < min_score:
        return {"allowed": False, "zone": "LATE", "reason": "LATE_SESSION_WEAK_SETUP"}
    if int(tm.get("replays", 0) or 0) <= 0:
        return {"allowed": False, "zone": "LATE", "reason": "LATE_SESSION_NO_EVIDENCE"}
    if _safe_float(tm.get("p_tp_first"), 0.0) < min_p_tp:
        return {"allowed": False, "zone": "LATE", "reason": "LATE_SESSION_TP_UNREACHABLE"}
    if _safe_float(tm.get("expected_r"), -1.0) < min_expected_r:
        return {"allowed": False, "zone": "LATE", "reason": "LATE_SESSION_NEG_EXPECTANCY"}
    return {"allowed": True, "zone": "LATE", "reason": ""}


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
