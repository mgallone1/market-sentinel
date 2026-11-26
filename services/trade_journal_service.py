import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4
from zoneinfo import ZoneInfo

from services.telemetry_features import TELEMETRY_V2_COLUMNS as TELEMETRY_V2_COLUMNS_SQL


def get_trade_journal_db_path() -> Path:
    """Determina il percorso persistente: volume Railway (/app/data) se disponibile, altrimenti data/market_sentinel.db."""
    railway_vol = Path("/app/data")
    if railway_vol.exists():
        return railway_vol / "market_sentinel.db"
    local_dir = Path(__file__).resolve().parent.parent / "data"
    local_dir.mkdir(parents=True, exist_ok=True)
    return local_dir / "market_sentinel.db"


ROME_TZ = ZoneInfo("Europe/Rome")


def _telemetry_v2_values(payload: Optional[Dict[str, Any]]) -> List[Optional[float]]:
    """Values of the telemetry v2 columns taken from a context/features dict (None if absent/invalid)."""
    from services.telemetry_features import TELEMETRY_V2_COLUMNS

    src = payload or {}
    out: List[Optional[float]] = []
    for col in TELEMETRY_V2_COLUMNS:
        try:
            v = src.get(col)
            v = float(v) if v is not None else None
            out.append(v if v is not None and v == v and v not in (float("inf"), float("-inf")) else None)
        except (TypeError, ValueError):
            out.append(None)
    return out


def _migrate_telemetry_v2(conn: sqlite3.Connection, table: str) -> None:
    """Idempotent additive migration: one REAL column per telemetry v2 field (NULL on old rows)."""
    from services.telemetry_features import TELEMETRY_V2_COLUMNS

    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col in TELEMETRY_V2_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} REAL;")


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    """Parsifica una stringa ISO-8601 (con o senza 'Z' / tz) in datetime timezone-aware."""
    if not value:
        return None
    try:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ROME_TZ)
        return dt
    except Exception:
        return None


def _parse_broker_ts(record: Dict[str, Any]) -> Optional[datetime]:
    """Estrae il timestamp di chiusura da un record Bybit (`updatedTime`) o Alpaca (`raw_time`)."""
    raw_ms = record.get("updatedTime")
    if raw_ms is not None and str(raw_ms).strip() != "":
        try:
            ts_val = float(raw_ms)
            if ts_val > 1e12:
                ts_val /= 1000.0
            if ts_val > 0:
                return datetime.fromtimestamp(ts_val, tz=timezone.utc).astimezone(ROME_TZ)
        except Exception:
            pass
    for key in ("raw_time", "closed_at", "timestamp"):
        dt = _parse_iso_dt(record.get(key))
        if dt is not None:
            return dt.astimezone(ROME_TZ)
    return None


def _normalize_position_side(broker: str, raw_side: Optional[str]) -> Optional[str]:
    """
    Mappa il side del record di chiusura broker al side originale della posizione (`LONG` | `SHORT`).
    Nota Bybit `get_closed_pnl`: `side` è il lato di chiusura (`Sell` chiude `LONG`, `Buy` chiude `SHORT`).
    Alpaca `get_recent_closed_trades`: `side` è già `LONG` o `SHORT`.
    """
    s = (raw_side or "").strip().upper()
    if not s or s == "UNKNOWN":
        return None
    if s in ("LONG", "SHORT"):
        return s
    b = (broker or "").strip().upper()
    if b == "BYBIT":
        if s == "SELL":
            return "LONG"
        if s == "BUY":
            return "SHORT"
    else:
        if s == "BUY":
            return "LONG"
        if s in ("SELL", "SELL_SHORT"):
            return "SHORT"
    return None


def _normalize_journal_side(raw_side: Optional[str]) -> Optional[str]:
    """Normalizza il side salvato su `trade_journal` (`BUY`/`LONG` -> `LONG`, `SELL`/`SHORT` -> `SHORT`)."""
    s = (raw_side or "").strip().upper()
    if s in ("BUY", "LONG"):
        return "LONG"
    if s in ("SELL", "SHORT", "SELL_SHORT"):
        return "SHORT"
    return None


