# Report ricerca meta-labeling — oversold

**Verdetto: NO EDGE — do not deploy**

- Simboli: SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM | intervallo 1d | dati 2010-01-04 00:00:00+00:00 -> 2026-11-23 00:00:00+00:00
- Eventi: 788 | fold OOS: 11 | configurazioni (n_trials DSR): 3 | PBO (CSCV): 0.4706
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_rate | 198 | 51.0 | 0.01843 | 1.53 | 0.23 | -0.130 | 100.0 | 0.7060 | 0.00000 | 0.523 | 0.014 | 0.2555 | 0.806 | no |
| rf | 198 | 51.0 | 0.01843 | 1.53 | 0.24 | -0.132 | 100.0 | 0.7105 | 0.00446 | 0.515 | 0.026 | 0.2577 | 0.822 | no |
| logit | 194 | 50.5 | 0.01784 | 1.51 | 0.21 | -0.133 | 98.7 | 0.7453 | 0.03928 | 0.528 | 0.050 | 0.2639 | 0.788 | no |
| primary_only | 194 | 50.5 | 0.01676 | 1.48 | 0.33 | -0.142 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 198 | 51.0 | 0.01843 | 1.53 | 0.24 | -0.147 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 194 | 51.0 | 0.01770 | 1.51 | 0.19 | -0.150 | 98.7 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 198 | 51.0 | 0.01843 | 1.53 | 0.20 | -0.156 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | False | True | False |
| logit | False | False | False | True | False |
| rf | False | False | False | True | False |

## Calibrazione OOS — rf

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 0 | n/a | n/a |
| 0.2-0.3 | 0 | n/a | n/a |
| 0.3-0.4 | 0 | n/a | n/a |
| 0.4-0.5 | 96 | 0.472 | 0.542 |
| 0.5-0.6 | 212 | 0.547 | 0.481 |
| 0.6-0.7 | 136 | 0.633 | 0.640 |
| 0.7-0.8 | 78 | 0.728 | 0.487 |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (rf): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| rev_ | 8 | 0.10796 |
| reg_ | 4 | 0.09758 |
| meta_ | 1 | 0.08523 |
| volu_ | 2 | 0.08523 |
| vol_ | 7 | 0.07777 |
| xs_ | 6 | 0.07347 |
| trend_ | 10 | 0.04038 |
| struct_ | 16 | 0.03177 |
| cal_ | 2 | 0.00512 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| xs_ | 0.00372 |
| cal_ | 0.00126 |
| volu_ | 0.00000 |
| meta_ | 0.00000 |
| vol_ | -0.00228 |
| reg_ | -0.00329 |
| struct_ | -0.00562 |
| rev_ | -0.00648 |
| trend_ | -0.01167 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2015-01-30 00:00 | 2016-01-28 00:00 | 205 | 50 | 0 | 0.508 | 0.97 |
| 2016-01-29 00:00 | 2017-01-26 00:00 | 194 | 49 | 0 | 0.487 | 1.05 |
| 2017-01-27 00:00 | 2018-01-25 00:00 | 226 | 2 | 0 | 0.425 | 1.35 |
| 2018-01-26 00:00 | 2019-01-25 00:00 | 154 | 72 | 0 | 0.381 | 1.62 |
| 2019-01-28 00:00 | 2020-01-24 00:00 | 203 | 37 | 0 | 0.387 | 1.58 |
| 2020-01-27 00:00 | 2021-01-22 00:00 | 216 | 34 | 0 | 0.385 | 1.60 |
| 2021-01-25 00:00 | 2022-01-20 00:00 | 220 | 13 | 0 | 0.366 | 1.73 |
| 2022-01-21 00:00 | 2023-01-20 00:00 | 157 | 130 | 0 | 0.358 | 1.79 |
| 2023-01-23 00:00 | 2024-01-22 00:00 | 275 | 22 | 0 | 0.393 | 1.55 |
| 2024-01-23 00:00 | 2025-01-22 00:00 | 239 | 36 | 0 | 0.364 | 1.75 |
| 2025-01-23 00:00 | 2026-01-22 00:00 | 234 | 77 | 0 | 0.368 | 1.71 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
