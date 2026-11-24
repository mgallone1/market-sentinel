"""PEAD pre-registrato (yfinance only). 2 trial: long-short, long-only. Nessun tuning.
Uso: python -m quant.research.pead fetch | run"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "pead_cache"
OUT = ROOT / "reports" / "pead"
START, END = "2012-01-01", "2026-11-25"  # end esclusivo -> include 2026-11-24
THRESH, HOLD, COST_LEG, BORROW = 0.05, 20, 0.0005, 0.01
SEED, N_RANDOM, N_BOOT = 20261124, 20, 5000

SP100 = """AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMT AMZN AVGO AXP BA BAC BK BKNG BLK BMY BRK-B C CAT CHTR CL CMCSA COF COP COST CRM CSCO CVS CVX DE DHR DIS DUK EMR F FDX GD GE GILD GM GOOG GOOGL GS HD HON IBM INTC INTU ISRG JNJ JPM KO LIN LLY LMT LOW MA MCD MDLZ MDT MET META MMM MO MRK MS MSFT NEE NFLX NKE NVDA ORCL PEP PFE PG PM PYPL QCOM RTX SBUX SCHW SO SPG T TGT TMO TMUS TSLA TXN UNH UNP UPS USB V VZ WFC WMT XOM""".split()


# ---------- logica pura (testata offline) ----------
def reaction_day_index(ts: pd.Timestamp, days: pd.DatetimeIndex) -> int | None:
    """Indice (in `days`, giorni di borsa) del giorno 1 = primo giorno il cui open segue l'annuncio.
    Prima delle 09:30 ET -> stesso giorno (se di borsa, altrimenti il successivo);
    dopo le 16:00, orario ignoto (00:00) o in seduta -> giorno di borsa successivo."""
    t = ts.tz_convert("America/New_York") if ts.tzinfo is not None else ts
    d = pd.Timestamp(t.date())
    minutes = t.hour * 60 + t.minute
    if minutes == 0:
        same = False                      # orario ignoto
    else:
        same = minutes < 9 * 60 + 30
    i = int(days.searchsorted(d, side="left" if same else "right"))
    return i if i < len(days) else None


def entry_exit_index(ts, days):
    """Entrata all'open del giorno 2 (salta la reazione), uscita al close del giorno 21."""
    r = reaction_day_index(ts, days)
    if r is None or r + HOLD >= len(days):
        return None
    return r + 1, r + HOLD


def window_returns(stock: pd.DataFrame, spy: pd.DataFrame, i_in: int, i_out: int, days):
    """(ritorno titolo, ritorno SPY) da open[i_in] a close[i_out]."""
    d0, d1 = days[i_in], days[i_out]
    rs = stock["close"].loc[d1] / stock["open"].loc[d0] - 1
    rm = spy["close"].loc[d1] / spy["open"].loc[d0] - 1
    return float(rs), float(rm)


def net_event_return(rs: float, rm: float, side: int, hold: int = HOLD):
    """(netto aggiustato, netto grezzo). side=+1 long, -1 short. Costi: 2 gambe x 5bp + borrow sui short."""
    cost = 2 * COST_LEG + (BORROW * hold / 252 if side < 0 else 0.0)
    return side * (rs - rm) - cost, side * rs - cost


def surprise_pct(rep, est):
    if est is None or rep is None or not np.isfinite(est) or not np.isfinite(rep) or est == 0:
        return np.nan
    return (rep - est) / abs(est)


def side_of(s, long_only=False):
    if not np.isfinite(s):
        return 0
    if s > THRESH:
        return 1
    if s < -THRESH and not long_only:
        return -1
    return 0


def cluster_t(r, groups):
    r = np.asarray(r, float)
    n = len(r)
    if n < 3:
        return float("nan")
    m = r.mean()
    g = pd.Series(r - m).groupby(np.asarray(groups)).sum()
    se = math.sqrt((g ** 2).sum()) / n
    return float(m / se) if se > 0 else float("nan")


