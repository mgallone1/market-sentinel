"""Test pre-registrato dell'anomalia overnight su SPY/QQQ/IWM (nessun tuning).

Overnight = close_{t-1} -> open_t (+ dividendo se ex-date t, reinvestito all'open);
intraday = open_t -> close_t. Identita': (1+on)(1+id) = 1+cc (cc = rendimento buy&hold
total return con dividendo reinvestito all'open ex-date).
Strategia O: compra MOC, vende MOO ogni giorno; costo c per lato su entrambe le gambe.
Uso: python -m quant.research.overnight
"""
from __future__ import annotations

import json
import math
import os
from datetime import date

import numpy as np
import pandas as pd

from quant.portfolio.backtest import block_bootstrap_sharpe_diff
from quant.validation.stats import deflated_sharpe_ratio

ASSETS = ("SPY", "QQQ", "IWM")
START, END = "2000-01-01", "2026-11-24"
SUBS = {"2000-2012": ("2000-01-01", "2012-12-31"), "2013-2026": ("2013-01-01", "2026-12-31")}
COST_GRID = (0.5, 1.0, 1.5, 2.0, 3.0)
KEEP_COST = 1.0           # bp per lato (regola KEEP)
SESSION_H = 6.5           # ore sessione regolare (frazione intraday del tasso risk-free)


def decompose(open_, close, div=None, split=None) -> pd.DataFrame:
    """Scompone in on / id / cc. `split` = azioni nuove per vecchia (es. 2 per 2:1) alla ex-date,
    da usare SOLO con prezzi non aggiustati per split (open_t e dividendo in azioni nuove)."""
    o, c = pd.Series(open_, dtype=float), pd.Series(close, dtype=float)
    d = pd.Series(0.0, index=o.index) if div is None else pd.Series(div, dtype=float).reindex(o.index).fillna(0.0)
    s = pd.Series(1.0, index=o.index) if split is None else pd.Series(split, dtype=float).reindex(o.index).fillna(1.0)
    s = s.where(s > 0, 1.0)
    on = (o + d) * s / c.shift(1) - 1.0
    idr = c / o - 1.0
    out = pd.DataFrame({"on": on, "id": idr})
    out["cc"] = (1 + out["on"]) * (1 + out["id"]) - 1
    return out.iloc[1:]


def apply_costs(on, c_bp: float):
    """Giro completo: acquisto al close (-c), vendita all'open (-c); c_bp in bp per lato."""
    c = c_bp / 1e4
    return (1 + pd.Series(on)) * (1 - c) ** 2 - 1


def effective_splits(open_, close, split) -> pd.Series:
    """Applica il fattore di split solo se i prezzi risultano NON aggiustati (salto ~1/s sulla ex-date)."""
    sp = pd.Series(split, dtype=float).reindex(open_.index).fillna(0.0)
    sp = sp[sp > 0]
    raw = open_ / close.shift(1) - 1
    keep = {}
    for dt, s in sp.items():
        if dt in raw.index and abs(raw[dt]) > 0.3 and abs((1 + raw[dt]) * s - 1) < 0.3:
            keep[dt] = s
    return pd.Series(keep, dtype=float)


def metrics(r) -> dict:
    r = pd.Series(r).dropna()
    n = len(r)
    if n < 3:
        return {}
    eq = (1 + r).cumprod()
    yrs = max((r.index[-1] - r.index[0]).days / 365.25, 1e-9)
    cagr = float(eq.iloc[-1] ** (1 / yrs) - 1) if eq.iloc[-1] > 0 else -1.0
    sd = float(r.std(ddof=1))
    return dict(n=n, cagr=cagr, vol=sd * math.sqrt(252),
                sharpe=float(r.mean() / sd * math.sqrt(252)) if sd > 0 else float("nan"),
                maxdd=float((eq / eq.cummax() - 1).min()), total=float(eq.iloc[-1] - 1))


def _bisect(f, lo=0.0, hi=200.0):
    """Radice di f (decrescente in c) in [lo, hi] bp; None se f(lo) <= 0."""
    if f(lo) <= 0:
        return None
    if f(hi) > 0:
        return float("inf")
    for _ in range(50):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if f(m) > 0 else (lo, m)
    return (lo + hi) / 2


def breakeven(on: pd.Series, bh_cagr: float) -> dict:
    return dict(
        sharpe0_bp=_bisect(lambda c: metrics(apply_costs(on, c))["sharpe"]),
        cagr_eq_bh_bp=_bisect(lambda c: metrics(apply_costs(on, c))["cagr"] - bh_cagr))


def load(sym: str):
    import yfinance as yf
    h = yf.Ticker(sym).history(start=START, end="2026-11-25", auto_adjust=False, actions=True)
    h.index = h.index.tz_localize(None).normalize()
    h = h[h.index < pd.Timestamp(date.today())]  # scarta la barra di oggi (possibile barra in formazione)
    sp = effective_splits(h["Open"], h["Close"], h["Stock Splits"])
    return h, decompose(h["Open"], h["Close"], h["Dividends"], sp), int(len(sp)), int((h["Stock Splits"] > 0).sum())


