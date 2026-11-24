"""Report JSON + Markdown e regola di verdetto (nessun arrotondamento dei risultati negativi)."""
from __future__ import annotations

import json
import math
from pathlib import Path

NO_EDGE = "NO EDGE — do not deploy"
RULES = {"oos_logloss_vs_base": "< 0", "dsr": "> 0.95 (p-value < 0.05)", "pbo": "< 0.2",
         "expectancy_ret": "> 0 (dopo costi)", "n_trades": ">= 200", "auc": "> 0.52",
         "beats_primary_only": "expectancy > primary_only (il filtro deve aggiungere valore, non solo beta)",
         "beats_random_control": "expectancy > random@<kind> con la stessa accettazione"}
MIN_AUC = 0.52


def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return x


def evaluate_config(row: dict, pbo: float, primary: dict | None = None, random_ctrl: dict | None = None) -> dict:
    """Controlla gli 8 criteri; NaN = fallito. Restituisce {criterio: bool, 'deployable': bool}.
    Oltre a edge assoluto richiede edge INCREMENTALE: il modello deve battere la strategia primaria
    senza filtro e un filtro casuale con la stessa accettazione (altrimenti cattura solo beta/timing)."""
    e = _f(row.get("expectancy_ret"))
    ok = dict(
        logloss=_f(row.get("logloss_vs_base")) < 0,
        dsr=_f(row.get("dsr")) > 0.95,
        pbo=_f(pbo) < 0.2,
        expectancy=e > 0,
        n_trades=(_f(row.get("n_trades")) >= 200),
        auc=_f(row.get("auc")) > MIN_AUC,
        beats_primary_only=e > _f((primary or {}).get("expectancy_ret")),
        beats_random_control=e > _f((random_ctrl or {}).get("expectancy_ret")),
    )
    ok["deployable"] = all(ok.values()) and row.get("role") == "model"
    return ok


def verdict(summary_rows: dict, pbo: float) -> dict:
    """summary_rows: config -> dict di metriche. Verdetto globale + elenco configurazioni deployable."""
    prim = summary_rows.get("primary_only")
    checks = {n: evaluate_config(r, pbo, prim, summary_rows.get(f"random@{n}"))
              for n, r in summary_rows.items() if r.get("role") == "model"}
    dep = [n for n, c in checks.items() if c["deployable"]]
    if dep:
        best = max(dep, key=lambda n: _f(summary_rows[n].get("dsr")))
        v = f"DEPLOYABLE: {best}"
    else:
        v = NO_EDGE
    return dict(verdict=v, deployable=bool(dep), deployable_configs=dep,
                deployable_kinds=sorted({summary_rows[n]["kind"] for n in dep}), checks=checks, rules=RULES)


def _fmt(x, nd=4):
    x = _f(x)
    return "n/a" if math.isnan(x) else f"{x:.{nd}f}"


def write_report(result, out_dir, name: str = "research", extra: dict | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = {n: dict(r) for n, r in result.summary.reset_index().set_index("config").to_dict("index").items()}
    v = verdict(rows, result.pbo)
    d = result.to_dict()
    d.update(name=name, **{k: v[k] for k in ("verdict", "deployable", "deployable_configs", "deployable_kinds",
                                              "checks", "rules")}, extra=extra or {})
    (out / "report.json").write_text(json.dumps(d, indent=2, default=str))

    L = [f"# Report ricerca meta-labeling — {name}", "",
         f"**Verdetto: {v['verdict']}**", "",
         f"- Simboli: {', '.join(result.config['symbols'])} | intervallo {result.config['interval']} | "
         f"dati {result.config['data_start']} -> {result.config['data_end']}",
         f"- Eventi: {result.config['n_events']} | fold OOS: {result.config['n_folds']} | "
         f"configurazioni (n_trials DSR): {result.n_trials} | PBO (CSCV): {_fmt(result.pbo)}",
         f"- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; "
         f"n_trades >= 200; AUC > 0.52; expectancy > primary_only e > filtro casuale. Fallire un criterio = NO EDGE.", "",
         "## Classifica modelli (OOS, dopo costi)", "",
         "| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | "
         "Brier | DSR | deploy |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    order = sorted(rows, key=lambda n: (rows[n]["role"] != "model", _f(rows[n].get("oos_logloss"))
                                        if not math.isnan(_f(rows[n].get("oos_logloss"))) else 9e9))
    for n in order:
        r = rows[n]
        dep = ("SI" if v["checks"][n]["deployable"] else "no") if n in v["checks"] else "(controllo)"
        L.append(f"| {n} | {int(_f(r['n_trades'])) if not math.isnan(_f(r['n_trades'])) else 0} | "
                 f"{_fmt(_f(r['win_rate']) * 100, 1)} | {_fmt(r['expectancy_ret'], 5)} | {_fmt(r['profit_factor'], 2)} | "
                 f"{_fmt(r['sharpe'], 2)} | {_fmt(r['max_dd'], 3)} | {_fmt(_f(r['acceptance_rate']) * 100, 1)} | "
                 f"{_fmt(r['oos_logloss'])} | {_fmt(r['logloss_vs_base'], 5)} | {_fmt(r['auc'], 3)} | "
                 f"{_fmt(r['ic'], 3)} | {_fmt(r['brier'])} | {_fmt(r['dsr'], 3)} | {dep} |")
    L += ["", "## Criteri per configurazione", "", "| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |",
          "|---|---|---|---|---|---|"]
    for n, c in v["checks"].items():
        L.append(f"| {n} | {c['logloss']} | {c['dsr']} | {c['pbo']} | {c['expectancy']} | {c['n_trades']} |")
    if result.best_kind:
        L += ["", f"## Calibrazione OOS — {result.best_kind}", "", "| bin | n | p media | frazione vincenti |", "|---|---|---|---|"]
        for c in result.details[result.best_kind]["calibration"]:
            L.append(f"| {c['lo']:.1f}-{c['hi']:.1f} | {c['n']} | {_fmt(c['mean_p'], 3)} | {_fmt(c['frac_pos'], 3)} |")
    if len(result.ablation):
        L += ["", f"## Ablazione per famiglia ({result.best_kind}): Δ log-loss quando la famiglia viene rimossa",
              "(>0 = la famiglia aiuta; <0 = peggiora il modello)", "", "| famiglia | colonne | Δ log-loss |", "|---|---|---|"]
        for f, r in result.ablation.iterrows():
            L.append(f"| {f} | {int(r['n_cols'])} | {_fmt(r['delta_logloss'], 5)} |")
    if len(result.importance):
        L += ["", "## Permutation importance per famiglia (ultimo fold, train, OOF)", "", "| famiglia | Δ log-loss |", "|---|---|"]
        for f, x in result.importance.items():
            L.append(f"| {f} | {_fmt(x, 5)} |")
    L += ["", "## Fold", "", "| test_start | test_end | n_train | n_test | purged | p* | payoff |", "|---|---|---|---|---|---|---|"]
    for _, r in result.folds.iterrows():
        L.append(f"| {str(r.test_start)[:16]} | {str(r.test_end)[:16]} | {r.n_train} | {r.n_test} | {r.n_purged} | "
                 f"{_fmt(r.p_star, 3)} | {_fmt(r.payoff, 2)} |")
    if not v["deployable"]:
        L += ["", f"> **{NO_EDGE}.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli."]
    (out / "report.md").write_text("\n".join(L) + "\n")
    return d
