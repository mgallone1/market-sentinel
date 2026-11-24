"""
Verifiche anti-artefatto sul risultato S1_grid|FUTURES (spot EIA):
 1) autocorrelazione lag-1 delle variazioni giornaliere dello spread: spot EIA (Londra vs NY, orari diversi)
    contro futures Yahoo (BZ=F/CL=F, chiusure quasi sincrone).
 2) stessa griglia con esecuzione al giorno DOPO il segnale (decisione su s[i], prezzo s[i+1]).
"""
import math, json
import numpy as np, pandas as pd, yfinance as yf
import quant.research.spreads as sp
from quant.research.experiments.brent_wti_spot import fred, stats

def grid_lagged(a, b, cost, lag=1, step_mult=0.25, max_n=8, kill=4.0):
    d = sp._clean_pair(a, b); s = (d.a - d.b).to_numpy(); idx = d.index; pa, pb = d.a.to_numpy(), d.b.to_numpy()
    m = pd.Series(s).rolling(60).mean().to_numpy(); sd = pd.Series(s).rolling(60).std(ddof=1).to_numpy()
    n = len(s); pnl = np.zeros(n); trades = []; longs, shorts = [], []; sc = 2 * cost["v"]
    pending = []  # (exec_index, action, payload)
    for i in range(61, n):
        dt = (idx[i] - idx[i - 1]).days / 365.0
        for p in longs + shorts:
            sg = 1 if p in longs else -1
            dd = sg * (s[i] - s[i - 1]) - cost["fin"] * (pa[i - 1] + pb[i - 1]) * dt
            pnl[i] += dd; p["pnl"] += dd
        # esegui ordini decisi lag giorni fa al prezzo di oggi
        for act in [x for x in pending if x[0] == i]:
            _, kind, p = act
            if kind == "open":
                p["e"] = s[i]; p["entry"] = idx[i]; pnl[i] -= sc; p["pnl"] = -sc
                (longs if p["side"] == 1 else shorts).append(p)
            elif kind == "close" and (p in longs or p in shorts):
                pnl[i] -= sc; p["pnl"] -= sc
                trades.append(dict(entry=p["entry"], exit=idx[i], pnl=p["pnl"]))
                (longs if p in longs else shorts).remove(p)
        pending = [x for x in pending if x[0] > i]
        if i + lag >= n:
            continue
        z = (s[i] - m[i]) / sd[i]
        if abs(z) > kill:
            for p in longs + shorts:
                pending.append((i + lag, "close", p))
            continue
        for lst, sg in ((longs, 1), (shorts, -1)):
            for p in lst:
                if sg * (s[i] - p["e"]) >= p["step"] - 1e-12 and not any(x[2] is p for x in pending):
                    pending.append((i + lag, "close", p))
        step = step_mult * sd[i]
        if step <= 0:
            continue
        kn = math.floor((s[i] - m[i]) / step); kp = math.floor((s[i - 1] - m[i]) / step)
        if kn != kp and abs(kn - kp) < 60:
            levels = range(kn + 1, kp + 1) if kn < kp else range(kp + 1, kn + 1)
            n_l = len(longs) + sum(1 for x in pending if x[1] == "open" and x[2]["side"] == 1)
            n_s = len(shorts) + sum(1 for x in pending if x[1] == "open" and x[2]["side"] == -1)
            for L in levels:
                if L < 0 and n_l < max_n:
                    pending.append((i + lag, "open", dict(side=1, step=step, pnl=0.0))); n_l += 1
                elif L > 0 and n_s < max_n:
                    pending.append((i + lag, "open", dict(side=-1, step=step, pnl=0.0))); n_s += 1
    return dict(pnl=pd.Series(pnl, index=idx), trades=trades)

def main():
    brent, wti = fred("DCOILBRENTEU").loc["1990":], fred("DCOILWTICO").loc["1990":]
    ds = sp._clean_pair(brent, wti); dsp = (ds.a - ds.b).diff().dropna()
    fb = yf.download("BZ=F", start="2008-01-01", progress=False)["Close"].squeeze()
    fc = yf.download("CL=F", start="2008-01-01", progress=False)["Close"].squeeze()
    fb.index = pd.to_datetime(fb.index).tz_localize(None); fc.index = pd.to_datetime(fc.index).tz_localize(None)
    df_ = sp._clean_pair(fb, fc); dfu = (df_.a - df_.b).diff().dropna()
    dfu = dfu[dfu.abs() < dfu.abs().quantile(0.995)]   # toglie i salti da roll piu' grandi
    common = dsp.index.intersection(dfu.index)
    out = {"autocorr_lag1_spot_1990_2026": float(dsp.autocorr(1)),
           "autocorr_lag1_spot_2008_2026": float(dsp.loc["2008":].autocorr(1)),
           "autocorr_lag1_futures_2008_2026": float(dfu.autocorr(1)),
           "autocorr_lag1_spot_same_days": float(dsp.loc[common].autocorr(1)),
           "autocorr_lag1_futures_same_days": float(dfu.loc[common].autocorr(1))}
    fut = dict(kind="abs", v=0.01, fin=0.0035)
    for lag in (0, 1):
        if lag == 0:
            sp.S1_COST = fut; r = sp.s1_grid(brent, wti, costs=True)
        else:
            r = grid_lagged(brent, wti, fut, lag=1)
        s = stats(r["pnl"], r["trades"])
        out[f"spot_grid_FUTURES_lag{lag}"] = {k: s[k] for k in ("sharpe", "sharpe_post2018", "boot_ci95", "win", "n_trades", "dsr_n110")}
    r = grid_lagged(fb, fc, fut, lag=1)
    s = stats(r["pnl"], r["trades"])
    out["futures_yahoo_grid_FUTURES_lag1_2008_2026"] = {k: s[k] for k in ("sharpe", "sharpe_post2018", "boot_ci95", "win", "n_trades", "dsr_n110")}
    print(json.dumps(out, indent=1, default=float))
    import pathlib; pathlib.Path("reports/brent_wti_spot/checks.json").write_text(json.dumps(out, indent=1, default=float))

if __name__ == "__main__":
    main()
