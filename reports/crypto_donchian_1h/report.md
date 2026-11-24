# Report ricerca meta-labeling — donchian_breakout

**Verdetto: NO EDGE — do not deploy**

- Simboli: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, LINKUSDT, AVAXUSDT, ADAUSDT, DOGEUSDT, SUIUSDT, NEARUSDT | intervallo 1h | dati 2023-11-01 00:00:00+00:00 -> 2026-11-01 00:00:00+00:00
- Eventi: 9110 | fold OOS: 8 | configurazioni (n_trials DSR): 6 | PBO (CSCV): 0.6500
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6746 | 0.00000 | 0.484 | -0.037 | 0.2400 | n/a | no |
| ensemble | 72 | 36.1 | -0.00264 | 0.82 | -0.16 | -0.010 | 1.2 | 0.6766 | 0.00200 | 0.503 | 0.025 | 0.2402 | 0.173 | no |
| hgb | 79 | 40.5 | 0.00115 | 1.09 | -0.21 | -0.014 | 1.4 | 0.6769 | 0.00225 | 0.498 | 0.014 | 0.2403 | 0.152 | no |
| rf | 10 | 50.0 | 0.00986 | 1.78 | 0.78 | -0.002 | 0.3 | 0.6780 | 0.00338 | 0.487 | -0.018 | 0.2405 | 0.718 | no |
| logit | 119 | 37.8 | 0.00032 | 1.02 | 0.29 | -0.007 | 2.2 | 0.6834 | 0.00880 | 0.501 | 0.019 | 0.2409 | 0.386 | no |
| gbm_montecarlo | 3305 | 36.6 | -0.00033 | 0.98 | -0.12 | -0.221 | 100.0 | 1.1656 | 0.49091 | 0.495 | -0.065 | 0.4126 | 0.200 | no |
| primary_only | 3200 | 36.8 | -0.00023 | 0.98 | -0.04 | -0.336 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@gbm_montecarlo | 3359 | 36.9 | -0.00016 | 0.99 | 0.22 | -0.189 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 126 | 31.0 | -0.00323 | 0.80 | 0.07 | -0.006 | 2.2 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 84 | 35.7 | -0.00247 | 0.84 | -0.40 | -0.012 | 1.4 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 20 | 35.0 | 0.00215 | 1.17 | -0.34 | -0.013 | 0.3 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@ensemble | 74 | 31.1 | -0.00551 | 0.67 | -0.38 | -0.006 | 1.2 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | False | False | False |
| gbm_montecarlo | False | False | False | False | True |
| logit | False | False | False | True | False |
| hgb | False | False | False | True | False |
| rf | False | False | False | True | False |
| ensemble | False | False | False | False | False |

## Calibrazione OOS — ensemble

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 3 | 0.055 | 0.667 |
| 0.1-0.2 | 52 | 0.154 | 0.500 |
| 0.2-0.3 | 2652 | 0.280 | 0.365 |
| 0.3-0.4 | 3386 | 0.318 | 0.376 |
| 0.4-0.5 | 29 | 0.426 | 0.379 |
| 0.5-0.6 | 3 | 0.545 | 0.333 |
| 0.6-0.7 | 2 | 0.682 | 0.000 |
| 0.7-0.8 | 3 | 0.720 | 1.000 |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 2 | 0.954 | 0.500 |

## Ablazione per famiglia (ensemble): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| reg_ | 4 | 0.00005 |
| deriv_ | 3 | -0.00012 |
| meta_ | 1 | -0.00030 |
| trend_ | 14 | -0.00031 |
| cal_ | 5 | -0.00038 |
| struct_ | 16 | -0.00041 |
| rev_ | 8 | -0.00061 |
| volu_ | 8 | -0.00116 |
| vol_ | 7 | -0.00151 |
| xs_ | 6 | -0.00152 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| struct_ | 0.03658 |
| xs_ | 0.01606 |
| volu_ | 0.00620 |
| vol_ | 0.00208 |
| reg_ | 0.00173 |
| meta_ | 0.00000 |
| deriv_ | -0.00008 |
| trend_ | -0.00217 |
| cal_ | -0.00588 |
| rev_ | -0.00834 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2024-11-02 00:00 | 2025-01-30 23:00 | 2911 | 921 | 0 | 0.380 | 1.63 |
| 2025-01-31 00:00 | 2025-04-30 23:00 | 3205 | 809 | 0 | 0.373 | 1.68 |
| 2025-05-01 00:00 | 2025-07-29 23:00 | 3282 | 817 | 0 | 0.370 | 1.71 |
| 2025-07-30 00:00 | 2025-10-27 23:00 | 3409 | 872 | 0 | 0.373 | 1.68 |
| 2025-10-28 00:00 | 2026-01-25 23:00 | 3416 | 730 | 0 | 0.379 | 1.64 |
| 2026-01-26 00:00 | 2026-04-25 23:00 | 3267 | 626 | 0 | 0.386 | 1.59 |
| 2026-04-26 00:00 | 2026-07-24 23:00 | 3074 | 718 | 0 | 0.372 | 1.69 |
| 2026-07-25 00:00 | 2026-10-22 23:00 | 2973 | 639 | 0 | 0.366 | 1.73 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
