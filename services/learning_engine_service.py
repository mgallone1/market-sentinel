"""
Quantitative Self-Learning Engine (Pillars 1-5) for Market Sentinel.

Componenti implementati:
1. Context Normalization & Hierarchical Backoff (Pillar 1/3).
2. MFE/MAE Causal Path Evaluator, Exit Frontier Optimizer con Anti-Overfitting Gate
   (N >= 15 e miglioramento LCB >= +0.05R netto fee) e ATR-Scaled Ratchet Tiers (Pillar 2).
3. Contextual Bayesian Allocator (Normal-Gamma shrinkage + decadimento esponenziale)
   con Shadow Mode & auto-riabilitazione guidata dagli shadow signal (Pillar 3).
4. Evaluation Cycle Runner per trade chiusi e shadow signal (Pillar 4).
5. Quant Drift Monitor (MetaGate) & Weekly Executive Self-Audit Report (Pillar 5).
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

from services.trade_journal_service import (
    ROME_TZ,
    TradeJournalService,
    _normalize_journal_side,
    _parse_iso_dt,
    get_trade_journal_db_path,
)

# Fee realistiche di default (Round-Trip) per valutazione netta
BYBIT_DEFAULT_RT_FEE_PCT = 0.12
ALPACA_DEFAULT_RT_FEE_PCT = 0.02

# Parametri baseline di uscita in multipli di ATR (1.4x ATR SL, R:R 1:3 -> 4.2x ATR TP)
BASELINE_EXIT_PARAMS = {
    "sl_atr": 1.4,
    "be_trig_atr": 1.61,
    "be_lock_atr": 0.35,
    "tp_atr": 4.2,
}


def _round_adaptive_price(price: float, ref_price: float) -> float:
    """Arrotonda il prezzo preservando cifre significative per asset a basso valore (es. DOGE, XRP)."""
    p = float(price)
    r = abs(float(ref_price or price or 0.0))
    if r >= 10000.0:
        dec = 1
    elif r >= 100.0:
        dec = 2
    elif r >= 5.0:
        dec = 3
    elif r >= 0.5:
        dec = 4
    elif r >= 0.05:
        dec = 5
    elif r >= 0.005:
        dec = 6
    else:
        dec = 7
    return round(p, dec)


def _vol_bucket(atr_pct: float) -> str:
    v = float(atr_pct or 0.0)
    if v < 1.0:
        return "VOL_LOW"
    if v <= 2.0:
        return "VOL_MED"
    return "VOL_HIGH"


def _session_bucket(rome_hour: int) -> str:
    h = int(rome_hour) % 24
    if 0 <= h <= 6:
        return "OVERNIGHT"
    if 7 <= h <= 13:
        return "EUROPE"
    if 14 <= h <= 21:
        return "US_PEAK"
    return "LATE"


def normalize_context_key(
    broker: str,
    side: str,
    macro_bias: Optional[str],
    atr_pct: float,
    rome_hour: int,
    engine: str = "INTRADAY_MOMENTUM",
) -> str:
    """
    Normalizza il contesto di ingresso in chiave discreta a 6 dimensioni:
    `BROKER|SIDE|MACRO_BIAS|VOL_BUCKET|SESSION_BUCKET|ENGINE`.
    """
    vol_b = _vol_bucket(atr_pct)
    sess_b = _session_bucket(rome_hour)
    b = (broker or "UNKNOWN").strip().upper()
    s = (side or "UNKNOWN").strip().upper()
    m = (macro_bias or "UNKNOWN").strip().upper()
    e = (engine or "INTRADAY_MOMENTUM").strip().upper()
    return f"{b}|{s}|{m}|{vol_b}|{sess_b}|{e}"


def backoff_context_keys(context_key: str) -> List[str]:
    """
    Restituisce la gerarchia di chiavi dal contesto granulare completo a quelli aggregati:
    1) Full 6-part: `broker|side|macro|vol|session|engine`
    2) Coarser 4-part: `broker|side|macro|engine`
    3) Coarser 3-part: `broker|side|macro`
    """
    raw = str(context_key or "").strip().upper()
    if not raw:
        return []
    parts = raw.split("|")
    keys = [raw]
    if len(parts) >= 6:
        k4 = f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[5]}"
        if k4 not in keys:
            keys.append(k4)
    if len(parts) >= 3:
        k3 = f"{parts[0]}|{parts[1]}|{parts[2]}"
        if k3 not in keys:
            keys.append(k3)
    return keys


def _extract_context_parts(
    context_key: Optional[str],
    broker: Optional[str] = None,
    side: Optional[str] = None,
    engine: Optional[str] = None,
    entry_context: Optional[Dict[str, Any]] = None,
    opened_at: Optional[str] = None,
) -> Tuple[str, str, str, str, str, str]:
    """Estrae la tupla a 6 componenti da `context_key` o ricostruendola dai metadati storici."""
    if context_key:
        parts = str(context_key).strip().upper().split("|")
        if len(parts) >= 6:
            return tuple(parts[:6])  # type: ignore[return-value]
    ctx = entry_context or {}
    b = (broker or "UNKNOWN").upper()
    s = (_normalize_journal_side(side) or (side or "UNKNOWN")).upper()
    m = str(ctx.get("macro_bias") or "UNKNOWN").upper()
    atr_val = float(ctx.get("atr_pct") or 1.2)
    sess_h = ctx.get("session_hour")
    if sess_h is None and opened_at:
        dt = _parse_iso_dt(opened_at)
        sess_h = dt.astimezone(ROME_TZ).hour if dt else 12
    sess_h = int(sess_h if sess_h is not None else 12)
    eng = str(engine or ctx.get("engine") or "INTRADAY_MOMENTUM").upper()
    return (b, s, m, _vol_bucket(atr_val), _session_bucket(sess_h), eng)


def _match_context_hierarchy(row_parts: Tuple[str, str, str, str, str, str], target_key: str) -> bool:
    """Verifica se `row_parts` (6 componenti) matcha una chiave esatta (6 parti) o gerarchica (4 o 3 parti)."""
    tparts = target_key.split("|")
    if len(tparts) >= 6:
        # Match su 6 parti accettando equivalente LONG/BUY e SHORT/SELL sul side
        return (
            row_parts[0] == tparts[0]
            and (_normalize_journal_side(row_parts[1]) or row_parts[1]) == (_normalize_journal_side(tparts[1]) or tparts[1])
            and row_parts[2] == tparts[2]
            and row_parts[3] == tparts[3]
            and row_parts[4] == tparts[4]
            and row_parts[5] == tparts[5]
        )
    if len(tparts) == 4:
        return (
            row_parts[0] == tparts[0]
            and (_normalize_journal_side(row_parts[1]) or row_parts[1]) == (_normalize_journal_side(tparts[1]) or tparts[1])
            and row_parts[2] == tparts[2]
            and row_parts[5] == tparts[3]
        )
    if len(tparts) == 3:
        return (
            row_parts[0] == tparts[0]
            and (_normalize_journal_side(row_parts[1]) or row_parts[1]) == (_normalize_journal_side(tparts[1]) or tparts[1])
            and row_parts[2] == tparts[2]
        )
    return False


def _prepare_ohlcv_df(ohlcv_df: Any) -> Optional[pd.DataFrame]:
    """Normalizza colonne (`high`, `low`, `close`) e indice temporale timezone-aware UTC."""
    if ohlcv_df is None or not isinstance(ohlcv_df, pd.DataFrame) or ohlcv_df.empty:
        return None
    df = ohlcv_df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    col_map = {str(c).lower(): c for c in df.columns}
    for req in ("high", "low", "close"):
        if req not in col_map:
            return None
    out = pd.DataFrame(
        {
            "high": pd.to_numeric(df[col_map["high"]], errors="coerce"),
            "low": pd.to_numeric(df[col_map["low"]], errors="coerce"),
            "close": pd.to_numeric(df[col_map["close"]], errors="coerce"),
        },
        index=pd.to_datetime(df.index, errors="coerce"),
    ).dropna()
    if out.empty:
        return None
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return out.sort_index()


def evaluate_trade_path_mfe_mae(
    ohlcv_df: pd.DataFrame,
    side: str,
    entry_price: float,
    opened_at_iso: str,
    closed_at_iso: str,
    exit_price: Optional[float] = None,
    realized_pct: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    Valuta il percorso OHLCV tra `opened_at_iso` e `closed_at_iso` per un singolo trade.

    Convenzione segni:
    - `mfe_pct` >= 0.0: massima escursione favorevole (%) raggiunta durante il trade.
    - `mae_pct` <= 0.0: massima escursione avversa (%) firmata negativa (es. `-0.85` per drawdown dello 0.85%).
    - `edge_ratio`: `round(mfe_pct / max(abs(mae_pct), 0.1), 2)`.
    - `capture_eff`: `round(realized_pct / max(mfe_pct, 0.1), 3)`.
    - `post_exit_4b_pct` / `post_exit_12b_pct`: rendimento direzionale nelle 4 / 12 barre successive all'uscita.
    """
    ep = float(entry_price or 0.0)
    if ep <= 0:
        return None
    df = _prepare_ohlcv_df(ohlcv_df)
    if df is None or df.empty:
        return None

    opened_dt = _parse_iso_dt(opened_at_iso)
    closed_dt = _parse_iso_dt(closed_at_iso)
    if opened_dt is None or closed_dt is None:
        return None
    opened_ts = pd.Timestamp(opened_dt.astimezone(timezone.utc))
    closed_ts = pd.Timestamp(closed_dt.astimezone(timezone.utc))
    if closed_ts < opened_ts:
        closed_ts = opened_ts

    trade_bars = df[(df.index >= opened_ts) & (df.index <= closed_ts)]
    if trade_bars.empty:
        # Fallback su barra che racchiude l'ingresso se durata trade < 1 barra
        if len(df.index) >= 2:
            diffs = df.index.to_series().diff().dropna()
            bar_step = diffs.median() if not diffs.empty else pd.Timedelta(minutes=15)
        else:
            bar_step = pd.Timedelta(minutes=15)
        trade_bars = df[(df.index <= closed_ts) & ((df.index + bar_step) > opened_ts)]
    if trade_bars.empty:
        return None

    is_long = str(side or "").strip().upper() in ("BUY", "LONG")
    max_high = float(trade_bars["high"].max())
    min_low = float(trade_bars["low"].min())
    last_close = float(trade_bars["close"].iloc[-1])

    if is_long:
        mfe_pct = max(0.0, ((max_high - ep) / ep) * 100.0)
        mae_pct = min(0.0, ((min_low - ep) / ep) * 100.0)
        bar_realized = ((last_close - ep) / ep) * 100.0
    else:
        mfe_pct = max(0.0, ((ep - min_low) / ep) * 100.0)
        mae_pct = min(0.0, ((ep - max_high) / ep) * 100.0)
        bar_realized = ((ep - last_close) / ep) * 100.0

    if realized_pct is not None:
        eff_realized = float(realized_pct)
    elif exit_price is not None and float(exit_price) > 0:
        xp = float(exit_price)
        eff_realized = (((xp - ep) / ep) * 100.0) if is_long else (((ep - xp) / ep) * 100.0)
    else:
        eff_realized = bar_realized

    edge_ratio = round(mfe_pct / max(abs(mae_pct), 0.1), 2)
    capture_eff = round(eff_realized / max(mfe_pct, 0.1), 3)
    bars_held = int(len(trade_bars))

    post_bars = df[df.index > closed_ts]
    exit_ref = float(exit_price) if (exit_price is not None and float(exit_price) > 0) else last_close

    def _dir_ret(target_price: float) -> float:
        if exit_ref <= 0:
            return 0.0
        return (((target_price - exit_ref) / exit_ref) * 100.0) if is_long else (((exit_ref - target_price) / exit_ref) * 100.0)

    post_exit_4b_pct = round(_dir_ret(float(post_bars["close"].iloc[3])), 4) if len(post_bars) >= 4 else None
    post_exit_12b_pct = round(_dir_ret(float(post_bars["close"].iloc[11])), 4) if len(post_bars) >= 12 else None

    return {
        "mfe_pct": round(mfe_pct, 4),
        "mae_pct": round(mae_pct, 4),
        "realized_pct": round(eff_realized, 4),
        "edge_ratio": edge_ratio,
        "capture_eff": capture_eff,
        "bars_held": bars_held,
        "post_exit_4b_pct": post_exit_4b_pct,
        "post_exit_12b_pct": post_exit_12b_pct,
    }


