"""Autopsy of the live journal (data/market_sentinel.db): where does profitability concentrate today?

Groups closed trades and evaluated shadow signals by strategy (engine), broker, NY / Rome hour, VIX bucket and macro
regime, and the lab candidate trades (table lab_strategy_trades) by strategy and exit reason.

    python -m quant.analyze_existing_journal [--db data/market_sentinel.db] [--out reports/JOURNAL_AUTOPSY.md]

Read-only. Run it on the Oracle host, where the real journal lives.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


def _ctx(raw) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


def _vix_bucket(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "n/a"
    return "<16" if v < 16 else ("16-20" if v < 20 else ("20-25" if v < 25 else ">=25"))


def _group_table(df: pd.DataFrame, by: str, ret: str) -> pd.DataFrame:
    def agg(g):
        r = g[ret].astype(float)
        wins, losses = r[r > 0], r[r <= 0]
        gl = -losses.sum()
        return pd.Series({"n": len(r), "win_rate": (r > 0).mean(), "mean": r.mean(), "sum": r.sum(),
                          "profit_factor": (wins.sum() / gl) if gl > 0 else np.nan})
    if df.empty or by not in df:
        return pd.DataFrame()
    return df.groupby(by, dropna=False).apply(agg, include_groups=False).sort_values("sum", ascending=False)


def _md(df: pd.DataFrame) -> str:
    """Markdown table without optional dependencies (tabulate may be missing on the server)."""
    cols = [df.index.name or ""] + [str(c) for c in df.columns]
    rows = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for k, r in df.iterrows():
        rows.append("| " + " | ".join([str(k)] + [f"{v:.4g}" if isinstance(v, (float, np.floating)) else str(v) for v in r]) + " |")
    return "\n".join(rows)


def load(db: Path) -> dict:
    con = sqlite3.connect(str(db))
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    out = {"tables": sorted(tables)}
    if "trade_journal" in tables:
        t = pd.read_sql_query("SELECT * FROM trade_journal WHERE status='CLOSED'", con)
        if len(t):
            ctx = t["entry_context"].map(_ctx)
            t["macro_bias"] = ctx.map(lambda c: c.get("macro_bias", "n/a"))
            t["vix_bucket"] = ctx.map(lambda c: _vix_bucket(c.get("vix")))
            opened = pd.to_datetime(t["opened_at"], utc=True, errors="coerce")
            t["hour_ny"] = opened.dt.tz_convert("America/New_York").dt.hour
            t["hour_rome"] = opened.dt.tz_convert("Europe/Rome").dt.hour
            t["ruleset"] = ctx.map(lambda c: c.get("ruleset_version", "pre-2026-11-26"))
        out["trades"] = t
    if "signal_shadows" in tables:
        s = pd.read_sql_query("SELECT * FROM signal_shadows WHERE status='EVALUATED'", con)
        if len(s):
            f = s["features_json"].map(_ctx)
            s["macro_bias"] = f.map(lambda c: c.get("macro_bias", "n/a"))
            created = pd.to_datetime(s["created_at"], utc=True, errors="coerce")
            s["hour_rome"] = created.dt.tz_convert("Europe/Rome").dt.hour
        out["shadows"] = s
    if "lab_strategy_trades" in tables:
        out["lab"] = pd.read_sql_query("SELECT * FROM lab_strategy_trades", con)
    con.close()
    return out


def report(db: Path) -> str:
    L: List[str] = [f"# Autopsia del journal `{db}`", ""]
    if not db.exists():
        return "\n".join(L + ["Database non trovato: eseguire lo script sul server Oracle, dove gira il bot.", ""])
    d = load(db)
    L.append(f"Tabelle: {', '.join(d['tables'])}")
    t, s, lab = d.get("trades"), d.get("shadows"), d.get("lab")
    nt = 0 if t is None else len(t)
    ns = 0 if s is None else len(s)
    nl = 0 if lab is None else len(lab)
    L += [f"Trade chiusi: {nt} | segnali shadow valutati: {ns} | trade candidati del lab: {nl}", ""]
    if nt == 0 and ns == 0 and nl == 0:
        L += ["**Il database non contiene trade chiusi né segnali valutati.** Nessuna conclusione possibile: il journal",
              "reale è sul server Oracle (volume persistente `/app/data`). Rieseguire lì lo script.", ""]
        return "\n".join(L)
    if nt:
        for by in ("engine", "broker", "macro_bias", "vix_bucket", "hour_ny", "hour_rome", "ruleset"):
            g = _group_table(t, by, "pnl_pct")
            if len(g):
                L += [f"## Trade chiusi per `{by}` (pnl_pct)", "", _md(g), ""]
    if ns:
        for by in ("engine", "reject_reason", "macro_bias", "hour_rome"):
            g = _group_table(s, by, "virtual_r")
            if len(g):
                L += [f"## Shadow valutati per `{by}` (virtual_r)", "", _md(g), ""]
    if nl:
        closed = lab[lab["status"] == "CLOSED"]
        for by in ("strategy", "exit_reason"):
            g = _group_table(closed, by, "pnl_pct")
            if len(g):
                L += [f"## Lab: trade chiusi per `{by}` (pnl_pct)", "", _md(g), ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/market_sentinel.db")
    ap.add_argument("--out")
    a = ap.parse_args()
    txt = report(Path(a.db))
    if a.out:
        Path(a.out).write_text(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
