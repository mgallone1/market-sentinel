"""Journal del laboratorio: SQLite (default) o Supabase (tabelle lab_*). Solo paper: nessun ordine reale."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from quant.lab.base import Decision

TABLES = ("decisions", "fills", "marks", "reviews", "positions", "cash", "runs")

# colonne e chiavi di conflitto (idempotenza)
CONFLICT = {
    "decisions": ["id"],
    "fills": ["ts", "strategy", "version", "key", "reason"],
    "marks": ["ts", "strategy", "version"],
    "reviews": ["ts", "strategy", "version"],
    "positions": ["strategy", "version", "key"],
    "cash": ["strategy", "version"],
    "runs": ["strategy", "version"],
}

SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, strategy TEXT, version TEXT, ts TEXT, note TEXT, targets_json TEXT);
CREATE TABLE IF NOT EXISTS fills(ts TEXT, strategy TEXT, version TEXT, key TEXT, qty REAL, price REAL, fee REAL,
  slippage REAL, reason TEXT, notional REAL DEFAULT 0, UNIQUE(ts, strategy, version, key, reason));
CREATE TABLE IF NOT EXISTS marks(ts TEXT, strategy TEXT, version TEXT, equity REAL, cash REAL, gross_exposure REAL,
  positions_json TEXT, UNIQUE(ts, strategy, version));
CREATE TABLE IF NOT EXISTS reviews(ts TEXT, strategy TEXT, version TEXT, period_from TEXT, period_to TEXT,
  metrics_json TEXT, lessons_text TEXT, flag TEXT, UNIQUE(ts, strategy, version));
CREATE TABLE IF NOT EXISTS positions(strategy TEXT, version TEXT, key TEXT, qty REAL, avg_price REAL,
  PRIMARY KEY(strategy, version, key));
CREATE TABLE IF NOT EXISTS cash(strategy TEXT, version TEXT, cash REAL, PRIMARY KEY(strategy, version));
CREATE TABLE IF NOT EXISTS runs(strategy TEXT, version TEXT, last_ts TEXT, PRIMARY KEY(strategy, version));
"""


def decision_id(strategy: str, version: str, ts: str) -> str:
    return hashlib.sha1(f"{strategy}|{version}|{ts}".encode()).hexdigest()[:16]


def instrument_to_dict(inst) -> Dict[str, Any]:
    return {"key": inst.key, "price_source": inst.price_source, "symbol": inst.symbol,
            "multiplier": inst.multiplier, "costs": asdict(inst.costs)}


def decision_row(d: Decision) -> Dict[str, Any]:
    targets = [{"key": t.instrument.key, "instrument": instrument_to_dict(t.instrument), "weight": float(t.weight),
                "reason": t.reason, "features": t.features} for t in d.targets]
    return {"id": decision_id(d.strategy, d.version, str(d.ts)), "strategy": d.strategy, "version": d.version,
            "ts": str(d.ts), "note": d.note, "targets_json": json.dumps(targets, default=str)}


