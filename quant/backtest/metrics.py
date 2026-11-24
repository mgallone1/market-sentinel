from __future__ import annotations

import numpy as np
import pandas as pd


def compute_metrics(trades: pd.DataFrame, equity: pd.Series, periods_per_year: float) -> dict:
    m: dict = {"n_trades": int(len(trades))}
    nan = float("nan")
    if len(trades):
        r = trades["ret_net"]
        w, lo = r[r > 0], r[r <= 0]
        aw = float(w.mean()) if len(w) else 0.0
        al = float(-lo.mean()) if len(lo) else 0.0
        gp, gl = float(w.sum()), float(-lo.sum())
        gross = float(trades["gross_pnl"].sum())
        m.update(win_rate=float(len(w) / len(r)), avg_win=aw, avg_loss=al,
                 payoff=aw / al if al > 0 else nan, profit_factor=gp / gl if gl > 0 else nan,
                 expectancy_ret=float(r.mean()), expectancy_R=float(trades["R"].mean()),
                 avg_bars_held=float(trades["bars_held"].mean()),
                 exit_reasons=trades["reason"].value_counts(normalize=True).to_dict(),
                 cost_share=float(trades["costs"].sum() / abs(gross)) if gross != 0 else nan)
    else:
        m.update(win_rate=nan, avg_win=nan, avg_loss=nan, payoff=nan, profit_factor=nan,
                 expectancy_ret=nan, expectancy_R=nan, avg_bars_held=nan, exit_reasons={}, cost_share=nan)
    eq = equity.astype(float)
    if len(eq) > 1:
        e0, e1 = float(eq.iloc[0]), float(eq.iloc[-1])
        years = len(eq) / periods_per_year
        rets = eq.pct_change().dropna()
        sd = float(rets.std())
        dd = float(np.sqrt((np.minimum(rets, 0) ** 2).mean()))
        m["total_return"] = e1 / e0 - 1
        m["CAGR"] = (e1 / e0) ** (1 / years) - 1 if e1 > 0 and years > 0 else nan
        m["sharpe"] = float(rets.mean() / sd * np.sqrt(periods_per_year)) if sd > 0 else nan
        m["sortino"] = float(rets.mean() / dd * np.sqrt(periods_per_year)) if dd > 0 else nan
        m["max_drawdown"] = float((eq / eq.cummax() - 1).min())
        m["exposure"] = float(trades["bars_held"].sum() / len(eq)) if len(trades) else 0.0
        m["turnover"] = float(2 * trades["notional"].sum() / e0) if len(trades) else 0.0
    else:
        m.update(total_return=nan, CAGR=nan, sharpe=nan, sortino=nan, max_drawdown=nan, exposure=nan, turnover=nan)
    return m
