"""Regole di uscita e simulazione di un singolo trade (loop numpy, senza pandas)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

INF = float("inf")


@dataclass(frozen=True)
class ExitRules:
    sl_atr: Optional[float] = 1.5
    tp_atr: Optional[float] = 3.0
    sl_pct: Optional[float] = None          # frazione del prezzo, alternativa ad ATR
    tp_pct: Optional[float] = None
    sl_clamp_pct: Optional[Tuple[float, float]] = None  # (min,max) in frazione, applicato allo SL ATR
    tp_rr: Optional[float] = None           # TP = tp_rr * distanza SL (ha priorita' su tp_atr/tp_pct)
    max_hold_bars: int = 48
    ratchets: tuple = ()                    # ((trigger_R, lock_R), ...)
    pct_ratchets: tuple = ()                # ((trigger_frac, lock_frac), ...) in % di prezzo
    breakeven_R: Optional[float] = None
    trailing_atr: Optional[float] = None    # chandelier sui close
    flatten_eod: bool = False
    hard_close_loss_pct: Optional[float] = None   # chiusura software a close (frazione)
    hard_close_gain_pct: Optional[float] = None

    def levels(self, side: int, entry: float, atr: float):
        """-> (sl_price, tp_price, risk_dist) oppure None se ATR necessario ma non disponibile."""
        ok_atr = atr == atr and atr > 0
        if self.sl_pct is not None:
            sd = entry * self.sl_pct
        elif self.sl_atr is not None:
            if not ok_atr:
                return None
            sd = self.sl_atr * atr
            if self.sl_clamp_pct is not None:
                sd = min(max(sd, entry * self.sl_clamp_pct[0]), entry * self.sl_clamp_pct[1])
        else:
            raise ValueError("ExitRules richiede sl_atr o sl_pct")
        if self.tp_rr is not None:
            td = self.tp_rr * sd
        elif self.tp_pct is not None:
            td = entry * self.tp_pct
        elif self.tp_atr is not None:
            if not ok_atr:
                return None
            td = self.tp_atr * atr
        else:
            td = None
        tp = entry + side * td if td is not None else side * INF
        return entry - side * sd, tp, sd


LEGACY_BOT_RULES = ExitRules(
    sl_atr=1.4, sl_clamp_pct=(0.009, 0.018), tp_rr=3.0, tp_atr=None,
    pct_ratchets=((0.004, -0.003), (0.008, 0.002), (0.012, 0.006), (0.016, 0.010)),
    hard_close_loss_pct=0.012, hard_close_gain_pct=0.036, max_hold_bars=48,
)


def wilder_atr(h, l, c, n: int = 14) -> np.ndarray:
    """ATR di Wilder causale: valore alla barra t usa solo dati <= t."""
    m = len(c)
    out = np.full(m, np.nan)
    if m < n:
        return out
    tr = np.empty(m)
    tr[0] = h[0] - l[0]
    pc = c[:-1]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    a = tr[:n].mean()
    out[n - 1] = a
    for i in range(n, m):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def simulate_trade(o, h, l, c, entry_idx, side, entry_price, sl_price, tp_price, rules: ExitRules,
                   atr_at_entry=float("nan"), session_last_bar_mask=None):
    """-> (exit_idx, exit_price, reason). Entry all'apertura di entry_idx."""
    n = len(c)
    s = 1 if side > 0 else -1
    stop, tp = float(sl_price), float(tp_price)
    entry = float(entry_price)
    risk = abs(entry - stop)
    rl = [(a * risk, b * risk) for a, b in rules.ratchets]
    rl += [(a * entry, b * entry) for a, b in rules.pct_ratchets]
    if rules.breakeven_R is not None:
        rl.append((rules.breakeven_R * risk, 0.0))
    trail = rules.trailing_atr * atr_at_entry if (rules.trailing_atr and atr_at_entry == atr_at_entry) else None
    hl, hg = rules.hard_close_loss_pct, rules.hard_close_gain_pct
    last_hold = entry_idx + rules.max_hold_bars - 1
    last = min(n - 1, last_hold)
    best = 0.0
    bestc = entry
    eod = rules.flatten_eod and session_last_bar_mask is not None
    for i in range(entry_idx, last + 1):
        oi = o[i]
        if s == 1:
            if oi <= stop:
                return i, float(oi), "SL_GAP"
            if oi >= tp:
                return i, float(oi), "TP_GAP"
            if l[i] <= stop:
                return i, stop, "SL"
            if h[i] >= tp:
                return i, tp, "TP"
        else:
            if oi >= stop:
                return i, float(oi), "SL_GAP"
            if oi <= tp:
                return i, float(oi), "TP_GAP"
            if h[i] >= stop:
                return i, stop, "SL"
            if l[i] <= tp:
                return i, tp, "TP"
        ci = c[i]
        exc = s * (ci - entry)
        if hl is not None and exc <= -hl * entry:
            return i, float(ci), "HARD_SL"
        if hg is not None and exc >= hg * entry:
            return i, float(ci), "HARD_TP"
        if exc > best:
            best = exc
        for trig, lock in rl:
            if best >= trig:
                new = entry + s * lock
                if s * (new - stop) > 0:
                    stop = new
        if trail is not None:
            if s * (ci - bestc) > 0:
                bestc = ci
            new = bestc - s * trail
            if s * (new - stop) > 0:
                stop = new
        if i == last_hold:
            return i, float(ci), "TIME"
        if eod and session_last_bar_mask[i]:
            return i, float(ci), "EOD_SESSION"
    return last, float(c[last]), "EOD_DATA"
