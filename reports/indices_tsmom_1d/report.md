# Report ricerca meta-labeling — tsmom

**Verdetto: NO EDGE — do not deploy**

- Simboli: ^GSPC, ^NDX, ^STOXX50E | intervallo 1d | dati 2005-01-03 00:00:00+00:00 -> 2026-11-23 00:00:00+00:00
- Eventi: 10094 | fold OOS: 14 | configurazioni (n_trials DSR): 6 | PBO (CSCV): 0.1630
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rf | 328 | 47.0 | 0.00710 | 1.56 | 0.37 | -0.017 | 33.3 | 0.6636 | -0.01224 | 0.584 | 0.141 | 0.2355 | 0.739 | no |
| logit | 324 | 42.6 | 0.00325 | 1.24 | 0.28 | -0.010 | 29.1 | 0.6667 | -0.00908 | 0.562 | 0.049 | 0.2370 | 0.599 | no |
| ensemble | 266 | 40.2 | 0.00326 | 1.25 | 0.26 | -0.006 | 21.4 | 0.6697 | -0.00611 | 0.551 | 0.036 | 0.2384 | 0.564 | no |
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.6758 | 0.00000 | 0.491 | -0.039 | 0.2411 | n/a | no |
| hgb | 221 | 36.7 | 0.00024 | 1.02 | -0.02 | -0.006 | 16.0 | 0.6766 | 0.00081 | 0.507 | -0.015 | 0.2407 | 0.132 | no |
| gbm_montecarlo | 940 | 36.6 | -0.00020 | 0.99 | -0.06 | -0.119 | 87.7 | 0.7895 | 0.11371 | 0.512 | 0.065 | 0.2900 | 0.097 | no |
| primary_only | 1084 | 35.8 | -0.00039 | 0.97 | -0.08 | -0.184 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@gbm_montecarlo | 1052 | 36.1 | -0.00024 | 0.98 | -0.14 | -0.120 | 87.7 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 453 | 38.6 | 0.00225 | 1.16 | 0.19 | -0.009 | 29.1 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 259 | 36.7 | 0.00012 | 1.01 | 0.32 | -0.013 | 16.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 479 | 41.1 | 0.00332 | 1.23 | 0.18 | -0.017 | 33.3 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@ensemble | 361 | 42.1 | 0.00380 | 1.29 | 0.38 | -0.003 | 21.4 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | True | False | False |
| gbm_montecarlo | False | False | True | False | True |
| logit | True | False | True | True | True |
| hgb | False | False | True | True | True |
| rf | True | False | True | True | True |
| ensemble | True | False | True | True | True |

## Calibrazione OOS — rf

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 3 | 0.026 | 0.000 |
| 0.1-0.2 | 2 | 0.106 | 0.000 |
| 0.2-0.3 | 1027 | 0.256 | 0.275 |
| 0.3-0.4 | 4745 | 0.356 | 0.396 |
| 0.4-0.5 | 906 | 0.429 | 0.485 |
| 0.5-0.6 | 93 | 0.575 | 0.419 |
| 0.6-0.7 | 0 | n/a | n/a |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (rf): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| volu_ | 2 | 0.02716 |
| trend_ | 10 | 0.02028 |
| rev_ | 8 | 0.01692 |
| meta_ | 1 | 0.01258 |
| struct_ | 16 | 0.00839 |
| cal_ | 2 | 0.00322 |
| vol_ | 7 | 0.00282 |
| reg_ | 4 | 0.00128 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| struct_ | 0.00183 |
| rev_ | 0.00055 |
| meta_ | 0.00032 |
| reg_ | 0.00016 |
| cal_ | 0.00005 |
| volu_ | -0.00000 |
| vol_ | -0.00024 |
| trend_ | -0.00046 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2012-01-11 00:00 | 2013-01-09 00:00 | 2861 | 502 | 0 | 0.382 | 1.62 |
| 2013-01-10 00:00 | 2014-01-08 00:00 | 3080 | 469 | 0 | 0.386 | 1.59 |
| 2014-01-09 00:00 | 2015-01-07 00:00 | 3225 | 472 | 0 | 0.384 | 1.61 |
| 2015-01-08 00:00 | 2016-01-06 00:00 | 3277 | 453 | 0 | 0.386 | 1.59 |
| 2016-01-07 00:00 | 2017-01-03 00:00 | 3308 | 491 | 0 | 0.369 | 1.71 |
| 2017-01-04 00:00 | 2017-12-29 00:00 | 3314 | 477 | 0 | 0.375 | 1.67 |
| 2018-01-02 00:00 | 2018-12-27 00:00 | 3289 | 505 | 0 | 0.371 | 1.70 |
| 2018-12-28 00:00 | 2019-12-24 00:00 | 3327 | 505 | 0 | 0.371 | 1.70 |
| 2019-12-26 00:00 | 2020-12-21 00:00 | 3333 | 473 | 0 | 0.366 | 1.73 |
| 2020-12-22 00:00 | 2021-12-17 00:00 | 3343 | 468 | 0 | 0.366 | 1.73 |
| 2021-12-20 00:00 | 2022-12-14 00:00 | 3331 | 493 | 0 | 0.365 | 1.74 |
| 2022-12-15 00:00 | 2023-12-13 00:00 | 3382 | 505 | 2 | 0.375 | 1.67 |
| 2023-12-14 00:00 | 2024-12-10 00:00 | 3373 | 491 | 0 | 0.371 | 1.69 |
| 2024-12-11 00:00 | 2025-12-08 00:00 | 3396 | 472 | 0 | 0.374 | 1.68 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
