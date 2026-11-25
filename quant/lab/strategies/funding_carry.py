"""FundingCarry: short perp + long spot a nozionale uguale (delta-neutral) quando il funding e' alto.

Regola (quant/backtest/carry.py): media degli ultimi 9 print di funding, annualizzata con la cadenza mediana dei
print; entra se > 10%, esce se < 3% (isteresi). Stato RICOSTRUITO da 90 giorni di funding (macchina a stati su tutti
i print) quindi senza persistenza. Simboli BTC, ETH, SOL, XRP, DOGE. Ogni simbolo attivo: gamba perp -0.5/N e gamba
spot +0.5/N (N = simboli attivi) -> gross totale <= 1.0, nozionale uguale. Strumenti BYBIT:<SYM> (perp) e
BYBIT_SPOT:<SYM> (spot, price_source "bybit_spot": il MarketData live deve supportarlo). Costi: preset bybit_perp e
crypto_spot (taker). Non modellato: rischio di liquidazione/margine della gamba perp, basis.
Expected = None: nel repo non ci sono report con numeri di carry per periodo (solo messaggi di commit: carry
cross-sezionale settimanale Sharpe 1.71 su 6/6 anni positivi, NON lo stesso test; replica su 40 coin "non
confermata"). I risultati 2024/2025/2026 del carry delta-neutral non sono committati: da misurare dal lab.
"""
from __future__ import annotations

import numpy as np

from quant.core import COST_PRESETS
from quant.lab.base import Decision, Instrument, Target
from quant.lab.strategies._util import funding_series, utc

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
ENTRY_APR, EXIT_APR, N_PRINTS, LEG_FRAC = 0.10, 0.03, 9, 0.5


def carry_state(f, entry=ENTRY_APR, exit_=EXIT_APR, n=N_PRINTS):
    """Macchina a stati sui print di funding (Series). -> (active, apr_ultimo | None)."""
    if len(f) < n:
        return False, None
    gap_h = float(np.median(np.diff(f.index.values).astype("timedelta64[s]").astype(float))) / 3600.0
    ppy = 8760.0 / gap_h if gap_h > 0 else 1095.0
    vals = f.to_numpy(float)
    act, apr = False, None
    for k in range(n - 1, len(vals)):
        apr = float(np.mean(vals[k - n + 1:k + 1])) * ppy
        if not act and apr > entry:
            act = True
        elif act and apr < exit_:
            act = False
    return act, apr


class FundingCarry:
    name = "funding_carry"
    version = "1.0"
    schedule = "10 0,8,16 * * *"
    capital = 100_000.0
    expected = None
    lookback_days = 90

    def __init__(self, symbols=None):
        self.symbols = list(symbols or SYMBOLS)
        self.perp = {s: Instrument(f"BYBIT:{s}", "bybit", s, COST_PRESETS["bybit_perp"]) for s in self.symbols}
        self.spot = {s: Instrument(f"BYBIT_SPOT:{s}", "bybit_spot", s, COST_PRESETS["crypto_spot"])
                     for s in self.symbols}

    def decide(self, now_utc, data) -> Decision:
        now = utc(now_utc)
        st = {}
        for s in self.symbols:
            try:
                f = funding_series(data.funding(s, self.lookback_days, now), now)
                st[s] = carry_state(f)
            except Exception:  # noqa: BLE001
                st[s] = (False, None)
        act = [s for s in self.symbols if st[s][0]]
        leg = LEG_FRAC / len(act) if act else 0.0
        targets = []
        for s in self.symbols:
            on, apr = st[s]
            feats = {"apr_9prints": apr, "active": on, "entry_apr": ENTRY_APR, "exit_apr": EXIT_APR, "leg_weight": leg}
            apr_s = "n/d" if apr is None else f"{apr * 100:.1f}%"
            why = (f"carry ON: funding medio 9 print {apr_s} annuo (soglie in {ENTRY_APR:.0%}/out {EXIT_APR:.0%})"
                   if on else f"carry OFF: funding medio 9 print {apr_s} annuo")
            targets.append(Target(self.perp[s], -leg if on else 0.0, why + " -> short perp", feats))
            targets.append(Target(self.spot[s], leg if on else 0.0, why + " -> long spot", feats))
        note = f"{len(act)}/{len(self.symbols)} simboli attivi: {','.join(act) or 'nessuno'}"
        return Decision(self.name, self.version, now.isoformat(), targets, note=note)
