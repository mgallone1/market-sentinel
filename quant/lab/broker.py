"""PaperBroker: esecuzione SIMULATA (nessun ordine reale) con fee/slippage/funding del CostModel."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pandas as pd

from quant.core import CostModel
from quant.lab.base import Decision, Instrument, Strategy
from quant.lab.storage import instrument_to_dict  # noqa: F401  (riesportato per comodita')

FUNDING_REASON, FINANCING_REASON = "FUNDING", "FINANCING"


def _iso(t) -> str:
    t = pd.Timestamp(t)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _inst_from_dict(d: Dict[str, Any]) -> Instrument:
    return Instrument(d["key"], d["price_source"], d["symbol"], CostModel(**d["costs"]), float(d.get("multiplier", 1.0)))


def trade_fee(costs: CostModel, qty: float, notional: float) -> float:
    fee = costs.taker_fee * notional
    if costs.per_share or costs.min_ticket:
        fee += max(costs.per_share * abs(qty), costs.min_ticket)
    return fee


class PaperBroker:
    def __init__(self, storage, data, no_trade_band: float = 0.02):
        self.storage, self.data, self.band = storage, data, no_trade_band
        self._known: Dict[tuple, Dict[str, Instrument]] = {}

    # ---- helper ----
    def _capital(self, strategy: Strategy) -> float:
        c = self.storage.cash(strategy.name, strategy.version)
        if c is None:
            c = float(strategy.capital)
            self.storage.set_cash(strategy.name, strategy.version, c)
        return c

    def _instruments(self, strategy: Strategy, decision: Optional[Decision] = None) -> Dict[str, Instrument]:
        """Strumenti noti: dalla decisione corrente e dalle decisioni passate (targets_json)."""
        out: Dict[str, Instrument] = dict(self._known.get((strategy.name, strategy.version), {}))
        for row in reversed(self.storage.query("decisions", strategy.name, 50)):
            if row.get("version") != strategy.version:
                continue
            try:
                for t in json.loads(row.get("targets_json") or "[]"):
                    out[t["key"]] = _inst_from_dict(t["instrument"])
            except Exception:  # noqa: BLE001
                continue
        if decision:
            for t in decision.targets:
                out[t.instrument.key] = t.instrument
            self._known.setdefault((strategy.name, strategy.version), {}).update(out)
        return out

    def _px(self, inst: Instrument, now) -> float:
        return float(self.data.last_price(inst.price_source, inst.symbol, now))

    def _equity(self, strategy, insts, now, cash=None):
        pos = self.storage.positions(strategy.name, strategy.version)
        cash = self._capital(strategy) if cash is None else cash
        eq, detail = cash, {}
        for key, p in pos.items():
            inst = insts.get(key)
            px = self._px(inst, now) if inst else p["avg_price"]
            val = p["qty"] * px * (inst.multiplier if inst else 1.0)
            eq += val
            detail[key] = {"qty": p["qty"], "price": px, "value": val}
        return eq, detail

    # ---- API ----
    def rebalance(self, strategy: Strategy, decision: Decision, now_utc) -> List[Dict[str, Any]]:
        sname, ver, ts = strategy.name, strategy.version, _iso(now_utc)
        insts = self._instruments(strategy, decision)
        cash = self._capital(strategy)
        pos = self.storage.positions(sname, ver)
        equity, _ = self._equity(strategy, insts, now_utc, cash)

        weights: Dict[str, float] = {k: 0.0 for k in pos}           # posizioni non piu' nel target => flat
        reasons: Dict[str, str] = {k: "uscita: assente dal target" for k in pos}
        for t in decision.targets:
            weights[t.instrument.key] = float(t.weight)
            reasons[t.instrument.key] = t.reason
        gross = sum(abs(w) for w in weights.values())
        scale_note = ""
        if gross > 1.0 + 1e-9:
            f = 1.0 / gross
            weights = {k: w * f for k, w in weights.items()}
            scale_note = f" [scaled x{f:.3f}: sum|w|={gross:.2f}>1]"

        fills: List[Dict[str, Any]] = []
        for key, w in weights.items():
            inst = insts.get(key)
            if inst is None:
                continue
            px = self._px(inst, now_utc)
            if px <= 0:
                continue
            mult = inst.multiplier
            cur = pos.get(key, {"qty": 0.0, "avg_price": 0.0})
            cur_w = cur["qty"] * px * mult / equity if equity > 0 else 0.0
            if abs(w - cur_w) < self.band and not (w == 0.0 and cur["qty"] != 0.0):
                continue
            if w == 0.0 and cur["qty"] == 0.0:
                continue
            tgt_qty = w * equity / (px * mult)
            dq = tgt_qty - cur["qty"]
            if abs(dq) < 1e-12:
                continue
            s = inst.costs.slippage_bps / 1e4
            exec_px = px * (1 + s) if dq > 0 else px * (1 - s)
            notional = abs(dq) * exec_px * mult
            fee = trade_fee(inst.costs, dq, notional)
            slip = abs(dq) * px * mult * s
            cash -= dq * exec_px * mult + fee
            new_qty = cur["qty"] + dq
            if abs(new_qty) < 1e-12:
                new_qty, avg = 0.0, 0.0
            elif cur["qty"] == 0 or (cur["qty"] > 0) != (new_qty > 0):
                avg = exec_px
            elif abs(new_qty) > abs(cur["qty"]):
                avg = (cur["avg_price"] * abs(cur["qty"]) + exec_px * abs(dq)) / abs(new_qty)
            else:
                avg = cur["avg_price"]
            self.storage.set_position(sname, ver, key, new_qty, avg)
            row = {"ts": ts, "strategy": sname, "version": ver, "key": key, "qty": dq, "price": exec_px, "fee": fee,
                   "slippage": slip, "reason": f"REBAL w={w:+.3f}: {reasons.get(key, '')}{scale_note}",
                   "notional": notional}
            self.storage.log_fill(row)
            fills.append(row)
        self.storage.set_cash(sname, ver, cash)
        return fills

    def accrue(self, strategy: Strategy, now_utc, since_utc) -> List[Dict[str, Any]]:
        """Funding dei perp (per ogni print in (since, now]) e borrow degli short azionari. Nessun costo sui long."""
        if since_utc is None:
            return []
        sname, ver = strategy.name, strategy.version
        now, since = pd.Timestamp(now_utc), pd.Timestamp(since_utc)
        now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
        since = since.tz_localize("UTC") if since.tzinfo is None else since.tz_convert("UTC")
        pos = self.storage.positions(sname, ver)
        if not pos or now <= since:
            return []
        insts = self._instruments(strategy)
        cash = self._capital(strategy)
        out: List[Dict[str, Any]] = []
        for key, p in pos.items():
            inst = insts.get(key)
            if inst is None or p["qty"] == 0:
                continue
            px = self._px(inst, now)
            value = p["qty"] * px * inst.multiplier           # firmato
            if inst.costs.apply_funding:
                days = max(2, int((now - since).total_seconds() // 86400) + 2)
                fs = self.data.funding(inst.symbol, days, now)
                fs = fs[(fs.index > since) & (fs.index <= now)]
                for t, rate in fs.items():
                    cost = value * float(rate)                # long paga se rate>0; short incassa
                    cash -= cost
                    row = {"ts": _iso(now), "strategy": sname, "version": ver, "key": key, "qty": 0.0, "price": px,
                           "fee": cost, "slippage": 0.0, "reason": f"{FUNDING_REASON} {_iso(t)} rate={float(rate):+.6f}",
                           "notional": abs(value)}
                    self.storage.log_fill(row)
                    out.append(row)
            elif p["qty"] < 0 and inst.costs.borrow_rate_annual > 0:
                cost = abs(value) * inst.costs.borrow_rate_annual * (now - since).total_seconds() / (365 * 86400)
                cash -= cost
                row = {"ts": _iso(now), "strategy": sname, "version": ver, "key": key, "qty": 0.0, "price": px,
                       "fee": cost, "slippage": 0.0, "reason": f"{FINANCING_REASON} borrow short",
                       "notional": abs(value)}
                self.storage.log_fill(row)
                out.append(row)
        self.storage.set_cash(sname, ver, cash)
        return out

    def mark(self, strategy: Strategy, now_utc) -> Dict[str, Any]:
        insts = self._instruments(strategy)
        cash = self._capital(strategy)
        equity, detail = self._equity(strategy, insts, now_utc, cash)
        gross = sum(abs(d["value"]) for d in detail.values())
        row = {"ts": _iso(now_utc), "strategy": strategy.name, "version": strategy.version, "equity": equity,
               "cash": cash, "gross_exposure": gross / equity if equity > 0 else 0.0,
               "positions_json": json.dumps(detail)}
        self.storage.log_mark(row)
        return row
