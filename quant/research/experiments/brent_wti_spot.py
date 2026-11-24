"""
Spread Brent-WTI con dati corretti (spot EIA via FRED: DCOILBRENTEU, DCOILWTICO; nessun salto da roll).
Regole IDENTICHE a quant/research/spreads.py (S1: z60 ingresso |z|>2, uscita |z|<0.5, max 20 giorni, stop |z|>4;
S1-grid: passo 0.25*std60, max 8 per lato, kill |z|>4). Pre-registrato prima dell'esecuzione:
  scenari di costo: CFD = $0.03/bbl/gamba/lato + 5%/anno su entrambi i nozionali (come prima);
                    FUTURES = $0.01/bbl/gamba/lato + rinnovo mensile ~0.35%/anno del nozionale, nessun finanziamento.
  criteri: Sharpe netto > 0.5; >=70% anni con trade positivi; Sharpe post-2018 > 0.3; IC95% bootstrap > 0;
           DSR > 0.95 con n_trials=110 e varianza nulla teorica 1/T.
Limite: lo spot e' un benchmark di prezzo, non uno strumento negoziabile; i futures lo seguono a meno della curva.
"""
import io, json, urllib.request
import numpy as np, pandas as pd
import quant.research.spreads as sp
from quant.validation import deflated_sharpe_ratio

def fred(sid):
    raw = urllib.request.urlopen(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=60).read().decode()
    d = pd.read_csv(io.StringIO(raw)); d.columns = ["date", "v"]
    d["v"] = pd.to_numeric(d["v"], errors="coerce")
    return d.dropna().set_index(pd.to_datetime(d.dropna()["date"]))["v"]

def stats(pnl: pd.Series, trades):
    t0 = pd.Timestamp(min(t["entry"] for t in trades)) - pd.Timedelta(days=1) if trades else pnl.index[0]
    p = pnl.loc[t0:]
    sh = lambda x: float(x.mean() / x.std(ddof=1) * np.sqrt(252)) if x.std(ddof=1) > 0 else float("nan")
    lo, hi = sp.boot_sharpe(p.to_numpy())
    yr = p.groupby(p.index.year).sum(); ty = sorted({pd.Timestamp(t["exit"]).year for t in trades})
    yrs = yr.loc[[y for y in ty if y in yr.index]]
    T = len(p)
    return dict(sharpe=sh(p), sharpe_1990_2007=sh(p.loc[:"2007"]), sharpe_2008_2026=sh(p.loc["2008":]),
                sharpe_post2018=sh(p.loc["2019":]), boot_ci95=[lo, hi], n_trades=len(trades),
                win=float(np.mean([t["pnl"] > 0 for t in trades])) if trades else None,
                pnl_total_per_unit=float(p.sum()), worst_drawdown_per_unit=float((p.cumsum() - p.cumsum().cummax()).min()),
                years_pos=float((yrs > 0).mean()) if len(yrs) else None, by_year={int(k): round(float(v), 2) for k, v in yr.items()},
                dsr_n110=float(deflated_sharpe_ratio(p.to_numpy(), 110, 1.0 / T)))

def main():
    brent, wti = fred("DCOILBRENTEU"), fred("DCOILWTICO")
    brent, wti = brent.loc["1990":], wti.loc["1990":]
    out = {"data": dict(brent=[str(brent.index[0].date()), str(brent.index[-1].date())],
                        wti=[str(wti.index[0].date()), str(wti.index[-1].date())])}
    scen = {"CFD": dict(kind="abs", v=0.03, fin=0.05), "FUTURES": dict(kind="abs", v=0.01, fin=0.0035)}
    for name, cost in scen.items():
        sp.S1_COST = cost
        for strat, fn in (("S1", sp.s1_run), ("S1_grid", sp.s1_grid)):
            r = fn(brent, wti, costs=True); g = fn(brent, wti, costs=False)
            s = stats(r["pnl"], r["trades"]); s["sharpe_gross"] = stats(g["pnl"], g["trades"])["sharpe"]
            s["keep"] = bool(s["sharpe"] > 0.5 and (s["years_pos"] or 0) >= 0.7 and s["sharpe_post2018"] > 0.3
                             and s["boot_ci95"][0] > 0 and s["dsr_n110"] > 0.95)
            out[f"{strat}|{name}"] = s
    print(json.dumps(out, indent=1, default=float))
    return out

if __name__ == "__main__":
    o = main()
    import pathlib; pathlib.Path("reports/brent_wti_spot").mkdir(parents=True, exist_ok=True)
    pathlib.Path("reports/brent_wti_spot/report.json").write_text(json.dumps(o, indent=1, default=float))
