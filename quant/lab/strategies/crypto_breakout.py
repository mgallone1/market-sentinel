"""CryptoBreakout4hMaker: donchian_breakout 4h (n=96 barre, quant/strategies/baselines.py) long/short su 10 perp.

Segnale: close rompe max/min delle 96 barre precedenti -> entrata all'open della barra successiva (qui: target
emesso alla chiusura della barra, eseguito al prezzo live). Un'unica posizione per simbolo alla volta. Uscite
ExitRules(sl_atr=1.5, tp_atr=3.0, max_hold_bars=30) gestite DENTRO la strategia: lo stato (posizioni aperte) e'
ricostruito rieseguendo il segnale e `simulate_trade` su 120 giorni di barre 4h chiuse; target 0 quando l'uscita e'
scattata su una barra chiusa. Peso = +-1/10 del capitale per segnale (gross <= 1.0).
Costi: preset bybit_perp (maker 0.02% disponibile nel CostModel). Il fill maker NON e' modellato dal paper broker
(riempie all'ultimo prezzo): l'incertezza di fill maker (ordini non eseguiti, selezione avversa) va MISURATA live.
Limite: lo stato dipende dalla finestra di replay (120g), una posizione piu' vecchia di 30 barre e' comunque chiusa.
Expected = None: report crypto_donchian_4h riga primary_only: 837 trade, expectancy +0.458%/trade, PF 1.18, Sharpe
0.66, maxDD -18.9% (verdetto NO EDGE come meta-labeling); media/std per periodo non riportate.
"""
from __future__ import annotations

import numpy as np

from quant.backtest.exits import ExitRules, simulate_trade, wilder_atr
from quant.core import COST_PRESETS, crypto_perp
from quant.lab.base import Decision, Instrument, Target
from quant.lab.strategies._util import closed_bars, utc
from quant.strategies import STRATEGIES

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT", "AVAXUSDT", "ADAUSDT", "DOGEUSDT",
           "SUIUSDT", "NEARUSDT"]
RULES = ExitRules(sl_atr=1.5, tp_atr=3.0, max_hold_bars=30)


def replay_position(bars, symbol: str, rules: ExitRules = RULES, n: int = 96):
    """-> (side, info) side in {-1,0,1} a fine dati (barre chiuse), info dict per le feature."""
    sig = STRATEGIES["donchian_breakout"](bars, crypto_perp(symbol), "4h", None, n=n).to_numpy(int)
    o, h, l, c = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = wilder_atr(h, l, c)
    N = len(c)
    i = 0
    while i < N:
        if sig[i] == 0:
            i += 1
            continue
        side, e = int(sig[i]), i + 1
        lv = rules.levels(side, c[i] if e >= N else o[e], atr[i])
        if lv is None:
            i += 1
            continue
        if e >= N:                                   # segnale sull'ultima barra chiusa: entrata ora
            return side, dict(signal_bar=str(bars.index[i]), entry_ref=float(c[i]), atr=float(atr[i]),
                              sl=float(lv[0]), tp=float(lv[1]), bars_held=0, status="entry_now")
        sl, tp, _ = lv
        xi, xp, why = simulate_trade(o, h, l, c, e, side, o[e], sl, tp, rules, atr[i])
        if why == "EOD_DATA":
            return side, dict(signal_bar=str(bars.index[i]), entry_ref=float(o[e]), atr=float(atr[i]),
                              sl=float(sl), tp=float(tp), bars_held=int(N - e), status="open")
        i = max(xi, i + 1)
    return 0, dict(status="flat")


class CryptoBreakout4hMaker:
    name = "crypto_breakout_4h"
    version = "1.0"
    schedule = "2 0,4,8,12,16,20 * * *"
    capital = 100_000.0
    expected = None
    lookback_days = 120

    def __init__(self, symbols=None):
        self.symbols = list(symbols or SYMBOLS)
        self.inst = {s: Instrument(f"BYBIT:{s}", "bybit", s, COST_PRESETS["bybit_perp"]) for s in self.symbols}

    def decide(self, now_utc, data) -> Decision:
        now = utc(now_utc)
        w_unit = 1.0 / len(self.symbols)
        targets, n_open = [], 0
        for s in self.symbols:
            try:
                b = closed_bars(data.bars("bybit", s, "4h", self.lookback_days, now), now, 4)
                if len(b) < 130:
                    raise ValueError("storia insufficiente")
                side, info = replay_position(b, s)
            except Exception as e:  # noqa: BLE001
                side, info = 0, {"status": f"errore dati: {e}"}
            n_open += abs(side)
            if side:
                why = (f"donchian96 {'LONG' if side > 0 else 'SHORT'} ({info['status']}), barre tenute "
                       f"{info['bars_held']}/30, SL {info['sl']:.4g} TP {info['tp']:.4g} (1.5/3.0 ATR)")
            else:
                why = f"flat ({info.get('status')}): nessun breakout aperto o uscita SL/TP/tempo scattata"
            targets.append(Target(self.inst[s], side * w_unit, why, info))
        return Decision(self.name, self.version, now.isoformat(), targets,
                        note=f"{n_open}/{len(self.symbols)} posizioni aperte, peso {w_unit:.2f} ciascuna")