def _parse_entry_context(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _simulate_exit_r_values(
    trades: List[Dict[str, Any]],
    sl_atr: float,
    be_trig_atr: float,
    be_lock_atr: float,
    tp_atr: float,
    fee_rt_pct: float,
) -> List[float]:
    """Simula il rendimento netto in R multipli di una combinazione `(sl_atr, be_trig_atr, be_lock_atr, tp_atr)`."""
    r_values: List[float] = []
    for t in trades:
        ctx = _parse_entry_context(t.get("entry_context"))
        atr_pct = float(t.get("atr_pct") or ctx.get("atr_pct") or 0.0)
        if atr_pct <= 0:
            orig_sl = float(t.get("sl_pct") or ctx.get("sl_pct") or 0.0)
            atr_pct = (orig_sl / 1.4) if orig_sl > 0 else 1.2
        atr_pct = max(0.20, atr_pct)

        mfe_pct = max(0.0, float(t.get("mfe_pct") or 0.0))
        abs_mae = abs(float(t.get("mae_pct") or 0.0))
        realized_pct = float(t.get("pnl_pct") if t.get("pnl_pct") is not None else (t.get("realized_pct") or 0.0))

        sl_pct = max(0.15, sl_atr * atr_pct)
        be_trig_pct = be_trig_atr * atr_pct
        be_lock_pct = be_lock_atr * atr_pct
        tp_pct = tp_atr * atr_pct

        # Modello conservativo privo di look-ahead ottimistico:
        # se MAE >= SL, assume stop-out pieno a -sl_pct; altrimenti valuta TP e Break-Even Lock.
        if abs_mae >= sl_pct:
            gross_ret = -sl_pct
        elif mfe_pct >= tp_pct:
            gross_ret = tp_pct
        elif mfe_pct >= be_trig_pct:
            gross_ret = max(be_lock_pct, min(mfe_pct, realized_pct))
        else:
            gross_ret = min(mfe_pct, max(-sl_pct, realized_pct))

        net_ret = gross_ret - float(fee_rt_pct)
        r_values.append(net_ret / sl_pct)
    return r_values


def _sample_stats_r(r_values: List[float]) -> Tuple[float, float, float]:
    """Restituisce `(mean_r, se_r, lcb_r)` con z=1.28 (90% one-sided Lower Confidence Bound)."""
    n = len(r_values)
    if n == 0:
        return 0.0, 0.0, 0.0
    mean_r = sum(r_values) / n
    if n == 1:
        se_r = 1.0
    else:
        var_r = sum((x - mean_r) ** 2 for x in r_values) / (n - 1)
        se_r = math.sqrt(max(var_r, 1e-6) / n)
    lcb_r = mean_r - 1.28 * se_r
    return mean_r, se_r, lcb_r


def optimize_exit_frontier(
    evaluated_trades: List[Dict[str, Any]],
    side: Optional[str] = None,
    fee_rt_pct: float = BYBIT_DEFAULT_RT_FEE_PCT,
) -> Dict[str, Any]:
    """
    Ottimizza i parametri di uscita `(sl_atr, be_trig_atr, be_lock_atr, tp_atr)` sui trade con MFE/MAE valutato,
    al netto di `fee_rt_pct`, imponendo il doppio Gate Anti-Overfitting:
    - Campione minimo `N >= 15`
    - Miglioramento LCB (`best_lcb_r - baseline_expectancy_r >= +0.05R`).
    """
    filtered: List[Dict[str, Any]] = []
    target_side = _normalize_journal_side(side) if side else None
    for t in evaluated_trades or []:
        if t.get("mfe_pct") is None or t.get("mae_pct") is None:
            continue
        if target_side is not None:
            t_side = _normalize_journal_side(t.get("side"))
            if t_side != target_side:
                continue
        filtered.append(t)

    n = len(filtered)
    if n == 0:
        return {
            "approved": False,
            "n_samples": 0,
            "baseline_expectancy_r": 0.0,
            "best_expectancy_r": 0.0,
            "best_lcb_r": 0.0,
            "best_params": dict(BASELINE_EXIT_PARAMS),
            "reason": "Nessun trade con valutazione MFE/MAE disponibile.",
        }

    base_rs = _simulate_exit_r_values(
        filtered,
        sl_atr=BASELINE_EXIT_PARAMS["sl_atr"],
        be_trig_atr=BASELINE_EXIT_PARAMS["be_trig_atr"],
        be_lock_atr=BASELINE_EXIT_PARAMS["be_lock_atr"],
        tp_atr=BASELINE_EXIT_PARAMS["tp_atr"],
        fee_rt_pct=fee_rt_pct,
    )
    base_mean, _, base_lcb = _sample_stats_r(base_rs)

    best_params = dict(BASELINE_EXIT_PARAMS)
    best_mean = base_mean
    best_lcb = base_lcb

    sl_grid = (1.0, 1.2, 1.4, 1.8)
    be_trig_grid = (0.9, 1.2, 1.6)
    be_lock_grid = (0.25, 0.35, 0.55)
    tp_grid = (2.0, 2.5, 3.0, 3.6, 4.2)

    for sl_a in sl_grid:
        for bt_a in be_trig_grid:
            for bl_a in be_lock_grid:
                if bl_a >= bt_a:
                    continue
                for tp_a in tp_grid:
                    if tp_a < sl_a * 1.5 or bt_a >= tp_a:
                        continue
                    rs = _simulate_exit_r_values(
                        filtered,
                        sl_atr=sl_a,
                        be_trig_atr=bt_a,
                        be_lock_atr=bl_a,
                        tp_atr=tp_a,
                        fee_rt_pct=fee_rt_pct,
                    )
                    m_r, _, lcb_r = _sample_stats_r(rs)
                    if lcb_r > best_lcb:
                        best_lcb = lcb_r
                        best_mean = m_r
                        best_params = {
                            "sl_atr": sl_a,
                            "be_trig_atr": bt_a,
                            "be_lock_atr": bl_a,
                            "tp_atr": tp_a,
                        }

    lcb_gain = best_lcb - base_mean
    if n < 15:
        approved = False
        reason = f"Gate Anti-Overfitting: campione insufficiente N={n} < 15 minimo."
    elif lcb_gain < 0.05:
        approved = False
        reason = (
            f"Gate Anti-Overfitting: miglioramento LCB ({lcb_gain:+.3f}R) "
            f"inferiore a soglia +0.050R rispetto a baseline ({base_mean:+.3f}R)."
        )
    else:
        approved = True
        reason = (
            f"Approvato: N={n} >= 15, LCB {best_lcb:+.3f}R supera baseline {base_mean:+.3f}R "
            f"di {lcb_gain:+.3f}R netti."
        )

    return {
        "approved": approved,
        "n_samples": n,
        "baseline_expectancy_r": round(base_mean, 4),
        "baseline_lcb_r": round(base_lcb, 4),
        "best_expectancy_r": round(best_mean, 4),
        "best_lcb_r": round(best_lcb, 4),
        "best_params": best_params,
        "reason": reason,
    }


def compute_atr_ratchet_levels(
    atr_pct: float,
    side: str,
    entry_price: float,
    adaptive_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Calcola Stop Loss, Take Profit e i 4 scalini del Ratchet Trailing Stop scalati proporzionalmente su `sl_pct`
    (eliminando lo strozzamento fisso a +0.40% su asset volatili e garantendo BE >= +0.25% a copertura fee).
    """
    atr = max(0.20, float(atr_pct or 1.0))
    ep = float(entry_price or 0.0)
    is_long = str(side or "").strip().upper() in ("BUY", "LONG")

    default_sl = max(0.90, min(2.20, atr * 1.4))
    default_tp = default_sl * 3.0

    sl_raw = default_sl
    tp_raw = default_tp
    if isinstance(adaptive_params, dict) and adaptive_params.get("approved") is True:
        bp = adaptive_params.get("best_params") if isinstance(adaptive_params.get("best_params"), dict) else adaptive_params
        if "sl_atr" in bp:
            cand_sl = atr * float(bp["sl_atr"])
            sl_raw = max(0.8 * default_sl, min(1.5 * default_sl, cand_sl))
        if "tp_atr" in bp:
            cand_tp = atr * float(bp["tp_atr"])
            tp_raw = max(0.8 * default_tp, min(1.5 * default_tp, cand_tp))

    sl_pct = round(sl_raw, 2)
    tp_pct = round(tp_raw, 2)

    tight_trigger_pct = round(sl_pct * 0.75, 2)
    tight_lock_pct = round(-sl_pct * 0.40, 2)

    be_trigger_pct = round(sl_pct * 1.15, 2)
    be_lock_pct = round(max(0.25, sl_pct * 0.25), 2)

    mid_trigger_pct = round(sl_pct * 1.80, 2)
    mid_lock_pct = round(sl_pct * 0.80, 2)

    max_trigger_pct = round(sl_pct * 2.40, 2)
    max_lock_pct = round(sl_pct * 1.40, 2)

    if ep > 0:
        if is_long:
            sl_price = _round_adaptive_price(ep * (1.0 - sl_pct / 100.0), ep)
            tp_price = _round_adaptive_price(ep * (1.0 + tp_pct / 100.0), ep)
            tight_sl = _round_adaptive_price(ep * (1.0 + tight_lock_pct / 100.0), ep)
            be_sl = _round_adaptive_price(ep * (1.0 + be_lock_pct / 100.0), ep)
            mid_sl = _round_adaptive_price(ep * (1.0 + mid_lock_pct / 100.0), ep)
            max_sl = _round_adaptive_price(ep * (1.0 + max_lock_pct / 100.0), ep)
        else:
            sl_price = _round_adaptive_price(ep * (1.0 + sl_pct / 100.0), ep)
            tp_price = _round_adaptive_price(ep * (1.0 - tp_pct / 100.0), ep)
            tight_sl = _round_adaptive_price(ep * (1.0 - tight_lock_pct / 100.0), ep)
            be_sl = _round_adaptive_price(ep * (1.0 - be_lock_pct / 100.0), ep)
            mid_sl = _round_adaptive_price(ep * (1.0 - mid_lock_pct / 100.0), ep)
            max_sl = _round_adaptive_price(ep * (1.0 - max_lock_pct / 100.0), ep)
    else:
        sl_price = tp_price = tight_sl = be_sl = mid_sl = max_sl = 0.0

    return {
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "tight_trigger_pct": tight_trigger_pct,
        "tight_lock_pct": tight_lock_pct,
        "tight_sl": tight_sl,
        "be_trigger_pct": be_trigger_pct,
        "be_lock_pct": be_lock_pct,
        "be_sl": be_sl,
        "mid_trigger_pct": mid_trigger_pct,
        "mid_lock_pct": mid_lock_pct,
        "mid_sl": mid_sl,
        "max_trigger_pct": max_trigger_pct,
        "max_lock_pct": max_lock_pct,
        "max_sl": max_sl,
    }


def _load_context_observations(
    db_path: Path,
    now_dt: datetime,
    half_life_days: float,
) -> List[Dict[str, Any]]:
    """Carica tutte le osservazioni in unità R da `trade_journal` (CLOSED) e `signal_shadows` (EVALUATED)."""
    obs: List[Dict[str, Any]] = []
    if not Path(db_path).exists():
        return obs

    TradeJournalService(db_path)  # Garantisce schema aggiornato in modo additivo
    hl = max(1.0, float(half_life_days or 35.0))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        real_rows = conn.execute(
            """
            SELECT broker, symbol, side, entry_price, notional_usd, opened_at, closed_at,
                   pnl_usd, pnl_pct, entry_context, engine, context_key, fees_usd
            FROM trade_journal
            WHERE status = 'CLOSED'
            """
        ).fetchall()

        for r in real_rows:
            ctx = _parse_entry_context(r["entry_context"])
            sl_pct = float(ctx.get("sl_pct") or 1.2)
            sl_pct = max(0.25, sl_pct)
            pnl_pct = float(r["pnl_pct"] or 0.0)
            r_val = pnl_pct / sl_pct

            ts_dt = _parse_iso_dt(r["closed_at"]) or _parse_iso_dt(r["opened_at"]) or now_dt
            age_days = max(0.0, (now_dt - ts_dt).total_seconds() / 86400.0)
            w = 0.5 ** (age_days / hl)

            parts = _extract_context_parts(
                r["context_key"],
                broker=r["broker"],
                side=r["side"],
                engine=r["engine"],
                entry_context=ctx,
                opened_at=r["opened_at"],
            )
            obs.append(
                {
                    "source": "REAL",
                    "parts": parts,
                    "r": r_val,
                    "w": w,
                }
            )

        shadow_rows = conn.execute(
            """
            SELECT broker, symbol, side, engine, context_key, created_at, evaluated_at, virtual_r
            FROM signal_shadows
            WHERE status = 'EVALUATED' AND virtual_r IS NOT NULL
            """
        ).fetchall()

        for s in shadow_rows:
            ts_dt = _parse_iso_dt(s["evaluated_at"]) or _parse_iso_dt(s["created_at"]) or now_dt
            age_days = max(0.0, (now_dt - ts_dt).total_seconds() / 86400.0)
            w = 0.5 ** (age_days / hl)
            parts = _extract_context_parts(
                s["context_key"],
                broker=s["broker"],
                side=s["side"],
                engine=s["engine"],
                opened_at=s["created_at"],
            )
            obs.append(
                {
                    "source": "SHADOW",
                    "parts": parts,
                    "r": float(s["virtual_r"]),
                    "w": w,
                }
            )

    return obs


def _compute_allocation_from_obs(
    obs: List[Dict[str, Any]],
    context_key: str,
) -> Dict[str, Any]:
    """Calcola la policy bayesiana (Normal-Gamma shrinkage + backoff gerarchico) da una lista di osservazioni."""
    hierarchy = backoff_context_keys(context_key)
    matched: List[Dict[str, Any]] = []
    matched_key = context_key
    backoff_level = 0

    for idx, hk in enumerate(hierarchy):
        cand = [o for o in obs if _match_context_hierarchy(o["parts"], hk)]
        sum_w_cand = sum(o["w"] for o in cand)
        matched = cand
        matched_key = hk
        backoff_level = idx
        if sum_w_cand >= 8.0:
            break

    n_real = sum(1 for o in matched if o["source"] == "REAL")
    n_shadow = sum(1 for o in matched if o["source"] == "SHADOW")
    n_eff = sum(o["w"] for o in matched)

    prior_n = 10.0
    prior_mean = 0.0
    prior_var = 1.0

    if n_eff > 0:
        raw_mean = sum(o["w"] * o["r"] for o in matched) / n_eff
        ss_res = sum(o["w"] * ((o["r"] - raw_mean) ** 2) for o in matched)
    else:
        raw_mean = 0.0
        ss_res = 0.0

    post_n = prior_n + n_eff
    post_mean = (prior_n * prior_mean + n_eff * raw_mean) / post_n
    prior_ss = prior_n * prior_var
    coupling_ss = (prior_n * n_eff / post_n) * ((raw_mean - prior_mean) ** 2)
    post_var = (prior_ss + ss_res + coupling_ss) / max(post_n - 1.0, 1.0)
    post_se = math.sqrt(max(post_var, 1e-6) / post_n)

    lcb_r = post_mean - 1.28 * post_se
    ucb_r = post_mean + 1.28 * post_se

    if n_eff < 8.0:
        scale = 1.0
        mode = "LEARNING_PRIOR"
    elif n_eff >= 15.0 and lcb_r >= 0.10:
        scale = 1.25
        mode = "BOOSTED"
    elif n_eff >= 15.0 and lcb_r <= -0.25 and post_mean <= -0.15:
        scale = 0.0
        mode = "SHADOW_BLOCKED"
    elif n_eff >= 10.0 and post_mean < -0.05 and lcb_r < -0.10:
        scale = 0.5
        mode = "CAUTIOUS"
    else:
        scale = 1.0
        mode = "STANDARD"

    return {
        "context_key": context_key,
        "matched_key": matched_key,
        "backoff_level": backoff_level,
        "mode": mode,
        "scale": scale,
        "n_eff": round(n_eff, 2),
        "n_real": n_real,
        "n_shadow": n_shadow,
        "mean_r": round(post_mean, 4),
        "raw_mean_r": round(raw_mean, 4),
        "post_se": round(post_se, 4),
        "lcb_r": round(lcb_r, 4),
        "ucb_r": round(ucb_r, 4),
    }


def compute_context_allocation(
    db_path: Path,
    context_key: str,
    half_life_days: float = 35.0,
) -> Dict[str, Any]:
    """
    Allocatore Bayesiano Contestuale con decadimento temporale (`half_life_days`) e
    auto-riabilitazione da `SHADOW_BLOCKED` quando gli shadow signal valutati mostrano recupero di edge.
    """
    now_dt = datetime.now(ROME_TZ)
    obs = _load_context_observations(Path(db_path), now_dt, half_life_days)
    return _compute_allocation_from_obs(obs, context_key)


EQUITY_FLATTEN_LEAD_MINUTES = 8.0


def _truncate_to_equity_session(
    fwd_df: pd.DataFrame,
    created_dt: datetime,
    now: Optional[datetime] = None,
) -> Tuple[pd.DataFrame, bool]:
    """Keep only the forward bars an intraday equity trade could live through.

    US equity positions are force-flattened `EQUITY_FLATTEN_LEAD_MINUTES` before the NYSE close
    of the signal's own session (16:00 ET, or 13:00 ET on early-close days), so a shadow signal
    must be marked there, not on the next sessions. Returns (bars, session_still_running).
    """
    from services import market_calendar

    created_ny = market_calendar.now_ny(created_dt)
    bounds = market_calendar.session_bounds(created_ny.date())
    if bounds is None or fwd_df is None or fwd_df.empty:
        return fwd_df, False
    cutoff = pd.Timestamp(bounds[1]) - pd.Timedelta(minutes=EQUITY_FLATTEN_LEAD_MINUTES)
    idx = fwd_df.index
    if not isinstance(idx, pd.DatetimeIndex):
        return fwd_df, False
    idx_utc = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    step = pd.Timedelta(minutes=5)
    if len(idx_utc) >= 2:
        step = pd.Timedelta(pd.Series(idx_utc).diff().dropna().median())
    keep = (idx_utc + step) <= cutoff.tz_convert("UTC")
    now_ts = pd.Timestamp(now or datetime.now(timezone.utc))
    now_ts = now_ts.tz_localize("UTC") if now_ts.tzinfo is None else now_ts.tz_convert("UTC")
    return fwd_df[keep], bool(now_ts < cutoff.tz_convert("UTC"))


def _fallback_evaluate_shadow_bars(
    ohlcv_df: pd.DataFrame,
    broker: str,
    side: str,
    signal_price: float,
    sl_pct: float,
    tp_pct: float,
    created_at_iso: str,
) -> Optional[Dict[str, Any]]:
    """
    Valutazione causale di fallback su barre chiuse successive a `created_at_iso`
    quando `services.strategy_engines_service.evaluate_shadow_bars` non è disponibile.
    """
    sp = float(signal_price or 0.0)
    if sp <= 0:
        return None
    df = _prepare_ohlcv_df(ohlcv_df)
    if df is None or df.empty:
        return None
    cdt = _parse_iso_dt(created_at_iso)
    if cdt is None:
        return None
    created_ts = pd.Timestamp(cdt.astimezone(timezone.utc))
    fwd = df[df.index > created_ts]
    if fwd.empty:
        return None

    is_long = str(side or "").strip().upper() in ("BUY", "LONG")
    sl_p = sp * (1.0 - sl_pct / 100.0) if is_long else sp * (1.0 + sl_pct / 100.0)
    tp_p = sp * (1.0 + tp_pct / 100.0) if is_long else sp * (1.0 - tp_pct / 100.0)

    max_fav = 0.0
    max_adv = 0.0
    hit_outcome = "TIME_EXIT"
    gross_pnl_pct = 0.0

    for _, row in fwd.iterrows():
        hi = float(row["high"])
        lo = float(row["low"])
        cl = float(row["close"])
        if is_long:
            fav = max(0.0, ((hi - sp) / sp) * 100.0)
            adv = min(0.0, ((lo - sp) / sp) * 100.0)
            max_fav = max(max_fav, fav)
            max_adv = min(max_adv, adv)
            if lo <= sl_p:
                hit_outcome = "SL"
                gross_pnl_pct = -abs(sl_pct)
                break
            if hi >= tp_p:
                hit_outcome = "TP"
                gross_pnl_pct = abs(tp_pct)
                break
            gross_pnl_pct = ((cl - sp) / sp) * 100.0
        else:
            fav = max(0.0, ((sp - lo) / sp) * 100.0)
            adv = min(0.0, ((sp - hi) / sp) * 100.0)
            max_fav = max(max_fav, fav)
            max_adv = min(max_adv, adv)
            if hi >= sl_p:
                hit_outcome = "SL"
                gross_pnl_pct = -abs(sl_pct)
                break
            if lo <= tp_p:
                hit_outcome = "TP"
                gross_pnl_pct = abs(tp_pct)
                break
            gross_pnl_pct = ((sp - cl) / sp) * 100.0

    fee_rt = ALPACA_DEFAULT_RT_FEE_PCT if str(broker).upper() == "ALPACA" else BYBIT_DEFAULT_RT_FEE_PCT
    net_pnl_pct = gross_pnl_pct - fee_rt
    virtual_r = net_pnl_pct / max(abs(sl_pct), 0.15)
    return {
        "virtual_pnl_pct": round(net_pnl_pct, 4),
        "virtual_r": round(virtual_r, 4),
        "mfe_pct": round(max_fav, 4),
        "mae_pct": round(max_adv, 4),
        "hit_outcome": hit_outcome,
    }


def run_evaluation_cycle(
    db_path: Path,
    ohlcv_fetcher: Callable[[str, str, str, str], Any],
) -> Dict[str, int]:
    """
    Esegue un ciclo incrementale di valutazione causale:
    1. Popola MFE/MAE, `capture_eff`, `edge_ratio`, `bars_held` e `exit_eval` sui trade chiusi pendenti.
    2. Valuta gli shadow signal maturi (`>= 90` minuti) tramite `evaluate_shadow_bars` (o fallback interno).
    """
    journal = TradeJournalService(db_path)
    trades_evaluated = 0
    shadows_evaluated = 0
    errors = 0

    try:
        from services.strategy_engines_service import evaluate_shadow_bars  # type: ignore
    except Exception:
        evaluate_shadow_bars = None

    # 1. Valuta trade chiusi senza MFE/MAE
    for tr in journal.get_pending_mfe_trades(limit=25):
        try:
            opened_at = tr.get("opened_at") or ""
            closed_at = tr.get("closed_at") or opened_at
            df = ohlcv_fetcher(tr["broker"], tr["symbol"], opened_at, closed_at)
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                continue
            eval_res = evaluate_trade_path_mfe_mae(
                df,
                side=tr["side"],
                entry_price=float(tr["entry_price"]),
                opened_at_iso=opened_at,
                closed_at_iso=closed_at,
                exit_price=float(tr["exit_price"]),
                realized_pct=float(tr["pnl_pct"]) if tr.get("pnl_pct") is not None else None,
            )
            if not eval_res:
                continue
            ok = journal.update_trade_path_eval(
                trade_id=tr["trade_id"],
                mfe_pct=eval_res["mfe_pct"],
                mae_pct=eval_res["mae_pct"],
                capture_eff=eval_res["capture_eff"],
                edge_ratio=eval_res["edge_ratio"],
                bars_held=eval_res["bars_held"],
                exit_eval=eval_res,
            )
            if ok:
                trades_evaluated += 1
        except Exception:
            errors += 1

    # 2. Valuta shadow signals pendenti
    now_iso = datetime.now(ROME_TZ).isoformat()
    for sh in journal.get_pending_shadows(min_age_minutes=90, limit=30):
        try:
            df = ohlcv_fetcher(sh["broker"], sh["symbol"], sh["created_at"], now_iso)
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                continue
            sh_res: Optional[Dict[str, Any]] = None
            if evaluate_shadow_bars is not None:
                cdt = _parse_iso_dt(sh["created_at"])
                prep_df = _prepare_ohlcv_df(df)
                if cdt is None or prep_df is None or prep_df.empty:
                    continue
                created_ts = pd.Timestamp(cdt.astimezone(timezone.utc))
                fwd_df = prep_df[prep_df.index > created_ts].rename(
                    columns={"high": "High", "low": "Low", "close": "Close"}
                )
                session_open_still = False
                if str(sh["broker"]).upper() == "ALPACA":
                    fwd_df, session_open_still = _truncate_to_equity_session(fwd_df, cdt)
                if fwd_df.empty:
                    continue
                fee_rt = (
                    ALPACA_DEFAULT_RT_FEE_PCT
                    if str(sh["broker"]).upper() == "ALPACA"
                    else BYBIT_DEFAULT_RT_FEE_PCT
                )
                sh_res = evaluate_shadow_bars(
                    side=sh["side"],
                    signal_price=float(sh["signal_price"]),
                    sl_pct=float(sh["sl_pct"]),
                    tp_pct=float(sh["tp_pct"]),
                    future_ohlcv_df=fwd_df,
                    fee_rt_pct=fee_rt,
                )
                if not sh_res or sh_res.get("status", "EVALUATED") != "EVALUATED":
                    continue
                if session_open_still and str(sh_res.get("hit_outcome")) not in ("SL", "TP"):
                    continue  # equity session still running: wait for the forced-flatten mark
            else:
                sh_res = _fallback_evaluate_shadow_bars(
                    df,
                    broker=sh["broker"],
                    side=sh["side"],
                    signal_price=float(sh["signal_price"]),
                    sl_pct=float(sh["sl_pct"]),
                    tp_pct=float(sh["tp_pct"]),
                    created_at_iso=sh["created_at"],
                )

            if not sh_res:
                continue
            ok = journal.update_shadow_eval(
                shadow_id=sh["shadow_id"],
                virtual_pnl_pct=float(sh_res["virtual_pnl_pct"]),
                virtual_r=float(sh_res["virtual_r"]),
                mfe_pct=float(sh_res.get("mfe_pct") or 0.0),
                mae_pct=float(sh_res.get("mae_pct") or 0.0),
                hit_outcome=str(sh_res.get("hit_outcome") or "TIME_EXIT"),
            )
            if ok:
                shadows_evaluated += 1
        except Exception:
            errors += 1

    return {
        "trades_evaluated": trades_evaluated,
        "shadows_evaluated": shadows_evaluated,
        "errors": errors,
    }


def _inspect_quant_drift(meta_gate_path: Optional[str]) -> Dict[str, Any]:
    path = meta_gate_path or os.environ.get("QUANT_META_GATE_PATH")
    if not path or not os.path.exists(path):
        return {
            "active": False,
            "deployable": False,
            "n_events": 0,
            "path": path,
            "verdict": "MetaGate non configurato",
        }
    try:
        from quant.live.gate import MetaGate

        gate = MetaGate.load(path)
        meta = gate.meta or {}
        return {
            "active": True,
            "deployable": bool(gate.deployable),
            "n_events": int(meta.get("n_events", 0) or 0),
            "kind": meta.get("kind"),
            "interval": meta.get("interval"),
            "base_rate": meta.get("base_rate"),
            "verdict": meta.get("verdict", ""),
            "trained_at": meta.get("trained_at"),
            "path": path,
        }
    except Exception as e:
        return {
            "active": False,
            "deployable": False,
            "n_events": 0,
            "path": path,
            "verdict": f"Errore caricamento MetaGate: {e}",
        }


def get_learning_dashboard_summary(
    db_path: Path,
    meta_gate_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Aggrega il riepilogo completo per Dashboard & Report:
    - `real_stats` (netto fee realistiche)
    - `shadow_stats`
    - `context_allocations`
    - `exit_frontier`
    - `engines_breakdown`
    - `quant_drift`
    - `latest_audit`
    """
    p = Path(db_path)
    journal = TradeJournalService(p)

    with sqlite3.connect(p) as conn:
        conn.row_factory = sqlite3.Row
        closed_rows = [
            dict(r)
            for r in conn.execute("SELECT * FROM trade_journal WHERE status = 'CLOSED'").fetchall()
        ]
        shadow_rows = [dict(r) for r in conn.execute("SELECT * FROM signal_shadows").fetchall()]

    # 1. Real stats netti
    total = len(closed_rows)
    net_pnls_usd: List[float] = []
    r_vals: List[float] = []
    total_fees_usd = 0.0
    mfe_vals: List[float] = []
    mae_vals: List[float] = []
    cap_vals: List[float] = []
    edge_vals: List[float] = []

    engine_buckets: Dict[str, List[Dict[str, Any]]] = {}
    discovered_contexts: set[str] = set()

    for r in closed_rows:
        ctx = _parse_entry_context(r.get("entry_context"))
        broker = str(r.get("broker") or "BYBIT").upper()
        notional = float(r.get("notional_usd") or ctx.get("invested_usd") or 0.0)
        recorded_fee = float(r.get("fees_usd") or ctx.get("fee_usd") or 0.0)
        default_rt = ALPACA_DEFAULT_RT_FEE_PCT if broker == "ALPACA" else BYBIT_DEFAULT_RT_FEE_PCT
        est_fee = (notional * default_rt / 100.0) if notional > 0 else 0.0
        eff_fee = recorded_fee if recorded_fee > 0 else est_fee
        total_fees_usd += eff_fee

        raw_pnl = float(r.get("pnl_usd") or 0.0)
        pnl_is_net = bool(ctx.get("pnl_is_net")) or (broker == "BYBIT" and bool(ctx.get("historical_import")))
        net_pnl = raw_pnl if pnl_is_net else (raw_pnl - eff_fee)
        net_pnls_usd.append(net_pnl)

        sl_pct = max(0.25, float(ctx.get("sl_pct") or 1.2))
        pnl_pct = float(r.get("pnl_pct") or 0.0)
        net_pnl_pct = pnl_pct if pnl_is_net else (pnl_pct - (default_rt if notional > 0 or pnl_pct != 0 else 0.0))
        r_val = net_pnl_pct / sl_pct
        r_vals.append(r_val)

        if r.get("mfe_pct") is not None:
            mfe_vals.append(float(r["mfe_pct"]))
        if r.get("mae_pct") is not None:
            mae_vals.append(float(r["mae_pct"]))
        if r.get("capture_eff") is not None:
            cap_vals.append(float(r["capture_eff"]))
        if r.get("edge_ratio") is not None:
            edge_vals.append(float(r["edge_ratio"]))

        eng = str(r.get("engine") or ctx.get("engine") or "INTRADAY_MOMENTUM").upper()
        engine_buckets.setdefault(eng, []).append({"net_pnl": net_pnl, "r": r_val})

        parts = _extract_context_parts(
            r.get("context_key"),
            broker=broker,
            side=r.get("side"),
            engine=eng,
            entry_context=ctx,
            opened_at=r.get("opened_at"),
        )
        discovered_contexts.add("|".join(parts))

    wins_usd = [x for x in net_pnls_usd if x > 0]
    losses_usd = [abs(x) for x in net_pnls_usd if x <= 0]
    gross_profit = sum(wins_usd)
    gross_loss = sum(losses_usd)
    pf_net = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    real_stats = {
        "total": total,
        "wins": len(wins_usd),
        "losses": len(losses_usd),
        "win_rate": round((len(wins_usd) / total) * 100.0, 1) if total > 0 else 0.0,
        "profit_factor_net": round(pf_net, 2),
        "expectancy_r": round(sum(r_vals) / total, 4) if total > 0 else 0.0,
        "expectancy_usd": round(sum(net_pnls_usd) / total, 2) if total > 0 else 0.0,
        "total_pnl_usd": round(sum(net_pnls_usd), 2),
        "total_fees_usd": round(total_fees_usd, 2),
        "avg_mfe_pct": round(sum(mfe_vals) / len(mfe_vals), 3) if mfe_vals else 0.0,
        "avg_mae_pct": round(sum(mae_vals) / len(mae_vals), 3) if mae_vals else 0.0,
        "avg_capture_eff": round(sum(cap_vals) / len(cap_vals), 3) if cap_vals else 0.0,
        "avg_edge_ratio": round(sum(edge_vals) / len(edge_vals), 2) if edge_vals else 0.0,
    }

    # 2. Shadow stats
    pending_sh = [s for s in shadow_rows if s.get("status") == "PENDING"]
    eval_sh = [s for s in shadow_rows if s.get("status") == "EVALUATED"]
    sh_wins = [s for s in eval_sh if float(s.get("virtual_r") or 0.0) > 0]
    sh_rs = [float(s.get("virtual_r") or 0.0) for s in eval_sh]
    for s in eval_sh:
        if s.get("context_key"):
            discovered_contexts.add(str(s["context_key"]).upper())

    shadow_stats = {
        "pending": len(pending_sh),
        "evaluated": len(eval_sh),
        "shadow_win_rate": round((len(sh_wins) / len(eval_sh)) * 100.0, 1) if eval_sh else 0.0,
        "shadow_expectancy_r": round(sum(sh_rs) / len(eval_sh), 4) if eval_sh else 0.0,
    }

    # 3. Context allocations
    now_dt = datetime.now(ROME_TZ)
    obs = _load_context_observations(p, now_dt, half_life_days=35.0)
    allocations: List[Dict[str, Any]] = []
    for ck in sorted(discovered_contexts):
        alloc = _compute_allocation_from_obs(obs, ck)
        allocations.append(alloc)
    allocations.sort(
        key=lambda a: (
            1 if a["mode"] == "SHADOW_BLOCKED" else (1 if a["mode"] == "BOOSTED" else 0),
            abs(a["mean_r"]) * a["n_eff"],
        ),
        reverse=True,
    )

    # 4. Exit Frontier
    exit_frontier = optimize_exit_frontier(closed_rows)

    # 5. Engines breakdown
    engines_breakdown: Dict[str, Dict[str, Any]] = {}
    for eng, items in engine_buckets.items():
        cnt = len(items)
        ewins = [it["net_pnl"] for it in items if it["net_pnl"] > 0]
        eloss = [abs(it["net_pnl"]) for it in items if it["net_pnl"] <= 0]
        gp = sum(ewins)
        gl = sum(eloss)
        epf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)
        engines_breakdown[eng] = {
            "total": cnt,
            "wins": len(ewins),
            "win_rate": round((len(ewins) / cnt) * 100.0, 1) if cnt > 0 else 0.0,
            "net_pnl_usd": round(sum(it["net_pnl"] for it in items), 2),
            "expectancy_r": round(sum(it["r"] for it in items) / cnt, 4) if cnt > 0 else 0.0,
            "profit_factor_net": round(epf, 2),
        }

    # 6. Quant drift + latest audit
    quant_drift = _inspect_quant_drift(meta_gate_path)
    latest_audit = journal.get_latest_audit("WEEKLY_AUDIT")

    return {
        "real_stats": real_stats,
        "shadow_stats": shadow_stats,
        "context_allocations": allocations[:12],
        "exit_frontier": exit_frontier,
        "engines_breakdown": engines_breakdown,
        "quant_drift": quant_drift,
        "latest_audit": latest_audit,
    }


def build_weekly_learning_report(db_path: Path) -> Tuple[Dict[str, Any], str]:
    """
    Genera la diagnosi esecutiva settimanale netta di commissioni e la salva in `learning_audit`.
    Restituisce `(metrics_dict, telegram_markdown_text)`.
    """
    p = Path(db_path)
    summary = get_learning_dashboard_summary(p)
    rs = summary["real_stats"]
    sh = summary["shadow_stats"]
    ef = summary["exit_frontier"]
    qd = summary["quant_drift"]
    allocs = summary["context_allocations"]

    boosted = [a for a in allocs if a["mode"] == "BOOSTED"][:3]
    blocked = [a for a in allocs if a["mode"] == "SHADOW_BLOCKED"][:3]

    lines = [
        "🧠 *WEEKLY LEARNING AUDIT (NETTO COMMISSIONI)*",
        "────────────────────────",
        f"• *Trade Reali:* `{rs['total']}` | *WR:* `{rs['win_rate']:.1f}%` | *PF Netto:* `{rs['profit_factor_net']:.2f}`",
        f"• *Expectancy Netta:* `{rs['expectancy_r']:+.3f}R` (`${rs['expectancy_usd']:+.2f}/trade`) | *Fee Totali:* `${rs['total_fees_usd']:.2f}`",
        f"• *Path MFE/MAE:* MFE medio `+{rs['avg_mfe_pct']:.2f}%` | MAE `{rs['avg_mae_pct']:.2f}%` | *Capture Eff:* `{rs['avg_capture_eff']:.2f}` | *Edge Ratio:* `{rs['avg_edge_ratio']:.2f}`",
        f"• *Shadow Signals:* `{sh['evaluated']}` valutati (`{sh['pending']}` pending) | *Shadow WR:* `{sh['shadow_win_rate']:.1f}%` | *Exp:* `{sh['shadow_expectancy_r']:+.3f}R`",
        f"• *Exit Frontier:* `{'APPROVATA' if ef['approved'] else 'IN ATTESA'}` (N={ef['n_samples']}, LCB `{ef['best_lcb_r']:+.3f}R`) — {ef['reason']}",
        f"• *Quant Drift (MetaGate):* `{'ATTIVO' if qd['active'] else 'OFF'}` | *Deployable:* `{qd['deployable']}` | *Eventi:* `{qd['n_events']}`",
    ]
    if boosted:
        lines.append("• *Contesti BOOSTED (1.25x):* " + ", ".join(f"`{a['context_key']}` ({a['mean_r']:+.2f}R)" for a in boosted))
    if blocked:
        lines.append("• *Contesti SHADOW_BLOCKED (0.0x):* " + ", ".join(f"`{a['context_key']}` ({a['lcb_r']:+.2f}R LCB)" for a in blocked))

    summary_text = "\n".join(lines)
    TradeJournalService(p).save_learning_audit("WEEKLY_AUDIT", summary, summary_text)
    return summary, summary_text


class LearningEngineService:
    """Wrapper OOP attorno alle funzioni pure del motore di apprendimento quantitativo."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path is not None else get_trade_journal_db_path()

    def normalize_context_key(
        self,
        broker: str,
        side: str,
        macro_bias: Optional[str],
        atr_pct: float,
        rome_hour: int,
        engine: str = "INTRADAY_MOMENTUM",
    ) -> str:
        return normalize_context_key(broker, side, macro_bias, atr_pct, rome_hour, engine)

    def backoff_context_keys(self, context_key: str) -> List[str]:
        return backoff_context_keys(context_key)

    def evaluate_trade_path_mfe_mae(
        self,
        ohlcv_df: pd.DataFrame,
        side: str,
        entry_price: float,
        opened_at_iso: str,
        closed_at_iso: str,
        exit_price: Optional[float] = None,
        realized_pct: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        return evaluate_trade_path_mfe_mae(
            ohlcv_df, side, entry_price, opened_at_iso, closed_at_iso, exit_price, realized_pct
        )

    def optimize_exit_frontier(
        self,
        evaluated_trades: List[Dict[str, Any]],
        side: Optional[str] = None,
        fee_rt_pct: float = BYBIT_DEFAULT_RT_FEE_PCT,
    ) -> Dict[str, Any]:
        return optimize_exit_frontier(evaluated_trades, side=side, fee_rt_pct=fee_rt_pct)

    def compute_atr_ratchet_levels(
        self,
        atr_pct: float,
        side: str,
        entry_price: float,
        adaptive_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return compute_atr_ratchet_levels(atr_pct, side, entry_price, adaptive_params)

    def compute_context_allocation(
        self,
        context_key: str,
        db_path: Optional[Path] = None,
        half_life_days: float = 35.0,
    ) -> Dict[str, Any]:
        return compute_context_allocation(db_path or self.db_path, context_key, half_life_days)

    def run_evaluation_cycle(
        self,
        ohlcv_fetcher: Callable[[str, str, str, str], Any],
        db_path: Optional[Path] = None,
    ) -> Dict[str, int]:
        return run_evaluation_cycle(db_path or self.db_path, ohlcv_fetcher)

    def get_learning_dashboard_summary(
        self,
        db_path: Optional[Path] = None,
        meta_gate_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        return get_learning_dashboard_summary(db_path or self.db_path, meta_gate_path)

    def build_weekly_learning_report(
        self,
        db_path: Optional[Path] = None,
    ) -> Tuple[Dict[str, Any], str]:
        return build_weekly_learning_report(db_path or self.db_path)


learning_engine = LearningEngineService()
