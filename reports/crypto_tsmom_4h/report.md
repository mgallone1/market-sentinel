# Report ricerca meta-labeling — tsmom

**Verdetto: NO EDGE — do not deploy**

- Simboli: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, LINKUSDT, AVAXUSDT, ADAUSDT, DOGEUSDT, SUIUSDT, NEARUSDT | intervallo 4h | dati 2023-11-01 00:00:00+00:00 -> 2026-11-01 00:00:00+00:00
- Eventi: 39759 | fold OOS: 8 | configurazioni (n_trials DSR): 6 | PBO (CSCV): 0.9130
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rf | 754 | 40.1 | 0.00160 | 1.07 | 0.27 | -0.023 | 16.4 | 0.6666 | -0.00001 | 0.521 | 0.113 | 0.2365 | 0.536 | no |
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6667 | 0.00000 | 0.492 | 0.042 | 0.2367 | n/a | no |
| ensemble | 621 | 40.4 | 0.00257 | 1.11 | 0.45 | -0.026 | 10.6 | 0.6669 | 0.00020 | 0.500 | 0.047 | 0.2367 | 0.634 | no |
| hgb | 641 | 39.3 | 0.00044 | 1.02 | 0.18 | -0.029 | 11.8 | 0.6669 | 0.00027 | 0.504 | 0.054 | 0.2364 | 0.483 | no |
| logit | 542 | 43.2 | 0.00475 | 1.21 | 0.60 | -0.022 | 8.9 | 0.6691 | 0.00246 | 0.500 | 0.050 | 0.2375 | 0.717 | no |
| gbm_montecarlo | 2878 | 38.7 | 0.00108 | 1.04 | 0.52 | -0.219 | 93.7 | 0.8691 | 0.20248 | 0.513 | -0.044 | 0.3218 | 0.671 | no |
| primary_only | 2720 | 38.3 | 0.00062 | 1.03 | 0.00 | -0.485 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@gbm_montecarlo | 3081 | 38.0 | 0.00049 | 1.02 | 0.08 | -0.286 | 93.7 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 868 | 36.5 | -0.00200 | 0.92 | -0.42 | -0.039 | 8.9 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 915 | 37.3 | -0.00218 | 0.92 | -0.24 | -0.032 | 11.8 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 990 | 37.8 | -0.00220 | 0.91 | -0.38 | -0.031 | 16.4 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@ensemble | 929 | 36.7 | -0.00237 | 0.91 | -0.65 | -0.041 | 10.6 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | False | False | False |
| gbm_montecarlo | False | False | False | True | True |
| logit | False | False | False | True | True |
| hgb | False | False | False | True | True |
| rf | True | False | False | True | True |
| ensemble | False | False | False | True | True |

## Calibrazione OOS — rf

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 163 | 0.176 | 0.337 |
| 0.2-0.3 | 3174 | 0.281 | 0.341 |
| 0.3-0.4 | 20784 | 0.346 | 0.378 |
| 0.4-0.5 | 1680 | 0.427 | 0.447 |
| 0.5-0.6 | 9 | 0.549 | 0.667 |
| 0.6-0.7 | 0 | n/a | n/a |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 5 | 0.990 | 0.400 |

## Ablazione per famiglia (rf): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| reg_ | 4 | 0.00413 |
| struct_ | 16 | 0.00378 |
| meta_ | 1 | 0.00288 |
| vol_ | 7 | 0.00271 |
| cal_ | 5 | 0.00246 |
| xs_ | 6 | 0.00231 |
| trend_ | 14 | 0.00227 |
| rev_ | 8 | 0.00176 |
| volu_ | 8 | 0.00165 |
| deriv_ | 3 | 0.00137 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| meta_ | 0.00149 |
| vol_ | 0.00088 |
| volu_ | 0.00054 |
| struct_ | 0.00036 |
| cal_ | 0.00013 |
| reg_ | 0.00004 |
| deriv_ | 0.00002 |
| xs_ | -0.00017 |
| rev_ | -0.00043 |
| trend_ | -0.00137 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2024-11-05 00:00 | 2025-02-02 20:00 | 13526 | 3394 | 0 | 0.378 | 1.65 |
| 2025-02-03 00:00 | 2025-05-03 20:00 | 14114 | 3202 | 0 | 0.374 | 1.68 |
| 2025-05-04 00:00 | 2025-08-01 20:00 | 13798 | 3141 | 0 | 0.379 | 1.64 |
| 2025-08-02 00:00 | 2025-10-30 20:00 | 13408 | 3501 | 0 | 0.380 | 1.63 |
| 2025-10-31 00:00 | 2026-01-28 20:00 | 13471 | 3161 | 0 | 0.380 | 1.63 |
| 2026-01-29 00:00 | 2026-04-28 20:00 | 13079 | 2862 | 0 | 0.389 | 1.57 |
| 2026-04-29 00:00 | 2026-07-27 20:00 | 12976 | 3438 | 0 | 0.373 | 1.68 |
| 2026-07-28 00:00 | 2026-10-25 20:00 | 13111 | 3116 | 0 | 0.375 | 1.67 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
