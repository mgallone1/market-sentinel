"""
Griglia coperta sul petrolio con filtro di regime (test pre-registrato, parametri fissi, nessun tuning).

Regime e range usano SOLO chiusure giornaliere fino al giorno precedente (causale) e valgono per il giorno successivo.
Varianti: G0 originale (oil_grid.simulate), G1 regime+range+cap+kill switch, G2 = G1 sempre ON, C = G1 con giorni ON casuali.
Valori in $ per 1 barile per livello.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from quant.research import oil_grid

SPREAD, FIN, CAP, N_SEEDS = 0.04, 0.05, 10, 20


def daily_params(close: pd.Series) -> pd.DataFrame:
    """Parametri calcolati alla chiusura del giorno t (indice = t). Usarli per il giorno successivo."""
    c = close.where(close > 0).astype(float)
    lc = np.log(c)
    r1 = lc.diff()
    r5 = lc.diff(5)
    sig_d = r1.rolling(20).std()
    vr5 = r5.rolling(56).var() / (5 * r1.rolling(60).var())
    z = (lc - lc.shift(60)).abs() / (r1.rolling(60).std() * math.sqrt(60))
    center = c.rolling(20).mean()
    half = 2 * sig_d * math.sqrt(20)
    step = (0.25 * sig_d * c).round(2).clip(lower=0.05)
    on = (vr5 < 0.8) & (z < 1.0) & sig_d.notna()
    out = pd.DataFrame({"sigma_d": sig_d, "vr5": vr5, "z": z, "lo": center * (1 - half), "hi": center * (1 + half),
                        "step": step, "on": on})
    ok = out[["sigma_d", "vr5", "z", "lo", "hi", "step"]].notna().all(axis=1)
    out["on"] = out["on"] & ok
    return out


def params_for_sessions(params: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Per ogni sessione prende i parametri dell'ultima chiusura giornaliera STRETTAMENTE precedente."""
    pos = params.index.searchsorted(sessions, side="left") - 1
    res = params.iloc[np.clip(pos, 0, None)].astype(float).copy()
    res.index = sessions
    res.loc[pos < 0, :] = np.nan
    res["on"] = res["on"].fillna(0).astype(bool)
    return res


def simulate_regime(prices: pd.Series, bar_params: pd.DataFrame, sess, spread=SPREAD, fin_annual=FIN, cap=CAP) -> dict:
    """bar_params: una riga per barra (on, lo, hi, step); sess: sessione (data) di ogni barra."""
    p = prices.astype(float)
    n = len(p)
    sess = pd.DatetimeIndex(sess)
    on_b = bar_params["on"].to_numpy(bool)
    lo_b, hi_b, st_b = (bar_params[k].to_numpy(float) for k in ("lo", "hi", "step"))
    us, cnt = np.unique(sess.values, return_counts=True)
    gap = np.append(np.diff(us).astype("timedelta64[D]").astype(float), 1.0)
    dt_day = dict(zip(us, gap / cnt))
    longs: list[tuple[float, float]] = []
    shorts: list[tuple[float, float]] = []
    lvl = None
    realized = fin_cost = gross = 0.0
    kills, worst_kill = 0, 0.0
    eq = np.zeros(n)
    unr = np.zeros(n)
    inv_max = 0
    vals = p.to_numpy()
    for i in range(n):
        px = vals[i]
        on = on_b[i]
        s, lo, hi = st_b[i], lo_b[i], hi_b[i]
        new_day = i == 0 or sess[i] != sess[i - 1]
        if longs or shorts:
            kill = (new_day and not on) or (on and not (lo <= px <= hi))
            if kill:
                pnl = sum(px - e for e, _ in longs) + sum(e - px for e, _ in shorts) - spread * (len(longs) + len(shorts))
                realized += pnl
                gross += max(pnl, 0.0)
                kills += 1
                worst_kill = min(worst_kill, pnl)
                longs, shorts, lvl = [], [], None
        if on and lo <= px <= hi:
            if lvl is None:  # griglia ancorata all'ultimo livello attraversato; il passo nuovo vale dal giorno nuovo
                lvl = math.floor(px / s) * s
            while px >= lvl + s or px <= lvl - s:
                lvl = round(lvl + s if px >= lvl + s else lvl - s, 8)
                keep = []
                for e, si in longs:
                    if lvl - e >= si - 1e-9:
                        g = si - spread; realized += g; gross += max(g, 0.0)
                    else:
                        keep.append((e, si))
                longs = keep
                keep = []
                for e, si in shorts:
                    if e - lvl >= si - 1e-9:
                        g = si - spread; realized += g; gross += max(g, 0.0)
                    else:
                        keep.append((e, si))
                shorts = keep
                if lo <= lvl <= hi:
                    if len(longs) - len(shorts) < cap and not any(abs(e - lvl) < 1e-9 for e, _ in longs):
                        longs.append((lvl, s))
                    if len(longs) - len(shorts) > -cap and not any(abs(e - lvl) < 1e-9 for e, _ in shorts):
                        shorts.append((lvl, s))
        elif not on:
            lvl = None
        notional = sum(abs(e) for e, _ in longs) + sum(abs(e) for e, _ in shorts)
        fin = notional * fin_annual / 365 * dt_day[sess.values[i]]
        fin_cost += fin
        realized -= fin
        u = sum(px - e for e, _ in longs) + sum(e - px for e, _ in shorts)
        unr[i] = u
        eq[i] = realized + u
        inv_max = max(inv_max, abs(len(longs) - len(shorts)))
    return dict(equity=pd.Series(eq, index=p.index), realized=float(realized), unrealized=float(unr[-1]) if n else 0.0,
                fin_cost=float(fin_cost), gross=float(gross), n_kills=kills, worst_kill=float(worst_kill),
                max_abs_net_inventory=inv_max, open_positions_end=len(longs) + len(shorts))


