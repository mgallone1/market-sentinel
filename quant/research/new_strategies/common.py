"""Shared metrics for the new-strategy backtests: per-trade stats, daily P&L, beta-adjusted series, DSR, PBO."""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from quant.validation.stats import deflated_sharpe_ratio, pbo_cscv

POSITION_WEIGHT = 0.10  # fraction of strategy capital per trade (as the lab and the bot base size)


def trade_stats(trades: pd.DataFrame) -> Dict[str, float]:
    n = len(trades)
    if n == 0:
        return {"n_trades": 0}
    r = trades["ret"].to_numpy(float)
    wins, losses = r[r > 0], r[r <= 0]
    avg_w = float(wins.mean()) if len(wins) else float("nan")
    avg_l = float(-losses.mean()) if len(losses) else float("nan")
    gl = float(-losses.sum())
    out = {
        "n_trades": int(n),
        "win_rate": float((r > 0).mean()),
        "avg_win": avg_w,
        "avg_loss": avg_l,
        "payoff": float(avg_w / avg_l) if (avg_l and avg_l > 0 and np.isfinite(avg_w)) else float("nan"),
        "expectancy": float(r.mean()),
        "expectancy_r": float(trades["r_multiple"].mean()) if "r_multiple" in trades else float("nan"),
        "profit_factor": float(wins.sum() / gl) if gl > 0 else float("inf"),
        "tp1_rate": float(trades["tp1_hit"].mean()) if "tp1_hit" in trades else float("nan"),
    }
    if "exit_reason" in trades:
        out["exits"] = trades["exit_reason"].value_counts().to_dict()
    return out


def daily_series(trades: pd.DataFrame, calendar: pd.DatetimeIndex, tz: str = "UTC",
                 weight: float = POSITION_WEIGHT) -> pd.Series:
    s = pd.Series(0.0, index=calendar)
    if len(trades):
        d = pd.DatetimeIndex(trades["exit_time"]).tz_convert(tz).normalize().tz_localize(None)
        g = pd.Series(weight * trades["ret"].to_numpy(float), index=d).groupby(level=0).sum()
        s = s.add(g.reindex(calendar).fillna(0.0), fill_value=0.0)
    return s


def beta_adjusted(daily: pd.Series, bench: pd.Series, window: int = 60, min_obs: int = 20) -> pd.Series:
    """R_excess,t = R_t - beta_t * R_bench,t, beta from the `window` days ending at t-1."""
    j = pd.concat([daily.rename("s"), bench.reindex(daily.index).fillna(0.0).rename("b")], axis=1).fillna(0.0)
    cov = j["s"].rolling(window, min_periods=min_obs).cov(j["b"])
    var = j["b"].rolling(window, min_periods=min_obs).var()
    beta = (cov / var.where(var > 0)).shift(1).fillna(0.0)
    return j["s"] - beta * j["b"]


def series_stats(daily: pd.Series, periods: float) -> Dict[str, float]:
    r = daily.to_numpy(float)
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    eq = (1.0 + daily).cumprod()
    return {
        "sharpe": float(r.mean() / sd * math.sqrt(periods)) if sd > 0 else float("nan"),
        "total_return": float(eq.iloc[-1] - 1.0) if len(eq) else 0.0,
        "max_drawdown": float((eq / eq.cummax() - 1.0).min()) if len(eq) else 0.0,
        "sr_period": float(r.mean() / sd) if sd > 0 else float("nan"),
    }


def dsr_and_pbo(series: Dict[str, pd.Series]) -> Dict[str, Dict[str, float]]:
    names = list(series)
    srs = np.array([series[n].mean() / series[n].std(ddof=1) if series[n].std(ddof=1) > 0 else np.nan for n in names])
    var_sr = float(np.nanvar(srs)) if np.isfinite(srs).sum() > 1 else 0.0
    out = {n: {"dsr": deflated_sharpe_ratio(series[n].to_numpy(), len(names), var_sr)} for n in names}
    M = np.column_stack([series[n].to_numpy() for n in names]) if names else np.zeros((0, 0))
    pbo = float("nan")
    if M.shape[1] >= 2:
        S = 16
        while S > 2 and M.shape[0] < S * 5:
            S -= 2
        try:
            pbo = float(pbo_cscv(M, n_splits=S)[0])
        except Exception:  # noqa: BLE001
            pbo = float("nan")
    out["_pbo"] = {"pbo": pbo, "n_configs": len(names)}
    return out


def by_quarter(trades: pd.DataFrame) -> List[Dict[str, float]]:
    if not len(trades):
        return []
    q = pd.DatetimeIndex(trades["exit_time"]).tz_convert("UTC").tz_localize(None).to_period("Q").astype(str)
    rows = []
    for k, g in trades.groupby(q):
        s = trade_stats(g)
        rows.append({"quarter": k, "n": s["n_trades"], "win_rate": s["win_rate"], "expectancy": s["expectancy"],
                     "profit_factor": s["profit_factor"], "sum_ret": float(g["ret"].sum())})
    return rows


def recommend(main: Dict, control_e: Optional[float], quarters: List[Dict], dsr: float) -> Dict[str, object]:
    n = main.get("n_trades", 0)
    if n < 30:
        return {"verdict": "NON VALUTABILE", "criteria": {"n_trades>=30": False}}
    tot = sum(q["sum_ret"] for q in quarters)
    worst = min((q["sum_ret"] for q in quarters), default=0.0)
    crit = {
        "1_n>=100": n >= 100,
        "2_E>0_and_PF>1.10": main["expectancy"] > 0 and main["profit_factor"] > 1.10,
        "3_DSR>0.95": bool(dsr > 0.95),
        "4_E>control": control_e is not None and main["expectancy"] > control_e,
        "5_stable_quarters": tot > 0 and (worst >= 0 or -worst <= 0.5 * tot),
    }
    return {"verdict": "AVVIARE PAPER 6 MESI" if all(crit.values()) else "NON RACCOMANDATA", "criteria": crit}
