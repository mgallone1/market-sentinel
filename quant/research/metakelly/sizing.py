"""Fractional Kelly sizing and the 70% gross-exposure portfolio constraint."""
from __future__ import annotations



import numpy as np
import pandas as pd

GROSS_CAP = 0.70
W_MAX = 0.10
MIN_ALLOC = 0.01


def kelly_fraction(p: np.ndarray, payoff_ratio: np.ndarray) -> np.ndarray:
    """f* = (p R - (1 - p)) / R for a binary bet paying R per unit risked (R > 0)."""
    p = np.asarray(p, float)
    R = np.asarray(payoff_ratio, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        f = (p * R - (1.0 - p)) / R
    return np.where(np.isfinite(f) & (R > 0), f, 0.0)


def kelly_weights(p, payoff_ratio, c: float, w_max: float = W_MAX) -> np.ndarray:
    """w = clip(c f*, 0, w_max); f* <= 0 -> 0 (trade not taken, no hard threshold)."""
    return np.clip(float(c) * kelly_fraction(p, payoff_ratio), 0.0, float(w_max))


def simulate_portfolio(
    events: pd.DataFrame,
    desired_w: np.ndarray,
    cap: float = GROSS_CAP,
    min_alloc: float = MIN_ALLOC,
    one_per_symbol: bool = True,
) -> pd.DataFrame:
    """Allocate weights chronologically under a gross cap and one open trade per symbol.

    events: columns t0, t1, symbol, ret (net trade return). A trade asks for desired_w; it receives
    min(desired_w, cap - open_gross) and is skipped if that is < min_alloc, if desired_w <= 0, or if
    the symbol already has an open trade. Positions free their weight strictly after t1.
    Returns the taken trades with column `w` and `pnl` = w * ret.
    """
    ev = events.reset_index(drop=True).copy()
    ev["w_req"] = np.asarray(desired_w, float)
    order = np.argsort(ev["t0"].to_numpy(), kind="stable")
    open_pos: list = []  # (t1, w, symbol)
    taken_rows, taken_w = [], []
    for i in order:
        row = ev.iloc[i]
        t0 = row["t0"]
        open_pos = [op for op in open_pos if op[0] >= t0]
        wq = float(row["w_req"])
        if not (wq > 0.0):
            continue
        if one_per_symbol and any(op[2] == row["symbol"] for op in open_pos):
            continue
        gross = sum(op[1] for op in open_pos)
        w = min(wq, cap - gross)
        if w < min_alloc:
            continue
        open_pos.append((row["t1"], w, row["symbol"]))
        taken_rows.append(i)
        taken_w.append(w)
    out = ev.iloc[taken_rows].copy()
    out["w"] = taken_w
    out["pnl"] = out["w"] * out["ret"]
    return out.drop(columns=["w_req"]).sort_values("t0")


def max_gross_exposure(trades: pd.DataFrame) -> float:
    """Peak sum of weights of simultaneously open trades (checks the cap)."""
    if trades is None or trades.empty:
        return 0.0
    ev = [(t, w) for t, w in zip(trades["t0"], trades["w"])] + [(t, -w) for t, w in zip(trades["t1"], trades["w"])]
    # closings after openings at the same timestamp (a trade is open through t1)
    ev.sort(key=lambda x: (x[0], x[1] < 0))
    g, peak = 0.0, 0.0
    for _, dw in ev:
        g += dw
        peak = max(peak, g)
    return peak
