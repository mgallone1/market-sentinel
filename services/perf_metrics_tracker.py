"""
Performance & Metrics Persistent Tracker for Market Sentinel.
Registra e aggrega gli snapshot su multipli timeframe:
- realtime (ultimi 60 snapshot a 3 secondi)
- 1m (1 minuto)
- 1h (1 ora)
- 1d (1 giorno)
- 1w (1 settimana)
- 1M (1 mese)
Calcola variazioni assolute ($) e percentuali (%) su ciascun orizzonte temporale.
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, List

DB_PATH = Path(__file__).parent.parent / "perf_history.db"

def init_perf_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                total_equity REAL NOT NULL,
                bybit_equity REAL NOT NULL,
                alpaca_equity REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                cumulative_realized_pnl REAL NOT NULL,
                cumulative_volume_usd REAL NOT NULL,
                open_positions_count INTEGER NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_epoch ON equity_snapshots(epoch)
        """)
        conn.commit()

init_perf_db()

class PerfMetricsTracker:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        init_perf_db()

    def record_snapshot(self, total_equity: float, bybit_equity: float, alpaca_equity: float,
                        unrealized_pnl: float, cumulative_realized: float,
                        cumulative_volume: float, positions_count: int):
        now = datetime.now(ZoneInfo("Europe/Rome"))
        epoch = int(now.timestamp())
        iso_str = now.isoformat()

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO equity_snapshots 
                    (timestamp, epoch, total_equity, bybit_equity, alpaca_equity, unrealized_pnl, 
                     cumulative_realized_pnl, cumulative_volume_usd, open_positions_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (iso_str, epoch, total_equity, bybit_equity, alpaca_equity, 
                      unrealized_pnl, cumulative_realized, cumulative_volume, positions_count))
                conn.commit()
        except Exception as e:
            print(f"[!] Errore salvataggio snapshot perf: {e}")

    def get_timeframe_history(self, timeframe: str = "3s") -> List[Dict[str, Any]]:
        """
        Restituisce lo storico campionato in base al timeframe selezionato:
        - '3s': ultimi 60 punti (raw)
        - '1m': raggruppato ogni 60 secondi
        - '1h': raggruppato ogni 3600 secondi
        - '1d': raggruppato ogni 86400 secondi
        - '1w': raggruppato ogni 604800 secondi
        - '1M': raggruppato ogni 2592000 secondi (30gg)
        """
        step_seconds = {
            "3s": 1,
            "1m": 60,
            "1h": 3600,
            "1d": 86400,
            "1w": 604800,
            "1M": 2592000
        }.get(timeframe, 1)

        limit_points = 60

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                if step_seconds == 1:
                    cursor.execute("""
                        SELECT * FROM equity_snapshots
                        ORDER BY epoch DESC
                        LIMIT ?
                    """, (limit_points,))
                else:
                    # Query aggregata per step temporale (prende l'ultimo valore per ciascun bucket)
                    cursor.execute(f"""
                        SELECT * FROM equity_snapshots
                        WHERE id IN (
                            SELECT MAX(id)
                            FROM equity_snapshots
                            GROUP BY (epoch / {step_seconds})
                        )
                        ORDER BY epoch DESC
                        LIMIT ?
                    """, (limit_points,))
                
                rows = cursor.fetchall()
                return [dict(r) for r in reversed(rows)]
        except Exception as e:
            print(f"[!] Errore lettura timeframe {timeframe}: {e}")
            return []

    def get_variations(self, current_equity: float, current_realized_pnl: float) -> Dict[str, Dict[str, Any]]:
        """
        Calcola la variazione di Equity e PnL rispetto a:
        - 3 secondi fa (ultimo tick)
        - 1 minuto fa
        - 1 ora fa
        - 1 giorno fa
        - 1 settimana fa
        - 1 mese fa
        """
        now_epoch = int(datetime.now(ZoneInfo("Europe/Rome")).timestamp())
        intervals = {
            "3s": 3,
            "1m": 60,
            "1h": 3600,
            "1d": 86400,
            "1w": 604800,
            "1M": 2592000
        }

        results = {}

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                for tf_label, seconds in intervals.items():
                    target_epoch = now_epoch - seconds
                    cursor.execute("""
                        SELECT total_equity, cumulative_realized_pnl
                        FROM equity_snapshots
                        WHERE epoch <= ?
                        ORDER BY epoch DESC
                        LIMIT 1
                    """, (target_epoch,))
                    row = cursor.fetchone()

                    if row:
                        past_eq = float(row["total_equity"])
                        past_pnl = float(row["cumulative_realized_pnl"])
                        diff_eq = current_equity - past_eq
                        diff_eq_pct = (diff_eq / (past_eq or 1.0)) * 100
                        diff_pnl = current_realized_pnl - past_pnl
                    else:
                        diff_eq = 0.0
                        diff_eq_pct = 0.0
                        diff_pnl = 0.0

                    results[tf_label] = {
                        "delta_equity": round(diff_eq, 2),
                        "delta_equity_pct": round(diff_eq_pct, 4),
                        "delta_pnl": round(diff_pnl, 2)
                    }
        except Exception as e:
            print(f"[!] Errore calcolo variazioni: {e}")

        return results

perf_tracker = PerfMetricsTracker()
