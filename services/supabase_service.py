"""
Supabase Service
Modulo per la gestione della persistenza dinamica su schema 'finance' di Supabase.
Include fallback su SQLite locale in assenza temporanea delle credenziali d'ambiente.
"""

import os
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Carica le variabili da .env
ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False

DB_DIR = Path(__file__).parent.parent / "data"
DB_DIR.mkdir(exist_ok=True)
SQLITE_PATH = DB_DIR / "market_sentinel.db"

class SupabaseService:
    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL", "").strip()
        self.supabase_key = os.getenv("SUPABASE_KEY", "").strip()
        self.client: Optional[Client] = None

        if HAS_SUPABASE and self.supabase_url and self.supabase_key:
            try:
                self.client = create_client(self.supabase_url, self.supabase_key)
            except Exception as e:
                print(f"[SupabaseService] Errore connessione Supabase: {e}, fallback a SQLite.")
                self.client = None
        
        # Inizializza SQLite di fallback o locale
        self._init_sqlite()

    def _init_sqlite(self):
        with sqlite3.connect(SQLITE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                asset_name TEXT NOT NULL,
                shares REAL NOT NULL,
                average_buy_price REAL NOT NULL,
                currency TEXT DEFAULT 'EUR',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, ticker)
            );
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                rule_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                summary_text TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            conn.commit()

    def upsert_position(self, user_id: int, ticker: str, asset_name: str, shares: float, price: float, currency: str = "EUR") -> bool:
        """Salva o aggiorna una posizione in portafoglio."""
        ticker = ticker.strip().upper()
        if self.client:
            try:
                data = {
                    "user_id": user_id,
                    "ticker": ticker,
                    "asset_name": asset_name,
                    "shares": shares,
                    "average_buy_price": price,
                    "currency": currency
                }
                # Tabella finance_portfolio nello schema public
                self.client.table("finance_portfolio").upsert(data, on_conflict="user_id, ticker").execute()
                return True
            except Exception as e:
                print(f"[SupabaseService] Errore upsert Supabase: {e}")

        # Fallback locale SQLite
        with sqlite3.connect(SQLITE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO portfolio (user_id, ticker, asset_name, shares, average_buy_price, currency, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, ticker) DO UPDATE SET
                shares = excluded.shares,
                average_buy_price = excluded.average_buy_price,
                updated_at = CURRENT_TIMESTAMP
            """, (user_id, ticker, asset_name, shares, price, currency))
            conn.commit()
        return True

    def get_portfolio(self, user_id: int) -> List[Dict[str, Any]]:
        """Restituisce le posizioni correnti dell'utente."""
        if self.client:
            try:
                res = self.client.table("finance_portfolio").select("*").eq("user_id", user_id).execute()
                if res.data:
                    return res.data
            except Exception as e:
                print(f"[SupabaseService] Errore lettura Supabase: {e}")

        # Fallback locale SQLite
        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM portfolio WHERE user_id = ?", (user_id,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def delete_position(self, user_id: int, ticker: str) -> bool:
        """Rimuove un titolo dal portafoglio."""
        ticker = ticker.strip().upper()
        if self.client:
            try:
                self.client.table("finance_portfolio").delete().eq("user_id", user_id).eq("ticker", ticker).execute()
                return True
            except Exception as e:
                print(f"[SupabaseService] Errore delete Supabase: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM portfolio WHERE user_id = ? AND ticker = ?", (user_id, ticker))
            conn.commit()
        return True

    def add_user_rule(self, user_id: int, rule_text: str) -> bool:
        """Aggiunge una regola/vincolo personale di rischio."""
        if self.client:
            try:
                self.client.table("finance_user_rules").insert({"user_id": user_id, "rule_text": rule_text}).execute()
                return True
            except Exception as e:
                print(f"[SupabaseService] Errore inserimento regola Supabase: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO user_rules (user_id, rule_text) VALUES (?, ?)", (user_id, rule_text))
            conn.commit()
        return True

    def log_message(self, user_id: int, role: str, content: str):
        """Salva un messaggio nella cronologia per la memoria di breve/lungo termine."""
        if self.client:
            try:
                self.client.table("finance_chat_history").insert({
                    "user_id": user_id,
                    "role": role,
                    "content": content
                }).execute()
            except Exception as e:
                print(f"[SupabaseService] Errore salvataggio chat history su Supabase: {e}")

        # Salva anche in locale SQLite
        with sqlite3.connect(SQLITE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)", (user_id, role, content))
            conn.commit()

    def get_recent_chat_history(self, user_id: int, limit: int = 12) -> List[Dict[str, str]]:
        """Recupera la memoria a breve termine (ultimi scambi entro 7 giorni)."""
        if self.client:
            try:
                res = self.client.table("finance_chat_history").select("role, content").eq("user_id", user_id).order("id", desc=True).limit(limit).execute()
                if res.data:
                    return list(reversed(res.data))
            except Exception as e:
                print(f"[SupabaseService] Errore lettura chat history da Supabase: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
            rows = cursor.fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def get_long_term_summary(self, user_id: int) -> str:
        """Recupera la sintesi strategica di lungo termine (decisioni e tesi degli ultimi 30 giorni)."""
        if self.client:
            try:
                res = self.client.table("finance_memory_summary").select("summary_text").eq("user_id", user_id).limit(1).execute()
                if res.data:
                    return res.data[0]["summary_text"]
            except Exception as e:
                pass

        with sqlite3.connect(SQLITE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT summary_text FROM memory_summary WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return row[0] if row else ""

    def save_long_term_summary(self, user_id: int, summary_text: str):
        """Aggiorna la memoria strategica a lungo termine."""
        if self.client:
            try:
                self.client.table("finance_memory_summary").upsert({
                    "user_id": user_id,
                    "summary_text": summary_text
                }, on_conflict="user_id").execute()
            except Exception as e:
                print(f"[SupabaseService] Errore salvataggio summary Supabase: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO memory_summary (user_id, summary_text, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET summary_text = excluded.summary_text, updated_at = CURRENT_TIMESTAMP
            """, (user_id, summary_text))
            conn.commit()
