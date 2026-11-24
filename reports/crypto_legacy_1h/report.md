# Report ricerca meta-labeling — legacy

**Verdetto: NO EDGE — do not deploy**

- Simboli: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, LINKUSDT, AVAXUSDT, ADAUSDT, DOGEUSDT, SUIUSDT, NEARUSDT | intervallo 1h | dati 2023-11-01 00:00:00+00:00 -> 2026-11-01 00:00:00+00:00
- Eventi: 7256 | fold OOS: 8 | configurazioni (n_trials DSR): 6 | PBO (CSCV): 0.2140
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6843 | 0.00000 | 0.517 | -0.013 | 0.2455 | n/a | no |
| ensemble | 57 | 38.6 | -0.00431 | 0.52 | -1.03 | -0.004 | 1.3 | 0.6867 | 0.00239 | 0.507 | -0.007 | 0.2466 | 0.011 | no |
| hgb | 86 | 36.0 | -0.00415 | 0.53 | -1.30 | -0.006 | 1.8 | 0.6871 | 0.00283 | 0.507 | 0.001 | 0.2467 | 0.003 | no |
| logit | 72 | 50.0 | -0.00190 | 0.76 | -0.62 | -0.005 | 1.7 | 0.6900 | 0.00572 | 0.505 | -0.011 | 0.2476 | 0.053 | no |
| rf | 109 | 45.0 | -0.00274 | 0.69 | -0.61 | -0.006 | 2.7 | 0.6904 | 0.00615 | 0.498 | -0.020 | 0.2483 | 0.043 | no |
| gbm_montecarlo | 3073 | 42.8 | -0.00182 | 0.76 | -1.98 | -0.280 | 90.8 | 0.9947 | 0.31037 | 0.510 | -0.036 | 0.3546 | 0.001 | no |
| primary_only | 3296 | 43.0 | -0.00167 | 0.78 | -2.28 | -0.457 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@gbm_montecarlo | 3201 | 43.1 | -0.00163 | 0.79 | -1.65 | -0.280 | 90.8 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 84 | 45.2 | -0.00452 | 0.46 | -1.53 | -0.005 | 1.7 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 90 | 48.9 | 0.00060 | 1.08 | 0.22 | -0.002 | 1.8 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 130 | 45.4 | -0.00097 | 0.88 | -0.20 | -0.004 | 2.7 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@ensemble | 63 | 46.0 | -0.00199 | 0.74 | -0.99 | -0.003 | 1.3 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | False | False | False |
| gbm_montecarlo | False | False | False | False | True |
| logit | False | False | False | False | False |
| hgb | False | False | False | False | False |
| rf | False | False | False | False | False |
| ensemble | False | False | False | False | False |

## Calibrazione OOS — ensemble

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 1 | 0.048 | 0.000 |
| 0.1-0.2 | 7 | 0.186 | 0.429 |
| 0.2-0.3 | 18 | 0.252 | 0.333 |
| 0.3-0.4 | 3323 | 0.369 | 0.419 |
| 0.4-0.5 | 1649 | 0.427 | 0.440 |
| 0.5-0.6 | 39 | 0.527 | 0.333 |
| 0.6-0.7 | 1 | 0.694 | 0.000 |
| 0.7-0.8 | 1 | 0.712 | 1.000 |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (ensemble): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| trend_ | 14 | -0.00016 |
| deriv_ | 3 | -0.00021 |
| volu_ | 8 | -0.00021 |
| rev_ | 8 | -0.00064 |
| xs_ | 6 | -0.00079 |
| cal_ | 5 | -0.00083 |
| reg_ | 4 | -0.00119 |
| vol_ | 7 | -0.00127 |
| meta_ | 1 | -0.00127 |
| struct_ | 16 | -0.00132 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| struct_ | 0.02535 |
| xs_ | 0.01250 |
| cal_ | 0.00616 |
| reg_ | 0.00374 |
| vol_ | 0.00362 |
| rev_ | 0.00085 |
| meta_ | 0.00000 |
| trend_ | -0.00117 |
| deriv_ | -0.00381 |
| volu_ | -0.00548 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2024-11-02 00:00 | 2025-01-30 23:00 | 2184 | 733 | 0 | 0.481 | 1.08 |
| 2025-01-31 00:00 | 2025-04-30 23:00 | 2332 | 567 | 0 | 0.492 | 1.03 |
| 2025-05-01 00:00 | 2025-07-29 23:00 | 2411 | 792 | 0 | 0.494 | 1.02 |
| 2025-07-30 00:00 | 2025-10-27 23:00 | 2689 | 636 | 0 | 0.494 | 1.02 |
| 2025-10-28 00:00 | 2026-01-25 23:00 | 2731 | 536 | 0 | 0.503 | 0.99 |
| 2026-01-26 00:00 | 2026-04-25 23:00 | 2579 | 552 | 0 | 0.500 | 1.00 |
| 2026-04-26 00:00 | 2026-07-24 23:00 | 2553 | 574 | 0 | 0.501 | 1.00 |
| 2026-07-25 00:00 | 2026-10-22 23:00 | 2321 | 649 | 0 | 0.507 | 0.97 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
