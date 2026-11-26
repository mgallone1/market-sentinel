# Risultati: famiglia `phys_` nel meta-labeling (pre-registrato)

**Verdetto complessivo: NESSUN MIGLIORAMENTO**

Protocollo e criteri: `PREREGISTRATION.md`. Report completi per braccio in `<dataset>_<base|phys>/`.

## Dataset A (donchian_breakout)

Verdetto deploy: BASE = NO EDGE — do not deploy | PHYS = NO EDGE — do not deploy

| modello | logloss BASE | logloss PHYS | Δ logloss | t (8 fold) | AUC BASE | AUC PHYS | Δ AUC | PHYS vs base_rate | expectancy BASE | expectancy PHYS |
|---|---|---|---|---|---|---|---|---|---|---|
| logit | 0.68345 | 0.68229 | -0.00115 | -0.39 | 0.501 | 0.491 | -0.010 | +0.00764 | +0.00032 | -0.00194 |
| hgb | 0.67690 | 0.67695 | +0.00005 | +0.05 | 0.498 | 0.507 | +0.009 | +0.00230 | +0.00115 | -0.00186 |

Modello migliore PHYS: `hgb` | ablazione `phys_` (Δ logloss se rimossa): -0.00069

| criterio | esito |
|---|---|
| 1_d_logloss<=-0.001 | NO |
| 2_d_auc>=+0.005 | OK |
| 3_t_fold<=-2 | NO |
| 4_ablation_phys>0 | NO |

Esito dataset A: NON SUPERATO

## Dataset B (legacy)

Verdetto deploy: BASE = NO EDGE — do not deploy | PHYS = NO EDGE — do not deploy

| modello | logloss BASE | logloss PHYS | Δ logloss | t (8 fold) | AUC BASE | AUC PHYS | Δ AUC | PHYS vs base_rate | expectancy BASE | expectancy PHYS |
|---|---|---|---|---|---|---|---|---|---|---|
| logit | 0.69001 | 0.68747 | -0.00254 | -1.16 | 0.505 | 0.510 | +0.005 | +0.00317 | -0.00190 | -0.00050 |
| hgb | 0.68713 | 0.68763 | +0.00050 | +1.11 | 0.507 | 0.508 | +0.000 | +0.00333 | -0.00415 | -0.00517 |

Modello migliore PHYS: `logit` | ablazione `phys_` (Δ logloss se rimossa): -0.00078

| criterio | esito |
|---|---|
| 1_d_logloss<=-0.001 | OK |
| 2_d_auc>=+0.005 | OK |
| 3_t_fold<=-2 | NO |
| 4_ablation_phys>0 | NO |

Esito dataset B: NON SUPERATO

