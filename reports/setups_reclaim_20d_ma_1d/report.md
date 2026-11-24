# Report ricerca meta-labeling — reclaim_20d_ma

**Verdetto: NO EDGE — do not deploy**

- Simboli: SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM | intervallo 1d | dati 2010-01-04 00:00:00+00:00 -> 2026-11-23 00:00:00+00:00
- Eventi: 2334 | fold OOS: 11 | configurazioni (n_trials DSR): 3 | PBO (CSCV): 0.1128
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_rate | 888 | 54.2 | 0.01343 | 1.58 | 0.49 | -0.180 | 100.0 | 0.7038 | 0.00000 | 0.447 | -0.086 | 0.2553 | 0.968 | no |
| rf | 850 | 54.4 | 0.01397 | 1.60 | 0.54 | -0.184 | 93.5 | 0.7054 | 0.00166 | 0.455 | -0.063 | 0.2560 | 0.979 | no |
| logit | 875 | 54.2 | 0.01339 | 1.58 | 0.49 | -0.195 | 97.3 | 0.7072 | 0.00345 | 0.443 | -0.088 | 0.2570 | 0.967 | no |
| primary_only | 804 | 54.2 | 0.01227 | 1.54 | 0.79 | -0.283 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 888 | 54.2 | 0.01343 | 1.58 | 0.40 | -0.216 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 874 | 53.9 | 0.01323 | 1.57 | 0.47 | -0.204 | 97.3 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 848 | 53.7 | 0.01261 | 1.54 | 0.42 | -0.201 | 93.5 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | True | True | True | True |
| logit | False | True | True | True | True |
| rf | False | True | True | True | True |

## Calibrazione OOS — rf

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 0 | n/a | n/a |
| 0.2-0.3 | 4 | 0.275 | 0.500 |
| 0.3-0.4 | 95 | 0.347 | 0.474 |
| 0.4-0.5 | 572 | 0.476 | 0.584 |
| 0.5-0.6 | 847 | 0.547 | 0.522 |
| 0.6-0.7 | 7 | 0.612 | 0.571 |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (rf): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| vol_ | 7 | 0.00595 |
| xs_ | 6 | 0.00519 |
| trend_ | 10 | 0.00477 |
| meta_ | 1 | 0.00395 |
| volu_ | 2 | 0.00395 |
| rev_ | 8 | 0.00242 |
| reg_ | 4 | 0.00125 |
| cal_ | 2 | 0.00088 |
| struct_ | 16 | 0.00004 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| cal_ | 0.00201 |
| meta_ | 0.00000 |
| volu_ | 0.00000 |
| xs_ | -0.00041 |
| vol_ | -0.00057 |
| struct_ | -0.00123 |
| trend_ | -0.00145 |
| rev_ | -0.00147 |
| reg_ | -0.00361 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2015-01-30 00:00 | 2016-01-28 00:00 | 663 | 164 | 0 | 0.434 | 1.30 |
| 2016-01-29 00:00 | 2017-01-26 00:00 | 740 | 160 | 0 | 0.416 | 1.41 |
| 2017-01-27 00:00 | 2018-01-25 00:00 | 750 | 123 | 0 | 0.400 | 1.50 |
| 2018-01-26 00:00 | 2019-01-25 00:00 | 753 | 146 | 0 | 0.399 | 1.50 |
| 2019-01-28 00:00 | 2020-01-24 00:00 | 752 | 116 | 0 | 0.416 | 1.41 |
| 2020-01-27 00:00 | 2021-01-22 00:00 | 721 | 150 | 0 | 0.408 | 1.45 |
| 2021-01-25 00:00 | 2022-01-20 00:00 | 683 | 141 | 0 | 0.402 | 1.49 |
| 2022-01-21 00:00 | 2023-01-20 00:00 | 681 | 130 | 0 | 0.401 | 1.49 |
| 2023-01-23 00:00 | 2024-01-22 00:00 | 680 | 120 | 0 | 0.420 | 1.38 |
| 2024-01-23 00:00 | 2025-01-22 00:00 | 658 | 145 | 0 | 0.413 | 1.42 |
| 2025-01-23 00:00 | 2026-01-22 00:00 | 670 | 130 | 0 | 0.415 | 1.41 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
