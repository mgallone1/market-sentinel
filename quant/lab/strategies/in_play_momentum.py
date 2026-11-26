"""ALPACA_IN_PLAY_MOMENTUM (lab paper, v1.1: stop at least 0.5 ATR — reports/PREREG_NEW_STRATEGIES_V1_1.md): trade only the US large caps with an institutional catalyst.

Rules (reports/PREREG_NEW_STRATEGIES.md §2, live code in services/strategy_engines_service.py §8b):
at 09:45 NY a name is In Play if RVOL(09:30-09:45 vs the same window of the previous 20 sessions) >= 2 and
(|gap| >= 1.5% or |residual vs SPY| > 2 sigma); top 2 by RVOL, otherwise no trade today. Entry: 15m ORB or first EMA9
pullback in the catalyst direction, from 09:50 to 30 minutes before the close (NYSE calendar, 13:00 early closes).
Exits: SL opposite side of the opening range capped at 1.5 ATR(5m); 50% at +1.5R and stop to breakeven; 1.5 ATR trail
to the forced close 8 minutes before the bell; time-stop after 45 minutes below +0.4R.
State is rebuilt from today's closed 5m bars at every run. Paper only.
Backtest: 22 trades on 40 Yahoo sessions -> NON VALUTABILE (reports/NEW_STRATEGIES_POTENTIAL_AUDIT.md).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd

from quant.core import COST_PRESETS
from quant.lab.base import Decision, Instrument, Target
from quant.lab.strategies import _journal
from quant.lab.strategies._util import closed_bars, utc
from services import market_calendar
from services.strategy_engines_service import (
    ENGINE_IN_PLAY_MOMENTUM,
    IN_PLAY_PARAMS,
    LAB_STRATEGY_VERSION,
    STRATEGY_RULESET_VERSION,
    in_play_entry,
    in_play_metrics,
    opening_window_stats,
    select_in_play,
    simulate_active_exit,
    wilder_atr_array,
)

SYMBOLS = ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "META", "GOOGL", "AMD"]
WEIGHT = 0.10
SLIP_SIDE, SLIP_STOP = 0.0003, 0.0006


def _cap(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})


def replay_day(bars: Dict[str, pd.DataFrame], day, now: pd.Timestamp) -> Tuple[Dict[str, Dict], List[Dict]]:
    """-> (open positions by symbol, journal rows) for session `day` using closed 5m bars up to `now`."""
    stats = {s: opening_window_stats(b) for s, b in bars.items()}
    if "SPY" not in stats or day not in stats["SPY"].index:
        return {}, []
    metrics = {s: in_play_metrics(stats[s], stats["SPY"], day) for s in SYMBOLS if s in stats and day in stats[s].index}
    picks = select_in_play(metrics)
    picked = {p["symbol"] for p in picks}
    rows, open_pos = [], {}
    base = {"strategy": ENGINE_IN_PLAY_MOMENTUM, "strategy_version": LAB_STRATEGY_VERSION,
            "ruleset_version": STRATEGY_RULESET_VERSION, "broker": "ALPACA_PAPER"}
    for s, m in metrics.items():  # qualified but ranked out of the top 2: logged as rejected
        if s in picked or m.get("rvol") is None or m["rvol"] < IN_PLAY_PARAMS["rvol_min"]:
            continue
        if any(q["symbol"] == s for q in select_in_play({s: m})):
            rows.append({**base, "trade_key": f"{ENGINE_IN_PLAY_MOMENTUM}|{s}|{day}", "symbol": s, "status": "REJECTED",
                         "signal_time": str(day), "reject_reason": "RANKED_OUT_TOP2", "rvol": m["rvol"],
                         "gap_pct": m.get("gap_pct"), "idio_ret": m.get("idio_ret"), "diagnostics": m})
    for p in picks:
        df = bars[p["symbol"]]
        ent = in_play_entry(df, day, p["side"])
        row = {**base, "trade_key": f"{ENGINE_IN_PLAY_MOMENTUM}|{p['symbol']}|{day}", "symbol": p["symbol"],
               "side": p["side"], "signal_time": str(day), "rvol": p["rvol"], "gap_pct": p.get("gap_pct"),
               "idio_ret": p.get("idio_ret"), "diagnostics": {"qualifier": p.get("qualifier"), "idio_z": p.get("idio_z")}}
        if not ent.get("triggered"):
            rows.append({**row, "status": "REJECTED", "reject_reason": ent.get("reject_reason", "NO_ENTRY")})
            continue
        o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
        atr = wilder_atr_array(h, l, c, 14)
        last = len(df) - 1
        end_pos = min(ent["end_pos"], last)
        sd = 1 if p["side"] == "LONG" else -1
        entry_t = df.index[ent["pos"]] + pd.Timedelta(minutes=5)
        row.update({"entry_time": entry_t.isoformat(), "entry_price": ent["entry"], "sl_price": ent["sl"],
                    "risk_pct": ent["risk"] / ent["entry"] * 100.0, "entry_type": ent["entry_type"]})
        if end_pos <= ent["pos"]:
            open_pos[p["symbol"]] = {"side": sd, "fraction": 1.0, "sl": ent["sl"]}
            rows.append({**row, "status": "OPEN", "remaining_fraction": 1.0})
            continue
        # the session's forced close (close - 8 min) is still ahead if the last closed bar ends before it
        b = market_calendar.session_bounds(day)
        flatten_cut = pd.Timestamp(b[1]).tz_convert("UTC") - pd.Timedelta(minutes=8)
        truncated = (df.index[last] + pd.Timedelta(minutes=5)) < flatten_cut
        ex = simulate_active_exit(o, h, l, c, ent["pos"], sd, ent["entry"], ent["sl"], atr, end_pos, tp1_r=1.5,
                                  tp1_frac=0.5, trail_atr=1.5, time_stop_bars=9, time_stop_r=0.4, fee_side=0.0,
                                  slip_entry=SLIP_SIDE, slip_exit=SLIP_SIDE, slip_stop=SLIP_STOP,
                                  end_reason="DATA_END" if truncated else "EOD_FORCE_CLOSE")
        if ex["exit_reason"] == "DATA_END":
            frac = ex["legs"][-1]["fraction"]
            open_pos[p["symbol"]] = {"side": sd, "fraction": frac, "sl": ent["sl"]}
            rows.append({**row, "status": "OPEN", "remaining_fraction": frac, "tp1_hit": ex["tp1_hit"]})
        else:
            rows.append({**row, "status": "CLOSED", "exit_reason": ex["exit_reason"], "tp1_hit": ex["tp1_hit"],
                         "exit_time": (df.index[ent["pos"] + ex["bars_held"]] + pd.Timedelta(minutes=5)).isoformat(),
                         "remaining_fraction": 0.0, "r_multiple": ex["r_multiple"], "pnl_pct": 100.0 * ex["ret"]})
    return open_pos, rows


class InPlayMomentum:
    name = "alpaca_in_play_momentum"
    version = LAB_STRATEGY_VERSION
    schedule = "*/5 13-21 * * 1-5"   # every 5 minutes in UTC hours covering the NYSE session (EST and EDT)
    capital = 100_000.0
    expected = None

    def __init__(self, symbols=None, journal_sink=None):
        self.symbols = list(symbols or SYMBOLS)
        self.journal_sink = journal_sink
        self.inst = {s: Instrument(f"ALPACA:{s}", "yahoo", s, COST_PRESETS["alpaca_equity"]) for s in self.symbols}

    def decide(self, now_utc, data) -> Decision:
        now = utc(now_utc)
        day = now.tz_convert("America/New_York").date()
        st = market_calendar.session_status(now)
        flat = [Target(self.inst[s], 0.0, "flat", {}) for s in self.symbols]
        if st.get("minutes_since_open") is None or st["minutes_since_open"] < 20:
            return Decision(self.name, self.version, now.isoformat(), flat,
                            note="fuori sessione NYSE o prima della chiusura della barra 09:45-09:50: nessuna posizione")
        try:
            bars = {s: _cap(closed_bars(data.bars("yahoo", s, "5m", 45, now), now, 5 / 60))
                    for s in self.symbols + ["SPY"]}
            pos, rows = replay_day(bars, day, now)
        except Exception as e:  # noqa: BLE001
            return Decision(self.name, self.version, now.isoformat(), flat, note=f"errore dati: {e}")
        _journal.record(rows, self.journal_sink)
        targets = []
        for s in self.symbols:
            p = pos.get(s)
            if p:
                targets.append(Target(self.inst[s], p["side"] * WEIGHT * p["fraction"],
                                      f"In Play {'LONG' if p['side'] > 0 else 'SHORT'}, frazione {p['fraction']:.2f}", p))
            else:
                targets.append(Target(self.inst[s], 0.0, "flat: non In Play o trade chiuso", {}))
        n_in_play = sum(1 for r in rows if r.get("status") in ("OPEN", "CLOSED"))
        return Decision(self.name, self.version, now.isoformat(), targets,
                        note=f"{len(pos)} posizioni aperte, {n_in_play} trade In Play oggi, {len(rows)} righe journal")