def metrics(eq: pd.Series, **extra) -> dict:
    v = eq.to_numpy()
    peak = np.maximum.accumulate(np.concatenate([[0.0], v]))[1:]
    d = dict(total=float(v[-1]), worst_equity=float(v.min()), max_drawdown=float((peak - v).max()))
    d.update(extra)
    return d


def by_year(eq: pd.Series) -> dict:
    last = eq.groupby(eq.index.year).last()
    return {int(y): float(x) for y, x in last.diff().fillna(last).items()}


def sessions_hourly(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex((idx + pd.Timedelta(hours=6)).tz_localize(None).normalize()) if idx.tz is None else \
        pd.DatetimeIndex((idx.tz_convert("America/New_York") + pd.Timedelta(hours=6)).tz_localize(None).normalize())


def run_variant(prices, sess, dp, on_days: pd.Series | None, fin, g2=False):
    """dp: parametri per sessione; on_days: maschera ON per sessione (sovrascrive)."""
    bp = dp.copy()
    valid = bp[["lo", "hi", "step"]].notna().all(axis=1)
    if g2:
        bp["on"] = valid
    elif on_days is not None:
        bp["on"] = on_days.reindex(bp.index).fillna(False).to_numpy() & valid.to_numpy()
    return simulate_regime(prices, bp.reset_index(drop=True), sess, SPREAD, fin, CAP)


def evaluate(name, prices, sess, daily_close, hourly: bool) -> dict:
    sess = pd.DatetimeIndex(sess)
    dp = params_for_sessions(daily_params(daily_close), sess)  # una riga per barra
    day_tab = pd.DataFrame({"on": dp["on"].to_numpy()}, index=sess).groupby(level=0).first()["on"]
    n_days = len(day_tab)
    on_frac = float(day_tab.mean())
    dpb = dp.reset_index(drop=True)
    step_med = float(np.nanmedian(dp.loc[dp["on"], "step"])) if dp["on"].any() else 0.25
    bpd = float(pd.Series(1, index=sess).groupby(level=0).sum().median()) if hourly else 1.0
    out = {"n_bars": int(len(prices)), "n_days": int(n_days), "pct_days_on": on_frac * 100, "g0_step": step_med, "fin": {}}
    rng_valid = day_tab.index[(dp.groupby(level=0).first()[["lo", "hi", "step"]].notna().all(axis=1)).reindex(day_tab.index).to_numpy()]
    k = int(round(on_frac * n_days))
    for fin in (FIN, 0.0):
        r = {}
        g0 = oil_grid.simulate(prices, step_med, SPREAD, fin, "hold", bars_per_day=bpd)
        r["G0"] = metrics(g0["equity"], realized=g0["realized"], fin_cost=g0["fin_cost"], n_kills=None, worst_kill=None,
                          gross=None, pct_days_on=100.0, max_abs_net_inventory=g0["max_abs_net_inventory"])
        r["G0"]["year"] = by_year(g0["equity"]) if not hourly else None
        for key, g2 in (("G1", False), ("G2", True)):
            bp = dpb.copy()
            if g2:
                bp["on"] = bp[["lo", "hi", "step"]].notna().all(axis=1).to_numpy()
            s = simulate_regime(prices, bp, sess, SPREAD, fin, CAP)
            pct = float((bp["on"].groupby(sess.values).first()).mean() * 100)
            r[key] = metrics(s["equity"], realized=s["realized"], fin_cost=s["fin_cost"], n_kills=s["n_kills"],
                             worst_kill=s["worst_kill"], gross=s["gross"], pct_days_on=pct,
                             max_abs_net_inventory=s["max_abs_net_inventory"])
            r[key]["year"] = by_year(s["equity"]) if not hourly else None
        runs = []
        for seed in range(N_SEEDS):
            rng = np.random.default_rng(seed)
            chosen = set(rng.choice(len(rng_valid), size=min(k, len(rng_valid)), replace=False)) if len(rng_valid) else set()
            on_set = set(rng_valid[list(chosen)]) if chosen else set()
            bp = dpb.copy()
            bp["on"] = np.array([pd.Timestamp(d) in on_set for d in sess])
            s = simulate_regime(prices, bp, sess, SPREAD, fin, CAP)
            runs.append(metrics(s["equity"], realized=s["realized"], n_kills=s["n_kills"], worst_kill=s["worst_kill"],
                                gross=s["gross"], fin_cost=s["fin_cost"]))
        tot = np.array([x["total"] for x in runs])
        r["C"] = dict(total_mean=float(tot.mean()), total_p5=float(np.percentile(tot, 5)), total_p95=float(np.percentile(tot, 95)),
                      max_drawdown_mean=float(np.mean([x["max_drawdown"] for x in runs])),
                      worst_equity_mean=float(np.mean([x["worst_equity"] for x in runs])),
                      n_kills_mean=float(np.mean([x["n_kills"] for x in runs])),
                      fin_cost_mean=float(np.mean([x["fin_cost"] for x in runs])),
                      worst_kill_min=float(min(x["worst_kill"] for x in runs)), n_seeds=N_SEEDS)
        out["fin"][f"{fin:.2f}"] = r
    return out


def load_data(cache: Path):
    import yfinance as yf
    cache.mkdir(parents=True, exist_ok=True)

    def get(tk, label, **kw):
        f = cache / f"{label}.pkl"
        if f.exists():
            return pd.read_pickle(f)
        d = yf.download(tk, progress=False, auto_adjust=False, **kw)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        c = d["Close"].dropna().iloc[:-1]  # scarta l'ultima barra (possibile barra in formazione)
        c.to_pickle(f)
        return c
    return {
        "WTI_h": get("CL=F", "wti_h", period="730d", interval="1h"),
        "BRENT_h": get("BZ=F", "brent_h", period="730d", interval="1h"),
        "WTI_d": get("CL=F", "wti_d", start="2005-01-01", interval="1d"),
        "BRENT_d": get("BZ=F", "brent_d", start="2007-01-01", interval="1d"),
    }


def main(out_dir="reports/oil_grid_regime", cache="/tmp/oil_regime_cache"):
    d = load_data(Path(cache))
    res = {}
    for name, hourly, dk in (("WTI_h", True, "WTI_d"), ("BRENT_h", True, "BRENT_d"), ("WTI_d", False, "WTI_d"), ("BRENT_d", False, "BRENT_d")):
        px = d[name]
        daily = d[dk].copy()
        daily.index = pd.DatetimeIndex(daily.index).tz_localize(None).normalize() if daily.index.tz is None else daily.index.tz_convert(None).normalize()
        if hourly:
            sess = sessions_hourly(px.index)
        else:
            px = px.copy(); px.index = daily.index if len(px) == len(daily) else pd.DatetimeIndex(px.index).tz_localize(None).normalize()
            sess = px.index
        res[name] = evaluate(name, px, sess, daily, hourly)
        res[name]["period"] = [str(px.index[0]), str(px.index[-1])]
    # KEEP rule
    f5 = {k: v["fin"]["0.05"] for k, v in res.items()}
    fails = []
    for k in res:
        if not f5[k]["G1"]["total"] > 0:
            fails.append(f"G1 totale <= 0 su {k}")
        if not f5[k]["G1"]["max_drawdown"] < 0.5 * f5[k]["G1"]["gross"]:
            fails.append(f"G1 maxDD >= 50% dei profitti lordi realizzati su {k}")
    for k in ("WTI_h", "BRENT_h"):
        if not f5[k]["G1"]["total"] > f5[k]["G2"]["total"]:
            fails.append(f"G1 <= G2 su {k}")
        if not f5[k]["G1"]["total"] > f5[k]["C"]["total_p95"]:
            fails.append(f"G1 <= 95mo percentile di C su {k}")
    res["verdict"] = {"decision": "KEEP" if not fails else "DISCARD", "failed": fails}
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(res, indent=1, default=str))
    (out / "report.md").write_text(render(res))
    print(json.dumps(res["verdict"], ensure_ascii=False))


