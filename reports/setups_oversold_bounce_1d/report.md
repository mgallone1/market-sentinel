# Report ricerca meta-labeling — oversold_bounce

**Verdetto: NO EDGE — do not deploy**

- Simboli: SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM | intervallo 1d | dati 2010-01-04 00:00:00+00:00 -> 2026-11-23 00:00:00+00:00
- Eventi: 455 | fold OOS: 1 | configurazioni (n_trials DSR): 3 | PBO (CSCV): 0.7873
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| logit | 10 | 70.0 | 0.04436 | 3.63 | 1.61 | -0.002 | 100.0 | 0.7736 | -0.00705 | 0.500 | n/a | 0.2900 | 0.984 | no |
| rf | 10 | 70.0 | 0.04436 | 3.63 | 1.61 | -0.002 | 100.0 | 0.7750 | -0.00571 | 0.500 | n/a | 0.2907 | 0.984 | no |
| base_rate | 10 | 70.0 | 0.04436 | 3.63 | 1.60 | -0.002 | 100.0 | 0.7807 | 0.00000 | 0.500 | n/a | 0.2935 | 0.984 | no |
| primary_only | 10 | 70.0 | 0.04436 | 3.63 | 1.48 | -0.015 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 10 | 70.0 | 0.04436 | 3.63 | 1.47 | -0.002 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 10 | 70.0 | 0.04436 | 3.63 | 1.25 | -0.002 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 10 | 70.0 | 0.04436 | 3.63 | 1.40 | -0.003 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | True | False | True | False |
| logit | True | True | False | True | False |
| rf | True | True | False | True | False |

## Calibrazione OOS — logit

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 0 | n/a | n/a |
| 0.2-0.3 | 0 | n/a | n/a |
| 0.3-0.4 | 0 | n/a | n/a |
| 0.4-0.5 | 16 | 0.441 | 0.812 |
| 0.5-0.6 | 0 | n/a | n/a |
| 0.6-0.7 | 0 | n/a | n/a |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (logit): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| struct_ | 16 | -0.01607 |
| vol_ | 7 | -0.01985 |
| xs_ | 6 | -0.02320 |
| rev_ | 8 | -0.02439 |
| meta_ | 1 | -0.02626 |
| volu_ | 2 | -0.02626 |
| trend_ | 10 | -0.02802 |
| cal_ | 2 | -0.03018 |
| reg_ | 4 | -0.03314 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| xs_ | 0.02113 |
| reg_ | 0.00415 |
| volu_ | 0.00000 |
| meta_ | 0.00000 |
| vol_ | -0.00093 |
| struct_ | -0.01017 |
| cal_ | -0.02255 |
| trend_ | -0.03951 |
| rev_ | -0.04175 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2023-01-23 00:00 | 2024-01-22 00:00 | 159 | 16 | 0 | 0.397 | 1.52 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