class TradeJournalService:
    """
    Trade Journal & Causal Post-Mortem Intelligence Engine:
    1. Registra le condizioni contestuali esatte al momento dell'ingresso (Macro, Ciclo, CVD, OBI, Sentiment, Target, Context Key).
    2. Registra l'esito del trade alla chiusura, riconcilia le chiusure broker con i record OPEN evitando duplicati untracked.
    3. Traccia MFE/MAE, Shadow Signals per i segnali scartati/bloccati e report di learning audit.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path is not None else get_trade_journal_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT UNIQUE,
                    broker TEXT NOT NULL,           -- 'BYBIT' | 'ALPACA'
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,             -- 'BUY' | 'SELL' | 'LONG' | 'SHORT'
                    entry_price REAL NOT NULL,
                    notional_usd REAL NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    exit_price REAL,
                    pnl_usd REAL,
                    pnl_pct REAL,
                    close_reason TEXT,              -- 'TAKE_PROFIT' | 'STOP_LOSS' | 'RATCHET_BE' | 'RATCHET_LOCK' | 'MACRO_SHIELD' | 'EXCHANGE_EXIT' | 'MANUAL'
                    entry_context TEXT,             -- JSON: macro_bias, cycle_tempo, hurst_fld, cvd_ratio, rsi, obi_bias, sentinel_sentiment, sl_pct, tp_pct, atr_pct
                    post_mortem_analysis TEXT,      -- Sintesi diagnostica e lezione appresa
                    learned_lesson TEXT,
                    status TEXT DEFAULT 'OPEN'      -- 'OPEN' | 'CLOSED'
                );
            """)

            # Additive schema migration on existing trade_journal table
            existing_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(trade_journal)").fetchall()
            }
            additive_columns = [
                ("client_order_id", "TEXT"),
                ("engine", "TEXT DEFAULT 'INTRADAY_MOMENTUM'"),
                ("context_key", "TEXT"),
                ("mfe_pct", "REAL"),
                ("mae_pct", "REAL"),
                ("capture_eff", "REAL"),
                ("edge_ratio", "REAL"),
                ("bars_held", "INTEGER"),
                ("fees_usd", "REAL DEFAULT 0.0"),
                ("exit_eval_json", "TEXT"),
            ]
            for col_name, col_def in additive_columns:
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE trade_journal ADD COLUMN {col_name} {col_def};")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_symbol ON trade_journal(symbol);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_status ON trade_journal(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_client_order_id ON trade_journal(client_order_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_context_key ON trade_journal(context_key);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_engine ON trade_journal(engine);")

            # Shadow Signals table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signal_shadows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shadow_id TEXT UNIQUE,
                    broker TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    context_key TEXT NOT NULL,
                    reject_reason TEXT NOT NULL,
                    signal_price REAL NOT NULL,
                    sl_pct REAL NOT NULL,
                    tp_pct REAL NOT NULL,
                    features_json TEXT,
                    created_at TEXT NOT NULL,
                    evaluated_at TEXT,
                    status TEXT DEFAULT 'PENDING',
                    virtual_pnl_pct REAL,
                    virtual_r REAL,
                    mfe_pct REAL,
                    mae_pct REAL,
                    hit_outcome TEXT
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_shadows_status_created ON signal_shadows(status, created_at);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_shadows_context_key ON signal_shadows(context_key);"
            )

            # Telemetry v2 (orthogonal state variables): additive, idempotent, NULL on old rows
            _migrate_telemetry_v2(conn, "trade_journal")
            _migrate_telemetry_v2(conn, "signal_shadows")

            # Learning Audit table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learning_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    summary_text TEXT NOT NULL
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_audit_type_created ON learning_audit(report_type, created_at);"
            )
            conn.commit()

    def _unique_trade_id(self, conn: sqlite3.Connection, prefix: str, ts_ms: int) -> str:
        candidate = f"{prefix}_{ts_ms}"
        exists = conn.execute(
            "SELECT 1 FROM trade_journal WHERE trade_id = ? LIMIT 1", (candidate,)
        ).fetchone()
        if not exists:
            return candidate
        return f"{candidate}_{uuid4().hex[:6]}"

    def record_entry(
        self,
        broker: str,
        symbol: str,
        side: str,
        entry_price: float,
        notional_usd: float,
        context: Dict[str, Any],
        client_order_id: Optional[str] = None,
        engine: str = "INTRADAY_MOMENTUM",
        context_key: Optional[str] = None,
    ) -> str:
        """Registra una nuova operazione aperta congelando il contesto esatto e le metriche di setup."""
        now_dt = datetime.now(ROME_TZ)
        opened_at = now_dt.isoformat()
        ctx_copy = dict(context or {})
        eff_engine = str(engine or ctx_copy.get("engine") or "INTRADAY_MOMENTUM").upper()
        eff_context_key = context_key or ctx_copy.get("context_key")
        eff_client_order_id = client_order_id or ctx_copy.get("client_order_id")

        fallback_id = f"{broker.upper()}_{symbol}_{int(now_dt.timestamp() * 1000)}"
        try:
            with sqlite3.connect(self.db_path) as conn:
                trade_id = self._unique_trade_id(
                    conn, f"{broker.upper()}_{symbol}", int(now_dt.timestamp() * 1000)
                )
                tele_cols = ", ".join(TELEMETRY_V2_COLUMNS_SQL)
                tele_qs = ", ".join("?" for _ in TELEMETRY_V2_COLUMNS_SQL)
                conn.execute(
                    f"""
                    INSERT INTO trade_journal (
                        trade_id, broker, symbol, side, entry_price, notional_usd,
                        opened_at, entry_context, status, client_order_id, engine, context_key,
                        {tele_cols}
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, {tele_qs})
                    """,
                    (
                        trade_id,
                        broker.upper(),
                        symbol,
                        side.upper(),
                        float(entry_price),
                        float(notional_usd),
                        opened_at,
                        json.dumps(ctx_copy, ensure_ascii=False),
                        eff_client_order_id,
                        eff_engine,
                        eff_context_key,
                        *_telemetry_v2_values(ctx_copy),
                    ),
                )
                conn.commit()
            print(f"📖 [Trade Journal] Registrato ingresso {trade_id} ({symbol} {side} @ ${entry_price:.4f})")
            return trade_id
        except Exception as e:
            print(f"[!] Errore record_entry nel journal: {e}")
            return fallback_id

    def record_exit(
        self,
        broker: str,
        symbol: str,
        exit_price: float,
        pnl_usd: float,
        pnl_pct: float,
        close_reason: str,
        fees_usd: float = 0.0,
        bars_held: Optional[int] = None,
        closed_at_iso: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Chiude il trade nel journal e genera l'analisi post-mortem evitando spam di righe untracked."""
        now_dt = _parse_iso_dt(closed_at_iso) or datetime.now(ROME_TZ)
        closed_at = closed_at_iso or now_dt.isoformat()
        broker_u = broker.upper()
        fees_val = float(fees_usd or 0.0)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                row = cur.execute(
                    """
                    SELECT * FROM trade_journal
                    WHERE broker = ? AND symbol = ? AND status = 'OPEN'
                    ORDER BY opened_at DESC LIMIT 1
                    """,
                    (broker_u, symbol),
                ).fetchone()

                if not row:
                    # Verifica dedupe su 10 minuti prima di inserire un record untracked retroattivo
                    recent_untracked = cur.execute(
                        """
                        SELECT closed_at, pnl_usd FROM trade_journal
                        WHERE broker = ? AND symbol = ? AND status = 'CLOSED'
                          AND trade_id LIKE '%_untracked_%'
                        ORDER BY closed_at DESC LIMIT 10
                        """,
                        (broker_u, symbol),
                    ).fetchall()
                    for rec in recent_untracked:
                        rec_pnl = float(rec["pnl_usd"] or 0.0)
                        if abs(rec_pnl - float(pnl_usd)) <= 0.01:
                            rec_dt = _parse_iso_dt(rec["closed_at"])
                            if rec_dt is not None and abs((now_dt - rec_dt).total_seconds()) <= 600.0:
                                return None

                    trade_id = self._unique_trade_id(
                        conn, f"{broker_u}_{symbol}_untracked", int(now_dt.timestamp() * 1000)
                    )
                    cur.execute(
                        """
                        INSERT INTO trade_journal (
                            trade_id, broker, symbol, side, entry_price, notional_usd,
                            opened_at, closed_at, exit_price, pnl_usd, pnl_pct, close_reason,
                            post_mortem_analysis, learned_lesson, status, fees_usd, bars_held
                        )
                        VALUES (?, ?, ?, 'UNKNOWN', ?, 0.0, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED', ?, ?)
                        """,
                        (
                            trade_id,
                            broker_u,
                            symbol,
                            float(exit_price),
                            closed_at,
                            closed_at,
                            float(exit_price),
                            float(pnl_usd),
                            float(pnl_pct),
                            close_reason,
                            f"Chiusura su {symbol} in {close_reason} ({pnl_pct:+.2f}%)",
                            "Tracciamento automatico retroattivo",
                            fees_val,
                            bars_held,
                        ),
                    )
                    conn.commit()
                    return None

                trade_id = row["trade_id"]
                entry_ctx = json.loads(row["entry_context"] or "{}")

                analysis, lesson = self._generate_post_mortem(
                    symbol=symbol,
                    side=row["side"],
                    pnl_usd=float(pnl_usd),
                    pnl_pct=float(pnl_pct),
                    close_reason=close_reason,
                    context=entry_ctx,
                )

                cur.execute(
                    """
                    UPDATE trade_journal
                    SET closed_at = ?, exit_price = ?, pnl_usd = ?, pnl_pct = ?,
                        close_reason = ?, post_mortem_analysis = ?, learned_lesson = ?,
                        status = 'CLOSED', fees_usd = ?, bars_held = COALESCE(?, bars_held)
                    WHERE trade_id = ?
                    """,
                    (
                        closed_at,
                        float(exit_price),
                        float(pnl_usd),
                        float(pnl_pct),
                        close_reason,
                        analysis,
                        lesson,
                        fees_val,
                        bars_held,
                        trade_id,
                    ),
                )
                conn.commit()

                print(f"🎓 [Post-Mortem Engine] Trade {trade_id} analizzato: {lesson}")
                return {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "pnl_usd": float(pnl_usd),
                    "pnl_pct": float(pnl_pct),
                    "fees_usd": fees_val,
                    "analysis": analysis,
                    "lesson": lesson,
                }
        except Exception as e:
            print(f"[!] Errore record_exit nel journal: {e}")
            return None

    def deduplicate_legacy_untracked(self) -> int:
        """
        Rimuove in sicurezza i duplicati `*_untracked_*` (es. ALPACA_*_untracked_*)
        che condividono identico `(broker, symbol, round(pnl_usd, 2), substr(closed_at, 1, 16))`,
        preservando sempre la riga arricchita più vecchia (o la prima untracked se non esistono righe arricchite)
        e senza mai eliminare trade separati legittimi.
        """
        deleted = 0
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT id, trade_id, broker, symbol, pnl_usd, closed_at, entry_context
                    FROM trade_journal
                    WHERE status = 'CLOSED' AND closed_at IS NOT NULL AND pnl_usd IS NOT NULL
                    ORDER BY id ASC
                    """
                ).fetchall()

                groups: Dict[Tuple[str, str, float, str], List[sqlite3.Row]] = {}
                for r in rows:
                    key = (
                        str(r["broker"] or "").upper(),
                        str(r["symbol"] or ""),
                        round(float(r["pnl_usd"] or 0.0), 2),
                        str(r["closed_at"] or "")[:16],
                    )
                    groups.setdefault(key, []).append(r)

                ids_to_delete: List[int] = []
                for grp in groups.values():
                    if len(grp) <= 1:
                        continue
                    grp_sorted = sorted(
                        grp,
                        key=lambda r: (
                            1 if "_untracked_" in str(r["trade_id"] or "") else 0,
                            0 if (r["entry_context"] or "").strip() not in ("", "{}", "null") else 1,
                            str(r["closed_at"] or ""),
                            int(r["id"]),
                        ),
                    )
                    for dup in grp_sorted[1:]:
                        if "_untracked_" in str(dup["trade_id"] or ""):
                            ids_to_delete.append(int(dup["id"]))

                if ids_to_delete:
                    placeholders = ",".join("?" for _ in ids_to_delete)
                    cur = conn.execute(
                        f"DELETE FROM trade_journal WHERE id IN ({placeholders})",
                        ids_to_delete,
                    )
                    deleted = cur.rowcount if cur.rowcount >= 0 else len(ids_to_delete)
                    conn.commit()
        except Exception as e:
            print(f"[!] Errore deduplicate_legacy_untracked: {e}")
        return deleted

    def reconcile_closed_trades_with_open_journal(
        self, broker: str, closed_trades: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Riconcilia le chiusure restituite dal broker (Bybit `get_closed_pnl` / Alpaca `get_recent_closed_trades`)
        con le righe `'OPEN'` presenti in `trade_journal`.
        - Transiziona ciascuna riga OPEN abbinata a `'CLOSED'` una sola volta (idempotente).
        - Restituisce la lista dei trade appena chiusi così il chiamante può invocare `_risk_closed()` una sola volta.
        """
        if not closed_trades:
            return []
        broker_u = broker.strip().upper()
        transitioned: List[Dict[str, Any]] = []

        # Ordina cronologicamente dal più vecchio al più recente per abbinamento FIFO coerente
        sortable: List[Tuple[float, Dict[str, Any]]] = []
        for c in closed_trades:
            cdt = _parse_broker_ts(c)
            sortable.append((cdt.timestamp() if cdt else 0.0, c))
        sortable.sort(key=lambda item: item[0])

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()

                open_rows = cur.execute(
                    """
                    SELECT * FROM trade_journal
                    WHERE broker = ? AND status = 'OPEN'
                    ORDER BY opened_at ASC, id ASC
                    """,
                    (broker_u,),
                ).fetchall()
                if not open_rows:
                    return []

                used_open_ids = set()

                for _, c in sortable:
                    sym = str(c.get("symbol") or "").strip().upper()
                    if not sym:
                        continue
                    closed_dt = _parse_broker_ts(c)
                    if closed_dt is None:
                        continue
                    target_side = _normalize_position_side(broker_u, c.get("side"))

                    entry_p = float(c.get("avgEntryPrice") or c.get("entry_price") or 0.0)
                    matched_row = None
                    best_score = None

                    for r in open_rows:
                        if r["id"] in used_open_ids:
                            continue
                        if str(r["symbol"] or "").strip().upper() != sym:
                            continue
                        row_side = _normalize_journal_side(r["side"])
                        if target_side and row_side and row_side != target_side:
                            continue
                        opened_dt = _parse_iso_dt(r["opened_at"])
                        if opened_dt is not None and closed_dt.timestamp() < opened_dt.timestamp() - 0.001:
                            continue

                        # Preferisci corrispondenza prezzo più vicina e apertura più vecchia compatibile
                        row_entry = float(r["entry_price"] or 0.0)
                        price_diff = (
                            abs(row_entry - entry_p) / row_entry
                            if (row_entry > 0 and entry_p > 0)
                            else 0.0
                        )
                        score = (price_diff, opened_dt.timestamp() if opened_dt else 0.0, int(r["id"]))
                        if best_score is None or score < best_score:
                            best_score = score
                            matched_row = r

                    if matched_row is None:
                        continue

                    used_open_ids.add(matched_row["id"])
                    trade_id = matched_row["trade_id"]
                    entry_ctx = json.loads(matched_row["entry_context"] or "{}")
                    row_side = _normalize_journal_side(matched_row["side"]) or target_side or "UNKNOWN"

                    exit_p = float(c.get("avgExitPrice") or c.get("exit_price") or 0.0)
                    pnl_usd = float(
                        c.get("closedPnl")
                        if c.get("closedPnl") is not None
                        else (c.get("pnl") if c.get("pnl") is not None else 0.0)
                    )
                    fees_usd = (
                        float(c.get("openFee") or 0.0)
                        + float(c.get("closeFee") or 0.0)
                        + float(c.get("fees_usd") or 0.0)
                    )
                    invested = float(c.get("cumEntryValue") or 0.0) or (
                        float(c.get("closedSize") or c.get("qty") or 0.0) * entry_p
                    )
                    if invested <= 0:
                        invested = float(matched_row["notional_usd"] or 0.0)

                    if c.get("pnl_pct") is not None:
                        pnl_pct = float(c["pnl_pct"])
                    elif invested > 0:
                        pnl_pct = (pnl_usd / invested) * 100.0
                    elif entry_p > 0 and exit_p > 0:
                        if row_side == "SHORT":
                            pnl_pct = ((entry_p - exit_p) / entry_p) * 100.0
                        else:
                            pnl_pct = ((exit_p - entry_p) / entry_p) * 100.0
                    else:
                        pnl_pct = 0.0

                    # Determina close_reason deterministico
                    explicit_reason = c.get("close_reason")
                    if explicit_reason:
                        close_reason = str(explicit_reason).upper()
                    else:
                        tp_pct = float(entry_ctx.get("tp_pct") or 0.0)
                        sl_pct = float(entry_ctx.get("sl_pct") or 0.0)
                        if tp_pct > 0 and pnl_pct >= tp_pct * 0.80:
                            close_reason = "TAKE_PROFIT"
                        elif sl_pct > 0 and pnl_pct <= -sl_pct * 0.75:
                            close_reason = "STOP_LOSS"
                        elif pnl_usd > 0 and tp_pct <= 0 and pnl_pct >= 2.0:
                            close_reason = "TAKE_PROFIT"
                        elif pnl_usd < 0 and sl_pct <= 0 and pnl_pct <= -0.8:
                            close_reason = "STOP_LOSS"
                        else:
                            close_reason = "EXCHANGE_EXIT"

                    if broker_u == "BYBIT" and "pnl_is_net" not in entry_ctx:
                        entry_ctx["pnl_is_net"] = True

                    analysis, lesson = self._generate_post_mortem(
                        symbol=sym,
                        side=row_side,
                        pnl_usd=pnl_usd,
                        pnl_pct=pnl_pct,
                        close_reason=close_reason,
                        context=entry_ctx,
                    )

                    closed_at_iso = closed_dt.astimezone(ROME_TZ).isoformat()
                    cur.execute(
                        """
                        UPDATE trade_journal
                        SET closed_at = ?, exit_price = ?, pnl_usd = ?, pnl_pct = ?,
                            close_reason = ?, post_mortem_analysis = ?, learned_lesson = ?,
                            status = 'CLOSED', fees_usd = ?, entry_context = ?
                        WHERE trade_id = ? AND status = 'OPEN'
                        """,
                        (
                            closed_at_iso,
                            exit_p,
                            pnl_usd,
                            pnl_pct,
                            close_reason,
                            analysis,
                            lesson,
                            fees_usd,
                            json.dumps(entry_ctx, ensure_ascii=False),
                            trade_id,
                        ),
                    )
                    if cur.rowcount == 1:
                        transitioned.append(
                            {
                                "trade_id": trade_id,
                                "broker": broker_u,
                                "symbol": sym,
                                "side": row_side,
                                "pnl_usd": pnl_usd,
                                "pnl_pct": pnl_pct,
                                "fees_usd": fees_usd,
                                "close_reason": close_reason,
                            }
                        )
                conn.commit()
        except Exception as e:
            print(f"[!] Errore reconcile_closed_trades_with_open_journal ({broker_u}): {e}")
        return transitioned

    def record_shadow_signal(
        self,
        broker: str,
        symbol: str,
        side: str,
        engine: str,
        context_key: str,
        reject_reason: str,
        signal_price: float,
        sl_pct: float,
        tp_pct: float,
        features: Dict[str, Any],
    ) -> Optional[str]:
        """Registra un segnale scartato/bloccato in `signal_shadows` con cooldown di dedupe di 15 minuti."""
        now_dt = datetime.now(ROME_TZ)
        broker_u = broker.upper()
        side_u = side.upper()
        engine_u = engine.upper()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                recent = conn.execute(
                    """
                    SELECT created_at FROM signal_shadows
                    WHERE broker = ? AND symbol = ? AND side = ? AND engine = ? AND reject_reason = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (broker_u, symbol, side_u, engine_u, reject_reason),
                ).fetchone()
                if recent:
                    rec_dt = _parse_iso_dt(recent["created_at"])
                    if rec_dt is not None and (now_dt - rec_dt).total_seconds() < 900.0:
                        return None

                shadow_id = f"SHD_{broker_u}_{symbol}_{int(now_dt.timestamp() * 1000)}_{uuid4().hex[:6]}"
                tele_cols = ", ".join(TELEMETRY_V2_COLUMNS_SQL)
                tele_qs = ", ".join("?" for _ in TELEMETRY_V2_COLUMNS_SQL)
                conn.execute(
                    f"""
                    INSERT INTO signal_shadows (
                        shadow_id, broker, symbol, side, engine, context_key,
                        reject_reason, signal_price, sl_pct, tp_pct, features_json,
                        created_at, status, {tele_cols}
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', {tele_qs})
                    """,
                    (
                        shadow_id,
                        broker_u,
                        symbol,
                        side_u,
                        engine_u,
                        context_key,
                        reject_reason,
                        float(signal_price),
                        float(sl_pct),
                        float(tp_pct),
                        json.dumps(features or {}, ensure_ascii=False),
                        now_dt.isoformat(),
                        *_telemetry_v2_values(features),
                    ),
                )
                conn.commit()
                return shadow_id
        except Exception as e:
            print(f"[!] Errore record_shadow_signal: {e}")
            return None

    def get_pending_mfe_trades(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Restituisce i trade chiusi in attesa di valutazione MFE/MAE sul path OHLCV."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM trade_journal
                WHERE status = 'CLOSED'
                  AND mfe_pct IS NULL
                  AND exit_price > 0
                  AND entry_price > 0
                ORDER BY closed_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_trade_path_eval(
        self,
        trade_id: str,
        mfe_pct: float,
        mae_pct: float,
        capture_eff: float,
        edge_ratio: float,
        bars_held: int,
        exit_eval: Dict[str, Any],
    ) -> bool:
        """Aggiorna le metriche MFE/MAE, efficienza di cattura e diagnostica di uscita su un trade chiuso."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.execute(
                    """
                    UPDATE trade_journal
                    SET mfe_pct = ?, mae_pct = ?, capture_eff = ?,
                        edge_ratio = ?, bars_held = ?, exit_eval_json = ?
                    WHERE trade_id = ?
                    """,
                    (
                        float(mfe_pct),
                        float(mae_pct),
                        float(capture_eff),
                        float(edge_ratio),
                        int(bars_held),
                        json.dumps(exit_eval or {}, ensure_ascii=False),
                        trade_id,
                    ),
                )
                conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            print(f"[!] Errore update_trade_path_eval: {e}")
            return False

    def get_pending_shadows(self, min_age_minutes: int = 90, limit: int = 30) -> List[Dict[str, Any]]:
        """Restituisce gli shadow signal `PENDING` abbastanza maturi (`>= min_age_minutes`) per essere valutati."""
        now_dt = datetime.now(ROME_TZ)
        min_age_sec = max(0, int(min_age_minutes)) * 60.0
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM signal_shadows
                WHERE status = 'PENDING'
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                cdt = _parse_iso_dt(r["created_at"])
                if cdt is None:
                    continue
                if (now_dt - cdt).total_seconds() >= min_age_sec:
                    out.append(dict(r))
                    if len(out) >= int(limit):
                        break
            return out

    def update_shadow_eval(
        self,
        shadow_id: str,
        virtual_pnl_pct: float,
        virtual_r: float,
        mfe_pct: float,
        mae_pct: float,
        hit_outcome: str,
    ) -> bool:
        """Aggiorna lo stato di un shadow signal a `EVALUATED` con l'esito virtuale."""
        now_iso = datetime.now(ROME_TZ).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.execute(
                    """
                    UPDATE signal_shadows
                    SET evaluated_at = ?, status = 'EVALUATED',
                        virtual_pnl_pct = ?, virtual_r = ?,
                        mfe_pct = ?, mae_pct = ?, hit_outcome = ?
                    WHERE shadow_id = ?
                    """,
                    (
                        now_iso,
                        float(virtual_pnl_pct),
                        float(virtual_r),
                        float(mfe_pct),
                        float(mae_pct),
                        str(hit_outcome),
                        shadow_id,
                    ),
                )
                conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            print(f"[!] Errore update_shadow_eval: {e}")
            return False

    def save_learning_audit(self, report_type: str, metrics: Dict[str, Any], summary_text: str) -> int:
        """Salva un report di self-audit statistico nella tabella `learning_audit`."""
        now_iso = datetime.now(ROME_TZ).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO learning_audit (created_at, report_type, metrics_json, summary_text)
                VALUES (?, ?, ?, ?)
                """,
                (
                    now_iso,
                    str(report_type),
                    json.dumps(metrics or {}, ensure_ascii=False),
                    str(summary_text),
                ),
            )
            conn.commit()
            return int(cur.lastrowid or 0)

    def get_latest_audit(self, report_type: str = "WEEKLY_AUDIT") -> Optional[Dict[str, Any]]:
        """Recupera il report di audit più recente per `report_type`."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM learning_audit
                WHERE report_type = ?
                ORDER BY id DESC LIMIT 1
                """,
                (str(report_type),),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["metrics"] = json.loads(d.get("metrics_json") or "{}")
            except Exception:
                d["metrics"] = {}
            return d

    def get_open_trade_ids(self) -> List[Dict[str, Any]]:
        """Restituisce l'elenco dei trade attualmente in stato `OPEN`."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT trade_id, broker, symbol, side, entry_price, notional_usd,
                       opened_at, client_order_id, engine, context_key
                FROM trade_journal
                WHERE status = 'OPEN'
                ORDER BY opened_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def _generate_post_mortem(
        self, symbol: str, side: str, pnl_usd: float, pnl_pct: float, close_reason: str, context: Dict[str, Any]
    ) -> tuple[str, str]:
        """Genera l'analisi quantitativa e la lezione appresa."""
        macro = context.get("macro_bias", "UNKNOWN")
        cycle = context.get("cycle_tempo", "LIBERO")

        if pnl_pct > 0:
            if "TAKE_PROFIT" in close_reason:
                analysis = f"Vittoria piena target (+{pnl_pct:.2f}%): eccellente sincronizzazione tra macro ({macro}) e spinta ciclica ({cycle})."
                lesson = "Setup modello A+: la confluenza tra ciclo e flusso ha portato all'espansione completa del range."
            elif "RATCHET" in close_reason or "LOCK" in close_reason:
                analysis = f"Profitto protetto (+{pnl_pct:.2f}%): il Ratchet Stop ha blindato il rendimento prima di un ritracciamento avverso del book."
                lesson = "Protezione del guadagno efficace: impedito che un trade vincente si trasformasse in perdita."
            else:
                analysis = f"Chiusura in utile (+{pnl_pct:.2f}%): rendimento catturato regolarmente a mercato."
                lesson = "Esecuzione disciplinata."
        else:
            if "STOP_LOSS" in close_reason:
                analysis = f"Stop Loss eseguito ({pnl_pct:.2f}%): inversione rapida di volatilità intraday contro la direzione iniziale ({side})."
                lesson = "Perdita controllata e limitata dall'ATR Stop Loss. Nessun danno al capitale primario."
            elif "MACRO_SHIELD" in close_reason:
                analysis = f"Chiusura preventiva protettiva ({pnl_pct:.2f}%): il Macro Trend Shield ha rilevato un'inversione dell'asset guida, tagliando il trade prima del collasso."
                lesson = "Disciplina di portafoglio: stop anticipato per evitare il drawdown da contro-trend strutturale."
            else:
                analysis = f"Uscita in contenimento perdita ({pnl_pct:.2f}%)."
                lesson = "Gestione del rischio applicata rigorosamente."

        return analysis, lesson

    def get_recent_insights(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Restituisce lo storico dei trade analizzati con lezioni apprese per la dashboard e Telegram."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM trade_journal
                WHERE status = 'CLOSED'
                ORDER BY closed_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_learning_stats(self) -> Dict[str, Any]:
        """Calcola le metriche di apprendimento aggregate (win rate per ciclo, impatto macro)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM trade_journal WHERE status = 'CLOSED'").fetchall()
            if not rows:
                return {
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "avg_win": 0.0,
                    "avg_loss": 0.0,
                    "lessons_count": 0,
                }

            wins = [float(r["pnl_pct"] or 0.0) for r in rows if (r["pnl_pct"] or 0.0) > 0]
            losses = [float(r["pnl_pct"] or 0.0) for r in rows if (r["pnl_pct"] or 0.0) <= 0]
            win_rate = (len(wins) / len(rows)) * 100 if rows else 0.0

            return {
                "total_trades": len(rows),
                "win_rate": round(win_rate, 1),
                "wins_count": len(wins),
                "losses_count": len(losses),
                "avg_win_pct": round(sum(wins) / len(wins), 2) if wins else 0.0,
                "avg_loss_pct": round(sum(losses) / len(losses), 2) if losses else 0.0,
                "lessons_count": len(rows),
            }

    def sync_historical_trades_from_broker(self, closed_list: List[Dict[str, Any]], broker: str = "BYBIT"):
        """Sincronizza e arricchisce i trade chiusi storici se non ancora presenti nel Journal."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                for c in reversed(closed_list):
                    sym = c.get("symbol")
                    side = str(c.get("side", "")).upper()
                    pnl = float(c.get("closedPnl", 0.0))
                    entry = float(c.get("avgEntryPrice", 0.0))
                    exit_p = float(c.get("avgExitPrice", 0.0))
                    invested = float(c.get("cumEntryValue", 0.0)) or (float(c.get("closedSize", 0.0)) * entry)
                    pct = (pnl / invested) * 100 if invested > 0 else 0.0
                    ts = int(c.get("updatedTime", 0))
                    dt = datetime.fromtimestamp(ts / 1000, tz=ROME_TZ) if ts else datetime.now(ROME_TZ)
                    dt_str = dt.isoformat()
                    trade_id = f"{broker}_{sym}_{ts}"
                    fee_usd = float(c.get("openFee", 0) or 0) + float(c.get("closeFee", 0) or 0)

                    if pnl >= 250.0:
                        close_reason = "TAKE_PROFIT"
                        analysis = f"Vittoria piena target (+{pct:.2f}%): eccellente sincronizzazione con la spinta direzionale e volumi istituzionali."
                        lesson = "Setup modello A+: la confluenza tra trend e momentum ha portato al target 1:3 pieno."
                    elif 0 < pnl < 250.0:
                        close_reason = "RATCHET_LOCK"
                        analysis = f"Profitto protetto (+{pct:.2f}%): lo stop dinamico ha blindato l'utile prima del riassorbimento del range."
                        lesson = "Protezione del guadagno riuscita: impedito il drawdown su inversione intraday."
                    elif -70.0 <= pnl <= 0:
                        close_reason = "MACRO_SHIELD"
                        analysis = f"Uscita protettiva a controllo rischio ({pct:.2f}%): chiusura anticipata su divergenza o cambio bias."
                        lesson = "Taglio tempestivo delle perdite: drawdown limitato a frazioni minime."
                    else:
                        close_reason = "STOP_LOSS"
                        if 0 <= dt.hour < 7:
                            analysis = f"Stop Loss notturno ({pct:.2f}%): falso breakout (fakeout) in fascia oraria a bassa liquidità con spread allargato."
                            lesson = "Regola appresa: elevare il filtro volumi notturni e inibire ingressi breakout dopo false partenze."
                        else:
                            analysis = f"Stop Loss eseguito ({pct:.2f}%): inversione rapida di volatilità intraday contro la direzione iniziale."
                            lesson = "Perdita controllata e contenuta dall'ATR Stop Loss. Nessun danno all'equity principale."

                    context = {
                        "historical_import": True,
                        "pnl_is_net": True,
                        "session_hour": dt.hour,
                        "invested_usd": invested,
                        "fee_usd": fee_usd,
                    }

                    cur.execute(
                        """
                        INSERT OR IGNORE INTO trade_journal (
                            trade_id, broker, symbol, side, entry_price, notional_usd,
                            opened_at, closed_at, exit_price, pnl_usd, pnl_pct,
                            close_reason, entry_context, post_mortem_analysis, learned_lesson,
                            status, fees_usd
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED', ?)
                        """,
                        (
                            trade_id,
                            broker.upper(),
                            sym,
                            side,
                            entry,
                            invested,
                            dt_str,
                            dt_str,
                            exit_p,
                            pnl,
                            pct,
                            close_reason,
                            json.dumps(context),
                            analysis,
                            lesson,
                            fee_usd,
                        ),
                    )

                conn.commit()
        except Exception as e:
            print(f"[!] Errore sync_historical_trades_from_broker: {e}")
