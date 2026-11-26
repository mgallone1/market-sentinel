# Report ricerca meta-labeling — donchian_breakout [base]

**Verdetto: NO EDGE — do not deploy**

- Simboli: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, LINKUSDT, AVAXUSDT, ADAUSDT, DOGEUSDT, SUIUSDT, NEARUSDT | intervallo 1h | dati 2023-11-01 00:00:00+00:00 -> 2026-11-01 00:00:00+00:00
- Eventi: 9110 | fold OOS: 8 | configurazioni (n_trials DSR): 3 | PBO (CSCV): 0.8312
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200; AUC > 0.52; expectancy > primary_only e > filtro casuale. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6746 | 0.00000 | 0.484 | -0.037 | 0.2400 | n/a | no |
| hgb | 79 | 40.5 | 0.00115 | 1.09 | -0.21 | -0.014 | 1.4 | 0.6769 | 0.00225 | 0.498 | 0.014 | 0.2403 | 0.268 | no |
| logit | 119 | 37.8 | 0.00032 | 1.02 | 0.29 | -0.007 | 2.2 | 0.6834 | 0.00880 | 0.501 | 0.019 | 0.2409 | 0.544 | no |
| primary_only | 3200 | 36.8 | -0.00023 | 0.98 | -0.04 | -0.336 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 122 | 36.9 | 0.00137 | 1.10 | 0.61 | -0.004 | 2.2 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 84 | 39.3 | 0.00286 | 1.23 | 0.14 | -0.008 | 1.4 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | False | False | False |
| logit | False | False | False | True | False |
| hgb | False | False | False | True | False |

## Calibrazione OOS — hgb

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 3 | 0.073 | 0.667 |
| 0.1-0.2 | 5 | 0.192 | 0.800 |
| 0.2-0.3 | 2553 | 0.274 | 0.377 |
| 0.3-0.4 | 3525 | 0.318 | 0.369 |
| 0.4-0.5 | 22 | 0.441 | 0.409 |
| 0.5-0.6 | 16 | 0.504 | 0.250 |
| 0.6-0.7 | 1 | 0.629 | 0.000 |
| 0.7-0.8 | 1 | 0.720 | 1.000 |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 6 | 0.990 | 0.500 |

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
