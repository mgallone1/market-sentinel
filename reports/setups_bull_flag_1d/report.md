# Report ricerca meta-labeling — bull_flag

**Verdetto: NO EDGE — do not deploy**

- Simboli: SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM | intervallo 1d | dati 2010-01-04 00:00:00+00:00 -> 2026-11-23 00:00:00+00:00
- Eventi: 1486 | fold OOS: 11 | configurazioni (n_trials DSR): 3 | PBO (CSCV): 0.0000
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rf | 298 | 50.0 | 0.01265 | 1.43 | 0.08 | -0.105 | 100.0 | 0.7095 | -0.00020 | 0.446 | -0.107 | 0.2581 | 0.612 | no |
| base_rate | 298 | 50.0 | 0.01265 | 1.43 | 0.08 | -0.105 | 100.0 | 0.7097 | 0.00000 | 0.454 | -0.085 | 0.2582 | 0.614 | no |
| logit | 298 | 50.0 | 0.01265 | 1.43 | 0.07 | -0.106 | 100.0 | 0.7112 | 0.00151 | 0.439 | -0.119 | 0.2589 | 0.595 | no |
| primary_only | 295 | 50.2 | 0.01304 | 1.45 | 0.48 | -0.195 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 298 | 50.0 | 0.01265 | 1.43 | 0.12 | -0.108 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 298 | 50.0 | 0.01265 | 1.43 | 0.12 | -0.112 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 298 | 50.0 | 0.01265 | 1.43 | 0.17 | -0.110 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | True | True | True |
| logit | False | False | True | True | True |
| rf | True | False | True | True | True |

## Calibrazione OOS — rf

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 0 | n/a | n/a |
| 0.2-0.3 | 0 | n/a | n/a |
| 0.3-0.4 | 0 | n/a | n/a |
| 0.4-0.5 | 684 | 0.473 | 0.598 |
| 0.5-0.6 | 331 | 0.537 | 0.447 |
| 0.6-0.7 | 0 | n/a | n/a |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (rf): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| rev_ | 8 | 0.00077 |
| trend_ | 10 | 0.00064 |
| xs_ | 6 | 0.00059 |
| meta_ | 1 | 0.00052 |
| volu_ | 2 | 0.00052 |
| vol_ | 7 | 0.00046 |
| reg_ | 4 | 0.00014 |
| cal_ | 2 | 0.00006 |
| struct_ | 16 | -0.00124 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| struct_ | 0.00167 |
| cal_ | 0.00164 |
| meta_ | 0.00000 |
| volu_ | 0.00000 |
| trend_ | -0.00061 |
| rev_ | -0.00068 |
| xs_ | -0.00079 |
| vol_ | -0.00388 |
| reg_ | -0.01047 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2015-01-30 00:00 | 2016-01-28 00:00 | 370 | 104 | 0 | 0.383 | 1.61 |
| 2016-01-29 00:00 | 2017-01-26 00:00 | 405 | 89 | 0 | 0.401 | 1.50 |
| 2017-01-27 00:00 | 2018-01-25 00:00 | 420 | 60 | 0 | 0.403 | 1.48 |
| 2018-01-26 00:00 | 2019-01-25 00:00 | 400 | 61 | 0 | 0.397 | 1.52 |
| 2019-01-28 00:00 | 2020-01-24 00:00 | 372 | 78 | 0 | 0.418 | 1.39 |
| 2020-01-27 00:00 | 2021-01-22 00:00 | 385 | 131 | 0 | 0.424 | 1.36 |
| 2021-01-25 00:00 | 2022-01-20 00:00 | 408 | 81 | 0 | 0.381 | 1.63 |
| 2022-01-21 00:00 | 2023-01-20 00:00 | 418 | 78 | 0 | 0.394 | 1.54 |
| 2023-01-23 00:00 | 2024-01-22 00:00 | 429 | 99 | 0 | 0.402 | 1.48 |
| 2024-01-23 00:00 | 2025-01-22 00:00 | 480 | 111 | 0 | 0.384 | 1.60 |
| 2025-01-23 00:00 | 2026-01-22 00:00 | 503 | 123 | 0 | 0.387 | 1.58 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
