"""Esperimento pre-registrato E1-E4 (turn-of-month, rotazione settori/paesi). Uso: python -m quant.portfolio.equity_rotation"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant.portfolio.backtest import block_bootstrap_sharpe_diff, metrics, run_weights
from quant.validation import deflated_sharpe_ratio

OUT = Path("reports/equity_rotation")
COST_BPS = 2.0
SECTORS = "XLK XLF XLV XLE XLI XLY XLP XLU XLB XLRE XLC".split()
COUNTRIES = "EWJ EWG EWU EWC EWA EWZ EWH EWS EWT EWY EWW EWQ EWI EWP EWL EWN EWD INDA FXI EIDO".split()
BASKET = ["SPY", "QQQ", "IWM", "EFA"]
N_TRIALS_DSR = 100


# ---------------------------------------------------------------- segnali (puri, solo dati <= t)
def cash_daily(irx: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Rendimento giornaliero T-bill da ^IRX (% annuo /100/252), ffill sul calendario."""
    return (irx.reindex(index.union(irx.index)).ffill().reindex(index) / 100.0 / 252).fillna(0.0)


def tom_flags(index: pd.DatetimeIndex) -> pd.Series:
    """True al close t se si detiene t->t+1: penultimo, ultimo giorno di borsa del mese, 1o e 2o del successivo
    (posizione chiusa al close del 3o giorno). Calendario = quello reale dei dati."""
    s = pd.Series(np.arange(len(index)), index=index)
    key = pd.Series(index.to_period("M"), index=index)
    from_start = s.groupby(key).cumcount()
    from_end = s.groupby(key).cumcount(ascending=False)
    last_key = key.iloc[-1]
    # ultimo mese dei dati incompleto: i giorni "da fine" non sono noti
    if (last_key.end_time.normalize() - index[-1]).days > 3:
        from_end = from_end.where(key != last_key, 99)
    return ((from_end <= 1) | (from_start <= 1)).astype(bool)


def month_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby(index.to_period("M")).max().values)


def rotation_weights(prices: pd.DataFrame, cash_d: pd.Series, top_n: int):
    """Fine mese j: momentum 12-1 = P[j-1]/P[j-12]-1 sui close di fine mese; ammesso solo con 13 mesi di storia.
    Top-n per momentum, tenuto solo se mom > rendimento T-bill sulla stessa finestra, altrimenti slot in cash.
    Restituisce (pesi alle date di fine mese, matrice eleggibilita')."""
    me = month_ends(prices.index)
    M = prices.loc[me]
    C = (1 + cash_d).cumprod().loc[me]
    first = M.notna().values.argmax(axis=0)
    first = np.where(M.notna().any().values, first, 10 ** 9)
    mom = M.shift(1) / M.shift(12) - 1
    pos = np.arange(len(me))[:, None]
    mom = mom.where(pos - 12 >= first[None, :])
    cret = C.shift(1) / C.shift(12) - 1
    W = pd.DataFrame(0.0, index=me, columns=prices.columns)
    for i, d in enumerate(me):
        m = mom.loc[d].dropna()
        if m.empty:
            continue
        sel = m.sort_values(ascending=False, kind="stable").index[:top_n]
        sel = [a for a in sel if m[a] > cret.loc[d]]
        W.loc[d, sel] = 1.0 / top_n
    return W, mom.notna()


def ew_weights(elig: pd.DataFrame) -> pd.DataFrame:
    n = elig.sum(axis=1).replace(0, np.nan)
    return elig.astype(float).div(n, axis=0).fillna(0.0)


# ---------------------------------------------------------------- esecuzione
def run(prices: pd.DataFrame, weights: pd.DataFrame, cash_d: pd.Series, bps: float = COST_BPS):
    """Netto = rendimenti pesati - costi su turnover + cash sulla quota non investita."""
    cols = weights.columns
    res = run_weights(prices[cols], weights, pd.Series(bps, index=cols), pd.Series(0.0, index=cols))
    cash_part = (1 - res.weights.sum(axis=1)).clip(lower=0) * cash_d.reindex(res.net.index).fillna(0.0)
    return res, res.net + cash_part, res.gross + cash_part


