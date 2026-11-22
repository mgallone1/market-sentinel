"""
Performance & Metrics Persistent Tracker for Market Sentinel.
Registra a intervalli regolari e ad ogni chiusura di trade lo storico cumulativo in SQLite:
- timestamp
- equity_total (Bybit + Alpaca)
- bybit_equity
- alpaca_equity
- cumulative_realized_pnl
- cumulative_volume_usd
- net_unrealized_pnl
- win_rate
- profit_factor
- trades_count
Permette di costruire grafici di andamento su 24h, 7d, 30d, 90d.
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

    def get_history(self, limit: int = 120) -> List[Dict[str, Any]]:
        """Restituisce gli ultimi N snapshot orari/minutali per i grafici."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM equity_snapshots
                    ORDER BY epoch DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                # Ritorna in ordine cronologico crescente
                return [dict(r) for r in reversed(rows)]
        except Exception as e:
            print(f"[!] Errore lettura storico perf: {e}")
            return []

perf_tracker = PerfMetricsTracker()
