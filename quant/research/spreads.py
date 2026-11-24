"""
Spread / pairs trading pre-registrata (S1 Brent-WTI, S1-grid, S2 pairs distanza S&P100, S3 coppie ETF/azioni).
Esecuzione: segnale al close t, ordine al close t+1 (exit per tempo: al close del giorno limite; grid: al close del
giorno di attraversamento). Uscita su z: side*z >= -exit (include l'overshoot oltre la media). Nessun tuning.
Uso: python -m quant.research.spreads
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from quant.portfolio.backtest import metrics
from quant.validation import deflated_sharpe_ratio

OUT = Path("reports/spreads")
CACHE = Path("data/cache")
N_TRIALS = 100
S1_COST = dict(kind="abs", v=0.03, fin=0.05)          # $/barile/gamba/lato + 5%/anno su nozionale di entrambe
EQ_COST = dict(kind="bps", v=5e-4, borrow=0.01)       # 5 bps/gamba/lato + 1%/anno sulla gamba corta
ZERO = dict(kind="abs", v=0.0, fin=0.0)
ZERO_EQ = dict(kind="bps", v=0.0, borrow=0.0)
CAP_S1 = 10_000.0
GRID_MAX = 8

S3_PAIRS = [("GLD", "GDX"), ("XLE", "XOP"), ("EWA", "EWC"), ("KO", "PEP"), ("XOM", "CVX"), ("V", "MA"), ("HD", "LOW")]

SECTORS = {
    "IT": "AAPL MSFT NVDA AVGO ORCL CRM ADBE AMD CSCO ACN IBM INTC QCOM TXN INTU AMAT NOW MU",
    "COMM": "GOOGL META NFLX DIS CMCSA T VZ TMUS CHTR",
    "DISC": "AMZN TSLA HD MCD NKE LOW SBUX BKNG TJX GM F",
    "STAPLES": "WMT COST PG KO PEP PM MO MDLZ CL KHC",
    "HEALTH": "LLY UNH JNJ ABBV MRK TMO ABT PFE AMGN ISRG BMY GILD MDT CVS DHR",
    "FIN": "BRK-B JPM V MA BAC WFC GS MS AXP C BLK SCHW USB COF SPGI BK MET AIG",
    "IND": "GE CAT RTX HON UNP BA LMT UPS DE MMM FDX EMR GD",
    "ENERGY": "XOM CVX COP", "UTIL": "NEE DUK SO", "RE": "AMT SPG", "MAT": "LIN",
}
SECTOR_OF = {t: s for s, v in SECTORS.items() for t in v.split()}


# ---------------------------------------------------------------- dati
def fetch(tickers, start="2007-01-01", end="2026-11-25", retries=6) -> pd.DataFrame:
    import yfinance as yf
    tickers = sorted(set(tickers))
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"spreads_{len(tickers)}_{start}_{end}_{tickers[0]}_{tickers[-1]}.pkl".replace("^", "")
    if f.exists():
        return pd.read_pickle(f)
    for k in range(retries):
        try:
            d = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False, threads=False)["Close"]
            if isinstance(d, pd.Series):
                d = d.to_frame(tickers[0])
            if len(d):
                d.index = pd.DatetimeIndex(d.index).tz_localize(None)
                d.to_pickle(f)
                return d
        except Exception as e:  # 429 e simili
            print("retry", k, e)
        time.sleep(15 * (k + 1))
    raise RuntimeError("download fallito")


# ---------------------------------------------------------------- z-score causale
def zscore(s: pd.Series, w: int = 60) -> pd.Series:
    """z al close t con media/std (ddof=1) degli ultimi w valori incluso t."""
    return (s - s.rolling(w).mean()) / s.rolling(w).std(ddof=1)


# ---------------------------------------------------------------- motore generico a 2 gambe
def _leg_costs(cost, sA, sB, pa, pb):
    if cost["kind"] == "abs":
        return cost["v"] * (abs(sA) + abs(sB))
    return cost["v"] * (abs(sA) * pa + abs(sB) * pb)


def _carry(cost, sA, sB, pa, pb, dt):
    if cost["kind"] == "abs":
        return cost["fin"] * (abs(sA) * pa + abs(sB) * pb) * dt
    short = (abs(sA) * pa if sA < 0 else 0.0) + (abs(sB) * pb if sB < 0 else 0.0)
    return cost["borrow"] * short * dt


def run_pairs(pa, pb, z, beta, dates, cost, *, enter=2.0, exit_=0.5, stop=4.0, max_hold=None, gross=None,
              force_close_end=False, dollar=False) -> dict:
    """pa,pb,z,beta: array stessa lunghezza. Long spread = +A, -beta*B. gross=None -> 1 unita' per gamba (beta=1).
    Ritorna pnl giornaliero (stessa unita' dei prezzi, o frazione di gross) e lista trade."""
    n = len(pa)
    pnl = np.zeros(n)
    trades = []
    pos = 0; sA = sB = 0.0; hold = 0; pend_entry = None; pend_exit = False; cur = None
    for i in range(1, n):
        dt = (dates[i] - dates[i - 1]).days / 365.0
        if pos:
            d = sA * (pa[i] - pa[i - 1]) + sB * (pb[i] - pb[i - 1]) - _carry(cost, sA, sB, pa[i - 1], pb[i - 1], dt)
            pnl[i] += d; cur["pnl"] += d; hold += 1
            end = force_close_end and i == n - 1
            if pend_exit or (max_hold is not None and hold >= max_hold) or end:
                c = _leg_costs(cost, sA, sB, pa[i], pb[i])
                pnl[i] -= c; cur["pnl"] -= c
                cur.update(exit=dates[i], days=hold, reason="end" if end and not pend_exit else
                           ("time" if not pend_exit else cur.get("sig", "z")))
                trades.append(cur); pos = 0; cur = None; pend_exit = False
                continue
            if not np.isnan(z[i]):
                sz = pos * z[i]
                if sz >= -exit_:
                    pend_exit = True; cur["sig"] = "z"
                elif sz < -stop:
                    pend_exit = True; cur["sig"] = "stop"
            continue
        if pend_entry is not None:
            side, b = pend_entry; pend_entry = None
            if gross is None:
                nA = nB = 1.0
            elif dollar:
                nA, nB = gross / 2 / pa[i], gross / 2 / pb[i]
            else:
                nA = gross / (pa[i] + abs(b) * pb[i]); nB = nA * b
            pos = side; sA = side * nA; sB = -side * nB; hold = 0; pend_exit = False
            c = _leg_costs(cost, sA, sB, pa[i], pb[i])
            pnl[i] -= c
            cur = dict(entry=dates[i], side=side, pnl=-c)
            continue
        if not np.isnan(z[i]) and abs(z[i]) > enter and abs(z[i]) <= stop and i < n - (2 if force_close_end else 1):
            pend_entry = (-1 if z[i] > 0 else 1, 1.0 if gross is None else beta[i])
    return dict(pnl=pnl, trades=trades)


# ---------------------------------------------------------------- S1
def _clean_pair(bz: pd.Series, cl: pd.Series):
    d = pd.concat([bz, cl], axis=1, keys=["a", "b"]).dropna()
    return d[(d.a > 0) & (d.b > 0)]


def s1_run(bz, cl, costs=True) -> dict:
    d = _clean_pair(bz, cl)
    s = d.a - d.b
    z = zscore(s).to_numpy()
    r = run_pairs(d.a.to_numpy(), d.b.to_numpy(), z, np.ones(len(d)), d.index, S1_COST if costs else ZERO,
                  max_hold=20)
    return dict(pnl=pd.Series(r["pnl"], index=d.index), trades=r["trades"], capital=CAP_S1)


def s1_grid(bz, cl, costs=True) -> dict:
    d = _clean_pair(bz, cl)
    s = (d.a - d.b).to_numpy(); idx = d.index; pa, pb = d.a.to_numpy(), d.b.to_numpy()
    m = pd.Series(s).rolling(60).mean().to_numpy(); sd = pd.Series(s).rolling(60).std(ddof=1).to_numpy()
    cst = S1_COST if costs else ZERO
    n = len(s); pnl = np.zeros(n); trades = []
    longs, shorts = [], []   # dict(e,t,pnl,entry)
    side_cost = 2 * cst["v"]
    for i in range(61, n):
        dt = (idx[i] - idx[i - 1]).days / 365.0
        for p in longs + shorts:
            sgn = 1 if p in longs else -1
            d_ = sgn * (s[i] - s[i - 1]) - cst["fin"] * (pa[i - 1] + pb[i - 1]) * dt
            pnl[i] += d_; p["pnl"] += d_; p["days"] += 1
        z = (s[i] - m[i]) / sd[i]
        def close(p, reason):
            pnl[i] -= side_cost; p["pnl"] -= side_cost
            trades.append(dict(entry=p["entry"], exit=idx[i], pnl=p["pnl"], days=p["days"], reason=reason,
                               side=p["side"]))
        killed = abs(z) > 4
        if killed:
            for p in longs + shorts:
                close(p, "kill")
            longs, shorts = [], []
            continue
        for lst, sg in ((longs, 1), (shorts, -1)):
            keep = []
            for p in lst:
                if p["days"] > 0 and sg * (s[i] - p["e"]) >= p["step"] - 1e-12:
                    close(p, "tp")
                else:
                    keep.append(p)
            lst[:] = keep
        step = 0.25 * sd[i]
        if step <= 0:
            continue
        kn = math.floor((s[i] - m[i]) / step); kp = math.floor((s[i - 1] - m[i]) / step)
        if kn != kp and abs(kn - kp) < 60:
            levels = range(kn + 1, kp + 1) if kn < kp else range(kp + 1, kn + 1)
            for L in levels:
                if L < 0 and len(longs) < GRID_MAX:
                    longs.append(dict(e=s[i], step=step, pnl=-side_cost, days=0, entry=idx[i], side=1)); pnl[i] -= side_cost
                elif L > 0 and len(shorts) < GRID_MAX:
                    shorts.append(dict(e=s[i], step=step, pnl=-side_cost, days=0, entry=idx[i], side=-1)); pnl[i] -= side_cost
    return dict(pnl=pd.Series(pnl, index=idx), trades=trades, capital=CAP_S1 * 2 * GRID_MAX,
                open_end=len(longs) + len(shorts))


# ---------------------------------------------------------------- S2
def s2_run(px: pd.DataFrame, start="2010-01-01", n_pairs=20, form=252, trade=126, costs=True) -> dict:
    cost = EQ_COST if costs else ZERO_EQ
    px = px.dropna(axis=1, how="all")
    ds = px.index
    starts = [ds[ds >= pd.Timestamp(f"{y}-{mth:02d}-01")][0] for y in range(pd.Timestamp(start).year, 2027)
              for mth in (1, 7) if (ds >= pd.Timestamp(f"{y}-{mth:02d}-01")).any()]
    starts = [t for t in starts if t >= pd.Timestamp(start) and ds.get_loc(t) >= form]
    pnl = pd.Series(0.0, index=ds); trades = []; periods = []
    for t0 in starts:
        i0 = ds.get_loc(t0)
        if i0 + 2 > len(ds):
            continue
        fw = px.iloc[i0 - form:i0]; tw = px.iloc[i0:i0 + trade]
        ok = [c for c in px.columns if fw[c].notna().all() and tw[c].notna().all() and c in SECTOR_OF]
        nf = fw[ok] / fw[ok].iloc[0]
        cand = []
        for sec in set(SECTOR_OF[c] for c in ok):
            cs = [c for c in ok if SECTOR_OF[c] == sec]
            for a in range(len(cs)):
                for b in range(a + 1, len(cs)):
                    sp = nf[cs[a]] - nf[cs[b]]
                    cand.append(((sp ** 2).sum(), cs[a], cs[b], sp.std(ddof=1)))
        cand.sort(key=lambda x: x[0]); sel = cand[:n_pairs]
        periods.append(dict(start=str(t0.date()), pairs=[(a, b) for _, a, b, _ in sel]))
        base = fw[ok].iloc[0]
        for _, a, b, sdv in sel:
            spread = (tw[a] / base[a] - tw[b] / base[b]).to_numpy()
            z = spread / sdv
            # S2: converge = incrocio (side*z >= 0): exit_=0 ; nessuno stop; gross=1/n_pairs per coppia
            r = run_pairs(tw[a].to_numpy(), tw[b].to_numpy(), z, np.ones(len(tw)), tw.index, cost, enter=2.0,
                          exit_=0.0, stop=1e9, max_hold=None, gross=1.0 / n_pairs, force_close_end=True, dollar=True)
            pnl.loc[tw.index] += r["pnl"]
            for tr in r["trades"]:
                tr["pair"] = f"{a}/{b}"
            trades += r["trades"]
    return dict(pnl=pnl, trades=trades, capital=1.0, periods=periods)


# ---------------------------------------------------------------- S3
def s3_pair(a: pd.Series, b: pd.Series, costs=True, ols_w=252, z_w=60) -> dict:
    d = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    d = d[(d.a > 0) & (d.b > 0)]
    n = len(d); idx = d.index
    A, B = d.a.to_numpy(), d.b.to_numpy()
    z = np.full(n, np.nan); beta = np.full(n, np.nan)
    months = idx.to_period("M")
    # per mese: beta stimato sui 252 giorni precedenti al primo giorno del mese (causale)
    cur_beta = np.nan; cur_month = None
    for i in range(n):
        if months[i] != cur_month:
            cur_month = months[i]
            cur_beta = np.polyfit(B[i - ols_w:i], A[i - ols_w:i], 1)[0] if i >= ols_w else np.nan
        beta[i] = cur_beta
        if i >= ols_w + z_w and not np.isnan(cur_beta):
            res = A[i - z_w + 1:i + 1] - cur_beta * B[i - z_w + 1:i + 1]
            sdv = res.std(ddof=1)
            z[i] = (res[-1] - res.mean()) / sdv if sdv > 0 else np.nan
    r = run_pairs(A, B, z, beta, idx, EQ_COST if costs else ZERO_EQ, enter=2.0, exit_=0.5, stop=4.0, max_hold=30,
                  gross=1.0)
    return dict(pnl=pd.Series(r["pnl"], index=idx), trades=r["trades"], capital=1.0, z=pd.Series(z, index=idx))


def s3_run(px: pd.DataFrame, costs=True) -> dict:
    parts = {f"{a}/{b}": s3_pair(px[a], px[b], costs) for a, b in S3_PAIRS}
    pnl = sum(p["pnl"].reindex(px.index).fillna(0.0) for p in parts.values()) / len(parts)
    trades = [dict(t, pair=k) for k, p in parts.items() for t in p["trades"]]
    return dict(pnl=pnl, trades=trades, capital=1.0, parts=parts)


# ---------------------------------------------------------------- valutazione
def boot_sharpe(r: np.ndarray, block=20, n=2000, seed=0):
    T = len(r); rng = np.random.default_rng(seed)
    idx = np.empty((n, T), dtype=np.int64); idx[:, 0] = rng.integers(0, T, n)
    new = rng.random((n, T)) < 1.0 / block; st = rng.integers(0, T, (n, T))
    for t in range(1, T):
        idx[:, t] = np.where(new[:, t], st[:, t], (idx[:, t - 1] + 1) % T)
    x = r[idx]
    sh = x.mean(1) / x.std(1, ddof=1) * np.sqrt(252)
    return float(np.percentile(sh, 2.5)), float(np.percentile(sh, 97.5))


def _sh(r, rf=None):
    x = r - (rf if rf is not None else 0.0)
    return float(x.mean() / x.std(ddof=1) * np.sqrt(252)) if x.std(ddof=1) > 0 else float("nan")


def evaluate(res: dict, spy: pd.Series, rf: pd.Series, var_sr: float, first_date=None) -> dict:
    pnl = res["pnl"]
    if first_date is not None:
        pnl = pnl.loc[first_date:]
    r = pnl / res["capital"]
    tr = res["trades"]
    if len(tr):
        t0 = pd.Timestamp(min(t["entry"] for t in tr)) - pd.Timedelta(days=1)
        r = r.loc[t0:]
    m = metrics(r, spy)
    rfa = rf.reindex(r.index).ffill().fillna(0.0)
    yr = (1 + r).groupby(r.index.year).prod() - 1
    ty = sorted({pd.Timestamp(t["exit"]).year for t in tr})
    pos_years = float((yr.loc[[y for y in ty if y in yr.index]] > 0).mean()) if ty else float("nan")
    p = np.array([t["pnl"] for t in tr]) if tr else np.array([])
    k = max(1, int(math.ceil(0.05 * len(p)))) if len(p) else 0
    worst = float(np.sort(p)[:k].sum() / p.sum()) if len(p) and p.sum() != 0 else float("nan")
    post = r.loc["2019-01-01":]
    lo, hi = boot_sharpe(r.to_numpy())
    dsr = float(deflated_sharpe_ratio(r.to_numpy(), N_TRIALS, var_sr))
    out = dict(m, sharpe_rf=_sh(r, rfa / 252), sharpe_post2018=_sh(post) if len(post) > 60 else float("nan"),
               n_trades=len(tr), win_rate=float((p > 0).mean()) if len(p) else float("nan"),
               avg_hold_days=float(np.mean([t["days"] for t in tr])) if tr else float("nan"),
               by_year={int(k): float(v) for k, v in yr.items()}, pct_years_pos=pos_years,
               pnl_share_worst5pct_trades=worst, boot_sharpe_lo95=lo, boot_sharpe_hi95=hi, dsr_n100=dsr,
               first=str(r.index[0].date()), last=str(r.index[-1].date()),
               total_pnl=float(pnl.sum()), ret=r)
    out["keep"] = bool(out.get("sharpe", -9) > 0.5 and pos_years >= 0.7 and out["sharpe_post2018"] > 0.3
                       and dsr > 0.95 and lo > 0)
    return out


def run(n_boot_seed=0):
    OUT.mkdir(parents=True, exist_ok=True)
    fut = fetch(["BZ=F", "CL=F"], start="2007-06-01")
    fut = fut.loc["2008-01-01":]
    eq_t = sorted(set(SECTOR_OF) | {t for p in S3_PAIRS for t in p} | {"SPY"})
    eq = fetch(eq_t, start="2008-06-01")
    irx = fetch(["^IRX"], start="2008-01-01")["^IRX"] / 100.0
    spy = eq["SPY"].pct_change()
    res = {"S1": s1_run(fut["BZ=F"], fut["CL=F"]), "S1_grid": s1_grid(fut["BZ=F"], fut["CL=F"]),
           "S2": s2_run(eq.drop(columns=["SPY"]).reindex(columns=[c for c in eq.columns if c in SECTOR_OF])),
           "S3": s3_run(eq)}
    gross = {"S1": s1_run(fut["BZ=F"], fut["CL=F"], False), "S1_grid": s1_grid(fut["BZ=F"], fut["CL=F"], False),
             "S3": s3_run(eq, False)}
    gross["S2"] = s2_run(eq.drop(columns=["SPY"]).reindex(columns=[c for c in eq.columns if c in SECTOR_OF]), costs=False)
    cand = {k: (v["pnl"] / v["capital"]) for k, v in res.items()}
    cand.update({f"S3:{k}": p["pnl"] / p["capital"] for k, p in res["S3"]["parts"].items()})
    srs = [float(x.loc[x.ne(0).idxmax():].mean() / x.loc[x.ne(0).idxmax():].std(ddof=1)) for x in cand.values()]
    var_sr = float(np.var(srs, ddof=1))
    rep = {}
    for k, v in res.items():
        e = evaluate(v, spy, irx, var_sr)
        g = evaluate(gross[k], spy, irx, var_sr)
        e["gross_sharpe"] = g.get("sharpe"); e["gross_cagr"] = g.get("cagr")
        e.pop("ret")
        rep[k] = e
    rep["_meta"] = dict(n_trials_declared=N_TRIALS, trials_this_research=3, var_sr_trials=var_sr,
                        n_candidate_series=len(srs), capital_S1=CAP_S1, capital_S1_grid=CAP_S1 * 2 * GRID_MAX,
                        s2_periods=len(res["S2"]["periods"]), grid_open_end=res["S1_grid"].get("open_end"))
    (OUT / "report.json").write_text(json.dumps(rep, indent=1, default=float))
    write_md(rep)
    return rep


def write_md(rep):
    L = ["# Spread / pairs trading — report (pre-registrato, nessun tuning)", "",
         "Dati: yfinance adjusted close giornalieri. Esecuzione al close t+1 dopo il segnale; uscita su z con side*z >= -exit.",
         "Costi: S1/S1-grid 0.03 $/barile/gamba/lato + 5%/anno finanziamento su entrambe le gambe; S2/S3 5 bps/gamba/lato + 1%/anno borrow sulla gamba corta.",
         f"Capitale: S1 {rep['_meta']['capital_S1']:.0f} $ per unita' di spread; S1-grid {rep['_meta']['capital_S1_grid']:.0f} $ (16 unita' massime); S2/S3 capitale impegnato = 1 (gross 1x per slot).",
         "Nota: il Sharpe vs T-bill per S1/S1-grid e' non significativo (rendimento % su 10.000 $/unita' di spread dollar-neutral molto piccolo rispetto al tasso risk-free). Ticker senza dati yfinance (es. BK) esclusi.",
         "Rischi dichiarati: BZ=F/CL=F sono futures continui (salti di roll nello spread); S2 usa la lista S&P 100 corrente (survivorship bias, dichiarato); DSR con n_trials=100 e var_sr = varianza degli Sharpe giornalieri tra "
         f"{rep['_meta']['n_candidate_series']} serie candidate; bootstrap a blocchi (20) dello Sharpe contro zero.", "",
         "| Famiglia | Sharpe netto | Sharpe lordo | Sharpe vs T-bill | Sharpe post-2018 | CAGR | MaxDD | n trade | win | giorni medi | anni>0 | DSR(100) | CI95 Sharpe | corr SPY | % P&L peggior 5% | KEEP |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in ("S1", "S1_grid", "S2", "S3"):
        e = rep[k]
        L.append(f"| {k} | {e['sharpe']:.2f} | {e['gross_sharpe']:.2f} | {e['sharpe_rf']:.2f} | {e['sharpe_post2018']:.2f} | {e['cagr']:.2%} | {e['maxdd']:.1%} | {e['n_trades']} | {e['win_rate']:.0%} | {e['avg_hold_days']:.1f} | {e['pct_years_pos']:.0%} | {e['dsr_n100']:.2f} | [{e['boot_sharpe_lo95']:.2f}, {e['boot_sharpe_hi95']:.2f}] | {e['corr_bench']:.2f} | {e['pnl_share_worst5pct_trades']:.0%} | {'KEEP' if e['keep'] else 'DISCARD'} |")
    L += ["", "## Rendimenti per anno"]
    for k in ("S1", "S1_grid", "S2", "S3"):
        L.append(f"- {k}: " + ", ".join(f"{y}: {v:.1%}" for y, v in rep[k]["by_year"].items()))
    L += ["", "Regola KEEP: Sharpe netto > 0.5; anni positivi >= 70%; Sharpe post-2018 > 0.3; DSR > 0.95; CI95 inf > 0. Altrimenti DISCARD."]
    (OUT / "report.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    run()
