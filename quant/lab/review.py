"""Revisione periodica: live vs attese della ricerca, lezioni in italiano, scorecard per /lab."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

MIN_PERIODS = 8
PERIOD_RULE = {"day": "D", "week": "W", "month": "M"}
PERIODS_PER_YEAR = {"day": 365, "week": 52, "month": 12}


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _marks(storage, name: str, version: str) -> pd.DataFrame:
    rows = [r for r in storage.query("marks", name, 100000) if r["version"] == version]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)


def period_returns(marks: pd.DataFrame, period: str, capital: float, now) -> pd.Series:
    """Rendimento per periodo CHIUSO (ultima equity del periodo vs fine periodo precedente / capitale iniziale)."""
    if marks.empty:
        return pd.Series(dtype="float64")
    eq = pd.Series(marks["equity"].values, index=marks["ts"].dt.tz_convert(None))
    per = eq.index.to_period(PERIOD_RULE[period])
    last = eq.groupby(per).last()
    last = last[[p.end_time.tz_localize("UTC") <= now for p in last.index]]
    if last.empty:
        return pd.Series(dtype="float64")
    prev = last.shift(1)
    prev.iloc[0] = capital
    return last / prev - 1.0


def compute_metrics(storage, strategy, now) -> Dict[str, Any]:
    now = _utc(now)
    exp = getattr(strategy, "expected", None)
    period = exp.period if exp else "week"
    capital = float(strategy.capital)
    marks = _marks(storage, strategy.name, strategy.version)
    rets = period_returns(marks, period, capital, now)
    n = int(len(rets))
    fills = [r for r in storage.query("fills", strategy.name, 100000) if r["version"] == strategy.version]
    trades = [f for f in fills if not f["reason"].startswith(("FUNDING", "FINANCING"))]
    fund = sum(f["fee"] for f in fills if f["reason"].startswith("FUNDING"))
    fin = sum(f["fee"] for f in fills if f["reason"].startswith("FINANCING"))
    fees = sum(f["fee"] for f in trades)
    slip = sum(f["slippage"] for f in trades)
    traded = sum(abs(f.get("notional") or abs(f["qty"] * f["price"])) for f in trades)
    m: Dict[str, Any] = {"period": period, "n_periods": n, "capital": capital, "fees": fees, "slippage": slip,
                         "funding": fund, "financing": fin, "n_trades": len(trades),
                         "turnover": traded / capital if capital else 0.0,
                         "avg_slippage_bps": (slip / traded * 1e4) if traded else None,
                         "equity": None, "cum_return": 0.0, "max_dd": 0.0, "sharpe": None, "mean": None, "z": None}
    if not marks.empty:
        eq = marks["equity"].astype(float)
        m["equity"] = float(eq.iloc[-1])
        m["cum_return"] = float(eq.iloc[-1] / capital - 1)
        m["max_dd"] = float((np.r_[capital, eq.values] / np.maximum.accumulate(np.r_[capital, eq.values]) - 1).min())
        m["from"], m["to"] = marks["ts"].iloc[0].isoformat(), marks["ts"].iloc[-1].isoformat()
    if n:
        m["mean"] = float(rets.mean())
    if n >= MIN_PERIODS:
        sd = float(rets.std(ddof=1))
        m["sharpe"] = float(rets.mean() / sd * np.sqrt(PERIODS_PER_YEAR[period])) if sd > 0 else None
        if exp and exp.std_period_return > 0:
            m["z"] = float((rets.mean() - exp.mean_period_return) / (exp.std_period_return / np.sqrt(n)))
    m["flag"] = "TOO_EARLY" if n < MIN_PERIODS else ("UNDERPERFORMING" if (m["z"] is not None and m["z"] < -2) else "OK")
    m["net_pnl"] = (m["equity"] - capital) if m["equity"] is not None else 0.0
    m["costs"] = fees + slip + fund + fin
    return m


def lessons(m: Dict[str, Any], strategy, now, storage) -> List[str]:
    out = []
    gross = m["net_pnl"] + m["costs"]
    if m["costs"] > 0 and gross > 0 and m["costs"] / gross > 1.0:
        out.append(f"costi pari al {m['costs'] / gross * 100:.0f}% del rendimento lordo: valutare ordini maker o frequenza minore")
    elif m["costs"] > 0 and gross <= 0 and m["n_trades"]:
        out.append(f"rendimento lordo non positivo ({gross:+.0f} USD) e costi {m['costs']:.0f} USD: l'edge non copre i costi")
    exp_bps = max((t.instrument.costs.slippage_bps for t in _last_targets(storage, strategy)), default=None)
    if m["avg_slippage_bps"] is not None and exp_bps is not None and m["avg_slippage_bps"] > exp_bps * 1.2:
        out.append(f"slippage medio misurato {m['avg_slippage_bps']:.1f} bps vs {exp_bps:.1f} previsti")
    recent = _utc(now) - pd.Timedelta(days=7)
    rows = [f for f in storage.query("fills", strategy.name, 100000) if f["version"] == strategy.version
            and not f["reason"].startswith(("FUNDING", "FINANCING")) and _utc(f["ts"]) > recent]
    if not rows:
        out.append("nessun trade nel periodo: regime OFF")
    if m["funding"] < 0:
        out.append(f"il funding ha reso {-m['funding']:.0f} USD (incassato)")
    elif m["funding"] > 0:
        out.append(f"il funding ha pesato {m['funding']:.0f} USD")
    if m["flag"] == "UNDERPERFORMING":
        out.append(f"rendimento medio live sotto le attese (z={m['z']:.1f}): rivedere le ipotesi della ricerca")
    if m["max_dd"] < -0.15:
        out.append(f"drawdown massimo {m['max_dd'] * 100:.0f}%: oltre la soglia di attenzione")
    if m["flag"] == "TOO_EARLY":
        out.append(f"solo {m['n_periods']} periodi su {MIN_PERIODS} minimi: nessuna conclusione statistica")
    return out


def _last_targets(storage, strategy):
    from quant.lab.broker import PaperBroker
    class _T:
        def __init__(self, i): self.instrument = i
    return [_T(i) for i in PaperBroker(storage, None)._instruments(strategy).values()]


def weekly_review(storage, strategies, now_utc) -> str:
    now = _utc(now_utc)
    blocks = [f"*Lab review* {now:%Y-%m-%d}"]
    for s in strategies:
        m = compute_metrics(storage, s, now)
        ls = lessons(m, s, now, storage)
        text = "\n".join(f"- {x}" for x in ls)
        storage.log_review({"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "strategy": s.name, "version": s.version,
                            "period_from": m.get("from", ""), "period_to": m.get("to", ""),
                            "metrics_json": json.dumps(m, default=str), "lessons_text": text, "flag": m["flag"]})
        f = lambda v, fmt: "n/d" if v is None else fmt.format(v)  # noqa: E731
        exp = getattr(s, "expected", None)
        lines = [f"*{s.name}* v{s.version} [{m['flag']}]",
                 f"Equity {f(m['equity'], '{:,.0f}')} / {m['capital']:,.0f} USD, ritorno {m['cum_return'] * 100:+.2f}%, "
                 f"maxDD {m['max_dd'] * 100:.1f}%",
                 f"Periodi ({m['period']}): {m['n_periods']}, media {f(m['mean'] and m['mean'] * 100, '{:+.2f}%')}"
                 + (f" vs attesa {exp.mean_period_return * 100:+.2f}%" if exp else "")
                 + f", Sharpe {f(m['sharpe'], '{:.2f}')}" + (f", z {m['z']:.1f}" if m["z"] is not None else ""),
                 f"Trade {m['n_trades']}, turnover {m['turnover']:.2f}x, fee {m['fees']:.1f}, slippage {m['slippage']:.1f}, "
                 f"funding {m['funding']:+.1f}, fin. {m['financing']:.1f}"]
        lines += [f"- {x}" for x in ls]
        blocks.append("\n".join(lines[:12]))
    return "\n\n".join(blocks)


def scorecard(storage, strategies: Optional[list] = None) -> str:
    rows = storage.query("marks", None, 100000)
    keys = sorted({(r["strategy"], r["version"]) for r in rows})
    if not keys:
        return "Lab: nessun dato ancora."
    cap = {(s.name, s.version): float(s.capital) for s in (strategies or [])}
    out = ["*Lab scorecard*"]
    for name, ver in keys:
        mk = sorted((r for r in rows if r["strategy"] == name and r["version"] == ver), key=lambda r: r["ts"])
        start = cap.get((name, ver), mk[0]["equity"])
        eq = mk[-1]["equity"]
        dec = [d for d in storage.query("decisions", name, 20) if d["version"] == ver]
        note = (dec[0]["note"] if dec else "") or "-"
        out.append(f"*{name}* v{ver}: equity {eq:,.0f} ({(eq / start - 1) * 100:+.2f}%) - {note[:80]}")
    return "\n".join(out)