def tom_weights(prices: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    f = tom_flags(prices.index)
    return pd.DataFrame({c: f.astype(float) / len(cols) for c in cols})


def block_bootstrap_sharpe(r, block: int = 20, n: int = 2000, seed: int = 0):
    """(obs, lo95, hi95) dello Sharpe annualizzato di una serie (stesso bootstrap stazionario del diff)."""
    r = np.asarray(pd.Series(r).dropna().values, dtype=float)
    T = len(r)
    rng = np.random.default_rng(seed)
    idx = np.empty((n, T), dtype=np.int64)
    idx[:, 0] = rng.integers(0, T, n)
    new = rng.random((n, T)) < 1.0 / block
    starts = rng.integers(0, T, (n, T))
    for t in range(1, T):
        idx[:, t] = np.where(new[:, t], starts[:, t], (idx[:, t - 1] + 1) % T)
    x = r[idx]
    d = x.mean(axis=1) / x.std(axis=1, ddof=1) * np.sqrt(252)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(252)), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def inv_vol_blend(rets: pd.DataFrame, win: int = 252) -> pd.Series:
    """Pesi 1/vol (vol trailing 1y fino a t), ricalcolati a fine mese e applicati dal giorno dopo."""
    vol = rets.rolling(win, min_periods=win).std()
    me = month_ends(rets.index)
    w = pd.DataFrame(np.nan, index=rets.index, columns=rets.columns)
    iv = 1.0 / vol.loc[me]
    w.loc[me] = iv.div(iv.sum(axis=1), axis=0).values
    w = w.ffill().shift(1)
    ok = w.notna().all(axis=1)
    return (w * rets).sum(axis=1)[ok]


# ---------------------------------------------------------------- metriche
def summarize(net, gross, wh, cash_d, spy_ret, start):
    net, gross, wh = net.loc[start:], gross.loc[start:], wh.loc[start:]
    ex = net - cash_d.reindex(net.index).fillna(0.0)
    mn, me_ = metrics(net, spy_ret.reindex(net.index)), metrics(ex)
    post = ex.loc["2013-01-01":]
    turn = wh.diff().abs().fillna(wh.abs()).sum(axis=1)
    yr = {int(y): float(v) for y, v in ((1 + net).groupby(net.index.year).prod() - 1).items()}
    return dict(cagr=mn["cagr"], vol=mn["vol"], excess_sharpe=me_["sharpe"], sortino=me_["sortino"], maxdd=mn["maxdd"],
                pct_invested=float((wh.sum(axis=1) > 1e-9).mean()), sharpe_post2013=float(metrics(post).get("sharpe", np.nan)),
                corr_spy=mn.get("corr_bench"), turnover_ann=float(turn.mean() * 252),
                cost_drag_ann=float((gross - net).mean() * 252), n_days=mn["n_days"],
                start=str(net.index[0].date()), by_year=yr), ex


def verdict(name, ex, bench_ex, m, bm, dsr, low_tim):
    obs, lo, hi = block_bootstrap_sharpe_diff(ex, bench_ex, 20, 2000)
    sobs, slo, shi = block_bootstrap_sharpe(ex)
    a = m["excess_sharpe"] > bm["excess_sharpe"] and lo > 0
    dd_cut = 1 - abs(m["maxdd"]) / abs(bm["maxdd"]) if bm["maxdd"] < 0 else np.nan
    b = bool(low_tim and m["excess_sharpe"] > 0.5 and slo > 0 and dd_cut >= 0.40)
    c, d = m["sharpe_post2013"] > 0, dsr > 0.95
    keep = bool((a or b) and c and d)
    return dict(sharpe_diff_vs_bench=obs, ci95_diff=[lo, hi], own_excess_sharpe_ci95=[slo, shi], dd_reduction_vs_bench=float(dd_cut),
                pass_a_vs_bench=bool(a), pass_b_lowtim=b, pass_post2013=bool(c), dsr=float(dsr), pass_dsr=bool(d),
                verdict="KEEP" if keep else "DISCARD")


# ---------------------------------------------------------------- dati e main
def load_close(symbols, start="1995-01-01", end="2026-11-24"):
    from quant.core import equity
    from quant.data import load_bars
    px, drop = {}, []
    for s in symbols:
        try:
            c = load_bars(equity(s), "1d", start, end)["close"].copy()
            c.index = c.index.tz_localize(None).normalize() if c.index.tz is not None else c.index.normalize()
            px[s] = c[~c.index.duplicated()]
        except Exception as e:  # noqa: BLE001
            drop.append(f"{s}: {e}")
    return pd.DataFrame(px).sort_index(), drop


def tsmom_longonly_monthly(cash_d):
    from quant.portfolio.run_experiment import ETF, CRYPTO, load, six_forty
    from quant.portfolio.tsmom import n_active, tsmom_weights
    df, _ = load()
    crypto = {c for c in CRYPTO if c in df.columns}
    cost = pd.Series({c: (10.0 if c in crypto else 2.0) for c in df.columns})
    borrow = pd.Series({c: (0.0 if c in crypto else 0.01) for c in df.columns})
    res = run_weights(df, tsmom_weights(df, crypto, "monthly", "long_only"), cost, borrow)
    na = n_active(df)
    start = na[na >= 10].index[0]
    for o in (res.net, res.weights):
        o.index = o.index.tz_localize(None)
    sixty = six_forty(df)
    sixty.index = sixty.index.tz_localize(None)
    cp = (1 - res.weights.sum(axis=1)).clip(lower=0) * cash_d.reindex(res.net.index).fillna(0.0)
    return (res.net + cp).loc[start.tz_localize(None):], sixty


