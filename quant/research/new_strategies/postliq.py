"""Historical backtest of BYBIT_POST_LIQ_REVERSAL (pre-registered, reports/PREREG_NEW_STRATEGIES.md §1)."""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from services.strategy_engines_service import (
    POST_LIQ_PARAMS,
    detect_post_liq_reversal,
    oi_change_zscore,
    rolling_vwap,
    simulate_active_exit,
    wilder_atr_array,
)

log = logging.getLogger(__name__)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT", "AVAXUSDT", "ADAUSDT", "DOGEUSDT", "SUIUSDT", "NEARUSDT")
START, END = "2024-11-01", "2026-11-01"
FEE_SIDE, SLIP_ENTRY, SLIP_EXIT, SLIP_STOP = 0.00055, 0.0005, 0.0002, 0.0005
MAX_HOLD, TIME_STOP_BARS, TIME_STOP_R, VWAP_BARS = 96, 6, 0.5, 16
OI_LOOKBACK = 192  # 48 h of 15m bars
VARIANTS = {
    "a_spec_active": dict(mirror=0.0, active=True),
    "b_spec_fixed": dict(mirror=0.0, active=False),
    "c_mirror_active": dict(mirror=1.0, active=True),
    "d_mirror_fixed": dict(mirror=1.0, active=False),
}


def load_symbol(sym: str) -> Dict[str, object]:
    from quant.core import crypto_perp
    from quant.data import load_bars
    from quant.data.binance_metrics import get_open_interest

    d = load_bars(crypto_perp(sym, "bybit"), "15m", START, END)
    ends = d.index + pd.Timedelta(minutes=15)
    oi = get_open_interest(sym, pd.Timestamp(START) - pd.Timedelta(days=3), END)["sum_open_interest"]
    # OI snapshot at (or up to 15 min before) each bar end; older snapshots are treated as missing
    left = pd.DataFrame({"t": pd.DatetimeIndex(ends).astype("datetime64[ns, UTC]")})
    right = pd.DataFrame({"t": pd.DatetimeIndex(oi.index).astype("datetime64[ns, UTC]"), "oi": oi.to_numpy(float)})
    m = pd.merge_asof(left, right.sort_values("t"), on="t", direction="backward", tolerance=pd.Timedelta(minutes=15))
    oi_arr = m["oi"].to_numpy(float)
    fr = d["funding_rate"].dropna() if "funding_rate" in d else pd.Series(dtype=float)
    return {"bars": d, "ends": ends, "oi": oi_arr, "funding": fr}


def funding_pct_at(fr: pd.Series, ends: pd.DatetimeIndex, window_days: float = 30.0) -> np.ndarray:
    """Percentile of the latest print <= bar end within the prints of the previous 30 days (point-in-time)."""
    fr = fr.sort_index()
    vals = fr.to_numpy(float)
    t = fr.index
    pct = np.full(len(fr), np.nan)
    for k in range(len(fr)):
        m = (t > t[k] - pd.Timedelta(days=window_days)) & (t <= t[k])
        w = vals[m]
        if len(w) >= 10:
            pct[k] = 100.0 * ((w < vals[k]).sum() + 0.5 * (w == vals[k]).sum()) / len(w)
    s = pd.Series(pct, index=t)
    return s.reindex(s.index.union(ends)).sort_index().ffill().reindex(ends).to_numpy(float)


