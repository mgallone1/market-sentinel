"""Backtester a pesi target giornalieri + metriche + bootstrap (portafoglio multi-asset)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant.validation import deflated_sharpe_ratio  # noqa: F401  (ri-esportata per i report)


@dataclass
class PortfolioResult:
    net: pd.Series
    gross: pd.Series
    turnover: pd.Series
    weights: pd.DataFrame      # pesi effettivamente tenuti nel giorno t (decisi a t-1)
    costs: pd.Series           # costi totali (trading + borrow) in frazione di NAV


def run_weights(prices: pd.DataFrame, weights: pd.DataFrame, cost_bps: pd.Series,
                borrow_annual: pd.Series, cash_rate: float = 0.0) -> PortfolioResult:
    """Pesi decisi alla chiusura t, applicati da close t a close t+1 (shift di 1 giorno).
    Asset senza prezzo ancora disponibile (a t-1 o a t): peso 0, nessun backfill.
    Giorni senza prezzo nuovo (festivi): prezzo ffill => rendimento 0, nessun turnover (pesi tenuti)."""
    idx = prices.index
    px = prices.reindex(columns=weights.columns)
    pxf = px.ffill()
    rets = pxf.pct_change(fill_method=None).fillna(0.0)
    w = weights.reindex(idx).ffill().fillna(0.0)
    w = w.where(px.notna().cummax())               # nessun peso prima del primo prezzo
    w = w.fillna(0.0)
    wh = w.shift(1).fillna(0.0)                    # peso tenuto in t = deciso a t-1
    wh = wh.where(pxf.shift(1).notna(), 0.0)
    gross = (wh * rets).sum(axis=1) + (1 - wh.sum(axis=1)) * cash_rate / 252
    turn = wh.diff().abs().fillna(wh.abs())
    bps = cost_bps.reindex(wh.columns).fillna(0.0).values / 1e4
    trade_cost = (turn * bps).sum(axis=1)
    bor = borrow_annual.reindex(wh.columns).fillna(0.0).values / 252
    borrow_cost = ((-wh).clip(lower=0) * bor).sum(axis=1)
    costs = trade_cost + borrow_cost
    return PortfolioResult(gross - costs, gross, turn.sum(axis=1), wh, costs)


def metrics(r: pd.Series, bench: pd.Series | None = None) -> dict:
    r = r.dropna()
    n = len(r)
    if n < 30:
        return {}
    eq = (1 + r).cumprod()
    yrs = n / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1.0
    vol = r.std(ddof=1) * np.sqrt(252)
    sh = r.mean() / r.std(ddof=1) * np.sqrt(252) if r.std() > 0 else np.nan
    dn = r[r < 0].std(ddof=1) * np.sqrt(252) if (r < 0).sum() > 2 else np.nan
    mdd = float((eq / eq.cummax() - 1).min())
    m = (1 + r).groupby([r.index.year, r.index.month]).prod() - 1
    out = dict(cagr=float(cagr), vol=float(vol), sharpe=float(sh), sortino=float(r.mean() * 252 / dn) if dn else np.nan,
               maxdd=mdd, calmar=float(cagr / abs(mdd)) if mdd < 0 else np.nan, skew=float(r.skew()),
               worst_month=float(m.min()), pct_pos_months=float((m > 0).mean()), n_days=int(n))
    if bench is not None:
        a = pd.concat([r, bench], axis=1).dropna()
        out["corr_bench"] = float(a.iloc[:, 0].corr(a.iloc[:, 1])) if len(a) > 30 else np.nan
    return out


def _sharpe(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=-1) / x.std(axis=-1, ddof=1) * np.sqrt(252)


def block_bootstrap_sharpe_diff(r_a, r_b, block: int = 20, n: int = 2000, seed: int = 0):
    """Bootstrap stazionario circolare (blocchi geometrici, media `block`) su rendimenti allineati.
    Restituisce (diff_osservata, lo95, hi95) di Sharpe(a)-Sharpe(b) annualizzato."""
    df = pd.concat([pd.Series(r_a), pd.Series(r_b)], axis=1).dropna()
    a, b = df.iloc[:, 0].values, df.iloc[:, 1].values
    T = len(a)
    rng = np.random.default_rng(seed)
    idx = np.empty((n, T), dtype=np.int64)
    idx[:, 0] = rng.integers(0, T, n)
    new = rng.random((n, T)) < 1.0 / block
    starts = rng.integers(0, T, (n, T))
    for t in range(1, T):
        idx[:, t] = np.where(new[:, t], starts[:, t], (idx[:, t - 1] + 1) % T)
    d = _sharpe(a[idx]) - _sharpe(b[idx])
    obs = float(_sharpe(a) - _sharpe(b))
    return obs, float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))
