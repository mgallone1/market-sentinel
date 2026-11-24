"""Fattori cross-sectional cripto long/short (F1 momentum, F2 carry funding, F3 low-vol beta-neutral) + COMBO.
Pre-registrati, nessun tuning. Dati: Binance Vision 1d perp USDT con funding. Ribilancio lunedi' 00:00 UTC
con dati fino alla chiusura della domenica; pesi tenuti 7 giorni."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from quant.validation import deflated_sharpe_ratio

SYMS = ("BTC ETH BNB SOL XRP ADA DOGE TRX AVAX LINK DOT MATIC LTC BCH ATOM ETC XLM FIL NEAR APT ARB OP SUI INJ "
        "AAVE UNI MKR SAND MANA AXS GALA FTM ALGO EOS THETA XTZ CRV DYDX LDO RUNE").split()
UNIVERSE = [s + "USDT" for s in SYMS]
SEASON_DAYS = 60
FEE_BPS, SLIP_BPS = 5.5, 2.0
SIDE_BPS = FEE_BPS + SLIP_BPS
FACTORS = ("F1", "F2", "F3")
N_TRIALS_DSR = 100
OUT = Path("reports/crypto_factors")


def eligible(close: pd.DataFrame, asof: pd.Timestamp) -> list[str]:
    """Simboli con barra alla chiusura `asof` (giorno-barra domenica) e >= SEASON_DAYS barre di storia."""
    h = close.loc[:asof]
    if asof not in h.index:
        return []
    cnt = h.notna().sum()
    return [c for c in close.columns if pd.notna(h[c].iloc[-1]) and cnt[c] >= SEASON_DAYS]


def _quint(n: int) -> int:
    return max(1, n // 5)


def rebalance_weights(close: pd.DataFrame, funding: pd.DataFrame, monday: pd.Timestamp, factor: str,
                      btc: str = "BTCUSDT") -> pd.Series:
    """Pesi target per il ribilancio di `monday` 00:00; usa solo barre con open <= domenica (open monday-1d)."""
    sun = monday - pd.Timedelta(days=1)
    w = pd.Series(0.0, index=close.columns)
    el = eligible(close, sun)
    if len(el) < 10:
        return w
    c = close.loc[:sun, el]
    if factor == "F1":
        score = c.iloc[-2] / c.iloc[-29] - 1          # ritorno 28g saltando l'ultimo giorno
        lo_long, hi_long = False, True
    elif factor == "F2":
        score = funding.loc[:sun, el].iloc[-7:].mean()
        lo_long, hi_long = True, False
    elif factor == "F3":
        r = c.pct_change(fill_method=None).iloc[-60:]
        score = r.std(ddof=1)
        lo_long = True
    else:
        raise ValueError(factor)
    score = score.dropna()
    k = _quint(len(score))
    order = score.sort_values(kind="mergesort")
    low, high = list(order.index[:k]), list(order.index[-k:])
    if factor == "F1":
        longs, shorts = high, low
    else:  # F2, F3: long i piu' bassi, short i piu' alti
        longs, shorts = low, high
    gl = gs = 0.5
    if factor == "F3":
        r = c.pct_change(fill_method=None).iloc[-60:]
        rb = r[btc] if btc in r else r.mean(axis=1)
        beta = r.apply(lambda s: s.cov(rb) / rb.var() if rb.var() > 0 else np.nan)
        bl, bs = beta[longs].mean(), beta[shorts].mean()
        if np.isfinite(bl) and np.isfinite(bs) and bl > 0 and bs > 0:
            gl = float(np.clip(bs / (bl + bs), 0.25, 0.75))   # gl*bl = gs*bs, gross 1, cap 0.75
            gs = 1.0 - gl
    w[longs] = gl / len(longs)
    w[shorts] = -gs / len(shorts)
    return w


def weekly_weights(close, funding, factor) -> pd.DataFrame:
    mondays = [d for d in close.index if d.dayofweek == 0 and d >= close.index[0] + pd.Timedelta(days=SEASON_DAYS)]
    return pd.DataFrame({m: rebalance_weights(close, funding, m, factor) for m in mondays}).T


def run_factor(close: pd.DataFrame, funding: pd.DataFrame, W: pd.DataFrame, side_bps: float = SIDE_BPS) -> pd.DataFrame:
    """Rendimenti settimanali: gross, funding, costi, netto. Settimana = barre lun..dom dopo il ribilancio."""
    ret = close.pct_change(fill_method=None).fillna(0.0)
    fnd = funding.fillna(0.0)
    rows = {}
    prev = pd.Series(0.0, index=close.columns)
    for m, w in W.iterrows():
        sl = slice(m, m + pd.Timedelta(days=6))
        wk = (1 + ret.loc[sl]).prod() - 1
        gross = float((w * wk).sum())
        fpnl = float(-(w * fnd.loc[sl].sum()).sum())      # long paga funding positivo, short lo riceve
        turn = float((w - prev).abs().sum())
        cost = turn * side_bps / 1e4
        rows[m] = dict(gross=gross, funding=fpnl, cost=cost, turnover=turn, net=gross + fpnl - cost)
        prev = w
    out = pd.DataFrame(rows).T
    return out[out.index + pd.Timedelta(days=6) <= close.index[-1]]


def combo(rets: dict[str, pd.Series], win: int = 52, minp: int = 13) -> pd.Series:
    df = pd.DataFrame(rets)
    iv = 1.0 / df.rolling(win, min_periods=minp).std().shift(1)      # causale: vol fino a t-1
    iv = iv.replace([np.inf, -np.inf], np.nan)
    w = iv.div(iv.sum(axis=1), axis=0)
    w = w.where(iv.notna().all(axis=1), 1.0 / df.shape[1])
    return (w * df).sum(axis=1)


def boot_sharpe_ci(r: np.ndarray, block: int = 4, n: int = 2000, seed: int = 0):
    """Bootstrap stazionario (blocchi geometrici media `block`) dello Sharpe annualizzato (52)."""
    T = len(r)
    rng = np.random.default_rng(seed)
    idx = np.empty((n, T), dtype=np.int64)
    idx[:, 0] = rng.integers(0, T, n)
    new = rng.random((n, T)) < 1.0 / block
    st = rng.integers(0, T, (n, T))
    for t in range(1, T):
        idx[:, t] = np.where(new[:, t], st[:, t], (idx[:, t - 1] + 1) % T)
    x = r[idx]
    s = x.mean(1) / x.std(1, ddof=1) * np.sqrt(52)
    return float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))


def _sh(r):
    return float(r.mean() / r.std(ddof=1) * np.sqrt(52)) if len(r) > 2 and r.std() > 0 else float("nan")


def perf(df: pd.DataFrame, btc_w: pd.Series) -> dict:
    r = df["net"]
    eq = (1 + r).cumprod()
    yrs = len(r) / 52
    dn = r[r < 0].std(ddof=1) * np.sqrt(52)
    byy = r.groupby(r.index.year).apply(lambda x: float((1 + x).prod() - 1))
    post = r[r.index >= "2023-01-01"]
    a = pd.concat([r, btc_w], axis=1).dropna()
    out = dict(cagr=float(eq.iloc[-1] ** (1 / yrs) - 1), vol=float(r.std(ddof=1) * np.sqrt(52)), sharpe=_sh(r),
               sortino=float(r.mean() * 52 / dn), maxdd=float((eq / eq.cummax() - 1).min()),
               pct_pos_weeks=float((r > 0).mean()), by_year={int(k): v for k, v in byy.items()},
               n_years_pos=int((byy > 0).sum()), corr_btc=float(a.iloc[:, 0].corr(a.iloc[:, 1])),
               turnover_annual=float(df["turnover"].mean() * 52) if "turnover" in df else None,
               cost_annual=float(df["cost"].mean() * 52) if "cost" in df else None,
               funding_annual=float(df["funding"].mean() * 52) if "funding" in df else None,
               gross_annual=float(df["gross"].mean() * 52) if "gross" in df else None,
               sharpe_post2023=_sh(post), n_weeks=int(len(r)))
    out["boot_ci95_sharpe"] = boot_sharpe_ci(r.values)
    return out


def load_data(start="2021-01-01", end="2026-11-01"):
    from quant.data.binance_vision import get_bars

    def one(s):
        try:
            b = get_bars(s, "1d", start, end)
            return s, (b if len(b) else None)
        except Exception as e:  # noqa: BLE001
            print("skip", s, e, file=sys.stderr)
            return s, None
    with ThreadPoolExecutor(4) as ex:
        res = dict(ex.map(one, UNIVERSE))
    missing = [s for s, b in res.items() if b is None]
    ok = {s: b for s, b in res.items() if b is not None}
    close = pd.DataFrame({s: b["close"] for s, b in ok.items()})
    fund = pd.DataFrame({s: b["funding_rate"] for s, b in ok.items()})
    return close, fund, missing


def main():
    close, fund, missing = load_data()
    close = close.loc["2021-01-01":"2026-10-31"]
    fund = fund.reindex(close.index)
    res = {}
    for f in FACTORS:
        res[f] = run_factor(close, fund, weekly_weights(close, fund, f))
    cb = combo({f: res[f]["net"] for f in FACTORS})
    btc = (1 + close["BTCUSDT"].pct_change().fillna(0)).resample("W-SUN", label="left", closed="right").prod() - 1
    btc.index = btc.index + pd.Timedelta(days=0)
    # BTC settimanale allineato a lun..dom
    bw = {m: float((1 + close["BTCUSDT"].pct_change().loc[m:m + pd.Timedelta(days=6)].fillna(0)).prod() - 1)
          for m in res["F1"].index}
    btc_w = pd.Series(bw)
    stats = {f: perf(res[f], btc_w) for f in FACTORS}
    cdf = pd.DataFrame({"net": cb}).dropna()
    cdf["turnover"] = sum(res[f]["turnover"] for f in FACTORS) / 3
    stats["COMBO"] = perf(cdf[["net", "turnover"]], btc_w)
    srs = np.array([res[f]["net"].mean() / res[f]["net"].std(ddof=1) for f in FACTORS])
    var_sr = float(np.var(srs, ddof=1))
    for k, rr in [(f, res[f]["net"]) for f in FACTORS] + [("COMBO", cdf["net"])]:
        s = stats[k]
        s["dsr_n100"] = float(deflated_sharpe_ratio(rr.values, N_TRIALS_DSR, var_sr))
        s["keep_checks"] = dict(sharpe_gt_0_5=s["sharpe"] > 0.5, years_pos_ge_4=s["n_years_pos"] >= 4,
                                post2023_gt_0=s["sharpe_post2023"] > 0, dsr_gt_0_95=s["dsr_n100"] > 0.95,
                                boot_lo_gt_0=s["boot_ci95_sharpe"][0] > 0)
        s["verdict"] = "KEEP" if all(s["keep_checks"].values()) else "DISCARD"
    cnt = pd.Series({d: len(eligible(close, d - pd.Timedelta(days=1))) for d in res["F1"].index})
    meta = dict(missing_symbols=missing, n_loaded=int(close.shape[1]), var_sr_trials=var_sr,
                first_rebalance=str(res["F1"].index[0].date()), last_rebalance=str(res["F1"].index[-1].date()),
                eligible_min=int(cnt.min()), eligible_max=int(cnt.max()), eligible_mean=float(cnt.mean()),
                cost_side_bps=SIDE_BPS, n_trials_factors=3)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(dict(meta=meta, stats=stats), indent=1, default=float))
    write_md(meta, stats)
    print(json.dumps({k: (v["sharpe"], v["verdict"]) for k, v in stats.items()}))


def write_md(meta, st):
    L = ["# Fattori cross-sectional cripto (Binance USD-M perp, 1d)", "",
         f"Periodo ribilanci: {meta['first_rebalance']} .. {meta['last_rebalance']} (settimanale, lunedi' 00:00 UTC). "
         f"Simboli caricati: {meta['n_loaded']}/40; non disponibili (404/vuoti): {', '.join(meta['missing_symbols']) or 'nessuno'}. "
         f"Universo eleggibile per ribilancio: min {meta['eligible_min']}, media {meta['eligible_mean']:.1f}, max {meta['eligible_max']}.",
         f"Costi {meta['cost_side_bps']} bps per lato sul turnover; funding incluso. Prove pre-registrate: 3; DSR con n_trials=100, "
         f"var Sharpe tra prove = {meta['var_sr_trials']:.5f} (per-periodo, tra i 3 fattori).", "",
         "| Fattore | CAGR | Vol | Sharpe | Sortino | MaxDD | %sett+ | Sharpe 2023+ | Corr BTC | DSR(100) | CI95 Sharpe | Verdetto |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, s in st.items():
        L.append(f"| {k} | {s['cagr']:.1%} | {s['vol']:.1%} | {s['sharpe']:.2f} | {s['sortino']:.2f} | {s['maxdd']:.1%} | "
                 f"{s['pct_pos_weeks']:.1%} | {s['sharpe_post2023']:.2f} | {s['corr_btc']:.2f} | {s['dsr_n100']:.3f} | "
                 f"[{s['boot_ci95_sharpe'][0]:.2f}, {s['boot_ci95_sharpe'][1]:.2f}] | {s['verdict']} |")
    L += ["", "## Rendimento netto per anno (2026 parziale)", "", "| Fattore | " + " | ".join(str(y) for y in range(2021, 2027)) + " | anni+ |",
          "|---|" + "---|" * 7]
    for k, s in st.items():
        L.append(f"| {k} | " + " | ".join(f"{s['by_year'].get(y, float('nan')):.1%}" for y in range(2021, 2027)) + f" | {s['n_years_pos']} |")
    L += ["", "## Turnover, costi e funding (annualizzati, frazione NAV)", "", "| Fattore | Turnover | Gross | Funding | Costi |", "|---|---|---|---|---|"]
    for k, s in st.items():
        if s["gross_annual"] is None:
            L.append(f"| {k} | {s['turnover_annual']:.1f} | - | - | - |")
        else:
            L.append(f"| {k} | {s['turnover_annual']:.1f} | {s['gross_annual']:.1%} | {s['funding_annual']:.1%} | {s['cost_annual']:.1%} |")
    L += ["", "## Regola KEEP (tutte vere)", "", "| Fattore | Sharpe>0.5 | >=4/6 anni+ | Sharpe 2023+>0 | DSR>0.95 | CI lo>0 |", "|---|---|---|---|---|---|"]
    for k, s in st.items():
        c = s["keep_checks"]
        L.append(f"| {k} | {c['sharpe_gt_0_5']} | {c['years_pos_ge_4']} | {c['post2023_gt_0']} | {c['dsr_gt_0_95']} | {c['boot_lo_gt_0']} |")
    L += ["", "Note: pesi costanti nella settimana (nessun drift), turnover = somma |dw|; funding sommato sulle barre lun..dom; "
          "BTCUSDT incluso nell'universo; COMBO = pesi inverso-vol 52 settimane causali (equal-weight finche' < 13 settimane)."]
    (OUT / "report.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
