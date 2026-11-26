"""Builds reports/METALABELING_KELLY_AUDIT.md from reports/metakelly/<universe>/results.json."""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NAMES = {"eq": "Azioni Alpaca (1h, benchmark SPY)", "cr": "Perpetui crypto Bybit (15m, benchmark BTCUSDT)"}


def _f(x, d=3, pct=False):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x * 100:.2f}%" if pct else f"{x:.{d}f}"


def perf_table(r: dict) -> list:
    calib = r["calibration"]
    L = ["| configurazione | trade | win% | expectancy | PF netto | PF excess | Sharpe netto | Sharpe beta-adj | "
         "DSR netto | DSR beta-adj | max DD | max esposizione | Brier | log-loss |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for nm, s in r["summary"].items():
        cal = {}
        if nm.startswith("C_meta_C"):
            C = nm.split("_C")[1].split("_k")[0]
            cal = calib.get(f"p_C{C}", {})
        pf_exc = None if nm.startswith("B1") else s.get("profit_factor_excess")  # B1: per-trade beta not estimated
        L.append(f"| {nm} | {s.get('n_trades', 0)} | {_f(s.get('win_rate'), pct=True)} | {_f(s.get('expectancy'), pct=True)} | "
                 f"{_f(s.get('profit_factor'), 2)} | {_f(pf_exc, 2)} | {_f(s.get('sharpe_net'), 2)} | "
                 f"{_f(s.get('sharpe_excess'), 2)} | {_f(s.get('dsr_net'))} | {_f(s.get('dsr_excess'))} | "
                 f"{_f(s.get('max_drawdown'), pct=True)} | {_f(s.get('max_gross'), 2)} | {_f(cal.get('brier'), 4)} | "
                 f"{_f(cal.get('log_loss'), 4)} |")
    return L


def calib_table(r: dict) -> list:
    L = ["| previsore di P(TP prima di SL e di T_end) | n | Brier | log-loss | Δ log-loss vs base rate | t fold (log-loss) | "
         "Δ Brier vs base | t fold (Brier) |", "|---|---|---|---|---|---|---|---|"]
    for k, v in r["calibration"].items():
        L.append(f"| `{k}` | {v['n']} | {_f(v['brier'], 4)} | {_f(v['log_loss'], 4)} | {_f(v['d_logloss_vs_base'], 4)} | "
                 f"{_f(v['t_fold_logloss'], 2)} | {_f(v['d_brier_vs_base'], 5)} | {_f(v['t_fold_brier'], 2)} |")
    return L


def build(notes: dict | None = None) -> str:
    notes = notes or {}
    L = ["# Audit: Meta-Labeling L2 + Kelly frazionario vs benchmark beta-adjusted", "",
         "Protocollo pre-registrato: `reports/PREREG_METALABELING_KELLY.md` (commit 2570b10, prima di ogni run). "
         "Codice: `quant/research/metakelly/` (commit b21bdea, prima del primo run). Dati grezzi per universo in "
         "`reports/metakelly/<eq|cr>/` (`results.json`, `events.csv.gz`, `oos_predictions.csv.gz`).", ""]
    overall = []
    for u in ("eq", "cr"):
        p = ROOT / "reports" / "metakelly" / u / "results.json"
        if not p.exists():
            L += [f"## {NAMES[u]}", "", "Run non disponibile.", ""]
            continue
        r = json.loads(p.read_text())
        verdict = "PROMUOVIBILE AL PAPER LAB" if r["promoted"] else "SCARTATO"
        overall.append((u, verdict))
        L += [f"## {NAMES[u]} — esito: **{verdict}**", "",
              f"- Periodo OOS: {r['oos_period'][0]} → {r['oos_period'][1]}; eventi etichettati {r['n_events']}, "
              f"OOS {r['n_oos']}, fold {len(r['folds'])}; motori: {r['engines']}.",
              f"- Frequenza dell'etichetta y = 1 (TP prima di SL e T_end): **{_f(r['label_rate'], pct=True)}**.",
              f"- Feature: {', '.join(r['features'])}.",
              f"- PBO (CSCV, 6 configurazioni): beta-adjusted {_f(r['pbo_excess'])}, netto {_f(r['pbo_net'])}. "
              f"C migliore per log-loss: {r['best_C']}.", ""]
        if u in notes:
            L += [notes[u], ""]
        L += ["### Rendimenti OOS (A baseline, B benchmark, C meta + Kelly, controlli random@)", ""] + perf_table(r) + [""]
        L += ["### Calibrazione OOS", ""] + calib_table(r) + [""]
        L += ["### Criteri di promozione (migliore C per log-loss)", "", "| configurazione | criterio | esito |", "|---|---|---|"]
        for nm, v in r["verdicts"].items():
            for c, ok in v["criteria"].items():
                L.append(f"| {nm} | {c} | {'OK' if ok else 'NO'} |")
        L += ["", "### Fold", "", "| fold | test | n train | n test | purgati | in embargo | base rate train |",
              "|---|---|---|---|---|---|---|"]
        for f in r["folds"]:
            L.append(f"| {f['fold']} | {f['test_start'][:10]} → {f['test_end'][:10]} | {f['n_train']} | {f['n_test']} | "
                     f"{f['n_purged']} | {f['n_embargoed']} | {_f(f['base_rate'], 4)} |")
        L.append("")
    L.insert(4, "**Verdetto complessivo: " + "; ".join(f"{NAMES[u].split(' (')[0]} {v}" for u, v in overall) + "**")
    L.insert(5, "")
    if "general" in notes:
        L += [notes["general"], ""]
    return "\n".join(L) + "\n"


def write(notes: dict | None = None) -> Path:
    out = ROOT / "reports" / "METALABELING_KELLY_AUDIT.md"
    out.write_text(build(notes))
    return out
