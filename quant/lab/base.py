"""
Contratti del LABORATORIO di paper trading (quant/lab).

Obiettivo: far girare in parallelo piu' strategie in PAPER (nessun ordine reale), registrare ogni decisione con le
sue motivazioni, eseguire con lo stesso modello di costi dei backtest, e produrre revisioni periodiche
"cosa ha funzionato / cosa no" confrontando il live con le attese della ricerca.

Concetti:
- Strategy: produce, a ogni esecuzione pianificata, un TARGET di esposizioni (peso sul capitale della strategia,
  firmato: +long, -short) per strumento, con motivazioni e feature. Le strategie sono VERSIONATE: ogni modifica
  alle regole cambia `version`, e i log restano separati per (name, version).
- PaperBroker: porta le posizioni verso il target al prezzo di esecuzione (next bar / prezzo live), applicando
  fee, slippage, funding e finanziamento secondo un CostModel (quant.core), e marca a mercato.
- Journal (storage): tabelle decisions, fills, positions_mark, daily_pnl, reviews. Backend SQLite (default) o Supabase.
- Review: confronta metriche live con `expected` (dalla ricerca) e scrive lezioni.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from quant.core import CostModel


@dataclass(frozen=True)
class Instrument:
    key: str                 # identificativo unico nel lab, es. "BYBIT:BTCUSDT", "YAHOO:SPY", "SPREAD:BRENT-WTI"
    price_source: str        # "bybit" | "yahoo" | "binance_proxy" | "spread"
    symbol: str              # simbolo per la sorgente prezzi
    costs: CostModel
    multiplier: float = 1.0  # $ per unita' di prezzo (spread: barili per unita')


@dataclass
class Target:
    instrument: Instrument
    weight: float            # esposizione desiderata / capitale della strategia (firmata). 0 = flat
    reason: str              # motivazione leggibile ("1/3/12m momentum +0.67, vol 12%")
    features: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    strategy: str
    version: str
    ts: str                  # ISO UTC della decisione (dati fino a questo istante, solo barre chiuse)
    targets: List[Target]
    note: str = ""           # es. "regime OFF: funding sotto soglia"


@dataclass(frozen=True)
class Expected:
    """Attese dalla ricerca per il confronto live (per periodo di valutazione della strategia)."""
    sharpe: float
    mean_period_return: float        # rendimento medio netto per periodo (giorno/settimana/mese, vedi `period`)
    std_period_return: float
    period: str                      # "day" | "week" | "month"
    source_report: str               # percorso del report di ricerca


class Strategy(Protocol):
    name: str
    version: str
    schedule: str                    # cron a 5 campi in UTC, es. "5 0 * * *"
    capital: float                   # capitale paper assegnato (USD)
    expected: Optional[Expected]

    def decide(self, now_utc, data: "MarketData") -> Decision: ...


class MarketData(Protocol):
    """Accesso ai prezzi: SOLO barre chiuse fino a `now`. In produzione Bybit/Yahoo; in test sintetico."""
    def bars(self, source: str, symbol: str, interval: str, lookback_days: int, now_utc) -> "Any": ...
    def last_price(self, source: str, symbol: str, now_utc) -> float: ...
    def funding(self, symbol: str, lookback_days: int, now_utc) -> "Any": ...


class Storage(Protocol):
    def log_decision(self, d: Decision) -> str: ...
    def log_fill(self, row: Dict[str, Any]) -> None: ...
    def log_mark(self, row: Dict[str, Any]) -> None: ...
    def log_review(self, row: Dict[str, Any]) -> None: ...
    def positions(self, strategy: str, version: str) -> Dict[str, Dict[str, float]]: ...   # key -> {qty, avg_price}
    def set_position(self, strategy: str, version: str, key: str, qty: float, avg_price: float) -> None: ...
    def cash(self, strategy: str, version: str) -> Optional[float]: ...
    def set_cash(self, strategy: str, version: str, cash: float) -> None: ...
    def query(self, table: str, strategy: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]: ...
