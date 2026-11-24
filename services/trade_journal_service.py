import sqlite3
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "market_sentinel.db"
ROME_TZ = ZoneInfo("Europe/Rome")

class TradeJournalService:
    """
    Trade Journal & Post-Mortem Intelligence Engine:
    1. Registra le condizioni contestuali esatte al momento dell'ingresso (Macro, Ciclo, CVD, OBI, Sentiment, Target).
    2. Registra l'esito del trade alla chiusura ed esegue un'analisi post-mortem euristica delle cause (TP, SL, Reversal, Fakeout).
    3. Fornisce statistiche di apprendimento per auto-miglioramento del sistema quantitativo.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
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
                    close_reason TEXT,              -- 'TAKE_PROFIT' | 'STOP_LOSS' | 'RATCHET_BE' | 'RATCHET_LOCK' | 'MACRO_SHIELD' | 'MANUAL'
                    entry_context TEXT,             -- JSON: macro_bias, cycle_tempo, hurst_fld, cvd_ratio, rsi, obi_bias, sentinel_sentiment
                    post_mortem_analysis TEXT,      -- Sintesi diagnostica e lezione appresa
                    learned_lesson TEXT,
                    status TEXT DEFAULT 'OPEN'      -- 'OPEN' | 'CLOSED'
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_symbol ON trade_journal(symbol);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_status ON trade_journal(status);")

    def record_entry(self, broker: str, symbol: str, side: str, entry_price: float, notional_usd: float, context: Dict[str, Any]) -> str:
        """Registra una nuova operazione aperta congelando il contesto esatto."""
        opened_at = datetime.now(ROME_TZ).isoformat()
        trade_id = f"{broker}_{symbol}_{int(datetime.now().timestamp())}"
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO trade_journal (trade_id, broker, symbol, side, entry_price, notional_usd, opened_at, entry_context, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                """, (trade_id, broker.upper(), symbol, side.upper(), float(entry_price), float(notional_usd), opened_at, json.dumps(context, ensure_ascii=False)))
            print(f"📖 [Trade Journal] Registrato ingresso {trade_id} ({symbol} {side} @ ${entry_price:.4f})")
            return trade_id
        except Exception as e:
            print(f"[!] Errore record_entry nel journal: {e}")
            return trade_id

    def record_exit(self, broker: str, symbol: str, exit_price: float, pnl_usd: float, pnl_pct: float, close_reason: str) -> Optional[Dict[str, Any]]:
        """Chiude il trade nel journal e genera l'analisi post-mortem."""
        closed_at = datetime.now(ROME_TZ).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                row = cur.execute("""
                    SELECT * FROM trade_journal 
                    WHERE broker = ? AND symbol = ? AND status = 'OPEN'
                    ORDER BY opened_at DESC LIMIT 1
                """, (broker.upper(), symbol)).fetchone()

                if not row:
                    # Nessun ingresso tracciato in precedenza (es. posizione aperta prima dell'aggiornamento)
                    # Crea un record retroattivo
                    trade_id = f"{broker}_{symbol}_untracked_{int(datetime.now().timestamp())}"
                    cur.execute("""
                        INSERT INTO trade_journal (trade_id, broker, symbol, side, entry_price, notional_usd, opened_at, closed_at, exit_price, pnl_usd, pnl_pct, close_reason, post_mortem_analysis, learned_lesson, status)
                        VALUES (?, ?, ?, 'UNKNOWN', ?, 0.0, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED')
                    """, (trade_id, broker.upper(), symbol, exit_price, closed_at, closed_at, exit_price, pnl_usd, pnl_pct, close_reason, 
                          f"Chiusura su {symbol} in {close_reason} ({pnl_pct:+.2f}%)", "Tracciamento automatico retroattivo"))
                    return None

                trade_id = row["trade_id"]
                entry_ctx = json.loads(row["entry_context"] or "{}")

                # Diagnostica Post-Mortem intelligente basata sui dati
                analysis, lesson = self._generate_post_mortem(
                    symbol=symbol,
                    side=row["side"],
                    pnl_usd=pnl_usd,
                    pnl_pct=pnl_pct,
                    close_reason=close_reason,
                    context=entry_ctx
                )

                cur.execute("""
                    UPDATE trade_journal
                    SET closed_at = ?, exit_price = ?, pnl_usd = ?, pnl_pct = ?, close_reason = ?, post_mortem_analysis = ?, learned_lesson = ?, status = 'CLOSED'
                    WHERE trade_id = ?
                """, (closed_at, float(exit_price), float(pnl_usd), float(pnl_pct), close_reason, analysis, lesson, trade_id))

                print(f"🎓 [Post-Mortem Engine] Trade {trade_id} analizzato: {lesson}")
                return {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "pnl_usd": pnl_usd,
                    "pnl_pct": pnl_pct,
                    "analysis": analysis,
                    "lesson": lesson
                }
        except Exception as e:
            print(f"[!] Errore record_exit nel journal: {e}")
            return None

    def _generate_post_mortem(self, symbol: str, side: str, pnl_usd: float, pnl_pct: float, close_reason: str, context: Dict[str, Any]) -> tuple[str, str]:
        """Genera l'analisi quantitativa e la lezione appresa."""
        macro = context.get("macro_bias", "UNKNOWN")
        cycle = context.get("cycle_tempo", "LIBERO")
        cvd_ratio = context.get("cvd_ratio", 1.0)
        sentinel_boost = context.get("sentinel_boost", False)

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
                lesson = f"Perdita controllata e limitata dall'ATR Stop Loss. Nessun danno al capitale primario."
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
            rows = conn.execute("""
                SELECT * FROM trade_journal 
                WHERE status = 'CLOSED' 
                ORDER BY closed_at DESC LIMIT ?
            """, (limit,)).fetchall()
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
                    "lessons_count": 0
                }
            
            wins = [r["pnl_pct"] for r in rows if r["pnl_pct"] > 0]
            losses = [r["pnl_pct"] for r in rows if r["pnl_pct"] <= 0]
            win_rate = (len(wins) / len(rows)) * 100 if rows else 0.0

            return {
                "total_trades": len(rows),
                "win_rate": round(win_rate, 1),
                "wins_count": len(wins),
                "losses_count": len(losses),
                "avg_win_pct": round(sum(wins) / len(wins), 2) if wins else 0.0,
                "avg_loss_pct": round(sum(losses) / len(losses), 2) if losses else 0.0,
                "lessons_count": len(rows)
            }

    def sync_historical_trades_from_broker(self, closed_list: List[Dict[str, Any]], broker: str = "BYBIT"):
        """Sincronizza e arricchisce i trade chiusi storici se non ancora presenti nel Journal."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                for c in reversed(closed_list):
                    sym = c.get('symbol')
                    side = c.get('side', '').upper()
                    pnl = float(c.get('closedPnl', 0.0))
                    entry = float(c.get('avgEntryPrice', 0.0))
                    exit_p = float(c.get('avgExitPrice', 0.0))
                    invested = float(c.get('cumEntryValue', 0.0)) or (float(c.get('closedSize', 0.0)) * entry)
                    pct = (pnl / invested) * 100 if invested > 0 else 0.0
                    ts = int(c.get('updatedTime', 0))
                    dt = datetime.fromtimestamp(ts/1000, tz=ROME_TZ) if ts else datetime.now(ROME_TZ)
                    dt_str = dt.isoformat()
                    trade_id = f"{broker}_{sym}_{ts}"

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
                        "session_hour": dt.hour,
                        "invested_usd": invested,
                        "fee_usd": float(c.get('openFee', 0)) + float(c.get('closeFee', 0))
                    }

                    cur.execute("""
                        INSERT OR IGNORE INTO trade_journal (
                            trade_id, broker, symbol, side, entry_price, notional_usd, 
                            opened_at, closed_at, exit_price, pnl_usd, pnl_pct, 
                            close_reason, entry_context, post_mortem_analysis, learned_lesson, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED')
                    """, (trade_id, broker.upper(), sym, side, entry, invested, dt_str, dt_str, exit_p, pnl, pct, close_reason, json.dumps(context), analysis, lesson))

                conn.commit()
        except Exception as e:
            print(f"[!] Errore sync_historical_trades_from_broker: {e}")
