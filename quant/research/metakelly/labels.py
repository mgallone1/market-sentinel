"""Triple-barrier labels with session-bounded time barrier (US equities) or fixed horizon (crypto)."""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from services import market_calendar

FLATTEN_LEAD_MIN = 8.0


def equity_bar_end(idx: pd.DatetimeIndex, interval_min: float) -> pd.DatetimeIndex:
    """End time of each RTH bar: start + interval, capped at the session close (last bar is short)."""
    idx = pd.DatetimeIndex(idx)
    ends = []
    for t in idx:
        tny = t.tz_convert("America/New_York")
        b = market_calendar.session_bounds(tny.date())
        e = t + pd.Timedelta(minutes=interval_min)
        if b is not None:
            e = min(e, pd.Timestamp(b[1]).tz_convert(t.tz))
        ends.append(e)
    return pd.DatetimeIndex(ends)


def equity_time_barrier(idx: pd.DatetimeIndex, interval_min: float) -> np.ndarray:
    """For each bar i (entry at its end), position of the last bar of the SAME NY session whose end is
    <= session close - 8 min. Equals i when no forward bar fits (trade cannot be held)."""
    idx = pd.DatetimeIndex(idx)
    ends = equity_bar_end(idx, interval_min)
    ny_dates = np.array([t.tz_convert("America/New_York").date() for t in idx])
    out = np.arange(len(idx))
    cut_by_date: Dict = {}
    for d in set(ny_dates):
        b = market_calendar.session_bounds(d)
        cut_by_date[d] = (pd.Timestamp(b[1]) - pd.Timedelta(minutes=FLATTEN_LEAD_MIN)) if b else None
    last_ok: Dict = {}
    for j in range(len(idx)):
        cut = cut_by_date[ny_dates[j]]
        if cut is not None and ends[j] <= cut.tz_convert(ends[j].tz):
            last_ok[ny_dates[j]] = j
    for i in range(len(idx)):
        out[i] = max(i, last_ok.get(ny_dates[i], i))
    return out


def triple_barrier(
    high: np.ndarray, low: np.ndarray, close: np.ndarray,
    entry_pos: int, side: int, sl_pct: float, tp_pct: float, end_pos: int,
    cost_rt: float, stop_extra: float,
) -> Optional[Dict[str, float]]:
    """Label one trade entered at close[entry_pos]. SL checked before TP inside a bar.
    Returns None if there is no forward bar before the time barrier."""
    if end_pos <= entry_pos:
        return None
    e = float(close[entry_pos])
    sl, tp = sl_pct / 100.0, tp_pct / 100.0
    sl_px = e * (1 - sl) if side > 0 else e * (1 + sl)
    tp_px = e * (1 + tp) if side > 0 else e * (1 - tp)
    for j in range(entry_pos + 1, end_pos + 1):
        hit_sl = low[j] <= sl_px if side > 0 else high[j] >= sl_px
        hit_tp = high[j] >= tp_px if side > 0 else low[j] <= tp_px
        if hit_sl:
            return {"y": 0, "ret": -sl - cost_rt - stop_extra, "exit_pos": j, "outcome": "SL"}
        if hit_tp:
            return {"y": 1, "ret": tp - cost_rt, "exit_pos": j, "outcome": "TP"}
    mv = (close[end_pos] - e) / e * side
    return {"y": 0, "ret": float(mv - cost_rt), "exit_pos": end_pos, "outcome": "TIME"}
