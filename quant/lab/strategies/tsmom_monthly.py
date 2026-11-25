"""TsmomMonthly: TSMOM multi-asset long-only, ribilanciamento mensile, SENZA leva (paper).

Regole (quant/portfolio/tsmom.py, specifica pre-registrata): segnale = media dei segni dei rendimenti 21/63/252g,
peso ~ segnale x 0.40/vol EWMA, vol target di portafoglio 10%, long_only, banda no-trade 10%. Differenza dal backtest:
nel lab NON c'e' leva, quindi la leva lorda e' capata a 1.0 (il backtest usava cap 2.0, media 1.47): i pesi finali
sono riscalati a gross<=1 (approssimazione: la banda no-trade e' valutata prima del riscalamento).
Universo: 21 ETF + BTC-USD/ETH-USD via Yahoo. Schedule giornaliero, ma ribilancia SOLO l'ultimo giorno di borsa del
mese (calendario NYSE di services.risk_limits); negli altri giorni emette i pesi dell'ultimo ribilanciamento
(note "hold"): sono ricalcolati in modo deterministico troncando lo storico alla fine del mese precedente.

Expected: reports/tsmom_multiasset/report.md, riga long_only_monthly, finestra full: Sharpe netto 0.90, CAGR 8.8%,
vol 9.9% (leva lorda media 1.47). Media/std MENSILI NON presenti nel report: DERIVATI come
mean=((1+CAGR)^(1/12)-1)/1.47 e std=(vol/sqrt(12))/1.47, dove 1/1.47 approssima il taglio della leva a 1.0.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.core import CostModel
from quant.lab.base import Decision, Expected, Instrument, Target
from quant.lab.strategies._util import closed_bars, is_last_trading_day_of_month, utc
from quant.portfolio.tsmom import asset_vol, signals, tsmom_weights

ETF = "SPY QQQ IWM EFA EEM VGK EWJ TLT IEF LQD HYG TIP GLD SLV USO DBC DBA UUP FXE FXY VNQ".split()
CRYPTO = ["BTC-USD", "ETH-USD"]
UNIVERSE = ETF + CRYPTO
_CAGR, _VOL, _LEV = 0.0882, 0.0991, 1.47


class TsmomMonthly:
    name = "tsmom_monthly"
    version = "1.0"
    schedule = "15 21 * * 1-5"
    capital = 100_000.0
    expected = Expected(
        sharpe=0.90,
        mean_period_return=((1 + _CAGR) ** (1 / 12) - 1) / _LEV,
        std_period_return=(_VOL / np.sqrt(12)) / _LEV,
        period="month",
        source_report="reports/tsmom_multiasset/report.md",
    )
    lookback_days = 800

    def __init__(self, universe=None):
        self.universe = list(universe or UNIVERSE)
        self.instruments = {s: Instrument(f"YAHOO:{s}", "yahoo", s,
                                          CostModel(slippage_bps=10.0 if s in CRYPTO else 2.0))
                            for s in self.universe}

    def _prices(self, now, data) -> pd.DataFrame:
        px = {}
        for s in self.universe:
            try:
                b = closed_bars(data.bars("yahoo", s, "1d", self.lookback_days, now), now, 24,
                                same_day_after_hour=None if s in CRYPTO else 21)
            except Exception:  # noqa: BLE001
                continue
            if len(b) < 300:
                continue
            c = b["close"].copy()
            c.index = c.index.tz_localize(None).normalize()
            px[s] = c[~c.index.duplicated()]
        df = pd.DataFrame(px)
        return df[df.index.dayofweek < 5].sort_index()

    def decide(self, now_utc, data) -> Decision:
        now = utc(now_utc)
        rebalance = is_last_trading_day_of_month(now.date())
        px = self._prices(now, data)
        # si ribilancia solo se la barra di oggi e' presente; altrimenti pesi dell'ultimo ribilanciamento
        if rebalance and (px.empty or px.index[-1].date() != now.date()):
            rebalance = False
            reason_hold = "ultimo giorno del mese ma barra di oggi non disponibile"
        else:
            reason_hold = "non e' l'ultimo giorno di borsa del mese"
        if not rebalance:
            px = px[px.index < pd.Timestamp(now.year, now.month, 1)]
        if px.empty or len(px) < 260:
            return Decision(self.name, self.version, now.isoformat(), [], note="dati insufficienti")
        crypto = {c for c in CRYPTO if c in px.columns}
        w = tsmom_weights(px, crypto, "monthly", "long_only").iloc[-1].fillna(0.0)
        gross = float(w.abs().sum())
        scale = 1.0 / gross if gross > 1.0 else 1.0
        sig, vol = signals(px).iloc[-1], asset_vol(px, crypto).iloc[-1]
        targets = []
        for s in px.columns:
            ws = float(w[s]) * scale
            targets.append(Target(
                self.instruments[s], ws,
                f"momentum 1/3/12m {sig[s]:+.2f}, vol {vol[s] * 100:.0f}% -> peso {ws:.3f}" if sig[s] == sig[s]
                else "storia insufficiente (<252g): peso 0",
                {"signal": None if sig[s] != sig[s] else float(sig[s]),
                 "vol_ann": None if vol[s] != vol[s] else float(vol[s]),
                 "weight_pre_cap": float(w[s]), "scale_no_leverage": scale}))
        note = (f"ribilancio mensile: gross {gross:.2f}->{min(gross, 1.0):.2f}, {int((w > 0).sum())} asset long"
                if rebalance else f"hold: {reason_hold}; pesi invariati (gross {min(gross, 1.0):.2f})")
        return Decision(self.name, self.version, now.isoformat(), targets, note=note)