def _f(x, d=0):
    return "n/d" if x is None else f"{x:,.{d}f}".replace(",", "'")


def render(res) -> str:
    L = ["# Griglia coperta sul petrolio con filtro di regime — test pre-registrato\n",
         "Valori in $ per 1 barile per livello (moltiplicare per il lotto). Parametri fissi, nessun tuning. Regime e range da chiusure "
         "giornaliere fino al giorno precedente (causale): sigma_d = dev. std. rendimenti log 20g; VR5 su 60g; z trend = |ln(Pt/Pt-60)|/(sigma60*sqrt60); "
         "ON se VR5<0,8 e z<1; range = media 20g ±2*sigma_d*sqrt(20); passo = 0,25*sigma_d*prezzo (min 0,05 $). Spread 0,04 $ per posizione; "
         "finanziamento 5% annuo (e 0%) sul nozionale di ogni posizione aperta, pro-rata per barra (giorni di calendario). "
         "G1: coppie solo se ON e prezzo nel range, cap |inventario netto| 10, kill switch (chiusura di tutto alla chiusura della barra se il prezzo "
         "chiude fuori range o il regime passa a OFF al cambio giorno). G2 = G1 sempre ON (con parametri validi). C = G1 con giorni ON casuali "
         "(stessa frazione ON di G1, 20 seed). G0 = oil_grid.simulate (sempre ON, perdenti tenute) con passo fisso = mediana dei passi dei giorni ON di G1.\n",
         "Limiti: simulazione sulle chiusure di barra (attraversamenti intra-barra non visti); sui dati giornalieri il 'percorso intraday' e' la sola chiusura "
         "giornaliera. Giorni con prezzi <=0 o finestre con NaN (aprile 2020 WTI) risultano OFF. Posizioni aperte a fine dati valutate a mercato (senza spread di chiusura). "
         "Il livello di griglia resta ancorato tra un giorno e l'altro (si ri-ancora solo dopo OFF/kill); una prima versione che ri-ancorava ogni giorno non apriva mai posizioni sui dati giornalieri ed e' stata scartata prima di guardare i risultati orari. 'Profitti lordi' = somma delle chiusure positive (take profit netti di spread e kill switch positivi).\n"]
    for name, v in res.items():
        if name == "verdict":
            continue
        L.append(f"## {name} ({v['period'][0][:10]} → {v['period'][1][:10]}, {v['n_bars']} barre, {v['n_days']} giorni, ON G1 {v['pct_days_on']:.1f}%, passo G0 {v['g0_step']:.2f} $)\n")
        for fin, r in v["fin"].items():
            L.append(f"Finanziamento {float(fin)*100:.0f}%\n")
            L.append("| var | P&L totale | realizzato | peggior equity | max drawdown | n kill | % giorni ON | finanz. | peggior kill | profitti lordi |")
            L.append("|---|---|---|---|---|---|---|---|---|---|")
            for k in ("G0", "G1", "G2"):
                m = r[k]
                L.append(f"| {k} | {_f(m['total'])} | {_f(m['realized'])} | {_f(m['worst_equity'])} | {_f(m['max_drawdown'])} | {_f(m['n_kills'])} | "
                         f"{m['pct_days_on']:.1f} | {_f(m['fin_cost'])} | {_f(m['worst_kill'])} | {_f(m['gross'])} |")
            c = r["C"]
            L.append(f"| C (media, 5°–95° pct) | {_f(c['total_mean'])} ({_f(c['total_p5'])} … {_f(c['total_p95'])}) | n/d | {_f(c['worst_equity_mean'])} | "
                     f"{_f(c['max_drawdown_mean'])} | {c['n_kills_mean']:.1f} | {v['pct_days_on']:.1f} | {_f(c['fin_cost_mean'])} | {_f(c['worst_kill_min'])} | n/d |\n")
        if v["fin"]["0.05"]["G1"]["year"]:
            ys = sorted(v["fin"]["0.05"]["G1"]["year"])
            L.append("P&L per anno, finanziamento 5%\n")
            L.append("| anno | G0 | G1 | G2 |\n|---|---|---|---|")
            r = v["fin"]["0.05"]
            for y in ys:
                L.append(f"| {y} | " + " | ".join(_f(r[k]["year"].get(y, 0)) if r[k]["year"] else "n/d" for k in ("G0", "G1", "G2")) + " |")
            L.append("")
    vd = res["verdict"]
    L.append("## Verdetto\n")
    L.append("Regola KEEP (finanziamento 5%): G1 totale > 0 su tutti e 4 i dataset; G1 > G2 e G1 > 95° pct di C su entrambi gli orari; max drawdown G1 < 50% dei profitti lordi realizzati di G1 su ogni dataset.\n")
    L.append(f"**{vd['decision']}**" + ("" if not vd["failed"] else ". Criteri non soddisfatti: " + "; ".join(vd["failed"]) + "."))
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main(*sys.argv[1:])