def main():
    px, drop = load_close(["SPY", "QQQ", "IWM", "EFA", "IEF"] + SECTORS + COUNTRIES)
    irx, _ = load_close(["^IRX"], "1993-01-01")
    spy_idx = px["SPY"].dropna().index
    px = px.reindex(spy_idx.union(px.index)).sort_index()
    cash_d = cash_daily(irx["^IRX"].dropna(), px.index)
    spy_ret = px["SPY"].pct_change(fill_method=None).fillna(0.0)
    R, S = {}, {}   # R: dict nome -> (net, gross, wh, start); S: summary

    def add(name, w, start=None, bps=COST_BPS):
        res, net, gross = run(px, w, cash_d, bps)
        R[name] = (net, gross, res.weights, start or res.weights.sum(axis=1).gt(0).idxmax())

    spy_i = px["SPY"].dropna().index
    pxs = px.loc[spy_i[0]:]
    # E1 / E2
    add("E1", tom_weights(px, ["SPY"]).loc["1995-01-01":], "1995-01-01")
    add("E1_bh", pd.DataFrame({"SPY": 1.0}, index=px.index).loc["1995-01-01":], "1995-01-01", 0.0)
    w2 = tom_weights(px, BASKET).loc["2002-01-01":]
    add("E2", w2, "2002-01-01")
    ewb = ew_weights(px[BASKET].loc["2002-01-01":].notna()).reindex(month_ends(px.loc["2002-01-01":].index))
    add("E2_bh", ewb, "2002-01-01")
    # E3 / E4
    for nm, uni, k in (("E3", SECTORS, 3), ("E4", COUNTRIES, 4)):
        W, elig = rotation_weights(px[uni], cash_d, k)
        add(nm, W, W.index[elig.any(axis=1).values.argmax()])
        add(nm + "_ew", ew_weights(elig), R[nm][3])
    st = {n: r[3] for n, r in R.items()}
    M, EX = {}, {}
    for n, (net, gross, wh, s) in R.items():
        M[n], EX[n] = summarize(net, gross, wh, cash_d, spy_ret, s)
    pairs = {"E1": "E1_bh", "E2": "E2_bh", "E3": "E3_ew", "E4": "E4_ew"}
    var_sr = float(np.var([EX[k].mean() / EX[k].std(ddof=1) for k in pairs], ddof=1))
    V = {}
    for k, b in pairs.items():
        dsr = deflated_sharpe_ratio(EX[k].values, N_TRIALS_DSR, var_sr)
        V[k] = verdict(k, EX[k], EX[b].loc[EX[k].index], M[k], M[b], dsr, k in ("E1", "E2"))
    # 60/40 e combinazione
    tsm, sixty = tsmom_longonly_monthly(cash_d)
    kept = [k for k in V if V[k]["verdict"] == "KEEP"]
    comb = None
    sf = pd.concat([sixty, tsm], axis=1).dropna().index[0]
    if kept:
        legs = pd.concat([R[k][0] for k in kept] + [tsm], axis=1, keys=kept + ["TSMOM_LO_M"]).dropna()
        bl = inv_vol_blend(legs)
        j = pd.concat([bl, sixty], axis=1, keys=["blend", "60_40"]).dropna()
        cx = cash_d.reindex(j.index)
        obs, lo, hi = block_bootstrap_sharpe_diff(j["blend"] - cx, j["60_40"] - cx, 20, 2000)
        comb = dict(legs=kept + ["TSMOM_LO_M"], start=str(j.index[0].date()),
                    blend=metrics(j["blend"] - cx), sixty_forty=metrics(j["60_40"] - cx),
                    sharpe_diff=obs, ci95=[lo, hi])
    sixty_m = metrics(sixty - cash_d.reindex(sixty.index).fillna(0.0))
    res = dict(dropped=drop, end=str(px.index[-1].date()), var_sr_trials=var_sr, n_trials_dsr=N_TRIALS_DSR,
               first_price={c: str(px[c].first_valid_index().date()) for c in px.columns}, metrics=M, verdicts=V,
               sixty_forty_excess=sixty_m, tsmom_lo_monthly_excess=metrics(tsm - cash_d.reindex(tsm.index).fillna(0.0)),
               combination=comb, kept=kept)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(res, indent=1, default=float))
    for k, m in M.items():
        print(f"{k:7s} {m['start']} CAGR {m['cagr']:.1%} vol {m['vol']:.1%} exSR {m['excess_sharpe']:.2f} sort {m['sortino']:.2f} "
              f"DD {m['maxdd']:.1%} inv {m['pct_invested']:.0%} post13 {m['sharpe_post2013']:.2f} corr {m['corr_spy']:.2f} "
              f"turn {m['turnover_ann']:.1f} drag {m['cost_drag_ann']:.2%}")
    print(json.dumps(V, indent=1)); print(json.dumps(comb, indent=1, default=float))


if __name__ == "__main__":
    main()
