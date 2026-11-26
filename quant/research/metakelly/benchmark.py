"""Daily P&L, rolling-beta excess returns and performance statistics."""
from __future__ import annotations

import math
from typing import Dict, Optional

import numpy as np
import pandas as pd

from quant.validation.stats import deflated_sharpe_ratio


def daily_pnl(trades: pd.DataFrame, calendar: pd.DatetimeIndex, tz: str = "UTC") -> pd.Series:
    """Realised P&L per day (sum of w * ret of trades closed that day), on a fixed daily calendar."""
    cal = pd.DatetimeIndex(calendar)
    s = pd.Series(0.0, index=cal)
    if trades is not None and len(trades):
        d = pd.DatetimeIndex(trades["t1"]).tz_convert(tz).normalize().tz_localize(None)
        g = pd.Series(trades["pnl"].to_numpy(float), index=d).groupby(level=0).sum()
        s = s.add(g.reindex(cal).fillna(0.0), fill_value=0.0)
    return s


def rolling_beta(strat: pd.Series, bench: pd.Series, window: int = 60, min_obs: int = 20) -> pd.Series:
    """beta_t = Cov(strat, bench) / Var(bench) on the `window` days ending at t-1 (point-in-time)."""
    j = pd.concat([strat.rename("s"), bench.rename("b")], axis=1).fillna(0.0)
    cov = j["s"].rolling(window, min_periods=min_obs).cov(j["b"])
    var = j["b"].rolling(window, min_periods=min_obs).var()
    beta = (cov / var.where(var > 0)).shift(1)
    return beta.fillna(0.0)


def beta_adjusted_excess(strat: pd.Series, bench: pd.Series, window: int = 60, min_obs: int = 20,
                         costs: Optional[pd.Series] = None) -> pd.DataFrame:
    """R_excess,t = R_strat,t - beta_t * R_bench,t - costs_t (costs default 0: strat is already net)."""
    beta = rolling_beta(strat, bench, window, min_obs)
    b = bench.reindex(strat.index).fillna(0.0)
    c = costs.reindex(strat.index).fillna(0.0) if costs is not None else 0.0
    exc = strat - beta * b - c
    return pd.DataFrame({"strat": strat, "bench": b, "beta": beta, "excess": exc})


def trade_excess(ret: np.ndarray, side: np.ndarray, beta_sym: np.ndarray, bench_ret: np.ndarray) -> np.ndarray:
    """Per-trade excess: r_i - side_i * beta_i * R_bench over the holding window."""
    return (np.asarray(ret, float) - np.asarray(side, float) * np.nan_to_num(np.asarray(beta_sym, float))
            * np.nan_to_num(np.asarray(bench_ret, float)))


def profit_factor(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    gains, losses = x[x > 0].sum(), -x[x < 0].sum()
    return float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else float("nan"))


def sharpe(daily: pd.Series, periods: float) -> float:
    r = np.asarray(daily, float)
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return float(r.mean() / sd * math.sqrt(periods)) if sd > 0 else float("nan")


def max_drawdown(daily: pd.Series) -> float:
    eq = (1.0 + pd.Series(daily).fillna(0.0)).cumprod()
    return float((eq / eq.cummax() - 1.0).min()) if len(eq) else float("nan")


def perf_summary(trades: pd.DataFrame, daily: pd.Series, excess: pd.Series, periods: float,
                 n_trials: int = 1, var_sr: float = 0.0, trade_exc: Optional[np.ndarray] = None) -> Dict[str, float]:
    n = int(len(trades)) if trades is not None else 0
    ret = trades["ret"].to_numpy(float) if n else np.array([])
    return {
        "n_trades": n,
        "win_rate": float((ret > 0).mean()) if n else float("nan"),
        "expectancy": float(ret.mean()) if n else float("nan"),
        "profit_factor": profit_factor(ret) if n else float("nan"),
        "profit_factor_excess": profit_factor(trade_exc) if (trade_exc is not None and len(trade_exc)) else float("nan"),
        "total_return": float((1.0 + daily).prod() - 1.0),
        "sharpe_net": sharpe(daily, periods),
        "sharpe_excess": sharpe(excess, periods),
        "excess_cum": float(excess.sum()),
        "dsr_net": deflated_sharpe_ratio(daily.to_numpy(), max(1, n_trials), var_sr),
        "dsr_excess": deflated_sharpe_ratio(excess.to_numpy(), max(1, n_trials), var_sr),
        "max_drawdown": max_drawdown(daily),
    }