def scan_symbol(sym: str, data: Dict[str, object], mirror: float, active: bool) -> Tuple[List[Dict], Dict[str, int]]:
    d: pd.DataFrame = data["bars"]
    o, h, l, c, v = (d[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    ends = data["ends"]
    atr = wilder_atr_array(h, l, c, 14)
    vwap = rolling_vwap(h, l, c, v, VWAP_BARS)
    fpct = funding_pct_at(data["funding"], ends)
    oi = data["oi"]
    trades, rejects = [], {}
    busy_until = -1
    params = dict(POST_LIQ_PARAMS, mirror=mirror)
    for i in range(OI_LOOKBACK + 20, len(c) - 1):
        s = i - 1
        a = atr[s - 1]
        if not (np.isfinite(a) and h[s] - l[s] >= params["spike_atr_mult"] * a):
            continue  # cheap necessary condition (spike) before the full evaluation
        fp = None if not np.isfinite(fpct[i]) else float(fpct[i])
        z = oi_change_zscore(oi, s, OI_LOOKBACK)
        sig = detect_post_liq_reversal(o, h, l, c, v, i, fp, z, atr=atr, params=params)
        if not sig["triggered"]:
            rejects[sig["reject_reason"]] = rejects.get(sig["reject_reason"], 0) + 1
            continue
        if i <= busy_until:
            rejects["POSITION_OPEN"] = rejects.get("POSITION_OPEN", 0) + 1
            continue
        side = 1 if sig["side"] == "LONG" else -1
        end_pos = min(i + MAX_HOLD, len(c) - 1)
        kw = dict(fee_side=FEE_SIDE, slip_entry=SLIP_ENTRY, slip_exit=SLIP_EXIT, slip_stop=SLIP_STOP, end_reason="MAX_HOLD")
        if active:
            ex = simulate_active_exit(o, h, l, c, i, side, sig["entry"], sig["sl"], atr, end_pos, tp1_r=1.5, tp1_frac=0.5,
                                      trail_atr=1.5, time_stop_bars=TIME_STOP_BARS, time_stop_r=TIME_STOP_R, vwap=vwap, **kw)
        else:
            ex = simulate_active_exit(o, h, l, c, i, side, sig["entry"], sig["sl"], atr, end_pos, fixed_tp_r=2.0, **kw)
        if not ex.get("valid"):
            continue
        busy_until = i + ex["bars_held"]
        trades.append({"symbol": sym, "side": sig["side"], "entry_time": ends[i], "exit_time": ends[i + ex["bars_held"]],
                       "entry": sig["entry"], "sl": sig["sl"], "risk_pct": sig["risk"] / sig["entry"] * 100.0,
                       "ret": ex["ret"], "r_multiple": ex["r_multiple"], "exit_reason": ex["exit_reason"],
                       "tp1_hit": ex["tp1_hit"], "bars_held": ex["bars_held"], "funding_pct": fp, "oi_delta_z": z,
                       "spike_range_atr": sig["features"].get("spike_range_atr"), "pos": i})
    return trades, rejects


def random_control(trades: pd.DataFrame, data: Dict[str, Dict], seed: int = 0) -> pd.DataFrame:
    """Same number of trades per symbol and side, random entry bars, same risk %, same active exits."""
    rng = np.random.default_rng(seed)
    rows = []
    for t in trades.itertuples(index=False):
        d = data[t.symbol]["bars"]
        o, h, l, c, v = (d[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
        atr = wilder_atr_array(h, l, c, 14)
        vwap = rolling_vwap(h, l, c, v, VWAP_BARS)
        ends = data[t.symbol]["ends"]
        i = int(rng.integers(OI_LOOKBACK + 20, len(c) - MAX_HOLD - 1))
        side = 1 if t.side == "LONG" else -1
        entry = float(c[i])
        sl = entry * (1 - side * t.risk_pct / 100.0)
        ex = simulate_active_exit(o, h, l, c, i, side, entry, sl, atr, i + MAX_HOLD, tp1_r=1.5, tp1_frac=0.5, trail_atr=1.5,
                                  time_stop_bars=TIME_STOP_BARS, time_stop_r=TIME_STOP_R, vwap=vwap, fee_side=FEE_SIDE,
                                  slip_entry=SLIP_ENTRY, slip_exit=SLIP_EXIT, slip_stop=SLIP_STOP, end_reason="MAX_HOLD")
        rows.append({"symbol": t.symbol, "side": t.side, "entry_time": ends[i], "exit_time": ends[i + ex["bars_held"]],
                     "ret": ex["ret"], "r_multiple": ex["r_multiple"], "exit_reason": ex["exit_reason"], "tp1_hit": ex["tp1_hit"]})
    return pd.DataFrame(rows)


def run() -> Dict[str, object]:
    data = {}
    for s in SYMBOLS:
        data[s] = load_symbol(s)
        log.info("%s: %d barre, OI valido %.1f%%, funding print %d", s, len(data[s]["bars"]),
                 100 * np.isfinite(data[s]["oi"]).mean(), len(data[s]["funding"]))
    out = {"trades": {}, "rejects": {}}
    for name, cfg in VARIANTS.items():
        tr, rj = [], {}
        for s in SYMBOLS:
            t, r = scan_symbol(s, data[s], cfg["mirror"], cfg["active"])
            tr += t
            for k, n in r.items():
                rj[k] = rj.get(k, 0) + n
        out["trades"][name] = pd.DataFrame(tr).sort_values("entry_time").reset_index(drop=True) if tr else pd.DataFrame()
        out["rejects"][name] = rj
        log.info("%s: %d trade", name, len(tr))
    base = out["trades"]["a_spec_active"]
    out["trades"]["control_random"] = random_control(base, data) if len(base) else pd.DataFrame()
    btc = data["BTCUSDT"]["bars"]["close"]
    days = btc.index.normalize().tz_localize(None)
    out["bench_daily"] = btc.groupby(days).last().pct_change().fillna(0.0)
    return out
