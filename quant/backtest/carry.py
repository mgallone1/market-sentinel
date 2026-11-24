"""Funding carry delta-neutral: SHORT perp + LONG spot (a notional uguale). Regola pre-registrata, nessun fit.

Segnale al funding event k (barra con funding_rate non NaN): media degli ultimi `n_prints` print (incluso k,
noto all'open della barra k) annualizzata; entra se > entry_apr, esce se < exit_apr (reverse: simmetrico se
allow_reverse). Esecuzione all'open della barra successiva su ENTRAMBE le gambe.
Funding: la barra i incassa funding se la posizione e' gia' aperta a fine barra i-1 (conservativo: nessun
funding sulla barra di ingresso). Costi: fee taker (o maker) + slippage su entrambe le gambe, entrata e uscita.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.core import COST_PRESETS, interval_to_hours


@dataclass
class CarryResult:
    trades: pd.DataFrame
    equity: pd.Series
    metrics: dict = field(default_factory=dict)


TRADE_COLS = ["enter_ts", "exit_ts", "dir", "funding", "basis_pnl", "fees", "slippage", "net", "bars_held"]


def _daily_metrics(eq: pd.Series, pos_frac: float, decomp: dict) -> dict:
    nan = float("nan")
    m = dict(decomp)
    if len(eq) < 3:
        return {**m, "CAGR": nan, "sharpe": nan, "max_drawdown": nan, "time_in_market": pos_frac}
    d = eq.resample("1D").last().dropna()
    r = d.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    m["CAGR"] = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) if yrs > 0 and eq.iloc[-1] > 0 else nan
    m["sharpe"] = float(r.mean() / r.std() * np.sqrt(365)) if len(r) > 2 and r.std() > 0 else nan
    m["max_drawdown"] = float((eq / eq.cummax() - 1).min())
    m["time_in_market"] = pos_frac
    return m


def run_carry(perp: pd.DataFrame, spot: pd.DataFrame, interval: str = "1h", entry_apr: float = 0.10,
              exit_apr: float = 0.03, n_prints: int = 9, leg_frac: float = 0.5, allow_reverse: bool = False,
              entry_mode: str = "taker", initial_equity: float = 100_000.0, perp_cost: str = "bybit_perp",
              spot_cost: str = "crypto_spot") -> CarryResult:
    idx = perp.index.intersection(spot.index)
    perp, spot = perp.loc[idx], spot.loc[idx]
    n = len(idx)
    po, pc = perp["open"].to_numpy(float), perp["close"].to_numpy(float)
    so, sc = spot["open"].to_numpy(float), spot["close"].to_numpy(float)
    fr = perp["funding_rate"].to_numpy(float) if "funding_rate" in perp.columns else np.full(n, np.nan)
    ev = np.flatnonzero(~np.isnan(fr))
    maker = entry_mode == "maker"
    cp, cs = COST_PRESETS[perp_cost], COST_PRESETS[spot_cost]
    fee_p = cp.maker_fee if maker else cp.taker_fee
    fee_s = cs.maker_fee if maker else cs.taker_fee
    slip_p, slip_s = (0.0, 0.0) if maker else (cp.slippage_bps / 1e4, cs.slippage_bps / 1e4)
    # annualizzazione: print/anno dalla mediana della spaziatura tra eventi
    if len(ev) >= 2:
        gap_h = float(np.median(np.diff(ev))) * interval_to_hours(interval)
        ppy_f = 8760.0 / gap_h if gap_h > 0 else 1095.0
    else:
        ppy_f = 1095.0
    # macchina a stati sugli eventi: lista (entry_bar, exit_bar, dir) con dir=-1 short perp
    plans, cur = [], None
    for k, i in enumerate(ev):
        if k + 1 < n_prints or i + 1 >= n:
            continue
        apr = float(np.mean(fr[ev[k - n_prints + 1:k + 1]])) * ppy_f
        if cur is None:
            if apr > entry_apr:
                cur = [i + 1, None, -1]
            elif allow_reverse and apr < -entry_apr:
                cur = [i + 1, None, +1]
        else:
            out = apr < exit_apr if cur[2] < 0 else apr > -exit_apr
            if out:
                cur[1] = i + 1
                plans.append(tuple(cur))
                cur = None
    if cur is not None:
        cur[1] = n                      # chiusura forzata a fine dati (close ultima barra)
        plans.append(tuple(cur))
    dpnl = np.zeros(n)
    rows, eq_run, inpos = [], float(initial_equity), np.zeros(n, bool)
    carry_eq = np.full(n, np.nan)
    last_i = 0
    for e, x, d in plans:
        # equity prima dell'ingresso = equity corrente fino a e-1
        base = initial_equity + dpnl[:e].sum()
        notional = leg_frac * base
        qp, qs = notional / po[e], notional / so[e]
        sp, ss = d, -d                   # lato perp, lato spot (perp short <-> spot long)
        last = min(x, n) - 1             # ultima barra con posizione piena
        prev_p, prev_s = po[e], so[e]
        basis = fund = 0.0
        for i in range(e, last + 1):
            b = sp * qp * (pc[i] - prev_p) + ss * qs * (sc[i] - prev_s)
            prev_p, prev_s = pc[i], sc[i]
            f = 0.0
            if i > e and fr[i] == fr[i]:
                f = -sp * fr[i] * qp * po[i]          # perp short (sp=-1) incassa se funding>0
            dpnl[i] += b + f
            basis += b
            fund += f
        inpos[e:last + 1] = True
        if x < n:                          # gap close(x-1) -> open(x) ed eventuale funding all'open x
            b = sp * qp * (po[x] - prev_p) + ss * qs * (so[x] - prev_s)
            f = -sp * fr[x] * qp * po[x] if fr[x] == fr[x] else 0.0
            dpnl[x] += b + f
            basis += b
            fund += f
            xp_p, xp_s, xbar = po[x], so[x], x
        else:
            xp_p, xp_s, xbar = pc[n - 1], sc[n - 1], n - 1
        fe = qp * po[e] * fee_p + qs * so[e] * fee_s
        fx = qp * xp_p * fee_p + qs * xp_s * fee_s
        se = qp * po[e] * slip_p + qs * so[e] * slip_s
        sx = qp * xp_p * slip_p + qs * xp_s * slip_s
        fees, slip = fe + fx, se + sx
        dpnl[e] -= fe + se
        dpnl[xbar] -= fx + sx
        rows.append(dict(enter_ts=idx[e], exit_ts=idx[xbar], dir=d, funding=fund, basis_pnl=basis, fees=fees,
                         slippage=slip, net=fund + basis - fees - slip, bars_held=xbar - e))
    equity = pd.Series(initial_equity + np.cumsum(dpnl), index=idx, name="equity")
    trades = pd.DataFrame(rows, columns=TRADE_COLS)
    gross = trades["funding"].sum() + trades["basis_pnl"].sum() if len(trades) else 0.0
    decomp = dict(n_trades=len(trades), funding=float(trades["funding"].sum()), basis=float(trades["basis_pnl"].sum()),
                  fees=float((trades["fees"] + trades["slippage"]).sum()), net=float(trades["net"].sum()),
                  funding_share=float(trades["funding"].sum() / gross) if gross else float("nan"))
    return CarryResult(trades, equity, _daily_metrics(equity, float(inpos.mean()) if n else 0.0, decomp))


def combine_equal_weight(results: dict) -> CarryResult:
    """Portafoglio equal-weight (capitale diviso in parti uguali, nessun ribilanciamento)."""
    eqs = pd.concat({k: r.equity / r.equity.iloc[0] for k, r in results.items()}, axis=1).ffill().bfill()
    eq = eqs.mean(axis=1) * 100_000.0
    tr = pd.concat([r.trades.assign(symbol=k) for k, r in results.items()], ignore_index=True)
    tim = float(np.mean([r.metrics["time_in_market"] for r in results.values()]))
    scale = 1.0 / len(results)
    dec = {k: float(sum(r.metrics[k] for r in results.values()) * scale)
           for k in ("funding", "basis", "fees", "net")}
    g = dec["funding"] + dec["basis"]
    dec.update(n_trades=len(tr), funding_share=dec["funding"] / g if g else float("nan"))
    return CarryResult(tr, eq, _daily_metrics(eq, tim, dec))


def run_carry_universe(symbols, start="2023-11-01", end="2026-11-01", interval: str = "1h", **kw):
    """-> (CarryResult equal-weight, {sym: CarryResult}). Perp: Binance Vision um (con funding), spot: Binance spot."""
    from quant.data import binance_vision as bv
    res = {}
    for s in symbols:
        perp = bv.get_bars(s, interval, start, end, market="um")
        spot = bv.get_bars(s, interval, start, end, market="spot")
        res[s] = run_carry(perp, spot, interval, **kw)
    return combine_equal_weight(res), res
