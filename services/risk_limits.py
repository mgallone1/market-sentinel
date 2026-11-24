"""Pre-trade risk circuit breaker (adapted from day_trader/trader-risk/check.py).

Pure rules + small persisted state. Only ENTRIES go through check_entry();
exits/closes must never be routed here. Refuses rather than shrinks orders.
"""
import json
import os
import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

NYSE_HOLIDAYS = {
    "2026-01-01": "New Year's Day", "2026-01-19": "MLK Day", "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday", "2026-05-25": "Memorial Day", "2026-06-19": "Juneteenth",
    "2026-07-03": "Independence Day (observed)", "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day", "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day", "2027-01-18": "MLK Day", "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday", "2027-05-31": "Memorial Day", "2027-06-18": "Juneteenth (observed)",
    "2027-07-05": "Independence Day (observed)", "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day", "2027-12-24": "Christmas Day (observed)",
}


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


def _env_b(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "no", "off", "")


@dataclass
class RiskConfig:
    enabled: bool = True
    max_daily_loss_pct: float = 2.0
    max_trades_per_day: int = 6
    max_open_risk_pct: float = 3.0
    max_loss_per_trade_pct: float = 0.75
    min_reward_risk: float = 1.5
    require_stop: bool = True
    max_consec_losses: int = 4
    cooldown_min: int = 240
    fallback_stop_pct: float = 1.2  # stop assumed for open positions with no stop info
    alpaca_window: Tuple[int, int, int, int] = (9, 45, 15, 30)  # ET open h,m / close h,m
    state_path: str = "data/risk_state.json"

    @classmethod
    def from_env(cls) -> "RiskConfig":
        return cls(
            enabled=_env_b("RISK_ENABLED", True),
            max_daily_loss_pct=_env_f("RISK_MAX_DAILY_LOSS_PCT", 2.0),
            max_trades_per_day=int(_env_f("RISK_MAX_TRADES_PER_DAY", 6)),
            max_open_risk_pct=_env_f("RISK_MAX_OPEN_RISK_PCT", 3.0),
            max_loss_per_trade_pct=_env_f("RISK_MAX_LOSS_PER_TRADE_PCT", 0.75),
            min_reward_risk=_env_f("RISK_MIN_REWARD_RISK", 1.5),
            require_stop=_env_b("RISK_REQUIRE_STOP", True),
            max_consec_losses=int(_env_f("RISK_MAX_CONSEC_LOSSES", 4)),
            cooldown_min=int(_env_f("RISK_COOLDOWN_MIN", 240)),
            state_path=os.getenv("RISK_STATE_PATH", "data/risk_state.json"),
        )


# ------------------------------------------------------------------ time helpers

def _nth_sunday(year: int, month: int, n: int) -> _dt.date:
    d = _dt.date(year, month, 1)
    d += _dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + _dt.timedelta(weeks=n - 1)


def to_eastern(utc: _dt.datetime) -> _dt.datetime:
    """Naive New York wall time from a UTC datetime (US DST rule, no tz files)."""
    y = utc.year
    start = _dt.datetime.combine(_nth_sunday(y, 3, 2), _dt.time(7, 0))
    end = _dt.datetime.combine(_nth_sunday(y, 11, 1), _dt.time(6, 0))
    naive = utc.replace(tzinfo=None)
    return naive + _dt.timedelta(hours=-4 if start <= naive < end else -5)


def _utc(now: Optional[_dt.datetime]) -> _dt.datetime:
    if now is None:
        return _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=_dt.timezone.utc)
    return now.astimezone(_dt.timezone.utc)


def equity_window_check(cfg: RiskConfig, now: Optional[_dt.datetime]) -> Tuple[bool, str]:
    et = to_eastern(_utc(now))
    if et.weekday() >= 5:
        return False, "SESSION: weekend, no equity entries"
    hol = NYSE_HOLIDAYS.get(et.date().isoformat())
    if hol:
        return False, f"SESSION: NYSE holiday ({hol})"
    oh, om, ch, cm = cfg.alpaca_window
    t = et.time()
    if t < _dt.time(oh, om):
        return False, f"SESSION: before {oh:02d}:{om:02d} ET"
    if t > _dt.time(ch, cm):
        return False, f"SESSION: after {ch:02d}:{cm:02d} ET"
    return True, ""


# ------------------------------------------------------------------ state

class RiskState:
    """Per (UTC day, broker) record persisted atomically to a JSON file."""

    def __init__(self, path: str = "data/risk_state.json"):
        self.path = path
        self.data: Dict[str, Any] = {"days": {}}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("days"), dict):
                self.data = d
        except (OSError, ValueError):
            self.data = {"days": {}}

    def save(self) -> None:
        try:
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"[!] Risk state non salvato: {e}")

    def rec(self, broker: str, now: Optional[_dt.datetime] = None, equity: Optional[float] = None) -> Dict[str, Any]:
        """Today's record (created on rollover; streak/pause carried over)."""
        day = _utc(now).date().isoformat()
        days = self.data.setdefault("days", {})
        dr = days.setdefault(day, {})
        r = dr.get(broker)
        if r is None:
            prev = [(k, v[broker]) for k, v in days.items() if k < day and broker in v]
            carry = max(prev, key=lambda kv: kv[0])[1] if prev else {}
            r = {"start_equity": None, "realized_pnl": 0.0, "trades_opened": 0,
                 "consecutive_losses": int(carry.get("consecutive_losses", 0)),
                 "pause_until": carry.get("pause_until"), "notified": []}
            dr[broker] = r
            for k in sorted(days)[:-7]:  # prune
                days.pop(k, None)
            self.save()
        if r.get("start_equity") is None and equity and equity > 0:
            r["start_equity"] = float(equity)
            self.save()
        return r

    def should_notify(self, broker: str, reason_key: str, now: Optional[_dt.datetime] = None) -> bool:
        """True only the first time per day/broker/reason (dedupe)."""
        r = self.rec(broker, now)
        if reason_key in r["notified"]:
            return False
        r["notified"].append(reason_key)
        self.save()
        return True


