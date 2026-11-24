# Report ricerca meta-labeling — donchian_breakout

**Verdetto: NO EDGE — do not deploy**

- Simboli: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, LINKUSDT, AVAXUSDT, ADAUSDT, DOGEUSDT, SUIUSDT, NEARUSDT | intervallo 4h | dati 2023-11-01 00:00:00+00:00 -> 2026-11-01 00:00:00+00:00
- Eventi: 2286 | fold OOS: 8 | configurazioni (n_trials DSR): 6 | PBO (CSCV): 0.1732
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6881 | 0.00000 | 0.472 | 0.009 | 0.2465 | n/a | no |
| rf | 76 | 31.6 | -0.00526 | 0.78 | -0.68 | -0.009 | 7.7 | 0.6954 | 0.00736 | 0.468 | 0.002 | 0.2490 | 0.013 | no |
| ensemble | 83 | 33.7 | -0.00357 | 0.86 | -1.08 | -0.013 | 6.4 | 0.7124 | 0.02429 | 0.484 | 0.035 | 0.2529 | 0.002 | no |
| hgb | 141 | 35.5 | -0.00235 | 0.91 | -0.73 | -0.017 | 11.9 | 0.7138 | 0.02573 | 0.480 | 0.010 | 0.2542 | 0.010 | no |
| logit | 62 | 35.5 | -0.00138 | 0.94 | -0.60 | -0.014 | 5.8 | 0.7295 | 0.04137 | 0.489 | 0.057 | 0.2536 | 0.016 | no |
| gbm_montecarlo | 868 | 39.7 | 0.00347 | 1.13 | 1.00 | -0.108 | 100.0 | 0.9827 | 0.29464 | 0.527 | -0.021 | 0.3628 | 0.532 | no |
| primary_only | 837 | 40.4 | 0.00458 | 1.18 | 0.66 | -0.189 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@gbm_montecarlo | 879 | 40.3 | 0.00432 | 1.17 | 0.75 | -0.123 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 82 | 30.5 | -0.00721 | 0.74 | -1.22 | -0.023 | 5.8 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 156 | 38.5 | 0.00355 | 1.15 | 0.32 | -0.009 | 11.9 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 104 | 36.5 | -0.00258 | 0.90 | -0.23 | -0.007 | 7.7 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@ensemble | 89 | 34.8 | -0.00435 | 0.85 | -0.89 | -0.019 | 6.4 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | True | False | False |
| gbm_montecarlo | False | False | True | True | True |
| logit | False | False | True | False | False |
| hgb | False | False | True | False | False |
| rf | False | False | True | False | False |
| ensemble | False | False | True | False | False |

## Calibrazione OOS — rf

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 0 | n/a | n/a |
| 0.2-0.3 | 812 | 0.283 | 0.403 |
| 0.3-0.4 | 648 | 0.325 | 0.386 |
| 0.4-0.5 | 112 | 0.417 | 0.375 |
| 0.5-0.6 | 0 | n/a | n/a |
| 0.6-0.7 | 0 | n/a | n/a |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 1 | 0.990 | 0.000 |

## Ablazione per famiglia (rf): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| meta_ | 1 | -0.00126 |
| rev_ | 8 | -0.00192 |
| reg_ | 4 | -0.00193 |
| struct_ | 16 | -0.00207 |
| vol_ | 7 | -0.00238 |
| deriv_ | 3 | -0.00264 |
| volu_ | 8 | -0.00289 |
| trend_ | 14 | -0.00354 |
| xs_ | 6 | -0.00412 |
| cal_ | 5 | -0.00667 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| cal_ | 0.01020 |
| xs_ | 0.00056 |
| volu_ | 0.00030 |
| trend_ | 0.00025 |
| deriv_ | -0.00010 |
| meta_ | -0.00012 |
| vol_ | -0.00030 |
| rev_ | -0.00063 |
| reg_ | -0.00104 |
| struct_ | -0.00260 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2024-11-05 00:00 | 2025-02-02 20:00 | 693 | 244 | 0 | 0.372 | 1.69 |
| 2025-02-03 00:00 | 2025-05-03 20:00 | 798 | 195 | 0 | 0.364 | 1.75 |
| 2025-05-04 00:00 | 2025-08-01 20:00 | 827 | 244 | 0 | 0.364 | 1.75 |
| 2025-08-02 00:00 | 2025-10-30 20:00 | 913 | 143 | 0 | 0.371 | 1.69 |
| 2025-10-31 00:00 | 2026-01-28 20:00 | 840 | 212 | 0 | 0.381 | 1.63 |
| 2026-01-29 00:00 | 2026-04-28 20:00 | 806 | 167 | 0 | 0.394 | 1.54 |
| 2026-04-29 00:00 | 2026-07-27 20:00 | 778 | 194 | 0 | 0.372 | 1.69 |
| 2026-07-28 00:00 | 2026-10-25 20:00 | 712 | 174 | 0 | 0.366 | 1.73 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
