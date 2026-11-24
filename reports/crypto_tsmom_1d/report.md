# Report ricerca meta-labeling — tsmom

**Verdetto: NO EDGE — do not deploy**

- Simboli: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, LINKUSDT, AVAXUSDT, ADAUSDT, DOGEUSDT, SUIUSDT, NEARUSDT | intervallo 1d | dati 2023-11-01 00:00:00+00:00 -> 2026-11-01 00:00:00+00:00
- Eventi: 6879 | fold OOS: 4 | configurazioni (n_trials DSR): 6 | PBO (CSCV): 0.4723
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rf | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6671 | -0.00002 | 0.504 | -0.026 | 0.2371 | n/a | no |
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6671 | 0.00000 | 0.504 | -0.026 | 0.2371 | n/a | no |
| hgb | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6672 | 0.00015 | 0.504 | -0.027 | 0.2371 | n/a | no |
| ensemble | 31 | 41.9 | -0.01281 | 0.74 | -0.27 | -0.015 | 2.2 | 0.6673 | 0.00027 | 0.501 | -0.033 | 0.2372 | 0.222 | no |
| logit | 32 | 40.6 | -0.01615 | 0.69 | -0.27 | -0.016 | 2.2 | 0.6676 | 0.00051 | 0.502 | -0.032 | 0.2373 | 0.220 | no |
| gbm_montecarlo | 333 | 44.4 | 0.01228 | 1.28 | 0.38 | -0.170 | 80.2 | 0.7767 | 0.10960 | 0.490 | -0.034 | 0.2869 | 0.491 | no |
| primary_only | 333 | 42.0 | 0.00555 | 1.13 | 0.54 | -0.265 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@gbm_montecarlo | 391 | 44.0 | 0.01079 | 1.24 | 0.78 | -0.133 | 80.2 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 50 | 34.0 | -0.00741 | 0.87 | -0.35 | -0.020 | 2.2 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@ensemble | 55 | 32.7 | -0.01708 | 0.70 | -0.77 | -0.015 | 2.2 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | False | False | False |
| gbm_montecarlo | False | False | False | True | True |
| logit | False | False | False | False | False |
| hgb | False | False | False | False | False |
| rf | True | False | False | False | False |
| ensemble | False | False | False | False | False |

## Calibrazione OOS — rf

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 0 | n/a | n/a |
| 0.2-0.3 | 0 | n/a | n/a |
| 0.3-0.4 | 2951 | 0.371 | 0.386 |
| 0.4-0.5 | 0 | n/a | n/a |
| 0.5-0.6 | 0 | n/a | n/a |
| 0.6-0.7 | 0 | n/a | n/a |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (rf): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| xs_ | 6 | 0.01913 |
| meta_ | 1 | 0.01513 |
| vol_ | 7 | 0.01056 |
| trend_ | 10 | 0.00843 |
| rev_ | 8 | 0.00495 |
| deriv_ | 3 | 0.00342 |
| cal_ | 3 | 0.00247 |
| volu_ | 8 | 0.00227 |
| reg_ | 4 | 0.00218 |
| struct_ | 16 | 0.00012 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| cal_ | 0.00013 |
| vol_ | -0.00011 |
| deriv_ | -0.00014 |
| xs_ | -0.00058 |
| trend_ | -0.00253 |
| volu_ | -0.00309 |
| reg_ | -0.00360 |
| rev_ | -0.00552 |
| meta_ | -0.00554 |
| struct_ | -0.01121 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2025-05-14 00:00 | 2025-09-10 00:00 | 3391 | 711 | 0 | 0.397 | 1.52 |
| 2025-09-11 00:00 | 2026-01-08 00:00 | 3538 | 770 | 0 | 0.395 | 1.53 |
| 2026-01-09 00:00 | 2026-05-08 00:00 | 3466 | 658 | 0 | 0.387 | 1.58 |
| 2026-05-09 00:00 | 2026-09-05 00:00 | 3326 | 812 | 0 | 0.393 | 1.55 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