def reason_key(reason: str) -> str:
    return reason.split(":", 1)[0].strip()


# ------------------------------------------------------------------ rules

def _risk_of(entry: float, stop: Optional[float], qty: float) -> float:
    return abs(entry - stop) * qty if stop else 0.0


def open_risk_usd(cfg: RiskConfig, open_positions: List[Dict[str, Any]]) -> float:
    """Sum of distance-to-stop x size. Positions: dicts with entry_price/size and optional stop_loss."""
    total = 0.0
    for p in open_positions or []:
        size = abs(float(p.get("size", 0) or 0))
        entry = float(p.get("entry_price", 0) or 0)
        stop = float(p.get("stop_loss", 0) or 0)
        if stop > 0 and entry > 0:
            total += abs(entry - stop) * size
        else:
            total += entry * size * cfg.fallback_stop_pct / 100.0
    return total


def check_entry(cfg: RiskConfig, state: RiskState, broker: str, equity: float,
                open_positions: List[Dict[str, Any]], entry_price: float,
                stop_price: Optional[float], take_profit_price: Optional[float],
                qty_or_notional: float, now: Optional[_dt.datetime] = None,
                is_notional: bool = False) -> Tuple[bool, str]:
    """Pre-trade gate for NEW entries only. Returns (allowed, reason)."""
    if not cfg.enabled:
        return True, ""
    now = _utc(now)
    broker = broker.upper()
    if not equity or equity <= 0 or not entry_price or entry_price <= 0:
        return False, "DATA: equity/price non validi"
    r = state.rec(broker, now, equity)
    start = r.get("start_equity") or equity

    if broker == "ALPACA":
        ok, why = equity_window_check(cfg, now)
        if not ok:
            return False, why

    pu = r.get("pause_until")
    if pu:
        try:
            until = _dt.datetime.fromisoformat(pu)
            if until.tzinfo is None:
                until = until.replace(tzinfo=_dt.timezone.utc)
            if now < until:
                return False, f"COOLDOWN: {r['consecutive_losses']} perdite consecutive, pausa fino {until:%H:%M} UTC"
        except ValueError:
            pass

    daily_pnl = min(equity - start, r.get("realized_pnl", 0.0))  # equity delta = realized+unrealized
    if daily_pnl <= -start * cfg.max_daily_loss_pct / 100.0:
        return False, f"DAILY_LOSS: {daily_pnl / start * 100:.2f}% <= -{cfg.max_daily_loss_pct}%"

    if r.get("trades_opened", 0) >= cfg.max_trades_per_day:
        return False, f"TRADES_PER_DAY: {r['trades_opened']} >= {cfg.max_trades_per_day}"

    if not stop_price or stop_price <= 0:
        if cfg.require_stop:
            return False, "NO_STOP: stop obbligatorio"
        return True, ""

    qty = qty_or_notional / entry_price if is_notional else qty_or_notional
    stop_dist = abs(entry_price - stop_price)
    loss = stop_dist * qty
    if loss > equity * cfg.max_loss_per_trade_pct / 100.0 + 1e-9:
        return False, f"TRADE_RISK: perdita a stop {loss / equity * 100:.2f}% > {cfg.max_loss_per_trade_pct}%"

    if take_profit_price and take_profit_price > 0 and stop_dist > 0:
        rr = abs(take_profit_price - entry_price) / stop_dist
        if rr + 1e-9 < cfg.min_reward_risk:
            return False, f"REWARD_RISK: R:R {rr:.2f} < {cfg.min_reward_risk}"

    total = open_risk_usd(cfg, open_positions) + loss
    if total > equity * cfg.max_open_risk_pct / 100.0 + 1e-9:
        return False, f"OPEN_RISK: rischio aperto {total / equity * 100:.2f}% > {cfg.max_open_risk_pct}%"
    return True, ""


def record_open(cfg: RiskConfig, state: RiskState, broker: str, equity: Optional[float] = None,
                now: Optional[_dt.datetime] = None) -> None:
    if not cfg.enabled:
        return
    r = state.rec(broker.upper(), now, equity)
    r["trades_opened"] = int(r.get("trades_opened", 0)) + 1
    state.save()


def record_close(cfg: RiskConfig, state: RiskState, broker: str, pnl: float,
                 now: Optional[_dt.datetime] = None) -> None:
    if not cfg.enabled:
        return
    now = _utc(now)
    r = state.rec(broker.upper(), now)
    r["realized_pnl"] = float(r.get("realized_pnl", 0.0)) + float(pnl)
    if pnl < 0:
        r["consecutive_losses"] = int(r.get("consecutive_losses", 0)) + 1
        if r["consecutive_losses"] >= cfg.max_consec_losses:
            r["pause_until"] = (now + _dt.timedelta(minutes=cfg.cooldown_min)).isoformat()
    elif pnl > 0:
        r["consecutive_losses"] = 0
    state.save()
