"""Test pre-registrato del volatility risk premium (V1 contango short-vol, V2 VRP timing). 2 trial, nessun tuning."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from quant.portfolio.backtest import block_bootstrap_sharpe_diff, metrics, run_weights
from quant.validation import deflated_sharpe_ratio

END = "2026-11-24"
SPLIT_V1 = "2018-03-01"
SPLIT_V2 = "2013-01-01"
OUT = Path("reports/vrp")
CACHE = Path("/tmp/claude-0/-home-user-market-sentinel/f5084918-97a8-57e5-9b0d-91a2d3322c5e/scratchpad/vrp_px.pkl")
TAIL = {"2018-02 (Volmageddon)": ("2018-02-01", "2018-02-28"), "2020 covid": ("2020-02-15", "2020-03-31"),
        "2008-09..2009-03": ("2008-09-01", "2009-03-31"), "2022": ("2022-01-01", "2022-12-31")}


# ---------- funzioni pure (testate offline) ----------
def cash_index(irx: pd.Series) -> pd.Series:
    """Indice T-bill: accrual giornaliero = tasso (^IRX/100) del giorno precedente / 252."""
    rate = (irx.ffill() / 100.0).shift(1).fillna(0.0) / 252.0
    return 100.0 * (1.0 + rate).cumprod()


def v1_signal(vix: pd.Series, vix3m: pd.Series) -> pd.Series:
    """1 se VIX_t/VIX3M_t < 1 (contango), 0 altrimenti (cash o dato mancante). Usa solo dati <= t."""
    ratio = vix / vix3m
    return (ratio < 1.0).astype(float)


def vrp_series(vix: pd.Series, spy: pd.Series) -> pd.Series:
    """VRP_t = (VIX/100)^2/12 - RV21^2*21 (RV = std rendimenti giornalieri SPY, 21gg). Solo dati <= t."""
    rv = spy.pct_change(fill_method=None).rolling(21).std(ddof=1)
    return (vix / 100.0) ** 2 / 12.0 - rv ** 2 * 21.0


def v2_signal(vix: pd.Series, spy: pd.Series, window: int = 60) -> pd.Series:
    """Pesi SPY (1/0) decisi a fine mese e tenuti (ffill) fino al fine mese successivo.
    VRP > mediana dei `window` mesi PRECEDENTI (esclude il mese corrente). NaN prima di avere storia."""
    v = vrp_series(vix, spy).dropna()
    me = v.groupby([v.index.year, v.index.month]).tail(1)          # ultimo giorno di trading di ogni mese
    med = me.shift(1).rolling(window).median()
    ok = med.notna()
    sig = (me > med).astype(float).where(ok)
    return sig.reindex(vix.index.union(sig.index)).ffill()


def monthly_rebal_60_40(rets: pd.DataFrame, w=(0.6, 0.4)) -> pd.Series:
    """Rendimento di un portafoglio ribilanciato a inizio mese ai pesi w (deriva nel mese)."""
    out = pd.Series(0.0, index=rets.index)
    for _, g in rets.groupby([rets.index.year, rets.index.month]):
        cum = (1 + g).cumprod() * np.array(w)
        val = cum.sum(axis=1)
        out.loc[g.index] = val.pct_change().fillna(val.iloc[0] - 1.0).values
    return out


# ---------- dati ----------
def load_prices() -> pd.DataFrame:
    if CACHE.exists():
        return pd.read_pickle(CACHE)
    import yfinance as yf
    tk = ["^VIX", "^VIX3M", "SPY", "IEF", "SVXY", "VXX", "^IRX"]
    for k in range(6):
        d = yf.download(tk, start="1990-01-01", end="2026-11-25", auto_adjust=True, progress=False)["Close"]
        if d.dropna(how="all").shape[0] > 1000 and d["^VIX3M"].notna().sum() > 100:
            break
        time.sleep(20 * (k + 1))
    d.index = pd.DatetimeIndex(d.index).tz_localize(None)
    d = d.loc[:END]
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    d.to_pickle(CACHE)
    return d


# ---------- metriche ----------
def full_metrics(r: pd.Series, rf: pd.Series, invested: pd.Series | None = None) -> dict:
    r = r.dropna()
    rfa = rf.reindex(r.index).fillna(0.0)
    m = metrics(r)
    if not m:
        return {}
    ex = r - rfa
    m["excess_sharpe"] = float(ex.mean() / ex.std(ddof=1) * np.sqrt(252))
    dn = ex[ex < 0].std(ddof=1) * np.sqrt(252)
    m["sortino"] = float(ex.mean() * 252 / dn) if dn else float("nan")
    m["worst_day"] = float(r.min())
    m["pct_invested"] = float((invested.reindex(r.index) > 0).mean()) if invested is not None else float("nan")
    m["start"], m["end"] = str(r.index[0].date()), str(r.index[-1].date())
    return m


def tail_table(series: dict[str, pd.Series]) -> dict:
    out = {}
    for name, (a, b) in TAIL.items():
        row = {}
        for k, s in series.items():
            x = s.dropna().loc[a:b]
            first = s.dropna().index[0]
            row[k] = float((1 + x).prod() - 1) if len(x) > 5 and first <= pd.Timestamp(a) + pd.Timedelta(days=5) else None
        out[name] = row
    return out


def run() -> dict:
    px = load_prices()
    cash = cash_index(px["^IRX"])
    rf = cash.pct_change().fillna(0.0)
    vix3m = px["^VIX3M"]
    P = pd.DataFrame({"SPY": px["SPY"], "IEF": px["IEF"], "SVXY": px["SVXY"], "CASH": cash}).dropna(subset=["CASH"])
    zero = pd.Series(0.0, index=P.columns)
    bps1 = pd.Series({"SVXY": 5.0, "CASH": 0.0, "SPY": 0.0, "IEF": 0.0})
    bps2 = pd.Series({"SPY": 2.0, "IEF": 2.0, "CASH": 0.0, "SVXY": 0.0})

    # V1
    s1 = v1_signal(px["^VIX"], vix3m).reindex(P.index).fillna(0.0)
    w1 = pd.DataFrame(0.0, index=P.index, columns=P.columns)
    w1["SVXY"], w1["CASH"] = s1, 1 - s1
    r1 = run_weights(P, w1, bps1, zero).net
    start1 = P["SVXY"].first_valid_index()
    r1 = r1.loc[start1:].iloc[1:]
    # V2
    s2 = v2_signal(px["^VIX"], px["SPY"]).reindex(P.index).ffill()
    start2 = max(P["IEF"].first_valid_index(), s2.first_valid_index())
    w2 = pd.DataFrame(0.0, index=P.index, columns=P.columns)
    w2["SPY"], w2["IEF"] = s2, 1 - s2
    w2 = w2.where(s2.notna(), 0.0)
    r2 = run_weights(P, w2, bps2, zero).net.loc[start2:].iloc[1:]

    rets = P.pct_change(fill_method=None)
    b_spy = rets["SPY"].dropna()
    b_svxy = rets["SVXY"].dropna()
    b_6040 = monthly_rebal_60_40(rets.loc[start2:, ["SPY", "IEF"]].dropna().iloc[1:])
    strat = {"V1": r1, "V2": r2, "SPY_BH": b_spy, "SVXY_BH": b_svxy, "60/40": b_6040}
    inv = {"V1": s1.shift(1), "V2": s2.shift(1).where(s2.shift(1).notna()), "SPY_BH": pd.Series(1.0, index=P.index),
           "SVXY_BH": pd.Series(1.0, index=P.index), "60/40": pd.Series(1.0, index=P.index)}
    res = {"data_ranges": {c: [str(px[c].first_valid_index().date()), str(px[c].last_valid_index().date())] for c in px},
           "vix3m_used": "^VIX3M", "metrics": {}, "tails": tail_table(strat)}
    for k, r in strat.items():
        res["metrics"][k] = {"full": full_metrics(r, rf, inv[k])}
        post = r.loc[SPLIT_V1:] if k in ("V1", "SVXY_BH") else r.loc[SPLIT_V2:]
        res["metrics"][k]["post"] = full_metrics(post, rf, inv[k])
    res["metrics"]["V1"]["pre_2018_03"] = full_metrics(r1.loc[:"2018-02-28"], rf, inv["V1"])
    res["metrics"]["SVXY_BH"]["pre_2018_03"] = full_metrics(b_svxy.loc[:"2018-02-28"], rf, inv["SVXY_BH"])
    res["metrics"]["V1"]["post_2018_03"] = res["metrics"]["V1"]["post"]

    # validazione
    ex = {k: (strat[k] - rf.reindex(strat[k].index).fillna(0.0)) for k in strat}
    common = pd.concat([ex["V1"], ex["V2"]], axis=1).dropna()
    srs = [common[c].mean() / common[c].std(ddof=1) for c in common]
    var_sr = float(np.var(srs, ddof=1))
    verdicts = {}
    for k, bench, post_key in (("V1", "SVXY_BH", "post"), ("V2", "SPY_BH", "post")):
        obs, lo, hi = block_bootstrap_sharpe_diff(ex[k], ex[bench])
        d2 = float(deflated_sharpe_ratio(ex[k].values, 2, var_sr))
        d80 = float(deflated_sharpe_ratio(ex[k].values, 80, var_sr))
        post_sh = res["metrics"][k]["post"]["excess_sharpe"]
        crit = {"dsr_n2>0.95": d2 > 0.95, "excess_sharpe_post>0": post_sh > 0, "boot_lo95>0": lo > 0}
        if k == "V1":
            crit["worst_day>-25%"] = res["metrics"][k]["full"]["worst_day"] > -0.25
        verdicts[k] = dict(dsr_n2=d2, dsr_n80=d80, var_sr_trials=var_sr, excess_sharpe_post=post_sh,
                           boot_obs=obs, boot_lo95=lo, boot_hi95=hi, bench=bench, criteria=crit,
                           verdict="KEEP" if all(crit.values()) else "DISCARD",
                           failed=[c for c, v in crit.items() if not v])
    res["verdicts"] = verdicts
    return res


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    out = run()
    (OUT / "report.json").write_text(json.dumps(out, indent=1, default=lambda o: None if o != o else str(o)))
    print(json.dumps(out["verdicts"], indent=1))