class _Base:
    """Logica comune; i backend implementano _put / _select / _update_rows."""

    def _put(self, table: str, row: Dict[str, Any], replace: bool = True) -> None: raise NotImplementedError
    def _select(self, table: str, where: Dict[str, Any], limit: int) -> List[Dict[str, Any]]: raise NotImplementedError

    def log_decision(self, d: Decision) -> str:
        row = decision_row(d)
        self._put("decisions", row, replace=True)
        return row["id"]

    def log_fill(self, row: Dict[str, Any]) -> None:
        r = {"ts": "", "strategy": "", "version": "", "key": "", "qty": 0.0, "price": 0.0, "fee": 0.0,
             "slippage": 0.0, "reason": "", "notional": 0.0}
        r.update({k: v for k, v in row.items() if k in r})
        self._put("fills", r, replace=False)

    def log_mark(self, row: Dict[str, Any]) -> None:
        r = dict(row)
        if not isinstance(r.get("positions_json", ""), str):
            r["positions_json"] = json.dumps(r["positions_json"], default=str)
        self._put("marks", r, replace=True)

    def log_review(self, row: Dict[str, Any]) -> None:
        r = dict(row)
        for k in ("metrics_json",):
            if not isinstance(r.get(k, ""), str):
                r[k] = json.dumps(r[k], default=str)
        self._put("reviews", r, replace=True)

    def positions(self, strategy: str, version: str) -> Dict[str, Dict[str, float]]:
        rows = self._select("positions", {"strategy": strategy, "version": version}, 10000)
        return {r["key"]: {"qty": float(r["qty"]), "avg_price": float(r["avg_price"])}
                for r in rows if abs(float(r["qty"])) > 1e-12}

    def set_position(self, strategy: str, version: str, key: str, qty: float, avg_price: float) -> None:
        self._put("positions", {"strategy": strategy, "version": version, "key": key,
                                "qty": float(qty), "avg_price": float(avg_price)}, replace=True)

    def cash(self, strategy: str, version: str) -> Optional[float]:
        rows = self._select("cash", {"strategy": strategy, "version": version}, 1)
        return float(rows[0]["cash"]) if rows else None

    def set_cash(self, strategy: str, version: str, cash: float) -> None:
        self._put("cash", {"strategy": strategy, "version": version, "cash": float(cash)}, replace=True)

    def last_run(self, strategy: str, version: str) -> Optional[str]:
        rows = self._select("runs", {"strategy": strategy, "version": version}, 1)
        return rows[0]["last_ts"] if rows else None

    def set_last_run(self, strategy: str, version: str, ts: str) -> None:
        self._put("runs", {"strategy": strategy, "version": version, "last_ts": ts}, replace=True)

    def query(self, table: str, strategy: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Righe piu' recenti prima (ordine ts desc dove esiste)."""
        if table not in TABLES:
            raise ValueError(f"tabella sconosciuta: {table}")
        return self._select(table, {"strategy": strategy} if strategy else {}, limit)


class SQLiteStorage(_Base):
    def __init__(self, path: Optional[str] = None):
        self.path = str(path or os.getenv("LAB_DB_PATH") or "data/lab.db")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SQLITE_DDL)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _put(self, table, row, replace=True):
        cols = list(row)
        sql = (f"INSERT OR {'REPLACE' if replace else 'IGNORE'} INTO {table}({','.join(cols)}) "
               f"VALUES({','.join('?' * len(cols))})")
        c = self._conn()
        try:
            with c:
                c.execute(sql, [row[k] for k in cols])
        finally:
            c.close()

    def _select(self, table, where, limit):
        sql = f"SELECT * FROM {table}"
        if where:
            sql += " WHERE " + " AND ".join(f"{k}=?" for k in where)
        order = {"decisions": "ts DESC", "fills": "ts DESC, rowid DESC", "marks": "ts DESC", "reviews": "ts DESC",
                 "runs": "last_ts DESC"}.get(table)
        if order:
            sql += f" ORDER BY {order}"
        sql += " LIMIT ?"
        c = self._conn()
        try:
            return [dict(r) for r in c.execute(sql, [*where.values(), int(limit)]).fetchall()]
        finally:
            c.close()


class SupabaseStorage(_Base):
    """Stesse tabelle con prefisso lab_ (schema del client di services/supabase_service.py: public, tabelle prefissate)."""

    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        from supabase import create_client  # ImportError => fallback in make_storage
        self.client = create_client(url or os.environ["SUPABASE_URL"], key or os.environ["SUPABASE_KEY"])
        self.client.table("lab_runs").select("strategy").limit(1).execute()  # verifica raggiungibilita' / schema

    def _put(self, table, row, replace=True):
        self.client.table(f"lab_{table}").upsert(row, on_conflict=",".join(CONFLICT[table]),
                                                 ignore_duplicates=not replace).execute()

    def _select(self, table, where, limit):
        q = self.client.table(f"lab_{table}").select("*")
        for k, v in where.items():
            q = q.eq(k, v)
        order = {"decisions": "ts", "fills": "ts", "marks": "ts", "reviews": "ts", "runs": "last_ts"}.get(table)
        if order:
            q = q.order(order, desc=True)
        return list(q.limit(int(limit)).execute().data or [])


class ResilientStorage:
    """Delega al primario; al primo errore Supabase avvisa e passa a SQLite."""

    def __init__(self, primary, fallback: SQLiteStorage):
        self._cur, self._fb = primary, fallback

    def __getattr__(self, name):
        attr = getattr(self._cur, name)
        if not callable(attr):
            return attr

        def call(*a, **k):
            try:
                return getattr(self._cur, name)(*a, **k)
            except Exception as e:
                if self._cur is self._fb:
                    raise
                print(f"[lab] WARNING: Supabase errore ({e}); passo a SQLite {self._fb.path}", file=sys.stderr)
                self._cur = self._fb
                return getattr(self._cur, name)(*a, **k)
        return call


def make_storage():
    sqlite = lambda: SQLiteStorage()  # noqa: E731
    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY") and os.getenv("LAB_STORAGE", "").lower() != "sqlite":
        try:
            return ResilientStorage(SupabaseStorage(), sqlite())
        except Exception as e:
            print(f"[lab] WARNING: Supabase non disponibile ({e}); uso SQLite", file=sys.stderr)
    return sqlite()
