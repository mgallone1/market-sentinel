# Report ricerca meta-labeling — legacy [phys]

**Verdetto: NO EDGE — do not deploy**

- Simboli: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, LINKUSDT, AVAXUSDT, ADAUSDT, DOGEUSDT, SUIUSDT, NEARUSDT | intervallo 1h | dati 2023-11-01 00:00:00+00:00 -> 2026-11-01 00:00:00+00:00
- Eventi: 7256 | fold OOS: 8 | configurazioni (n_trials DSR): 3 | PBO (CSCV): 0.0143
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200; AUC > 0.52; expectancy > primary_only e > filtro casuale. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6843 | 0.00000 | 0.517 | -0.013 | 0.2455 | n/a | no |
| logit | 82 | 48.8 | -0.00050 | 0.93 | 0.30 | -0.003 | 2.0 | 0.6875 | 0.00317 | 0.510 | -0.008 | 0.2470 | 0.268 | no |
| hgb | 37 | 29.7 | -0.00517 | 0.46 | -1.37 | -0.006 | 0.8 | 0.6876 | 0.00333 | 0.508 | -0.015 | 0.2469 | 0.000 | no |
| primary_only | 3296 | 43.0 | -0.00167 | 0.78 | -2.28 | -0.457 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 95 | 44.2 | -0.00285 | 0.69 | -1.26 | -0.004 | 2.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 38 | 47.4 | 0.00155 | 1.22 | 0.74 | -0.001 | 0.8 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | True | False | False |
| logit | False | False | True | False | False |
| hgb | False | False | True | False | False |

## Calibrazione OOS — logit

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 1 | 0.010 | 0.000 |
| 0.1-0.2 | 7 | 0.190 | 0.286 |
| 0.2-0.3 | 0 | n/a | n/a |
| 0.3-0.4 | 3257 | 0.362 | 0.417 |
| 0.4-0.5 | 1675 | 0.433 | 0.439 |
| 0.5-0.6 | 93 | 0.530 | 0.473 |
| 0.6-0.7 | 3 | 0.656 | 0.333 |
| 0.7-0.8 | 3 | 0.727 | 0.667 |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (logit): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| volu_ | 8 | 0.00482 |
| trend_ | 14 | 0.00299 |
| cal_ | 5 | 0.00275 |
| rev_ | 8 | 0.00183 |
| vol_ | 7 | 0.00145 |
| struct_ | 16 | 0.00135 |
| deriv_ | 3 | 0.00129 |
| xs_ | 6 | 0.00090 |
| meta_ | 1 | 0.00090 |
| phys_ | 13 | -0.00078 |
| reg_ | 4 | -0.00081 |

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