def boot_months(vals, groups, n=N_BOOT, seed=SEED):
    """CI95 della media resampling di mesi interi."""
    df = pd.DataFrame({"v": np.asarray(vals, float), "g": np.asarray(groups)})
    s, c = df.groupby("g")["v"].sum().to_numpy(), df.groupby("g")["v"].count().to_numpy()
    rng = np.random.default_rng(seed)
    k = len(s)
    idx = rng.integers(0, k, size=(n, k))
    m = s[idx].sum(1) / c[idx].sum(1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def random_control(events: pd.DataFrame, prices: dict, spy, days, n_rep=N_RANDOM, seed=SEED):
    """Per ogni evento: stesso ticker/side, data di entrata casuale (seed fisso). Ritorna array (n_eventi, n_rep) di netti agg."""
    rng = np.random.default_rng(seed)
    out = np.full((len(events), n_rep), np.nan)
    for k, (tk, side) in enumerate(zip(events["ticker"], events["side"])):
        px = prices[tk]
        lo = max(int(days.searchsorted(px.index[0])), 0)
        hi = min(int(days.searchsorted(px.index[-1], side="right")), len(days)) - HOLD - 1
        if hi <= lo:
            continue
        for j in range(n_rep):
            i = int(rng.integers(lo, hi))
            rs, rm = window_returns(px, spy, i, i + HOLD - 1, days)
            out[k, j] = net_event_return(rs, rm, int(side))[0]
    return out


# ---------- dati ----------
def _retry(fn, tries=6):
    for a in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            wait = 10 * (a + 1) if "429" in str(e) or "Too Many" in str(e) else 3
            time.sleep(wait)
    return None


def fetch():
    import yfinance as yf
    CACHE.mkdir(parents=True, exist_ok=True)
    for tk in ["SPY"] + SP100:
        pp, ep = CACHE / f"{tk}_px.pkl", CACHE / f"{tk}_ed.pkl"
        if not pp.exists():
            d = _retry(lambda: yf.Ticker(tk).history(start=START, end=END, auto_adjust=True))
            if d is not None and len(d):
                d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize()
                d[["Open", "High", "Low", "Close"]].rename(columns=str.lower).to_pickle(pp)
            time.sleep(1.2)
        if tk != "SPY" and not ep.exists():
            e = _retry(lambda: yf.Ticker(tk).get_earnings_dates(limit=60))
            if e is not None and len(e):
                e.to_pickle(ep)
            time.sleep(1.5)
        print(tk, pp.exists(), ep.exists(), flush=True)


def load_all():
    spy = pd.read_pickle(CACHE / "SPY_px.pkl")
    days = spy.index
    prices, rows = {}, []
    for tk in SP100:
        pp, ep = CACHE / f"{tk}_px.pkl", CACHE / f"{tk}_ed.pkl"
        if not (pp.exists() and ep.exists()):
            continue
        px = pd.read_pickle(pp).dropna()
        ed = pd.read_pickle(ep)
        prices[tk] = px
        for ts, r in ed.iterrows():
            s = surprise_pct(r.get("Reported EPS"), r.get("EPS Estimate"))
            if not np.isfinite(s):
                continue
            rows.append((tk, ts, s))
    ev = pd.DataFrame(rows, columns=["ticker", "ts", "surprise"])
    return spy, days, prices, ev


def build_events(ev, prices, spy, days):
    recs = []
    for tk, ts, s in ev.itertuples(index=False):
        if ts.tz_convert("America/New_York").date() < pd.Timestamp(START).date():
            continue
        ix = entry_exit_index(ts, days)
        if ix is None:
            continue
        px = prices[tk]
        if days[ix[0]] not in px.index or days[ix[1]] not in px.index:
            continue
        rs, rm = window_returns(px, spy, ix[0], ix[1], days)
        recs.append(dict(ticker=tk, ann=ts, surprise=s, i_in=ix[0], i_out=ix[1], entry=days[ix[0]],
                         exit=days[ix[1]], rs=rs, rm=rm))
    return pd.DataFrame(recs)


def daily_series(ev, prices, spy, days):
    """Media equal-weight delle posizioni aperte: rendimento giornaliero aggiustato SPY, costi su entrata/uscita, borrow giornaliero."""
    acc: dict[int, list[float]] = {}
    for r in ev.itertuples():
        px, side = prices[r.ticker], r.side
        for i in range(r.i_in, r.i_out + 1):
            d, dp = days[i], days[i - 1]
            o_s = px["open"].loc[d] if i == r.i_in else px["close"].loc[dp]
            o_m = spy["open"].loc[d] if i == r.i_in else spy["close"].loc[dp]
            ret = side * ((px["close"].loc[d] / o_s - 1) - (spy["close"].loc[d] / o_m - 1))
            if i == r.i_in:
                ret -= COST_LEG
            if i == r.i_out:
                ret -= COST_LEG
            if side < 0:
                ret -= BORROW / 252
            acc.setdefault(i, []).append(ret)
    s = pd.Series({days[i]: float(np.mean(v)) for i, v in sorted(acc.items())})
    return s


def summarize(name, ev, ctrl, daily, var_sr):
    from quant.validation.stats import deflated_sharpe_ratio
    ev = ev.copy()
    ev["month"] = ev["entry"].dt.to_period("M").astype(str)
    ev["year"] = ev["entry"].dt.year
    n = len(ev)
    res = dict(variant=name, n_events=n)
    if n < 5:
        return res
    adj, raw = ev["net_adj"], ev["net_raw"]
    lo, hi = boot_months(adj, ev["month"])
    res.update(mean_net_adj=float(adj.mean()), mean_net_raw=float(raw.mean()),
               t_cluster_month=cluster_t(adj, ev["month"]), boot_ci95=[lo, hi],
               hit_rate=float((adj > 0).mean()), mean_gross_adj=float((ev["side"] * (ev["rs"] - ev["rm"])).mean()))
    rc = np.nanmean(ctrl, axis=1)
    diff = adj.to_numpy() - rc
    dlo, dhi = boot_months(diff, ev["month"])
    res["random_control"] = dict(mean=float(np.nanmean(rc)), per_rep_means=[float(x) for x in np.nanmean(ctrl, axis=0)],
                                 diff_mean=float(np.nanmean(diff)), diff_ci95=[dlo, dhi])
    by = ev.groupby("year")["net_adj"].agg(["count", "mean"])
    res["by_year"] = {int(y): dict(n=int(r["count"]), mean=float(r["mean"])) for y, r in by.iterrows()}
    ok = by[by["count"] >= 30]
    res["years_ge30"] = int(len(ok))
    res["years_pos_frac"] = float((ok["mean"] > 0).mean()) if len(ok) else float("nan")
    if n >= 100:
        q = pd.qcut(ev["surprise"].rank(method="first"), 10, labels=False)
        # per decili usiamo il ritorno long aggiustato (non signed) - monotonia segnale
        g = ev.assign(dec=q).groupby("dec").apply(lambda d: float((d["rs"] - d["rm"]).mean()), include_groups=False)
        res["by_decile_mkt_adj_return_unsigned"] = {int(k): float(v) for k, v in g.items()}
        res["decile_spearman"] = float(pd.Series(g.index, dtype=float).corr(pd.Series(g.values), method="spearman"))
    d = daily
    if len(d) > 10 and d.std() > 0:
        sr = d.mean() / d.std(ddof=1)
        res["daily"] = dict(n_days=len(d), sharpe_ann=float(sr * math.sqrt(252)), sharpe_daily=float(sr),
                            dsr_n2=deflated_sharpe_ratio(d.to_numpy(), 2, var_sr),
                            dsr_n80=deflated_sharpe_ratio(d.to_numpy(), 80, var_sr))
    return res


def verdict(res):
    if res["n_events"] < 300:
        return "INSUFFICIENT DATA", ["n_events < 300"]
    c = {
        "mean_net_adj>0 e CI95 low>0": res["boot_ci95"][0] > 0 and res["mean_net_adj"] > 0,
        "batte controllo random (diff CI low>0)": res["random_control"]["diff_ci95"][0] > 0,
        ">=2/3 anni positivi (anni con >=30 eventi)": res["years_ge30"] > 0 and res["years_pos_frac"] >= 2 / 3,
        "DSR(n=2)>0.95": res.get("daily", {}).get("dsr_n2", 0) > 0.95,
    }
    return ("KEEP" if all(c.values()) else "DISCARD"), [k for k, v in c.items() if not v]


def run():
    spy, days, prices, ev = load_all()
    events = build_events(ev, prices, spy, days)
    cov = dict(tickers_with_prices=len(prices), tickers_with_events=int(events["ticker"].nunique()) if len(events) else 0,
               events_with_surprise=int(len(ev)), events_usable=int(len(events)),
               first_announcement=str(events["ann"].min()) if len(events) else None,
               last_announcement=str(events["ann"].max()) if len(events) else None,
               missing_tickers=[t for t in SP100 if t not in prices])
    events["side_ls"] = events["surprise"].map(lambda s: side_of(s))
    events["side_lo"] = events["surprise"].map(lambda s: side_of(s, True))
    variants, dailies = {}, {}
    for name, col in (("long_short", "side_ls"), ("long_only", "side_lo")):
        e = events[events[col] != 0].copy()
        e["side"] = e[col]
        nets = [net_event_return(r.rs, r.rm, r.side) for r in e.itertuples()]
        e["net_adj"], e["net_raw"] = [x[0] for x in nets], [x[1] for x in nets]
        variants[name] = e
        dailies[name] = daily_series(e, prices, spy, days) if len(e) else pd.Series(dtype=float)
    shs = [d.mean() / d.std(ddof=1) for d in dailies.values() if len(d) > 10 and d.std() > 0]
    var_sr = max(float(np.var(shs, ddof=1)), 1e-6) if len(shs) == 2 else 1e-4
    out = dict(coverage=cov, params=dict(thresh=THRESH, hold=HOLD, cost_leg_bps=5, borrow_yr=BORROW, seed=SEED,
                                         n_random=N_RANDOM, n_boot=N_BOOT, var_sr_trials=var_sr, n_trials=2),
               bias="Universo = S&P100 odierno hardcoded: survivorship bias (nomi vincenti ex-post).", variants={})
    for name, e in variants.items():
        ctrl = random_control(e.reset_index(drop=True), prices, spy, days) if len(e) else np.empty((0, N_RANDOM))
        r = summarize(name, e, ctrl, dailies[name], var_sr)
        r["verdict"], r["failed"] = verdict(r) if len(e) >= 5 else ("INSUFFICIENT DATA", ["n<5"])
        out["variants"][name] = r
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(out, indent=1, default=str))
    (OUT / "report.md").write_text(render(out))
    print(json.dumps({k: (v["n_events"], v["verdict"]) for k, v in out["variants"].items()}), cov)


