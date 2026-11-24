"""
Contratti condivisi da tutti i moduli `quant`.

BARRE (pandas.DataFrame):
  - index: DatetimeIndex tz-aware UTC, nome "ts", = istante di APERTURA della barra, ordinato, senza duplicati.
  - colonne obbligatorie (float64): open, high, low, close, volume
  - colonne opzionali: taker_buy_volume (volume aggressivo in acquisto),
    funding_rate (tasso applicato a quella barra, NaN altrove), open_interest.
  - SOLO barre chiuse: i provider scartano la barra in formazione.

CONVENZIONE TEMPORALE (anti look-ahead):
  una decisione calcolata con i dati fino alla chiusura della barra t viene eseguita
  all'APERTURA della barra t+1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal

import pandas as pd

REQUIRED_COLS = ("open", "high", "low", "close", "volume")
AssetClass = Literal["crypto_perp", "crypto_spot", "equity", "etf", "index"]


@dataclass(frozen=True)
class CostModel:
    taker_fee: float = 0.0          # frazione del nozionale per lato (0.00055 = 0.055%)
    maker_fee: float = 0.0
    slippage_bps: float = 0.0       # slippage per lato in basis point
    per_share: float = 0.0          # commissione per azione (USD)
    min_ticket: float = 0.0         # commissione minima per ordine (USD)
    borrow_rate_annual: float = 0.0 # costo prestito titoli per short azionari
    apply_funding: bool = False     # perpetual: applica funding_rate alle posizioni aperte

    def one_way_frac(self, maker: bool = False) -> float:
        """Costo per lato come frazione del nozionale (fee + slippage)."""
        return (self.maker_fee if maker else self.taker_fee) + self.slippage_bps / 1e4


COST_PRESETS: Dict[str, CostModel] = {
    "bybit_perp": CostModel(taker_fee=0.00055, maker_fee=0.0002, slippage_bps=2.0, apply_funding=True),
    "binance_perp": CostModel(taker_fee=0.0005, maker_fee=0.0002, slippage_bps=2.0, apply_funding=True),
    "crypto_spot": CostModel(taker_fee=0.001, maker_fee=0.001, slippage_bps=3.0),
    "alpaca_equity": CostModel(taker_fee=0.0, maker_fee=0.0, slippage_bps=2.0, borrow_rate_annual=0.03),
    "ibkr_equity": CostModel(per_share=0.005, min_ticket=1.0, slippage_bps=2.0, borrow_rate_annual=0.03),
    "index_etf": CostModel(slippage_bps=1.0, borrow_rate_annual=0.01),
}


@dataclass(frozen=True)
class AssetSpec:
    symbol: str                       # simbolo nativo del venue (BTCUSDT, AAPL, ^GSPC, SPY)
    asset_class: AssetClass
    venue: str                        # bybit | binance | yahoo | alpaca | csv
    allow_short: bool = True
    session: Literal["24/7", "rth"] = "24/7"
    benchmark: str | None = None      # BTCUSDT per crypto, SPY per azioni USA
    cost_preset: str = "bybit_perp"
    extra: dict = field(default_factory=dict, hash=False, compare=False)

    @property
    def costs(self) -> CostModel:
        return COST_PRESETS[self.cost_preset]

    @property
    def bars_per_year_factor(self) -> float:
        """Ore di mercato per anno: 24*365 per 24/7, 6.5*252 per sessione regolare."""
        return 24 * 365 if self.session == "24/7" else 6.5 * 252


def crypto_perp(symbol: str, venue: str = "bybit") -> AssetSpec:
    return AssetSpec(symbol, "crypto_perp", venue, True, "24/7", "BTCUSDT",
                     "bybit_perp" if venue == "bybit" else "binance_perp")


def equity(symbol: str, venue: str = "yahoo", allow_short: bool = True) -> AssetSpec:
    return AssetSpec(symbol, "equity", venue, allow_short, "rth", "SPY", "alpaca_equity")


def index(symbol: str) -> AssetSpec:
    # gli indici non sono negoziabili direttamente: costi di un ETF/CFD replicante
    return AssetSpec(symbol, "index", "yahoo", True, "rth", None, "index_etf")


def interval_to_hours(interval: str) -> float:
    """'1m','5m','15m','1h','4h','1d' -> ore."""
    unit, n = interval[-1], float(interval[:-1])
    return {"m": n / 60, "h": n, "d": n * 24, "w": n * 24 * 7}[unit]


def validate_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Verifica il contratto BARRE; solleva ValueError se violato. Restituisce df."""
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"colonne mancanti: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError("index deve essere DatetimeIndex tz-aware (UTC)")
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise ValueError("index deve essere crescente e senza duplicati")
    bad = (df["high"] < df[["open", "close"]].max(axis=1) - 1e-12) | (df["low"] > df[["open", "close"]].min(axis=1) + 1e-12)
    if bad.any():
        raise ValueError(f"{int(bad.sum())} barre con high/low incoerenti")
    return df
