"""
Esperimento pre-registrato: Crowding-Conditioned Trend (CCT) contro i segnali singoli.

Protocollo (fissato prima di vedere i risultati):
  universo 10 USDT perps, barre 4h, 2023-11-01..2026-11-01, costi bybit_perp (taker; maker come variante)
  uscite identiche per tutti: stop 2 ATR, target 6 ATR, time-stop 18 barre (72h)
  regole: cct(tau=0.5,f_max=1,phi_min=0) | trend_only(tau=0.5) | funding_contrarian(k=1.5) | flow_only(k=1)
  test interazioni: logit effetti principali vs logit + interazioni, walk-forward espandente purgato
  CCT si tiene solo se: expectancy netta > 0, > ogni singolo segnale, IC95% bootstrap (cluster per giorno)
  di (CCT - trend_only) > 0, stabile per anno, e le interazioni migliorano la log-loss OOS.
Uso: python -m quant.research.experiments.cct_experiment --out reports/cct_4h
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from quant.backtest import ExitRules, run_backtest, triple_barrier_labels
from quant.core import crypto_perp
from quant.data import load_bars
from quant.strategies.cct import cct, cct_features, flow_only, funding_contrarian, trend_only

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT", "AVAXUSDT", "ADAUSDT", "DOGEUSDT", "SUIUSDT", "NEARUSDT"]
RULES = ExitRules(sl_atr=2.0, tp_atr=6.0, max_hold_bars=18)
IV = "4h"
STRATS = {"CCT": cct, "S1 trend": trend_only, "S2 funding": funding_contrarian, "S3 flusso": flow_only}


def summarize(t: pd.DataFrame) -> dict:
    if t.empty:
        return dict(n=0)
    r = t["ret_net"]
    gp, gl = t.net_pnl[t.net_pnl > 0].sum(), -t.net_pnl[t.net_pnl < 0].sum()
    yr = r.groupby(pd.DatetimeIndex(t["entry_ts"]).year).agg(["mean", "count"])
    return dict(n=int(len(r)), exp=float(r.mean()), gross=float((t.gross_pnl / t.notional).mean()),
                win=float((r > 0).mean()), pf=float(gp / gl) if gl > 0 else np.nan,
                years={int(y): (float(m), int(c)) for y, (m, c) in yr.iterrows()})


def cluster_boot_diff(a: pd.DataFrame, b: pd.DataFrame | None, n_boot=2000, seed=0):
    """IC95% della media di a (o di a-b) ricampionando i GIORNI di ingresso (cluster) con reinserimento."""
    rng = np.random.default_rng(seed)
    da = a.assign(d=pd.DatetimeIndex(a.entry_ts).floor("D")).groupby("d")["ret_net"].agg(["sum", "count"])
    days = da.index
    if b is not None:
        db = b.assign(d=pd.DatetimeIndex(b.entry_ts).floor("D")).groupby("d")["ret_net"].agg(["sum", "count"])
        days = days.union(db.index)
        db = db.reindex(days, fill_value=0)
    da = da.reindex(days, fill_value=0)
    out = []
    for _ in range(n_boot):
        k = rng.integers(0, len(days), len(days))
        ma = da["sum"].values[k].sum() / max(1, da["count"].values[k].sum())
        if b is not None:
            mb = db["sum"].values[k].sum() / max(1, db["count"].values[k].sum())
            out.append(ma - mb)
        else:
            out.append(ma)
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def interaction_test(data: dict, spec_fn) -> dict:
    rows = []
    for s, b in data.items():
        spec = spec_fn(s)
        side = trend_only(b, spec, IV)
        x = cct_features(b, IV)
        lab = triple_barrier_labels(b, side, RULES, spec, IV)
        lab = lab[lab.side != 0].join(x, how="left")
        lab["sym"] = s
        rows.append(lab)
    d = pd.concat(rows).dropna(subset=["T", "F", "Phi", "V", "ret_net"]).sort_index()
    sd = d["side"].astype(float)
    M = pd.DataFrame({"Ts": d["T"] * sd, "Fs": d["F"] * sd, "Ps": d["Phi"] * sd, "V": d["V"]}, index=d.index)
    I = M.assign(FsT=M.Fs * M.Ts.abs(), PsT=M.Ps * M.Ts.abs(), FsV=M.Fs * M.V, PsV=M.Ps * M.V, FsPs=M.Fs * M.Ps)
    y = (d["ret_net"] > 0).astype(int).values
    ts = d.index
    t1 = pd.DatetimeIndex(d["t1"])
    start = ts.min() + pd.Timedelta(days=365)
    edges = list(pd.date_range(start, ts.max(), freq="120D")) + [ts.max() + pd.Timedelta(hours=4)]
    res = {"main": {"p": [], "y": [], "r": []}, "inter": {"p": [], "y": [], "r": []}}
    for a, bnd in zip(edges[:-1], edges[1:]):
        tr = (t1 < a)                     # purge: l'esito deve essere noto prima dell'inizio test
        te = (ts >= a) & (ts < bnd)
        if tr.sum() < 200 or te.sum() == 0 or len(np.unique(y[tr])) < 2:
            continue
        wins, losses = d.ret_net[tr & (d.ret_net > 0)].mean(), -d.ret_net[tr & (d.ret_net <= 0)].mean()
        for name, X in (("main", M), ("inter", I)):
            m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000)).fit(X[tr], y[tr])
            p = m.predict_proba(X[te])[:, 1]
            res[name]["p"].append(p); res[name]["y"].append(y[te]); res[name]["r"].append(d.ret_net[te].values)
            res[name].setdefault("pstar", []).append(np.full(te.sum(), losses / (wins + losses)))
    out = {"n_events": int(len(d))}
    for name, v in res.items():
        p, yy, rr, ps = (np.concatenate(v[k]) for k in ("p", "y", "r", "pstar"))
        base = np.clip(np.mean(yy), 1e-6, 1 - 1e-6)
        ll = -np.mean(yy * np.log(np.clip(p, 1e-6, 1)) + (1 - yy) * np.log(np.clip(1 - p, 1e-6, 1)))
        ll0 = -np.mean(yy * np.log(base) + (1 - yy) * np.log(1 - base))
        acc = p > ps
        out[name] = dict(n_oos=int(len(yy)), auc=float(roc_auc_score(yy, p)), logloss=float(ll), dll_vs_base=float(ll - ll0),
                         accept=float(acc.mean()), exp_accepted=float(rr[acc].mean()) if acc.any() else None,
                         n_accepted=int(acc.sum()), exp_all=float(rr.mean()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/cct_4h")
    ap.add_argument("--start", default="2023-11-01")
    ap.add_argument("--end", default="2026-11-01")
    a = ap.parse_args()
    spec_fn = lambda s: crypto_perp(s, "bybit")
    data = {s: load_bars(crypto_perp(s, "binance"), IV, a.start, a.end) for s in SYMS}
    results, trades = {}, {}
    for mode in ("taker", "maker"):
        for name, fn in STRATS.items():
            T = []
            for s, b in data.items():
                sig = fn(b, spec_fn(s), IV).to_frame("side")
                t = run_backtest(b, sig, spec_fn(s), RULES, IV, entry_mode=mode).trades
                T.append(t.assign(sym=s))
            t = pd.concat(T, ignore_index=True)
            trades[(mode, name)] = t
            r = summarize(t)
            if r["n"]:
                r["ci95"] = cluster_boot_diff(t, None)
            results[f"{mode}|{name}"] = r
        for name in STRATS:   # seconda passata: tutti i trade di S1 esistono
            r = results[f"{mode}|{name}"]
            if r.get("n") and name != "S1 trend":
                r["ci95_diff_vs_S1"] = cluster_boot_diff(trades[(mode, name)], trades[(mode, "S1 trend")])
    inter = interaction_test(data, spec_fn)
    # criteri
    c = results["taker|CCT"]
    singles = [results[f"taker|{k}"] for k in STRATS if k != "CCT" and results[f"taker|{k}"].get("n")]
    yrs_ok = all(m > 0 for y, (m, n) in c["years"].items() if n >= 30)
    crit = {
        "expectancy_netta>0": c["exp"] > 0,
        "batte_ogni_singolo_segnale": all(c["exp"] > s["exp"] for s in singles),
        "IC95_diff_vs_S1>0": c.get("ci95_diff_vs_S1", (np.nan, np.nan))[0] > 0,
        "stabile_per_anno": yrs_ok,
        "interazioni_migliorano_logloss_OOS": inter["inter"]["logloss"] < inter["main"]["logloss"],
    }
    verdict = "TENERE" if all(crit.values()) else "SCARTARE"
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(dict(results=results, interaction=inter, criteria=crit, verdict=verdict,
                                                    n_trials=len(STRATS) * 2 + 2), indent=1, default=str))
    L = [f"# CCT — Crowding-Conditioned Trend (esperimento pre-registrato)\n", f"**Verdetto: {verdict}**\n",
         "Universo 10 USDT perps, 4h, 2023-11 → 2026-11; uscite identiche (SL 2 ATR, TP 6 ATR, 72h); costi Bybit.\n",
         "| modo | regola | trade | win | lordo/trade | netto/trade | IC95% netto | PF | Δ vs S1 IC95% | netto per anno (n) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for k, r in results.items():
        mode, name = k.split("|")
        if not r.get("n"):
            L.append(f"| {mode} | {name} | 0 | | | | | | | |"); continue
        yrs = "; ".join(f"{y}: {m*100:+.2f}% ({n})" for y, (m, n) in r["years"].items())
        dv = r.get("ci95_diff_vs_S1")
        L.append(f"| {mode} | {name} | {r['n']} | {r['win']:.1%} | {r['gross']*100:+.3f}% | {r['exp']*100:+.3f}% | "
                 f"[{r['ci95'][0]*100:+.3f}, {r['ci95'][1]*100:+.3f}] | {r['pf']:.2f} | "
                 f"{'' if dv is None else f'[{dv[0]*100:+.3f}, {dv[1]*100:+.3f}]'} | {yrs} |")
    L += ["\n## Test delle interazioni (logit, walk-forward espandente purgato, eventi = segnali di trend)\n",
          f"Eventi: {inter['n_events']}\n", "| modello | n OOS | AUC | log-loss | Δ vs base | accettati | netto accettati | netto tutti |",
          "|---|---|---|---|---|---|---|---|"]
    for name in ("main", "inter"):
        v = inter[name]
        ea = "n/a" if v["exp_accepted"] is None else f"{v['exp_accepted']*100:+.3f}%"
        L.append(f"| {'effetti principali' if name=='main' else '+ interazioni'} | {v['n_oos']} | {v['auc']:.3f} | {v['logloss']:.4f} | "
                 f"{v['dll_vs_base']:+.4f} | {v['n_accepted']} ({v['accept']:.1%}) | {ea} | {v['exp_all']*100:+.3f}% |")
    L += ["\n## Criteri\n"] + [f"- {k}: {'OK' if v else 'NO'}" for k, v in crit.items()]
    (out / "report.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