def f(x, p=2):
    return "n/d" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x * 100:.{p}f}%"


def render(o):
    c = o["coverage"]
    L = ["# PEAD pre-registrato (S&P100, yfinance)", "",
         "## Dati e limiti", f"- {o['bias']}",
         f"- Ticker con prezzi: {c['tickers_with_prices']}/100; con eventi usabili: {c['tickers_with_events']}; mancanti: {', '.join(c['missing_tickers']) or 'nessuno'}",
         f"- Eventi con surprise valida: {c['events_with_surprise']}; usabili (finestra completa): {c['events_usable']}",
         f"- Copertura annunci: {c['first_announcement']} -> {c['last_announcement']} (yfinance limit=60 per ticker; storia limitata)",
         "- Timing: giorno 1 = primo open dopo l'annuncio (pre-market 09:30 ET stesso giorno; dopo chiusura/ignoto/in seduta giorno di borsa dopo); entrata open giorno 2, uscita close giorno 21 (20 giorni).",
         "- Costi: 5 bp per gamba x2, borrow 1%/anno sugli short; aggiustamento = ritorno titolo - SPY stessa finestra (nessun costo sulla gamba SPY).",
         "- Serie giornaliera: media equal-weight delle posizioni aperte, solo giorni con posizioni (giorni a poche posizioni pesano come quelli affollati: la media giornaliera puo divergere dalla media per evento); DSR con var Sharpe tra i 2 trial.", ""]
    for n, r in o["variants"].items():
        L += [f"## {n}: **{r['verdict']}**", f"- Eventi: {r['n_events']}; criteri falliti: {', '.join(r.get('failed', [])) or 'nessuno'}"]
        if "mean_net_adj" in r:
            rc = r["random_control"]
            L += [f"- Media netta agg. mercato: {f(r['mean_net_adj'])} (lordo {f(r['mean_gross_adj'])}); grezza netta: {f(r['mean_net_raw'])}",
                  f"- t cluster-mese: {r['t_cluster_month']:.2f}; bootstrap CI95 (mesi): [{f(r['boot_ci95'][0])}, {f(r['boot_ci95'][1])}]; hit rate {f(r['hit_rate'], 1)}",
                  f"- Controllo random (20 rep): media {f(rc['mean'])}; differenza {f(rc['diff_mean'])} CI95 [{f(rc['diff_ci95'][0])}, {f(rc['diff_ci95'][1])}]",
                  f"- Anni con >=30 eventi: {r['years_ge30']}, frazione positivi {f(r['years_pos_frac'], 0)}", "", "| Anno | n | media netta agg. |", "|---|---|---|"]
            L += [f"| {y} | {v['n']} | {f(v['mean'])} |" for y, v in r["by_year"].items()]
            if "by_decile_mkt_adj_return_unsigned" in r:
                L += ["", "Decili di surprise (1=piu negativo), ritorno 20g agg. mercato lordo senza segno:", ""]
                L += [f"- D{k + 1}: {f(v)}" for k, v in r["by_decile_mkt_adj_return_unsigned"].items()]
                L += [f"- Spearman decile/ritorno: {r['decile_spearman']:.2f}"]
            if "daily" in r:
                d = r["daily"]
                L += ["", f"- Serie giornaliera ({d['n_days']} giorni): Sharpe ann. {d['sharpe_ann']:.2f}; DSR(n=2) {d['dsr_n2']:.3f}; DSR(n=80) {d['dsr_n80']:.3f}"]
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    {"fetch": fetch, "run": run}[sys.argv[1]]()
