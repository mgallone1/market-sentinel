"""Runner of the pre-registered meta-labeling + Kelly experiment (reports/PREREG_METALABELING_KELLY.md).

python -m quant.research.metakelly.run --universe eq|cr [--workers 3]
Writes reports/metakelly/<universe>/results.json, events.parquet-like CSV and a markdown summary.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from quant.validation.stats import deflated_sharpe_ratio, pbo_cscv

from . import benchmark as bm
from . import candidates as cg
from . import features as ft
from .cv import assert_no_overlap, purged_expanding_splits
from .labels import equity_time_barrier, triple_barrier
from .model import fit_predict
from .sizing import W_MAX, kelly_weights, max_gross_exposure, simulate_portfolio

log = logging.getLogger("metakelly")
ROOT = Path(__file__).resolve().parents[3]
EQ_SYMS = ("NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "META", "GOOGL", "AMD")
CR_SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT", "AVAXUSDT", "ADAUSDT", "DOGEUSDT", "SUIUSDT", "NEARUSDT")
C_GRID = (0.01, 0.1, 1.0)
KELLY_GRID = (0.15, 0.25)
FIXED_W = 0.10

UNIVERSES = {
    "eq": dict(interval_min=60.0, cost_rt=0.0004, stop_extra=0.0003, bars_per_year=252 * 6.5,
               test_len=pd.Timedelta(days=91), embargo=pd.Timedelta(days=1), periods=252.0),
    "cr": dict(interval_min=15.0, cost_rt=0.0015, stop_extra=0.0003, bars_per_year=365 * 24 * 4,
               test_len=pd.Timedelta(days=61), embargo=pd.Timedelta(hours=24), periods=365.0, horizon=96),
}


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def load_eq() -> Dict:
    import yfinance as yf

    def dl(t, period, interval):
        d = yf.download(t, period=period, interval=interval, progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        d = d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        idx = pd.DatetimeIndex(d.index)
        d.index = idx.tz_localize("America/New_York").tz_convert("UTC") if idx.tz is None else idx.tz_convert("UTC")
        return d[~d.index.duplicated()].sort_index()

    bars = {s: dl(s, "730d", "1h") for s in EQ_SYMS + ("SPY",)}
    vix = dl("^VIX", "5y", "1d")["Close"]
    vix.index = pd.DatetimeIndex(vix.index).tz_convert("America/New_York").tz_localize(None).normalize()
    return {"bars": bars, "vix": vix}


def load_cr() -> Dict:
    from quant.core import crypto_perp
    from quant.data import load_bars

    bars, taker, fund = {}, {}, {}
    for s in CR_SYMS:
        d = load_bars(crypto_perp(s, "bybit"), "15m", "2024-11-01", "2026-11-01")
        bars[s] = cg.to_live(d)
        taker[s] = d["taker_buy_volume"] if "taker_buy_volume" in d else None
        fund[s] = (d["funding_rate"] * 100.0) if "funding_rate" in d else pd.Series(0.0, index=d.index)
    return {"bars": bars, "taker": taker, "funding": fund}


# ---------------------------------------------------------------------------
# stage 1 + labels + features
# ---------------------------------------------------------------------------

def _eq_worker(args):
    sym, df, macro = args
    return cg.equity_candidates(sym, df, macro)


def _cr_worker(args):
    sym, df, tb, fund, bias = args
    return cg.crypto_candidates(sym, df, tb, fund, bias)


def build_events(universe: str, data: Dict, workers: int) -> pd.DataFrame:
    bars = data["bars"]
    t = time.monotonic()
    if universe == "eq":
        macro = cg.equities_macro_bias(bars["SPY"], data["vix"])
        jobs = [(s, bars[s], macro) for s in EQ_SYMS]
        fn = _eq_worker
    else:
        bias = cg.btc_bias_series(bars["BTCUSDT"])
        jobs = [(s, bars[s], data["taker"][s], data["funding"][s], bias.reindex(bars[s].index).fillna("NEUTRAL"))
                for s in CR_SYMS]
        fn = _cr_worker
    with ProcessPoolExecutor(max_workers=workers) as ex:
        rows = [r for res in ex.map(fn, jobs) for r in res]
    log.info("%s: %d candidati in %.0fs", universe, len(rows), time.monotonic() - t)
    ev = pd.DataFrame(rows)
    return label_and_featurize(universe, ev, data)


def label_and_featurize(universe: str, ev: pd.DataFrame, data: Dict) -> pd.DataFrame:
    cfg = UNIVERSES[universe]
    bars = data["bars"]
    syms = EQ_SYMS if universe == "eq" else CR_SYMS
    bench_sym = "SPY" if universe == "eq" else "BTCUSDT"
    closes = {s: bars[s]["Close"] for s in syms}
    idio = ft.idio_panel(closes, bars[bench_sym]["Close"], window=140)
    ofi = {s: ft.ofi_series(bars[s].rename(columns=str.lower)) for s in syms}
    rv5 = ft.realized_vol_5d(bars["SPY"].rename(columns=str.lower)) if universe == "eq" else None
    bench_c = bars[bench_sym]["Close"]
    out = []
    for sym, g in ev.groupby("symbol"):
        df = bars[sym]
        idx = df.index
        o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
        if universe == "eq":
            tend = equity_time_barrier(idx, cfg["interval_min"])
        for r in g.itertuples(index=False):
            i = int(r.pos)
            end_pos = int(tend[i]) if universe == "eq" else min(i + cfg["horizon"], len(df) - 1)
            lab = triple_barrier(h, l, c, i, int(r.side), r.sl_pct, r.tp_pct, end_pos, cfg["cost_rt"], cfg["stop_extra"])
            if lab is None:
                continue
            j = int(lab["exit_pos"])
            t1 = idx[j] + pd.Timedelta(minutes=cfg["interval_min"])
            nu, s2, s2rs, n = ft.variance_inputs(o, h, l, c, idx, cfg["interval_min"], i)
            fp = ft.fp_features(nu, s2, s2rs, n, int(r.side), r.sl_pct, r.tp_pct, end_pos - i, cfg["bars_per_year"])
            t_bar = idx[i]
            row = dict(r._asdict())
            row.update(fp)
            row.update({"t1": t1, "y": lab["y"], "ret": lab["ret"], "outcome": lab["outcome"], "hold_bars": j - i})
            of = ofi[sym]
            row["ofi_bvc_short"] = float(of["ofi_bvc_short"].get(t_bar, np.nan))
            row["ofi_bvc_med"] = float(of["ofi_bvc_med"].get(t_bar, np.nan))
            idp = idio[sym]
            beta = float(idp["spy_beta"].get(t_bar, np.nan)) if sym != bench_sym else 1.0
            row["beta_sym"] = beta
            if universe == "eq":
                row["idio_z_drift"] = float(idp["idio_z_drift"].get(t_bar, np.nan))
                row["idio_cs_rank"] = float(idp["idio_cs_rank"].get(t_bar, np.nan))
                vix_y = data["vix"].loc[:t_bar.tz_convert("America/New_York").tz_localize(None).normalize() - pd.Timedelta(days=1)]
                rv = float(rv5.get(t_bar, np.nan))
                row["vrp_spread"] = (float(vix_y.iloc[-1]) / 100.0 - rv) if (len(vix_y) and np.isfinite(rv)) else np.nan
                row["session_frac_left"] = float(r.minutes_to_close) / 390.0
            b0 = bench_c.asof(t_bar)
            b1 = bench_c.asof(idx[j])
            row["bench_ret"] = float(b1 / b0 - 1.0) if (b0 and b1) else 0.0
            sl_c = r.sl_pct / 100.0 + cfg["cost_rt"] + cfg["stop_extra"]
            row["payoff_R"] = (r.tp_pct / 100.0 - cfg["cost_rt"]) / sl_c
            out.append(row)
    ev2 = pd.DataFrame(out).sort_values("t0").reset_index(drop=True)
    for e in sorted(ev2["engine"].unique()):
        ev2[f"eng_{e}"] = (ev2["engine"] == e).astype(float)
    return ev2


def feature_cols(universe: str, ev: pd.DataFrame) -> List[str]:
    cols = ["fp_p_tp_zero_drift", "fp_p_tp_rs_zero_drift", "fp_p_tp_bayes", "ofi_bvc_short", "ofi_bvc_med", "side"]
    if universe == "eq":
        cols += ["idio_z_drift", "idio_cs_rank", "vrp_spread", "session_frac_left"]
    cols += [c for c in ev.columns if c.startswith("eng_")]
    return cols


# ---------------------------------------------------------------------------
# always-long benchmark (B1)
# ---------------------------------------------------------------------------

def always_long_events(universe: str, data: Dict, t_from: pd.Timestamp, t_to: pd.Timestamp) -> pd.DataFrame:
    """Per symbol, back-to-back long trades (enter at every cycle bar when flat) with the momentum
    engine's default SL/TP (clamp(ATR% * 1.4, 0.9, max) and 3x) and the same time barrier."""
    cfg = UNIVERSES[universe]
    syms = EQ_SYMS if universe == "eq" else CR_SYMS
    max_sl = 2.5 if universe == "eq" else 1.8
    rows = []
    for sym in syms:
        df = data["bars"][sym]
        idx = df.index
        h, l, c = (df[k].to_numpy(float) for k in ("High", "Low", "Close"))
        atr = (cg.atr_wilder(df["High"], df["Low"], df["Close"], 14) / df["Close"] * 100.0).to_numpy()
        tend = equity_time_barrier(idx, cfg["interval_min"]) if universe == "eq" else None
        i = int(np.searchsorted(idx, t_from))
        while i < len(df) and idx[i] < t_to:
            if universe == "eq":
                end_pos = int(tend[i])
                b = cg.market_calendar.session_bounds(idx[i].tz_convert("America/New_York").date())
                bar_end = min(idx[i] + pd.Timedelta(hours=1), pd.Timestamp(b[1]).tz_convert("UTC")) if b else idx[i]
                if b is None or (pd.Timestamp(b[1]).tz_convert("UTC") - bar_end).total_seconds() < 1800:
                    i += 1
                    continue
            else:
                end_pos = min(i + cfg["horizon"], len(df) - 1)
            sl = float(np.clip(atr[i] * 1.4, 0.9, max_sl)) if np.isfinite(atr[i]) else 1.2
            lab = triple_barrier(h, l, c, i, 1, sl, 3 * sl, end_pos, cfg["cost_rt"], cfg["stop_extra"])
            if lab is None:
                i += 1
                continue
            j = int(lab["exit_pos"])
            rows.append({"symbol": sym, "t0": idx[i] + pd.Timedelta(minutes=cfg["interval_min"]),
                         "t1": idx[j] + pd.Timedelta(minutes=cfg["interval_min"]), "ret": lab["ret"], "side": 1})
            i = j + 1
    return pd.DataFrame(rows).sort_values("t0").reset_index(drop=True)


