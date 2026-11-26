"""Optional bridge from lab strategies to the bot journal (data/market_sentinel.db, table lab_strategy_trades).

Never raises: a journal failure must not stop the lab run."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

_JOURNAL = None


def journal():
    global _JOURNAL
    if _JOURNAL is None:
        try:
            from services.trade_journal_service import TradeJournalService
            _JOURNAL = TradeJournalService()
        except Exception:  # noqa: BLE001
            _JOURNAL = False
    return _JOURNAL or None


def record(rows: Iterable[Dict[str, Any]], sink: Optional[Any] = None) -> int:
    j = sink if sink is not None else journal()
    if j is None:
        return 0
    n = 0
    for r in rows:
        try:
            n += bool(j.upsert_lab_trade(r))
        except Exception:  # noqa: BLE001
            pass
    return n
