"""BrentWtiSpreadGrid: griglia mean-reversion sullo spread Brent-WTI (futures Yahoo BZ=F - CL=F, chiusure daily).

Regole (quant/research/spreads.py s1_grid): z60 dello spread, passo = 0.25*std60; a ogni livello attraversato verso
il basso (z<0) si apre 1 unita' LONG spread, verso l'alto 1 unita' SHORT, max 8 per lato; ogni unita' chiude a +1
passo a suo favore (passo fissato all'ingresso); se |z|>4 chiude tutto (kill).
LAG: il segnale e' calcolato SOLO su barre daily chiuse (data < oggi UTC) e agito oggi alle 20:45 UTC (circa
settlement NY): segnale di t-1 -> esecuzione a t. L'esecuzione alla stessa chiusura del segnale e' un artefatto
(reports/brent_wti_spot/report.md).
Stato: ricostruibile. Ogni decide() riesegue la griglia sullo storico daily (lookback 1100g), quindi non serve
persistenza; per audit scrive anche uno snapshot JSON in $LAB_STATE_DIR (default data/lab_state), best-effort.
Posizione: 1 unita' = 1 contratto per gamba (1000 barili), strumento "SPREAD:BRENT-WTI" multiplier 1000, costi
ASSUNTI $10 per unita' per lato (CostModel(per_share=10.0)). Target = unita' nette (long - short, i lati opposti si
compensano: lieve risparmio di costi rispetto al backtest) -> weight = netto*spread*1000/capital, capato a +-1.0
(gross) e 0 se spread < 0.5 $ (peso non definito). capital 50000.
Expected: reports/brent_wti_spot/report.md, riga futures Yahoo 2008-26 esecuzione giorno dopo: Sharpe netto 0.54
(IC95 [0.22; 0.91], DSR 0.40, scartato). Media/std per periodo NON riportati -> expected=None.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from quant.core import CostModel
from quant.lab.base import Decision, Instrument, Target
from quant.lab.strategies._util import closed_bars, utc

GRID_MAX = 8
STEP_FRAC = 0.25
KILL_Z = 4.0
UNIT_BBL = 1000.0


def replay_grid(s: np.ndarray, w: int = 60):
    """Riesegue la griglia su serie spread s (causale). -> (longs, shorts) liste di dict(e, step) aperte alla fine."""
    m = pd.Series(s).rolling(w).mean().to_numpy()
    sd = pd.Series(s).rolling(w).std(ddof=1).to_numpy()
    longs, shorts = [], []
    for i in range(w + 1, len(s)):
        z = (s[i] - m[i]) / sd[i]
        if abs(z) > KILL_Z:
            longs, shorts = [], []
            continue
        for p in longs + shorts:
            p["days"] += 1
        for lst, sg in ((longs, 1), (shorts, -1)):
            lst[:] = [p for p in lst if not (p["days"] > 0 and sg * (s[i] - p["e"]) >= p["step"] - 1e-12)]
        step = STEP_FRAC * sd[i]
        if step <= 0:
            continue
        kn = math.floor((s[i] - m[i]) / step)
        kp = math.floor((s[i - 1] - m[i]) / step)
        if kn != kp and abs(kn - kp) < 60:
            levels = range(kn + 1, kp + 1) if kn < kp else range(kp + 1, kn + 1)
            for L in levels:
                if L < 0 and len(longs) < GRID_MAX:
                    longs.append(dict(e=s[i], step=step, days=0))
                elif L > 0 and len(shorts) < GRID_MAX:
                    shorts.append(dict(e=s[i], step=step, days=0))
    return longs, shorts


class BrentWtiSpreadGrid:
    name = "brent_wti_grid"
    version = "1.0"
    schedule = "45 20 * * 1-5"
    capital = 50_000.0
    expected = None
    lookback_days = 1100

    def __init__(self):
        self.instrument = Instrument("SPREAD:BRENT-WTI", "spread", "BZ=F-CL=F",
                                     CostModel(per_share=10.0), multiplier=UNIT_BBL)

    def _spread(self, now, data) -> pd.Series:
        a = closed_bars(data.bars("yahoo", "BZ=F", "1d", self.lookback_days, now), now, 24)
        b = closed_bars(data.bars("yahoo", "CL=F", "1d", self.lookback_days, now), now, 24)
        if a.empty or b.empty:
            return pd.Series(dtype=float)
        a, b = a["close"], b["close"]
        a.index, b.index = a.index.normalize(), b.index.normalize()
        d = pd.concat([a[~a.index.duplicated()], b[~b.index.duplicated()]], axis=1, keys=["a", "b"]).dropna()
        d = d[(d.a > 0) & (d.b > 0)]
        return d.a - d.b

    def _snapshot(self, now, longs, shorts, spread):
        try:
            p = Path(os.getenv("LAB_STATE_DIR", "data/lab_state"))
            p.mkdir(parents=True, exist_ok=True)
            (p / f"{self.name}_v{self.version}.json").write_text(json.dumps(
                dict(asof=now.isoformat(), spread=spread, longs=longs, shorts=shorts), default=float))
        except Exception:  # noqa: BLE001
            pass

    def decide(self, now_utc, data) -> Decision:
        now = utc(now_utc)
        sp = self._spread(now, data)
        if len(sp) < 90:
            return Decision(self.name, self.version, now.isoformat(), [], note="dati insufficienti")
        s = sp.to_numpy(float)
        longs, shorts = replay_grid(s)
        net = len(longs) - len(shorts)
        last = float(s[-1])
        z = float((s[-1] - sp.iloc[-60:].mean()) / sp.iloc[-60:].std(ddof=1))
        try:
            px = float(data.last_price("yahoo", "BZ=F", now) - data.last_price("yahoo", "CL=F", now))
        except Exception:  # noqa: BLE001
            px = last
        w = 0.0
        if px >= 0.5:
            w = float(np.clip(net * px * UNIT_BBL / self.capital, -1.0, 1.0))
        reason = (f"griglia: {len(longs)} unita' long / {len(shorts)} short -> nette {net:+d}; spread chiuso "
                  f"{last:.2f} z60 {z:+.2f}; segnale di {sp.index[-1]:%Y-%m-%d} agito oggi (lag 1g)")
        feats = dict(units_long=len(longs), units_short=len(shorts), net_units=net, spread_last_close=last,
                     spread_now=px, z60=z, last_signal_date=str(sp.index[-1].date()), weight_uncapped=
                     (net * px * UNIT_BBL / self.capital if px >= 0.5 else None))
        self._snapshot(now, longs, shorts, last)
        if abs(z) > 4:
            state = f"KILL: |z60| {abs(z):.2f} > 4, tutte le unita' chiuse"
        elif not longs and not shorts:
            state = f"FLAT: nessuna unita' aperta (z60 {z:+.2f}, nessun livello attraversato da aprire)"
        elif net == 0:
            state = f"COPERTA: {len(longs)} long e {len(shorts)} short si compensano (z60 {z:+.2f})"
        else:
            state = f"{net:+d} unita' nette ({len(longs)} long / {len(shorts)} short), z60 {z:+.2f}"
        if px < 0.5:
            state += f"; peso forzato a 0 perche' lo spread live {px:.2f}$ < 0.5$"
        note = state
        return Decision(self.name, self.version, now.isoformat(), [Target(self.instrument, w, reason, feats)],
                        note=note)
