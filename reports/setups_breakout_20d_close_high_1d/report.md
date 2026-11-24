# Report ricerca meta-labeling — breakout_20d_close_high

**Verdetto: NO EDGE — do not deploy** (rivalutato con i criteri di edge incrementale: rf ha AUC 0.446 e non batte il filtro casuale; il rendimento positivo e' beta del mercato azionario, always_long fa +1.22%/trade con le stesse uscite)

- Simboli: SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM | intervallo 1d | dati 2010-01-04 00:00:00+00:00 -> 2026-11-23 00:00:00+00:00
- Eventi: 7489 | fold OOS: 11 | configurazioni (n_trials DSR): 3 | PBO (CSCV): 0.0541
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rf | 1038 | 51.1 | 0.01347 | 1.64 | 0.78 | -0.026 | 100.0 | 0.7130 | -0.00014 | 0.446 | -0.079 | 0.2598 | 0.999 | SI |
| base_rate | 1038 | 51.1 | 0.01347 | 1.64 | 0.78 | -0.025 | 100.0 | 0.7132 | 0.00000 | 0.446 | -0.078 | 0.2598 | 0.999 | no |
| logit | 1031 | 50.3 | 0.01308 | 1.61 | 0.75 | -0.026 | 97.0 | 0.7165 | 0.00338 | 0.445 | -0.075 | 0.2611 | 0.998 | no |
| primary_only | 959 | 51.0 | 0.01343 | 1.64 | 0.93 | -0.116 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 1038 | 51.1 | 0.01347 | 1.64 | 0.76 | -0.032 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 1033 | 51.1 | 0.01335 | 1.63 | 0.76 | -0.031 | 97.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 1038 | 51.1 | 0.01347 | 1.64 | 0.78 | -0.030 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | True | True | True | True |
| logit | False | True | True | True | True |
| rf | True | True | True | True | True |

## Calibrazione OOS — rf

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 0 | n/a | n/a |
| 0.2-0.3 | 0 | n/a | n/a |
| 0.3-0.4 | 516 | 0.389 | 0.599 |
| 0.4-0.5 | 4656 | 0.436 | 0.505 |
| 0.5-0.6 | 0 | n/a | n/a |
| 0.6-0.7 | 0 | n/a | n/a |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (rf): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| trend_ | 10 | 0.00038 |
| struct_ | 16 | 0.00006 |
| cal_ | 2 | 0.00005 |
| reg_ | 4 | 0.00002 |
| xs_ | 6 | -0.00013 |
| rev_ | 8 | -0.00019 |
| volu_ | 2 | -0.00021 |
| meta_ | 1 | -0.00021 |
| vol_ | 7 | -0.00042 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| cal_ | 0.00006 |
| xs_ | 0.00005 |
| meta_ | 0.00000 |
| volu_ | 0.00000 |
| trend_ | -0.00002 |
| vol_ | -0.00010 |
| rev_ | -0.00024 |
| reg_ | -0.00270 |
| struct_ | -0.00295 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2015-01-30 00:00 | 2016-01-28 00:00 | 2027 | 353 | 0 | 0.388 | 1.57 |
| 2016-01-29 00:00 | 2017-01-26 00:00 | 2004 | 516 | 0 | 0.376 | 1.66 |
| 2017-01-27 00:00 | 2018-01-25 00:00 | 2186 | 603 | 0 | 0.378 | 1.65 |
| 2018-01-26 00:00 | 2019-01-25 00:00 | 2338 | 331 | 0 | 0.369 | 1.71 |
| 2019-01-28 00:00 | 2020-01-24 00:00 | 2223 | 614 | 0 | 0.392 | 1.55 |
| 2020-01-27 00:00 | 2021-01-22 00:00 | 2345 | 531 | 0 | 0.402 | 1.49 |
| 2021-01-25 00:00 | 2022-01-20 00:00 | 2556 | 497 | 0 | 0.399 | 1.51 |
| 2022-01-21 00:00 | 2023-01-20 00:00 | 2634 | 224 | 0 | 0.393 | 1.55 |
| 2023-01-23 00:00 | 2024-01-22 00:00 | 2264 | 540 | 0 | 0.402 | 1.49 |
| 2024-01-23 00:00 | 2025-01-22 00:00 | 2391 | 495 | 0 | 0.389 | 1.57 |
| 2025-01-23 00:00 | 2026-01-22 00:00 | 2355 | 468 | 0 | 0.371 | 1.69 |