# ---------------------------------------------------------------------------
# experiment
# ---------------------------------------------------------------------------

def _fold_t(diff: np.ndarray, bounds: List[int]) -> float:
    m = np.array([diff[bounds[k]:bounds[k + 1]].mean() for k in range(len(bounds) - 1) if bounds[k + 1] > bounds[k]])
    if len(m) < 2 or m.std(ddof=1) == 0:
        return float("nan")
    return float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m))))


def _ll_vec(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def run(universe: str, workers: int = 3, out_dir: Path | None = None) -> Dict:
    cfg = UNIVERSES[universe]
    out_dir = out_dir or ROOT / "reports" / "metakelly" / universe
    out_dir.mkdir(parents=True, exist_ok=True)
    data = load_eq() if universe == "eq" else load_cr()
    ev = build_events(universe, data, workers)
    ev.to_csv(out_dir / "events.csv", index=False)
    cols = feature_cols(universe, ev)
    t0 = pd.DatetimeIndex(ev["t0"])
    t1 = pd.DatetimeIndex(ev["t1"])
    first = t0.min() + pd.Timedelta(days=365)
    folds = list(purged_expanding_splits(t0, t1, first, cfg["test_len"], cfg["embargo"]))
    log.info("%s: %d eventi, %d fold", universe, len(ev), len(folds))

    X = ev[cols].to_numpy(float)
    y = ev["y"].to_numpy(int)
    oos_idx, fold_bounds, fold_rows = [], [0], []
    preds = {C: [] for C in C_GRID}
    base = []
    for k, f in enumerate(folds):
        assert_no_overlap(t0, t1, f, cfg["embargo"])
        tr, te = f.train_idx, f.test_idx
        base.append(np.full(len(te), y[tr].mean()))
        for C in C_GRID:
            p, _ = fit_predict(X[tr], y[tr], X[te], C)
            preds[C].append(p)
        oos_idx.extend(te.tolist())
        fold_bounds.append(fold_bounds[-1] + len(te))
        fold_rows.append(dict(fold=k, test_start=str(f.test_start), test_end=str(f.test_end), n_train=len(tr),
                              n_test=len(te), n_purged=f.n_purged, n_embargoed=f.n_embargoed,
                              base_rate=float(y[tr].mean())))
    oos = ev.iloc[oos_idx].reset_index(drop=True)
    oos["p_base"] = np.concatenate(base)
    for C in C_GRID:
        oos[f"p_C{C}"] = np.concatenate(preds[C])
    yo = oos["y"].to_numpy(int)

    # ------------------------------------------------ calibration
    calib = {}
    ll_base = _ll_vec(oos["p_base"], yo)
    br_base = (oos["p_base"].to_numpy() - yo) ** 2
    for name in ["p_base"] + [f"p_C{C}" for C in C_GRID] + ["fp_p_tp", "fp_p_tp_zero_drift", "fp_p_tp_rs_zero_drift", "fp_p_tp_bayes"]:
        p = oos[name].to_numpy(float)
        m = np.isfinite(p)
        llv, brv = _ll_vec(p[m], yo[m]), (p[m] - yo[m]) ** 2
        calib[name] = dict(n=int(m.sum()), brier=float(brv.mean()), log_loss=float(llv.mean()),
                           d_logloss_vs_base=float((llv - ll_base[m]).mean()),
                           d_brier_vs_base=float((brv - br_base[m]).mean()),
                           t_fold_logloss=_fold_t(_ll_vec(oos[name].fillna(0.5), yo) - ll_base, fold_bounds),
                           t_fold_brier=_fold_t((oos[name].fillna(0.5).to_numpy() - yo) ** 2 - br_base, fold_bounds))

    # ------------------------------------------------ portfolios
    t_from = pd.Timestamp(folds[0].test_start)
    t_to = pd.Timestamp(folds[-1].test_end)
    tz = "America/New_York" if universe == "eq" else "UTC"
    if universe == "eq":
        sb = data["bars"]["SPY"]["Close"]
        days = pd.DatetimeIndex(sb.index).tz_convert(tz).normalize().tz_localize(None)
        bench_daily = sb.groupby(days).last().pct_change().fillna(0.0)
    else:
        sb = data["bars"]["BTCUSDT"]["Close"]
        days = pd.DatetimeIndex(sb.index).normalize().tz_localize(None)
        bench_daily = sb.groupby(days).last().pct_change().fillna(0.0)
    lo, hi = t_from.tz_convert(tz).normalize().tz_localize(None), t_to.tz_convert(tz).normalize().tz_localize(None)
    cal = bench_daily.loc[lo:hi].index
    bench_daily = bench_daily.reindex(cal).fillna(0.0)

    def evaluate(trades: pd.DataFrame) -> Dict:
        daily = bm.daily_pnl(trades, cal, tz)
        exc = bm.beta_adjusted_excess(daily, bench_daily)["excess"]
        te_ = bm.trade_excess(trades["ret"], trades["side"], trades.get("beta_sym", pd.Series(0.0, index=trades.index)),
                              trades.get("bench_ret", pd.Series(0.0, index=trades.index))) if len(trades) else np.array([])
        return dict(trades=trades, daily=daily, excess=exc, trade_exc=te_)

    res: Dict[str, Dict] = {}
    res["A_baseline_all"] = evaluate(simulate_portfolio(oos, np.full(len(oos), FIXED_W)))
    for e in sorted(oos["engine"].unique()):
        sub = oos[oos["engine"] == e]
        res[f"A_{e}"] = evaluate(simulate_portfolio(sub, np.full(len(sub), FIXED_W)))
    al = always_long_events(universe, data, t_from, t_to)
    al["beta_sym"] = 0.0
    al["bench_ret"] = 0.0
    res["B1_always_long"] = evaluate(simulate_portfolio(al, np.full(len(al), FIXED_W)))
    rng = np.random.default_rng(0)
    cfg_names = []
    for C in C_GRID:
        for kc in KELLY_GRID:
            nm = f"C_meta_C{C}_k{kc}"
            cfg_names.append(nm)
            w = kelly_weights(oos[f"p_C{C}"].to_numpy(), oos["payoff_R"].to_numpy(), kc, W_MAX)
            res[nm] = evaluate(simulate_portfolio(oos, w))
            k = int((w > 0).sum())
            wr = np.zeros(len(oos))
            if k:
                pick = rng.choice(len(oos), k, replace=False)
                wr[pick] = rng.permutation(w[w > 0])
            res["random@" + nm] = evaluate(simulate_portfolio(oos, wr))

    # DSR / PBO across the 6 meta configs
    srs = np.array([np.nanmean(res[n]["excess"]) / np.nanstd(res[n]["excess"], ddof=1)
                    if np.nanstd(res[n]["excess"], ddof=1) > 0 else np.nan for n in cfg_names])
    srs_net = np.array([np.nanmean(res[n]["daily"]) / np.nanstd(res[n]["daily"], ddof=1)
                        if np.nanstd(res[n]["daily"], ddof=1) > 0 else np.nan for n in cfg_names])
    var_ex = float(np.nanvar(srs)) if np.isfinite(srs).sum() > 1 else 0.0
    var_net = float(np.nanvar(srs_net)) if np.isfinite(srs_net).sum() > 1 else 0.0
    M_ex = np.column_stack([res[n]["excess"].to_numpy() for n in cfg_names])
    M_net = np.column_stack([res[n]["daily"].to_numpy() for n in cfg_names])

    def _pbo(M):
        S = 16
        while S > 2 and M.shape[0] < S:
            S -= 2
        try:
            return float(pbo_cscv(M, n_splits=S)[0])
        except Exception:
            return float("nan")

    pbo_ex, pbo_net = _pbo(M_ex), _pbo(M_net)
    summary = {}
    for nm, r in res.items():
        is_cfg = nm in cfg_names
        s = bm.perf_summary(r["trades"], r["daily"], r["excess"], cfg["periods"],
                            n_trials=6 if is_cfg else 1, var_sr=var_ex if is_cfg else 0.0, trade_exc=r["trade_exc"])
        if is_cfg:
            s["dsr_net"] = deflated_sharpe_ratio(r["daily"].to_numpy(), 6, var_net)
        s["max_gross"] = max_gross_exposure(r["trades"])
        summary[nm] = s
    bh = bm.perf_summary(pd.DataFrame(columns=["ret"]), bench_daily, bench_daily * 0.0, cfg["periods"])
    summary["B2_passive_" + ("SPY" if universe == "eq" else "BTC")] = bh

    # promotion criteria on the best config by log-loss
    bestC = min(C_GRID, key=lambda C: calib[f"p_C{C}"]["log_loss"])
    cand = [f"C_meta_C{bestC}_k{kc}" for kc in KELLY_GRID]
    verdicts = {}
    for nm in cand:
        s, cal_ = summary[nm], calib[f"p_C{bestC}"]
        crit = {
            "1_logloss_brier_below_base_t<=-2": bool(cal_["d_logloss_vs_base"] < 0 and cal_["d_brier_vs_base"] < 0
                                                    and cal_["t_fold_logloss"] <= -2 and cal_["t_fold_brier"] <= -2),
            "2_dsr_excess>0.95": bool(s["dsr_excess"] > 0.95),
            "3_pbo<0.20": bool(pbo_ex < 0.20),
            "4_excess>0_and_sharpe_excess>baseline": bool(s["excess_cum"] > 0
                                                         and s["sharpe_excess"] > summary["A_baseline_all"]["sharpe_excess"]),
            "5_expectancy>random_and_baseline": bool(s["expectancy"] > summary["random@" + nm]["expectancy"]
                                                     and s["expectancy"] > summary["A_baseline_all"]["expectancy"]),
            "6_n_trades>=100": bool(s["n_trades"] >= 100),
        }
        verdicts[nm] = dict(criteria=crit, promoted=all(crit.values()))
    out = dict(universe=universe, n_events=int(len(ev)), n_oos=int(len(oos)), features=cols, folds=fold_rows,
               engines=ev["engine"].value_counts().to_dict(), label_rate=float(ev["y"].mean()),
               calibration=calib, summary=summary, pbo_excess=pbo_ex, pbo_net=pbo_net, best_C=bestC,
               verdicts=verdicts, promoted=any(v["promoted"] for v in verdicts.values()),
               oos_period=[str(t_from), str(t_to)])
    (out_dir / "results.json").write_text(json.dumps(out, indent=2, default=lambda o: None if (isinstance(o, float) and not math.isfinite(o)) else str(o)))
    oos.to_csv(out_dir / "oos_predictions.csv", index=False)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", required=True, choices=list(UNIVERSES))
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    r = run(a.universe, a.workers)
    log.info("%s: promoted=%s best_C=%s", a.universe, r["promoted"], r["best_C"])


if __name__ == "__main__":
    main()