def load_rf(index) -> pd.DataFrame:
    import yfinance as yf
    irx = yf.download("^IRX", start="1999-12-01", end="2026-11-25", progress=False, auto_adjust=False)["Close"]
    irx = irx.iloc[:, 0] if isinstance(irx, pd.DataFrame) else irx
    irx.index = pd.to_datetime(irx.index).tz_localize(None).normalize()
    y = irx.shift(1).reindex(irx.index.union(index)).ffill().reindex(index) / 100.0  # tasso noto a t-1
    gap = pd.Series(index, index=index).diff().dt.days.fillna(1.0)
    f = SESSION_H / 24.0
    return pd.DataFrame({"rf_on": y * (gap - f) / 360.0, "rf_id": y * f / 360.0}).fillna(0.0)


def evaluate(sym: str, d: pd.DataFrame, rf: pd.DataFrame, n_boot: int = 2000) -> dict:
    on_net = apply_costs(d["on"], KEEP_COST)
    strat = {"O_net1bp": on_net, "O_gross": d["on"], "BH": d["cc"], "INTRADAY": d["id"]}
    res = {"periods": {}}
    for name, (a, b) in {"full": (None, None), **SUBS}.items():
        sl = slice(a, b)
        m = {k: metrics(v.loc[sl]) for k, v in strat.items()}
        if name == "full":
            m["O_net1bp"]["pct_bh_overnight"] = None
        lg = lambda s: float(np.log1p(s.loc[sl]).sum())
        m["pct_bh_total_return_overnight"] = lg(d["on"]) / lg(d["cc"]) if lg(d["cc"]) != 0 else None
        res["periods"][name] = m
    res["cost_sensitivity"] = {str(c): {p: metrics(apply_costs(d["on"], c).loc[slice(*(SUBS.get(p) or (None, None)))])
                                        for p in ("full", *SUBS)} for c in COST_GRID}
    res["breakeven"] = {p: breakeven(d["on"].loc[slice(*(SUBS.get(p) or (None, None)))],
                                     res["periods"][p]["BH"]["cagr"]) for p in ("full", *SUBS)}
    ex = {"O_net1bp": on_net - rf["rf_on"], "BH": d["cc"] - rf["rf_on"] - rf["rf_id"],
          "INTRADAY": d["id"] - rf["rf_id"]}
    res["excess_tbill"] = {p: {k: metrics(v.loc[slice(*(SUBS.get(p) or (None, None)))]) for k, v in ex.items()}
                           for p in ("full", *SUBS)}
    obs, lo, hi = block_bootstrap_sharpe_diff(on_net, d["cc"], block=20, n=n_boot, seed=0)
    res["bootstrap_sharpe_diff"] = dict(obs=obs, lo95=lo, hi95=hi)
    return res


def keep_rule(res: dict, dsr3: float) -> dict:
    f, bs = res["periods"]["full"], res["bootstrap_sharpe_diff"]
    subs_pos = all(res["periods"][p]["O_net1bp"]["sharpe"] > 0 for p in SUBS)
    conds = dict(sharpe_gt_bh=f["O_net1bp"]["sharpe"] > f["BH"]["sharpe"], ci_lo_gt0=bs["lo95"] > 0,
                 both_subperiods_positive=subs_pos, dsr3_gt_095=bool(dsr3 > 0.95))
    return dict(conditions=conds, verdict="KEEP" if all(conds.values()) else "DISCARD")


def run(out_dir: str = "reports/overnight", n_boot: int = 2000) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    results, nets, sanity = {}, {}, {}
    for s in ASSETS:
        h, d, n_eff, n_raw = load(s)
        rf = load_rf(d.index)
        results[s] = evaluate(s, d, rf, n_boot)
        nets[s] = apply_costs(d["on"], KEEP_COST)
        sanity[s] = dict(first=str(d.index[0].date()), last=str(d.index[-1].date()), n_days=len(d),
                         splits_in_data=n_raw, splits_applied=n_eff, n_dividends=int((h["Dividends"] > 0).sum()),
                         max_abs_on=float(d["on"].abs().max()), max_abs_id=float(d["id"].abs().max()))
    srs = [float(r.mean() / r.std(ddof=1)) for r in nets.values()]
    var_sr = float(np.var(srs, ddof=1))
    for s in ASSETS:
        r = nets[s]
        dsr3 = deflated_sharpe_ratio(r, 3, var_sr)
        dsr80 = deflated_sharpe_ratio(r, 80, var_sr)
        results[s]["dsr"] = dict(n_trials_3=dsr3, n_trials_80=dsr80)
        results[s]["keep"] = keep_rule(results[s], dsr3)
        results[s]["data_sanity"] = sanity[s]
    out = dict(spec=dict(assets=ASSETS, start=START, end=END, keep_cost_bp_per_side=KEEP_COST,
                         cost_grid_bp=COST_GRID, block=20, n_boot=n_boot, var_sr_trials=var_sr,
                         note="DSR: var_sr_trials = varianza tra i 3 asset dello Sharpe per-periodo netto"),
               results=results)
    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump(out, fh, indent=1, default=lambda x: None if x is None else float(x))
    return out


if __name__ == "__main__":
    o = run()
    for s, r in o["results"].items():
        print(s, r["keep"]["verdict"], r["keep"]["conditions"])
