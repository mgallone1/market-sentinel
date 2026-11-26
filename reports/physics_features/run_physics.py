"""Pre-registered test of the `phys_` feature family (see PREREGISTRATION.md in this folder).

Runs, for each dataset (A: donchian_breakout + default rules, B: legacy + LEGACY_BOT_RULES), two
walk-forward arms with identical events/folds/seed: BASE (current features) and PHYS (+ phys_).
Writes per-arm reports (report.json/.md) and the paired comparison (results.json, RESULTS.md).
Usage: python reports/physics_features/run_physics.py [A|B ...]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from quant.cli import _bars_per_day, load_universe, make_rules  # noqa: E402
from quant.research import run_walkforward, write_report  # noqa: E402

OUT = Path(__file__).resolve().parent
KINDS = ("base_rate", "logit", "hgb")
ML = ("logit", "hgb")
DATASETS = {
    "A": dict(strategy="donchian_breakout", rules="default"),
    "B": dict(strategy="legacy", rules="legacy"),
}


def log_loss_vec(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def run_arm(uni, bench, name, cfg, physics):
    rules = make_rules(cfg["rules"], "1h")
    bpd = _bars_per_day(uni)
    t0 = time.monotonic()
    res = run_walkforward(uni, "1h", cfg["strategy"], rules, KINDS,
                          train_bars=int(365 * bpd), test_bars=int(90 * bpd),
                          embargo_bars=max(int(2 * bpd), rules.max_hold_bars),
                          threshold="breakeven", sizing="kelly", benchmark=bench, seed=0,
                          ablation=physics, importance=False, physics=physics)
    arm = "phys" if physics else "base"
    d = write_report(res, OUT / f"{name}_{arm}", f"{cfg['strategy']} [{arm}]")
    logging.info("%s %s done in %.0fs: %s", name, arm, time.monotonic() - t0, d["verdict"])
    return res, d


def compare(name, base, phys):
    rb, rp = base[0], phys[0]
    sb, sp = rb.summary, rp.summary
    out = {"dataset": name, "kinds": {}}
    n_test = rb.folds["n_test"].to_numpy(int)
    assert list(n_test) == list(rp.folds["n_test"].to_numpy(int)), "fold diversi tra i bracci"
    for k in ML:
        pb, pp = rb.predictions[k], rp.predictions[k]
        assert np.array_equal(pb["y"].to_numpy(), pp["y"].to_numpy()), "eventi non allineati"
        diff = log_loss_vec(pp["p"], pp["y"]) - log_loss_vec(pb["p"], pb["y"])
        bounds = np.cumsum(np.r_[0, n_test])
        fold_d = np.array([diff[bounds[i]:bounds[i + 1]].mean() for i in range(len(n_test))])
        t_fold = float(fold_d.mean() / (fold_d.std(ddof=1) / math.sqrt(len(fold_d)))) if fold_d.std(ddof=1) > 0 else float("nan")
        out["kinds"][k] = dict(
            logloss_base=float(sb.loc[k, "oos_logloss"]), logloss_phys=float(sp.loc[k, "oos_logloss"]),
            d_logloss=float(sp.loc[k, "oos_logloss"] - sb.loc[k, "oos_logloss"]),
            auc_base=float(sb.loc[k, "auc"]), auc_phys=float(sp.loc[k, "auc"]),
            d_auc=float(sp.loc[k, "auc"] - sb.loc[k, "auc"]),
            logloss_vs_base_rate_phys=float(sp.loc[k, "logloss_vs_base"]),
            expectancy_base=float(sb.loc[k, "expectancy_ret"]) if "expectancy_ret" in sb else None,
            expectancy_phys=float(sp.loc[k, "expectancy_ret"]) if "expectancy_ret" in sp else None,
            n_trades_phys=int(sp.loc[k, "n_trades"]) if "n_trades" in sp else None,
            fold_d_logloss=[float(x) for x in fold_d], t_fold=t_fold,
            event_d_mean=float(diff.mean()), event_d_se=float(diff.std(ddof=1) / math.sqrt(len(diff))),
        )
    best = rp.best_kind if rp.best_kind in ML else min(ML, key=lambda k: float(sp.loc[k, "oos_logloss"]))
    abl = rp.ablation
    phys_abl = float(abl.loc["phys_", "delta_logloss"]) if len(abl) and "phys_" in abl.index else float("nan")
    kb = out["kinds"][best]
    crit = {
        "1_d_logloss<=-0.001": kb["d_logloss"] <= -0.001,
        "2_d_auc>=+0.005": kb["d_auc"] >= 0.005,
        "3_t_fold<=-2": (kb["t_fold"] <= -2.0) if np.isfinite(kb["t_fold"]) else False,
        "4_ablation_phys>0": (phys_abl > 0.0) if np.isfinite(phys_abl) else False,
    }
    out.update(best_kind_phys=best, ablation_phys_delta=phys_abl, criteria=crit, passed=all(crit.values()),
               verdict_base=base[1]["verdict"], verdict_phys=phys[1]["verdict"],
               ablation_table=(abl.reset_index().to_dict("records") if len(abl) else []))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("datasets", nargs="*", default=["A", "B"])
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("quant.research.walkforward").setLevel(logging.INFO)
    ns = argparse.Namespace(universe="crypto", interval="1h", start="2023-11-01", end="2026-11-01",
                            synthetic=False, n_synth=0)
    uni, bench = load_universe(ns)
    logging.info("universo: %s", {s: len(b) for s, (b, _) in uni.items()})
    res_path = OUT / "results.json"
    results = json.loads(res_path.read_text()) if res_path.exists() else {}
    for name in a.datasets:
        cfg = DATASETS[name]
        base = run_arm(uni, bench, name, cfg, physics=False)
        phys = run_arm(uni, bench, name, cfg, physics=True)
        results[name] = compare(name, base, phys)
        res_path.write_text(json.dumps(results, indent=2, default=str))
    overall = bool(results) and all(r["passed"] for r in results.values()) and set(results) >= {"A", "B"}
    write_md(results, overall)


def write_md(results, overall):
    L = ["# Risultati: famiglia `phys_` nel meta-labeling (pre-registrato)", "",
         f"**Verdetto complessivo: {'PHYS MIGLIORA LA PREVISIONE' if overall else 'NESSUN MIGLIORAMENTO'}**", "",
         "Protocollo e criteri: `PREREGISTRATION.md`. Report completi per braccio in `<dataset>_<base|phys>/`.", ""]
    for name, r in results.items():
        L += [f"## Dataset {name} ({DATASETS[name]['strategy']})", "",
              f"Verdetto deploy: BASE = {r['verdict_base']} | PHYS = {r['verdict_phys']}", "",
              "| modello | logloss BASE | logloss PHYS | Δ logloss | t (8 fold) | AUC BASE | AUC PHYS | Δ AUC | PHYS vs base_rate | expectancy BASE | expectancy PHYS |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, m in r["kinds"].items():
            L.append(f"| {k} | {m['logloss_base']:.5f} | {m['logloss_phys']:.5f} | {m['d_logloss']:+.5f} | {m['t_fold']:+.2f} | "
                     f"{m['auc_base']:.3f} | {m['auc_phys']:.3f} | {m['d_auc']:+.3f} | {m['logloss_vs_base_rate_phys']:+.5f} | "
                     f"{m['expectancy_base'] if m['expectancy_base'] is not None else float('nan'):+.5f} | "
                     f"{m['expectancy_phys'] if m['expectancy_phys'] is not None else float('nan'):+.5f} |")
        L += ["", f"Modello migliore PHYS: `{r['best_kind_phys']}` | ablazione `phys_` (Δ logloss se rimossa): "
              f"{r['ablation_phys_delta']:+.5f}", "",
              "| criterio | esito |", "|---|---|"]
        L += [f"| {c} | {'OK' if v else 'NO'} |" for c, v in r["criteria"].items()]
        L += ["", f"Esito dataset {name}: {'SUPERATO' if r['passed'] else 'NON SUPERATO'}", ""]
    (OUT / "RESULTS.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
