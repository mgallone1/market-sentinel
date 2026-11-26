# Report ricerca meta-labeling — donchian_breakout [phys]

**Verdetto: NO EDGE — do not deploy**

- Simboli: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, LINKUSDT, AVAXUSDT, ADAUSDT, DOGEUSDT, SUIUSDT, NEARUSDT | intervallo 1h | dati 2023-11-01 00:00:00+00:00 -> 2026-11-01 00:00:00+00:00
- Eventi: 9110 | fold OOS: 8 | configurazioni (n_trials DSR): 3 | PBO (CSCV): 0.9290
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200; AUC > 0.52; expectancy > primary_only e > filtro casuale. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6746 | 0.00000 | 0.484 | -0.037 | 0.2400 | n/a | no |
| hgb | 104 | 37.5 | -0.00186 | 0.86 | 0.01 | -0.015 | 1.8 | 0.6770 | 0.00230 | 0.507 | 0.022 | 0.2400 | 0.474 | no |
| logit | 88 | 35.2 | -0.00194 | 0.87 | 0.13 | -0.012 | 1.6 | 0.6823 | 0.00764 | 0.491 | 0.009 | 0.2410 | 0.543 | no |
| primary_only | 3200 | 36.8 | -0.00023 | 0.98 | -0.04 | -0.336 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 95 | 33.7 | -0.00344 | 0.79 | 0.20 | -0.009 | 1.6 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 108 | 40.7 | 0.00518 | 1.42 | 0.75 | -0.010 | 1.8 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | False | False | False |
| logit | False | False | False | False | False |
| hgb | False | False | False | False | False |

## Calibrazione OOS — hgb

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 18 | 0.177 | 0.722 |
| 0.2-0.3 | 2588 | 0.276 | 0.360 |
| 0.3-0.4 | 3506 | 0.318 | 0.380 |
| 0.4-0.5 | 1 | 0.429 | 1.000 |
| 0.5-0.6 | 8 | 0.552 | 0.375 |
| 0.6-0.7 | 1 | 0.600 | 1.000 |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 10 | 0.990 | 0.500 |

## Ablazione per famiglia (hgb): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| deriv_ | 3 | 0.00218 |
| struct_ | 16 | 0.00154 |
| meta_ | 1 | 0.00143 |
| volu_ | 8 | -0.00052 |
| trend_ | 14 | -0.00053 |
| phys_ | 13 | -0.00069 |
| reg_ | 4 | -0.00119 |
| rev_ | 8 | -0.00126 |
| cal_ | 5 | -0.00138 |
| vol_ | 7 | -0.00180 |
| xs_ | 6 | -0.00300 |

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
