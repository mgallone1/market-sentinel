"""Esperimento pre-registrato TSMOM multi-asset. Uso: python -m quant.portfolio.run_experiment"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from quant.core import equity
from quant.data import load_bars
from quant.portfolio.backtest import block_bootstrap_sharpe_diff, metrics, run_weights
from quant.portfolio.tsmom import n_active, tsmom_weights
from quant.validation import deflated_sharpe_ratio

ETF = "SPY QQQ IWM EFA EEM VGK EWJ TLT IEF LQD HYG TIP GLD SLV USO DBC DBA UUP FXE FXY VNQ".split()
CRYPTO = ["BTC-USD", "ETH-USD"]
START, END = "2005-01-01", "2026-11-24"
OUT = Path("reports/tsmom_multiasset")


def load():
    px, dropped = {}, []
    for s in ETF + CRYPTO:
        try:
            spec = equity(s)
            b = load_bars(spec, "1d", START, END)
            c = b["close"].copy()
            c.index = c.index.normalize()
            c = c[~c.index.duplicated()]
            if len(c) < 300:
                raise RuntimeError("pochi dati")
            px[s] = c
        except Exception as e:  # noqa: BLE001
            dropped.append(f"{s}: {e}")
    df = pd.DataFrame(px)
    df = df[df.index.dayofweek < 5].sort_index()   # unione dei giorni lavorativi
    return df, dropped


def six_forty(prices, cost=2.0):
    p = prices[["SPY", "IEF"]].ffill().dropna()
    r = p.pct_change().fillna(0.0)
    out = pd.Series(0.0, index=p.index)
    w = pd.Series([0.6, 0.4], index=p.columns)
    month = p.index.tz_localize(None).to_period("M")
    prev = None
    for i, d in enumerate(p.index):
        if prev is not None and month[i] != month[i - 1]:
            tgt = pd.Series([0.6, 0.4], index=p.columns)
            out.iloc[i - 1] -= (w - tgt).abs().sum() * cost / 1e4   # costo di ribilanciamento a fine mese
            w = tgt
        out.iloc[i] += float((w * r.loc[d]).sum()) if prev is not None else 0.0
        if prev is not None:
            w = w * (1 + r.loc[d]); w = w / w.sum()
        prev = d
    return out


def main():
    df, dropped = load()
    crypto = {c for c in CRYPTO if c in df.columns}
    cost = pd.Series({c: (10.0 if c in crypto else 2.0) for c in df.columns})
    borrow = pd.Series({c: (0.0 if c in crypto else 0.01) for c in df.columns})
    na = n_active(df)
    start = na[na >= 10].index[0]
    runs = {}
    for mode in ("long_short", "long_only"):
        for fr in ("weekly", "monthly"):
            runs[f"{mode}_{fr}"] = run_weights(df, tsmom_weights(df, crypto, fr, mode), cost, borrow)
    runs["risk_parity_weekly"] = run_weights(df, tsmom_weights(df, crypto, "weekly", "risk_parity"), cost, borrow)
    rets = {k: v.net for k, v in runs.items()}
    rets["60_40_monthly"] = six_forty(df)
    rets["SPY_buy_hold"] = df["SPY"].ffill().pct_change().fillna(0.0)
    rets = {k: v.loc[start:] for k, v in rets.items()}
    spy = rets["SPY_buy_hold"]
    wins = {"full": (start, None), "post2013": ("2013-01-01", None)}
    crisis = {"2008-09..2009-03": ("2008-09-01", "2009-03-31"), "2020-02..2020-04": ("2020-02-01", "2020-04-30"),
              "2022": ("2022-01-01", "2022-12-31")}
    def _t(x):
        if x is None:
            return None
        x = pd.Timestamp(x)
        return x.tz_localize("UTC") if x.tzinfo is None else x

    def sl(r, a, b):
        return r.loc[_t(a):_t(b)]
    M = {k: {w: metrics(sl(r, *ab), sl(spy, *ab)) for w, ab in wins.items()} for k, r in rets.items()}
    C = {k: {c: float((1 + sl(r, *ab)).prod() - 1) for c, ab in crisis.items()} for k, r in rets.items()}
    Y = {k: {int(y): float(v) for y, v in ((1 + r).groupby(r.index.year).prod() - 1).items()} for k, r in rets.items()}
    variants = [k for k in rets if k.startswith(("long_short", "long_only"))]
    srs = [rets[k].mean() / rets[k].std(ddof=1) for k in variants]
    var_sr = float(np.var(srs, ddof=1))
    rp = rets["risk_parity_weekly"]
    V = {}
    for k in variants:
        dsr = float(deflated_sharpe_ratio(rets[k].values, 4, var_sr))
        blend = 0.5 * rets[k] + 0.5 * rp
        obs, lo, hi = block_bootstrap_sharpe_diff(blend, rp, 20, 2000)
        post = M[k]["post2013"]["sharpe"]
        a, b, c = dsr > 0.95, post > 0, lo > 0
        V[k] = dict(dsr=dsr, sharpe_post2013=post, blend_minus_rp_sharpe=obs, ci95=[lo, hi],
                    blend_sharpe=float(metrics(blend)["sharpe"]),
                    pass_a_dsr=bool(a), pass_b_post2013=bool(b), pass_c_blend=bool(c),
                    verdict="KEEP" if (a and b and c) else "DISCARD",
                    failed=[n for n, ok in zip("abc", (a, b, c)) if not ok])
        _, l2, h2 = block_bootstrap_sharpe_diff(rets[k], spy, 20, 2000)
        V[k]["vs_spy_sharpe_diff_ci95"] = [l2, h2]
    T = {k: dict(turnover_ann=float(runs[k].turnover.loc[start:].mean() * 252),
                 cost_drag_ann=float(runs[k].costs.loc[start:].mean() * 252),
                 gross_sharpe=float(metrics(runs[k].gross.loc[start:])["sharpe"]),
                 avg_gross_lev=float(runs[k].weights.loc[start:].abs().sum(axis=1).mean())) for k in runs}
    res = dict(universe_used=list(df.columns), dropped=dropped, first_date={c: str(df[c].first_valid_index().date()) for c in df.columns},
               start_full=str(start.date()), end=str(df.index[-1].date()), var_sr_trials=var_sr,
               metrics=M, crisis=C, yearly=Y, verdicts=V, turnover_cost=T)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: v for k, v in res.items() if k in ("universe_used", "dropped", "start_full", "end")}))
    for k in rets:
        m = M[k]["full"]; p = M[k]["post2013"]
        print(f"{k:22s} full SR {m['sharpe']:.2f} CAGR {m['cagr']:.1%} vol {m['vol']:.1%} DD {m['maxdd']:.1%} | post13 SR {p['sharpe']:.2f}")
    print(json.dumps(V, indent=1))


if __name__ == "__main__":
    sys.exit(main())
