"""Historical backtest of ALPACA_IN_PLAY_MOMENTUM (pre-registered, reports/PREREG_NEW_STRATEGIES.md §2).

Data: Yahoo 5m (last ~60 days only) or, with `source="alpaca"` and ALPACA_API_KEY/ALPACA_SECRET_KEY in the
environment, the Alpaca market-data API v2 (IEX feed, multi-year 5m history) — the latter is the real test.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List

import pandas as pd

from services import market_calendar
from services.strategy_engines_service import (
    in_play_entry,
    in_play_metrics,
    opening_window_stats,
    select_in_play,
    simulate_active_exit,
    wilder_atr_array,
)

log = logging.getLogger(__name__)
SYMBOLS = ("NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "META", "GOOGL", "AMD")
SLIP_SIDE, SLIP_STOP = 0.0003, 0.0006
TIME_STOP_BARS, TIME_STOP_R = 9, 0.4
VARIANTS = {"a_active": True, "b_fixed": False}


def load_yahoo(symbols) -> Dict[str, pd.DataFrame]:
    import yfinance as yf

    out = {}
    for s in symbols:
        d = yf.download(s, period="60d", interval="5m", progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        d = d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        idx = pd.DatetimeIndex(d.index)
        d.index = idx.tz_localize("America/New_York").tz_convert("UTC") if idx.tz is None else idx.tz_convert("UTC")
        out[s] = d[~d.index.duplicated()].sort_index()
    return out


def load_alpaca(symbols, start: str, end: str, http_get=None) -> Dict[str, pd.DataFrame]:
    """5-minute bars from the Alpaca market-data API v2 (requires keys; IEX feed works on free accounts)."""
    import requests

    get = http_get or requests.get
    key, sec = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if not key or not sec:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY non impostate")
    hdr = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    out = {}
    for s in symbols:
        rows, token = [], None
        while True:
            params = {"timeframe": "5Min", "start": start, "end": end, "limit": 10000, "adjustment": "split",
                      "feed": os.environ.get("ALPACA_DATA_FEED", "iex")}
            if token:
                params["page_token"] = token
            r = get(f"https://data.alpaca.markets/v2/stocks/{s}/bars", headers=hdr, params=params, timeout=30)
            r.raise_for_status()
            js = r.json()
            rows += js.get("bars") or []
            token = js.get("next_page_token")
            if not token:
                break
        df = pd.DataFrame(rows)
        if df.empty:
            out[s] = df
            continue
        df.index = pd.to_datetime(df["t"], utc=True)
        out[s] = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})[
            ["Open", "High", "Low", "Close", "Volume"]].astype(float).sort_index()
    return out


def _simulate(df: pd.DataFrame, ent: Dict, side: str, active: bool) -> Dict:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    atr = wilder_atr_array(h, l, c, 14)
    sd = 1 if side == "LONG" else -1
    kw = dict(fee_side=0.0, slip_entry=SLIP_SIDE, slip_exit=SLIP_SIDE, slip_stop=SLIP_STOP, end_reason="EOD_FORCE_CLOSE")
    if active:
        return simulate_active_exit(o, h, l, c, ent["pos"], sd, ent["entry"], ent["sl"], atr, ent["end_pos"],
                                    tp1_r=1.5, tp1_frac=0.5, trail_atr=1.5, time_stop_bars=TIME_STOP_BARS,
                                    time_stop_r=TIME_STOP_R, **kw)
    return simulate_active_exit(o, h, l, c, ent["pos"], sd, ent["entry"], ent["sl"], atr, ent["end_pos"],
                                fixed_tp_r=2.0, **kw)


def _first_or_break_side(df: pd.DataFrame, day) -> str | None:
    """Control without the In Play filter: direction = first side of the 15m opening range broken by a 5m close."""
    ny = df.index.tz_convert("America/New_York")
    b = market_calendar.session_bounds(day)
    if b is None:
        return None
    sel = (ny >= pd.Timestamp(b[0])) & (ny < pd.Timestamp(b[1]))
    sub = df[sel]
    if len(sub) <= 3:
        return None
    hi, lo = sub["High"].iloc[:3].max(), sub["Low"].iloc[:3].min()
    for cl in sub["Close"].iloc[3:]:
        if cl > hi:
            return "LONG"
        if cl < lo:
            return "SHORT"
    return None


def run(source: str = "yahoo", start: str | None = None, end: str | None = None) -> Dict[str, object]:
    syms = list(SYMBOLS) + ["SPY"]
    bars = load_yahoo(syms) if source == "yahoo" else load_alpaca(syms, start, end)
    stats = {s: opening_window_stats(bars[s]) for s in syms}
    days = sorted(set(stats["SPY"].index))
    trades = {k: [] for k in VARIANTS}
    trades["control_no_filter"] = []
    trades["control_no_filter_fixed"] = []  # extra diagnostic (declared in the audit): exits ablation on the large sample
    selections: List[Dict] = []
    for day in days:
        metrics = {s: in_play_metrics(stats[s], stats["SPY"], day) for s in SYMBOLS if day in stats[s].index}
        if not metrics or all(m.get("rvol") is None for m in metrics.values()):
            continue  # warm-up: fewer than 20 previous sessions
        picks = select_in_play(metrics)
        selections.append({"date": str(day), "n_qualified": len(picks), "picks": [p["symbol"] for p in picks]})
        for p in picks:
            ent = in_play_entry(bars[p["symbol"]], day, p["side"])
            if not ent.get("triggered"):
                continue
            for name, active in VARIANTS.items():
                ex = _simulate(bars[p["symbol"]], ent, p["side"], active)
                if ex.get("valid"):
                    trades[name].append(_row(bars[p["symbol"]], p, ent, ex, day))
        for s in metrics:  # control: same entry/exit rules, every name, every day, no In Play filter
            side = _first_or_break_side(bars[s], day)
            if side is None:
                continue
            ent = in_play_entry(bars[s], day, side)
            if ent.get("triggered"):
                for key, active in (("control_no_filter", True), ("control_no_filter_fixed", False)):
                    ex = _simulate(bars[s], ent, side, active)
                    if ex.get("valid"):
                        trades[key].append(_row(bars[s], {"symbol": s, "side": side, **metrics[s]}, ent, ex, day))
    spy = bars["SPY"]["Close"]
    sd = spy.index.tz_convert("America/New_York").normalize().tz_localize(None)
    bench = spy.groupby(sd).last().pct_change().fillna(0.0)
    out = {"trades": {k: pd.DataFrame(v) for k, v in trades.items()}, "selections": selections,
           "bench_daily": bench, "n_sessions_evaluated": len(selections), "source": source,
           "period": [str(days[0]) if days else None, str(days[-1]) if days else None]}
    log.info("in play: %d sedute valutate, trade %s", len(selections), {k: len(v) for k, v in trades.items()})
    return out


def _row(df: pd.DataFrame, p: Dict, ent: Dict, ex: Dict, day) -> Dict:
    idx = df.index
    return {"symbol": p["symbol"], "side": p["side"], "date": str(day), "entry_time": idx[ent["pos"]] + pd.Timedelta(minutes=5),
            "exit_time": idx[ent["pos"] + ex["bars_held"]] + pd.Timedelta(minutes=5), "entry_type": ent["entry_type"],
            "entry": ent["entry"], "sl": ent["sl"], "ret": ex["ret"], "r_multiple": ex["r_multiple"],
            "exit_reason": ex["exit_reason"], "tp1_hit": ex["tp1_hit"], "bars_held": ex["bars_held"],
            "rvol": p.get("rvol"), "gap_pct": p.get("gap_pct"), "idio_ret": p.get("idio_ret"), "idio_z": p.get("idio_z")}
