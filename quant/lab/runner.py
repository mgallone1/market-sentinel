"""Runner del laboratorio (paper only): esegue le strategie quando il loro cron e' scaduto."""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from quant.lab.base import Decision
from quant.lab.broker import PaperBroker, _iso


# ---------------- cron minimale (min hour dom month dow) ----------------
def _field(expr: str, lo: int, hi: int) -> set:
    out = set()
    for part in expr.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-"))
        else:
            a = int(part)
            b = hi if step != 1 else a
        out.update(range(a, b + 1, step))
    return out


def cron_matches(expr: str, dt: datetime) -> bool:
    f = expr.split()
    if len(f) != 5:
        raise ValueError(f"cron non valido: {expr!r}")
    mi, ho, dom, mon, dow = f
    dows = {d % 7 for d in _field(dow, 0, 7)}
    py_dow = (dt.isoweekday()) % 7           # 0=domenica
    dom_ok, dow_ok = dt.day in _field(dom, 1, 31), py_dow in dows
    if dom != "*" and dow != "*":
        day_ok = dom_ok or dow_ok            # semantica cron standard
    else:
        day_ok = dom_ok and dow_ok
    return dt.minute in _field(mi, 0, 59) and dt.hour in _field(ho, 0, 23) and dt.month in _field(mon, 1, 12) and day_ok


def _dt(t) -> datetime:
    if isinstance(t, str):
        t = datetime.fromisoformat(t.replace("Z", "+00:00"))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def is_due(expr: str, last_ts, now, max_scan_days: int = 400) -> bool:
    """True se almeno un minuto che combacia cade in (last_ts, now]. Mai eseguita => True."""
    now = _dt(now).replace(second=0, microsecond=0)
    if last_ts is None:
        return True
    t = _dt(last_ts).replace(second=0, microsecond=0)
    t = max(t, now - timedelta(days=max_scan_days)) + timedelta(minutes=1)
    while t <= now:
        if cron_matches(expr, t):
            return True
        t += timedelta(minutes=1)
    return False


# ---------------- runner ----------------
class LabRunner:
    def __init__(self, strategies, storage, data, broker: Optional[PaperBroker] = None):
        self.strategies = list(strategies)
        self.storage, self.data = storage, data
        self.broker = broker or PaperBroker(storage, data)

    def _run_strategy(self, s, now_utc) -> Dict[str, Any]:
        ts = _iso(now_utc)
        try:
            last = self.storage.last_run(s.name, s.version)
            self.broker.accrue(s, now_utc, last)
            d = s.decide(now_utc, self.data)
            self.storage.log_decision(d)
            fills = self.broker.rebalance(s, d, now_utc)
            mark = self.broker.mark(s, now_utc)
            self.storage.set_last_run(s.name, s.version, ts)
            return {"strategy": s.name, "ok": True, "fills": len(fills), "equity": mark["equity"], "note": d.note}
        except Exception as e:  # noqa: BLE001 - isolamento: una strategia non ferma le altre
            msg = f"ERROR {type(e).__name__}: {e}"
            print(f"[lab] {s.name}: {msg}\n{traceback.format_exc()}", file=sys.stderr)
            try:
                self.storage.log_decision(Decision(s.name, s.version, ts, [], note=msg))
            except Exception as e2:  # noqa: BLE001
                print(f"[lab] {s.name}: log errore fallito: {e2}", file=sys.stderr)
            return {"strategy": s.name, "ok": False, "error": msg}

    def run_due(self, now_utc) -> List[Dict[str, Any]]:
        out = []
        for s in self.strategies:
            try:
                due = is_due(s.schedule, self.storage.last_run(s.name, s.version), now_utc)
            except Exception as e:  # noqa: BLE001
                print(f"[lab] {s.name}: schedule non valido: {e}", file=sys.stderr)
                continue
            if due:
                out.append(self._run_strategy(s, now_utc))
        return out

    def run_once(self, name: Optional[str] = None, now_utc=None) -> List[Dict[str, Any]]:
        now = now_utc or datetime.now(timezone.utc)
        return [self._run_strategy(s, now) for s in self.strategies if name is None or s.name == name]


def _load_strategies() -> list:
    import importlib
    mod = importlib.import_module("quant.lab.strategies")
    for attr in ("all_strategies", "get_strategies", "build_all"):
        if hasattr(mod, attr):
            return list(getattr(mod, attr)())
    if hasattr(mod, "STRATEGIES"):
        return list(mod.STRATEGIES)
    raise RuntimeError("quant.lab.strategies deve esporre all_strategies() o STRATEGIES")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lab paper trading (nessun ordine reale)")
    ap.add_argument("--once", action="store_true", help="esegue subito (ignora il cron)")
    ap.add_argument("--strategy", help="solo questa strategia")
    ap.add_argument("--synthetic", action="store_true", help="dati sintetici (test)")
    ap.add_argument("--review", action="store_true", help="revisione settimanale e stampa")
    ap.add_argument("--now", help="ISO UTC (default adesso)")
    a = ap.parse_args(argv)
    from quant.lab.storage import make_storage
    now = _dt(a.now) if a.now else datetime.now(timezone.utc)
    storage = make_storage()
    if a.synthetic:
        from quant.lab.marketdata import SyntheticMarketData
        data = SyntheticMarketData()
    else:
        from quant.lab.marketdata import LiveMarketData
        data = LiveMarketData()
    strategies = _load_strategies()
    if a.review:
        from quant.lab.review import weekly_review
        print(weekly_review(storage, strategies, now))
        return 0
    runner = LabRunner(strategies, storage, data)
    res = runner.run_once(a.strategy, now) if a.once else runner.run_due(now)
    for r in res:
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
