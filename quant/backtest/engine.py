"""Backtester event-driven (segnale a close t -> esecuzione open t+1)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from quant.core import AssetSpec, interval_to_hours
from .costs import trade_costs
from .exits import ExitRules, simulate_trade, wilder_atr
from .metrics import compute_metrics


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series
    metrics: dict


class Ctx:
    """Array numpy + maschere di sessione per un simbolo."""

    def __init__(self, bars: pd.DataFrame, spec: AssetSpec, interval: str):
        self.bars, self.spec = bars, spec
        self.o, self.h, self.l, self.c = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.atr = wilder_atr(self.h, self.l, self.c, 14)
        n = len(bars)
        self.hours = interval_to_hours(interval)
        self.last_mask = None
        self.in_sess = np.ones(n, bool)
        if spec.session == "rth":
            et = bars.index.tz_convert("America/New_York")
            d = (et.year * 10000 + et.month * 100 + et.day).to_numpy()
            self.last_mask = np.r_[d[1:] != d[:-1], True]
            if self.hours < 24:
                mins = (et.hour * 60 + et.minute).to_numpy()
                self.in_sess = (mins >= 570) & (mins < 960)


def plan_trade(ctx: Ctx, t: int, side: int, rules: ExitRules):
    """Simula l'uscita di un ingresso all'open di t+1. None se non eseguibile. Indipendente dal size."""
    ei = t + 1
    if ei >= len(ctx.c) or not ctx.in_sess[ei] or (side < 0 and not ctx.spec.allow_short):
        return None
    entry = float(ctx.o[ei])
    lv = rules.levels(side, entry, ctx.atr[t])
    if lv is None:
        return None
    sl, tp, risk = lv
    xi, xp, reason = simulate_trade(ctx.o, ctx.h, ctx.l, ctx.c, ei, side, entry, sl, tp, rules,
                                    ctx.atr[t], ctx.last_mask)
    return dict(t=t, ei=ei, xi=xi, entry=entry, exit=xp, reason=reason, risk=risk, side=side)


def finish_trade(ctx: Ctx, pl: dict, qty: float, maker_entry: bool = False) -> dict:
    idx = ctx.bars.index
    side, entry, xp = pl["side"], pl["entry"], pl["exit"]
    cs = trade_costs(ctx.spec, side, entry, xp, qty, idx[pl["ei"]], idx[pl["xi"]], ctx.bars, maker_entry,
                     stop_exit=pl["reason"] == "SL")
    gross = side * qty * (xp - entry)
    net = gross - cs["total"]
    notional = qty * entry
    return dict(entry_ts=idx[pl["ei"]], exit_ts=idx[pl["xi"]], side=side, entry_price=entry, exit_price=xp,
                qty=qty, notional=notional, gross_pnl=gross, costs=cs["total"], net_pnl=net,
                ret_net=net / notional, R=net / (qty * pl["risk"]), reason=pl["reason"],
                bars_held=pl["xi"] - pl["ei"] + 1, fees=cs["fees"], slippage=cs["slippage"],
                funding=cs["funding"], borrow=cs["borrow"])


def periods_per_year(spec: AssetSpec, hours: float) -> float:
    if hours >= 24:
        return 365.0 / (hours / 24) if spec.session == "24/7" else 252.0 / (hours / 24)
    return spec.bars_per_year_factor / hours


def _run(universe, rules, interval, initial_equity, risk_per_trade, size_frac, maker_entry,
         allow_overlap, max_gross) -> BacktestResult:
    cands, ctxs = [], {}
    for order, (sym, (bars, sig, spec)) in enumerate(universe.items()):
        ctx = ctxs[sym] = Ctx(bars, spec, interval)
        s = sig.reindex(bars.index)
        side = s["side"].fillna(0).to_numpy()
        sf = s["size_frac"].to_numpy(float) if "size_frac" in s.columns else None
        busy = -1
        for t in np.flatnonzero(side != 0):
            if not allow_overlap and t < busy:
                continue
            pl = plan_trade(ctx, int(t), 1 if side[t] > 0 else -1, rules)
            if pl is None:
                continue
            busy = pl["xi"]
            f = float(sf[t]) if sf is not None and sf[t] == sf[t] and sf[t] > 0 else size_frac
            cands.append((bars.index[pl["ei"]], order, sym, pl, f))
    cands.sort(key=lambda x: (x[0], x[1]))
    rows, open_, realized = [], [], 0.0
    for ets, _, sym, pl, f in cands:
        still = []
        for r in open_:
            if r["exit_ts"] < ets:
                realized += r["net_pnl"]
            else:
                still.append(r)
        open_ = still
        eq = initial_equity + realized
        if eq <= 0:
            continue
        if risk_per_trade:
            notional = min(eq * risk_per_trade / pl["risk"] * pl["entry"], eq * 1.0)
        else:
            notional = eq * f
        if max_gross is not None:
            notional = min(notional, max_gross * eq - sum(r["notional"] for r in open_))
        if notional <= 1e-9 * eq:
            continue
        r = finish_trade(ctxs[sym], pl, notional / pl["entry"], maker_entry)
        r["symbol"] = sym
        rows.append(r)
        open_.append(r)
    trades = pd.DataFrame(rows)
    cols = ["entry_ts", "exit_ts", "side", "entry_price", "exit_price", "qty", "notional", "gross_pnl", "costs",
            "net_pnl", "ret_net", "R", "reason", "bars_held", "symbol", "fees", "slippage", "funding", "borrow"]
    if trades.empty:
        trades = pd.DataFrame(columns=cols)
    # equity mark-to-market ai close su indice unione
    union = None
    for bars, _, _ in universe.values():
        union = bars.index if union is None else union.union(bars.index)
    eqv = np.full(len(union), float(initial_equity))
    closes = {s: b["close"].reindex(union).ffill().to_numpy() for s, (b, _, _) in universe.items()}
    for r in rows:
        i0, i1 = union.searchsorted(r["entry_ts"]), union.searchsorted(r["exit_ts"])
        cl = closes[r["symbol"]]
        eqv[i0:i1] += r["side"] * r["qty"] * (cl[i0:i1] - r["entry_price"])
        eqv[i1:] += r["net_pnl"]
    equity = pd.Series(eqv, index=union, name="equity")
    spec0 = next(iter(universe.values()))[2]
    ppy = periods_per_year(spec0, interval_to_hours(interval))
    return BacktestResult(trades, equity, compute_metrics(trades, equity, ppy))


def run_backtest(bars, signals, spec, rules, interval, initial_equity=100_000, risk_per_trade=None,
                 size_frac=0.10, maker_entry=False, allow_overlap=False) -> BacktestResult:
    return _run({spec.symbol: (bars, signals, spec)}, rules, interval, initial_equity, risk_per_trade,
                size_frac, maker_entry, allow_overlap, None)


def run_portfolio(universe: Dict[str, Tuple[pd.DataFrame, pd.DataFrame, AssetSpec]], rules, interval,
                  initial_equity=100_000, risk_per_trade=None, size_frac=0.10, maker_entry=False,
                  max_gross_exposure=0.7) -> BacktestResult:
    return _run(universe, rules, interval, initial_equity, risk_per_trade, size_frac, maker_entry,
                False, max_gross_exposure)
