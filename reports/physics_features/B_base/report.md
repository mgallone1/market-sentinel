# Report ricerca meta-labeling — legacy [base]

**Verdetto: NO EDGE — do not deploy**

- Simboli: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, LINKUSDT, AVAXUSDT, ADAUSDT, DOGEUSDT, SUIUSDT, NEARUSDT | intervallo 1h | dati 2023-11-01 00:00:00+00:00 -> 2026-11-01 00:00:00+00:00
- Eventi: 7256 | fold OOS: 8 | configurazioni (n_trials DSR): 3 | PBO (CSCV): 0.1378
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200; AUC > 0.52; expectancy > primary_only e > filtro casuale. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6843 | 0.00000 | 0.517 | -0.013 | 0.2455 | n/a | no |
| hgb | 86 | 36.0 | -0.00415 | 0.53 | -1.30 | -0.006 | 1.8 | 0.6871 | 0.00283 | 0.507 | 0.001 | 0.2467 | 0.014 | no |
| logit | 72 | 50.0 | -0.00190 | 0.76 | -0.62 | -0.005 | 1.7 | 0.6900 | 0.00572 | 0.505 | -0.011 | 0.2476 | 0.125 | no |
| primary_only | 3296 | 43.0 | -0.00167 | 0.78 | -2.28 | -0.457 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 81 | 49.4 | -0.00212 | 0.72 | -0.65 | -0.003 | 1.7 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 88 | 44.3 | -0.00063 | 0.92 | 0.04 | -0.003 | 1.8 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | True | False | False |
| logit | False | False | True | False | False |
| hgb | False | False | True | False | False |

## Calibrazione OOS — hgb

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 4 | 0.029 | 0.250 |
| 0.1-0.2 | 2 | 0.191 | 0.000 |
| 0.2-0.3 | 12 | 0.222 | 0.417 |
| 0.3-0.4 | 3674 | 0.375 | 0.425 |
| 0.4-0.5 | 1289 | 0.422 | 0.427 |
| 0.5-0.6 | 56 | 0.517 | 0.393 |
| 0.6-0.7 | 2 | 0.641 | 0.500 |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

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
