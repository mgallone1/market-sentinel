"""
Griglia coperta sul petrolio (strategia descritta dall'utente), simulata su dati reali.

Regola: a ogni attraversamento di un livello della griglia (passo s $/barile) si apre 1 long e 1 short
(1 barile ciascuno). Ogni posizione si chiude quando guadagna +s (take profit di uno scatto).
Le posizioni in perdita restano aperte (variante HOLD) oppure si chiude tutto a fine giornata (variante EOD).
Costi: spread per apertura+chiusura, finanziamento overnight annuo su ogni posizione aperta (long e short pagano).
Path: prezzi di chiusura (orari o giornalieri) -> gli attraversamenti intra-barra non visti sono IGNORATI
(sottostima i guadagni realizzati ma anche i nuovi ingressi; dichiarato nel report).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def simulate(prices: pd.Series, step: float, spread: float = 0.04, fin_annual: float = 0.05,
             mode: str = "hold", bars_per_day: float = 1.0) -> dict:
    p = prices.dropna()
    longs: list[float] = []   # prezzi di ingresso dei long aperti
    shorts: list[float] = []
    realized = 0.0
    fin_cost = 0.0
    n_trades = 0
    lvl = math.floor(p.iloc[0] / step) * step
    eq_curve, unreal_curve, inv_curve = [], [], []
    days = p.index.normalize()
    for i in range(len(p)):
        px = float(p.iloc[i])
        # attraversamenti di livello tra la chiusura precedente e questa
        while px >= lvl + step or px <= lvl - step:
            lvl = lvl + step if px >= lvl + step else lvl - step
            # take profit: long aperti a <= lvl - step, short aperti a >= lvl + step
            keep_l = []
            for e in longs:
                if lvl - e >= step - 1e-9:
                    realized += step - spread; n_trades += 1
                else:
                    keep_l.append(e)
            longs = keep_l
            keep_s = []
            for e in shorts:
                if e - lvl >= step - 1e-9:
                    realized += step - spread; n_trades += 1
                else:
                    keep_s.append(e)
            shorts = keep_s
            # nuova coppia long + short al livello attraversato (se non c'e' gia' una posizione a quel livello)
            if not any(abs(e - lvl) < 1e-9 for e in longs):
                longs.append(lvl)
            if not any(abs(e - lvl) < 1e-9 for e in shorts):
                shorts.append(lvl)
        # finanziamento overnight: ogni posizione aperta paga fin_annual sul nozionale, pro-rata per barra
        notional = sum(abs(e) for e in longs) + sum(abs(e) for e in shorts)
        fin = notional * fin_annual / 365 / bars_per_day
        fin_cost += fin
        realized -= fin
        unreal = sum(px - e for e in longs) + sum(e - px for e in shorts)
        last_of_day = (i == len(p) - 1) or (days[i + 1] != days[i])
        if mode == "eod" and last_of_day:
            realized += unreal - spread * (len(longs) + len(shorts)); n_trades += len(longs) + len(shorts)
            longs, shorts = [], []
            unreal = 0.0
            lvl = math.floor(px / step) * step
        eq_curve.append(realized + unreal); unreal_curve.append(unreal); inv_curve.append(len(longs) - len(shorts))
    eq = pd.Series(eq_curve, index=p.index)
    un = pd.Series(unreal_curve, index=p.index)
    return dict(final_equity=float(eq.iloc[-1]), realized=float(realized), unrealized=float(un.iloc[-1]),
                worst_equity=float(eq.min()), worst_equity_date=str(eq.idxmin().date()),
                worst_unrealized=float(un.min()), fin_cost=float(fin_cost), n_trades=n_trades,
                max_abs_net_inventory=int(np.max(np.abs(inv_curve))), open_positions_end=len(longs) + len(shorts),
                equity=eq)
