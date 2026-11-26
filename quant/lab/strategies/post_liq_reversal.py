"""BYBIT_POST_LIQ_REVERSAL (lab paper, v1.0): fade of a liquidation cascade once forced flow is exhausted.

Rules (reports/PREREG_NEW_STRATEGIES.md §1, live code in services/strategy_engines_service.py §8a):
funding percentile (30 days) >= 95 -> SHORT / <= 5 -> LONG; spike bar range >= 2.5 ATR14 in the crowding direction;
open-interest change on the spike z <= -2 vs the previous 48 h; next bar reabsorbs (close back in the previous range,
wick >= 50%, lower volume). Exits: SL spike extreme +- 0.25 ATR; 50% at +1.5R and stop to breakeven + fees; runner to the
4h VWAP or a 1.5 ATR trail; time-stop after 6 bars below +0.5R; safety max hold 96 bars.
State is rebuilt at every run by replaying the last closed 15m bars (stateless, restart-safe).
Backtest (Nov 2024 -> Oct 2026): 6 trades in 2 years on 10 perps -> NON VALUTABILE (reports/NEW_STRATEGIES_POTENTIAL_AUDIT.md).
Open interest: Bybit public v5 (Binance fallback); without OI data no entry is possible (NO_OI_DATA).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from quant.core import COST_PRESETS
from quant.lab.base import Decision, Instrument, Target
from quant.lab.strategies import _journal
from quant.lab.strategies._util import closed_bars, funding_series, utc
from services.strategy_engines_service import (
    ENGINE_POST_LIQ_REVERSAL,
    LAB_STRATEGY_VERSION,
    POST_LIQ_PARAMS,
    STRATEGY_RULESET_VERSION,
    detect_post_liq_reversal,
    funding_percentile,
    oi_change_zscore,
    rolling_vwap,
    simulate_active_exit,
    wilder_atr_array,
)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT", "AVAXUSDT", "ADAUSDT", "DOGEUSDT", "SUIUSDT", "NEARUSDT"]
WEIGHT = 0.10
FEE_SIDE, SLIP_ENTRY, SLIP_EXIT, SLIP_STOP = 0.00055, 0.0005, 0.0002, 0.0005
MAX_HOLD, OI_LOOKBACK, REPLAY_BARS = 96, 192, 104
NEAR_MISS = ("OI_NOT_COLLAPSING", "NO_REABSORPTION", "NO_OI_DATA")


def oi_at_bar_ends(oi: pd.Series, ends: pd.DatetimeIndex) -> np.ndarray:
    if oi is None or len(oi) == 0:
        return np.full(len(ends), np.nan)
    left = pd.DataFrame({"t": pd.DatetimeIndex(ends).astype("datetime64[ns, UTC]")})
    right = pd.DataFrame({"t": pd.DatetimeIndex(oi.index).astype("datetime64[ns, UTC]"), "oi": oi.to_numpy(float)})
    m = pd.merge_asof(left, right.sort_values("t"), on="t", direction="backward", tolerance=pd.Timedelta(minutes=15))
    return m["oi"].to_numpy(float)


def replay(symbol: str, bars: pd.DataFrame, funding: pd.Series, oi: pd.Series) -> Tuple[Dict, List[Dict]]:
    """-> (open position {side, fraction} or {}, journal rows) from closed 15m bars (lower-case OHLCV)."""
    o, h, l, c, v = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    ends = bars.index + pd.Timedelta(minutes=15)
    n = len(c)
    atr = wilder_atr_array(h, l, c, 14)
    vwap = rolling_vwap(h, l, c, v, 16)
    oi_arr = oi_at_bar_ends(oi, ends)
    rows, pos, busy = [], {}, -1
    for i in range(max(OI_LOOKBACK + 20, n - REPLAY_BARS), n):
        s = i - 1
        if not (np.isfinite(atr[s - 1]) and h[s] - l[s] >= POST_LIQ_PARAMS["spike_atr_mult"] * atr[s - 1]):
            continue
        fp = funding_percentile(funding, ends[i])
        z = oi_change_zscore(oi_arr, s, OI_LOOKBACK)
        sig = detect_post_liq_reversal(o, h, l, c, v, i, fp, z, atr=atr)
        base = {"strategy": ENGINE_POST_LIQ_REVERSAL, "strategy_version": LAB_STRATEGY_VERSION,
                "ruleset_version": STRATEGY_RULESET_VERSION, "broker": "BYBIT_PAPER", "symbol": symbol,
                "signal_time": ends[i].isoformat(), "funding_pct": fp, "oi_delta_z": z,
                "diagnostics": sig.get("features", {})}
        if not sig["triggered"]:
            if sig["reject_reason"] in NEAR_MISS:
                rows.append({**base, "trade_key": f"{ENGINE_POST_LIQ_REVERSAL}|{symbol}|{ends[i].isoformat()}",
                             "status": "REJECTED", "side": sig.get("side"), "reject_reason": sig["reject_reason"]})
            continue
        if i <= busy:
            continue
        side = 1 if sig["side"] == "LONG" else -1
        end_pos = min(i + MAX_HOLD, n - 1)
        truncated = i + MAX_HOLD > n - 1  # the safety time barrier is still in the future
        if end_pos > i:
            ex = simulate_active_exit(o, h, l, c, i, side, sig["entry"], sig["sl"], atr, end_pos, tp1_r=1.5,
                                      tp1_frac=0.5, trail_atr=1.5, time_stop_bars=6, time_stop_r=0.5, vwap=vwap,
                                      fee_side=FEE_SIDE, slip_entry=SLIP_ENTRY, slip_exit=SLIP_EXIT, slip_stop=SLIP_STOP,
                                      end_reason="DATA_END" if truncated else "MAX_HOLD")
        else:
            ex = {"valid": False}  # signal on the last closed bar: entry now, no bar to evaluate yet
        row = {**base, "trade_key": f"{ENGINE_POST_LIQ_REVERSAL}|{symbol}|{ends[i].isoformat()}", "side": sig["side"],
               "entry_time": ends[i].isoformat(), "entry_price": sig["entry"], "sl_price": sig["sl"],
               "risk_pct": sig["risk"] / sig["entry"] * 100.0}
        if not ex.get("valid") or ex["exit_reason"] == "DATA_END":
            frac = 1.0 if not ex.get("valid") else ex["legs"][-1]["fraction"]
            pos = {"side": side, "fraction": frac, "entry": sig["entry"], "sl": sig["sl"]}
            rows.append({**row, "status": "OPEN", "remaining_fraction": frac,
                         "tp1_hit": bool(ex.get("tp1_hit", False))})
            busy = n
        else:
            rows.append({**row, "status": "CLOSED", "exit_time": ends[i + ex["bars_held"]].isoformat(),
                         "exit_reason": ex["exit_reason"], "tp1_hit": ex["tp1_hit"], "remaining_fraction": 0.0,
                         "r_multiple": ex["r_multiple"], "pnl_pct": 100.0 * ex["ret"]})
            busy = i + ex["bars_held"]
    return pos, rows


class PostLiqReversal:
    name = "bybit_post_liq_reversal"
    version = LAB_STRATEGY_VERSION
    schedule = "1,16,31,46 * * * *"
    capital = 100_000.0
    expected = None

    def __init__(self, symbols=None, journal_sink=None):
        self.symbols = list(symbols or SYMBOLS)
        self.journal_sink = journal_sink
        self.inst = {s: Instrument(f"BYBIT:{s}", "bybit", s, COST_PRESETS["bybit_perp"]) for s in self.symbols}

    def decide(self, now_utc, data) -> Decision:
        now = utc(now_utc)
        targets, rows, n_open, errors = [], [], 0, 0
        for s in self.symbols:
            try:
                bars = closed_bars(data.bars("bybit", s, "15m", 5, now), now, 0.25)
                if len(bars) < OI_LOOKBACK + 40:
                    raise ValueError("storia 15m insufficiente")
                fund = funding_series(data.funding(s, 32, now), now)
                oi_fn = getattr(data, "open_interest", None)
                oi = oi_fn(s, 5, now) if oi_fn else pd.Series(dtype=float)
                pos, r = replay(s, bars, fund, oi)
                rows += r
            except Exception as e:  # noqa: BLE001
                pos, errors = {}, errors + 1
                targets.append(Target(self.inst[s], 0.0, f"flat (errore dati: {e})", {"status": "error"}))
                continue
            if pos:
                n_open += 1
                w = pos["side"] * WEIGHT * pos["fraction"]
                why = (f"post-liq {'LONG' if pos['side'] > 0 else 'SHORT'} aperto, frazione {pos['fraction']:.2f}, "
                       f"SL {pos['sl']:.6g}")
                targets.append(Target(self.inst[s], w, why, pos))
            else:
                targets.append(Target(self.inst[s], 0.0, "flat: nessun setup post-liquidazione attivo", {}))
        _journal.record(rows, self.journal_sink)
        return Decision(self.name, self.version, now.isoformat(), targets,
                        note=f"{n_open}/{len(self.symbols)} posizioni, {len(rows)} righe journal, errori dati {errors}")
