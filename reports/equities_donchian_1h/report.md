# Report ricerca meta-labeling — donchian_breakout

**Verdetto: NO EDGE — do not deploy**

- Simboli: SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM | intervallo 1h | dati 2024-12-02 14:30:00+00:00 -> 2026-11-23 20:30:00+00:00
- Eventi: 1758 | fold OOS: 6 | configurazioni (n_trials DSR): 6 | PBO (CSCV): 0.4128
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rf | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.7082 | -0.00071 | 0.467 | -0.055 | 0.2572 | n/a | no |
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.7089 | 0.00000 | 0.467 | -0.056 | 0.2575 | n/a | no |
| hgb | 2 | 50.0 | -0.00305 | 0.12 | -0.73 | -0.000 | 0.4 | 0.7092 | 0.00030 | 0.477 | -0.036 | 0.2576 | 0.042 | no |
| ensemble | 1 | 0.0 | -0.00810 | 0.00 | -0.84 | -0.001 | 0.1 | 0.7131 | 0.00426 | 0.467 | -0.054 | 0.2591 | 0.012 | no |
| logit | 1 | 0.0 | -0.00810 | 0.00 | -0.84 | -0.001 | 0.1 | 0.7285 | 0.01959 | 0.456 | -0.072 | 0.2616 | 0.012 | no |
| gbm_montecarlo | 466 | 46.6 | -0.00107 | 0.76 | -0.62 | -0.055 | 96.9 | 0.9831 | 0.27425 | 0.523 | 0.039 | 0.3456 | 0.195 | no |
| primary_only | 497 | 46.5 | -0.00107 | 0.76 | -1.41 | -0.060 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@gbm_montecarlo | 476 | 46.0 | -0.00137 | 0.70 | -1.00 | -0.053 | 96.9 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 1 | 0.0 | -0.00160 | 0.00 | -0.84 | -0.000 | 0.1 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 3 | 100.0 | 0.00547 | n/a | 1.01 | 0.000 | 0.4 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@ensemble | 1 | 0.0 | -0.01192 | 0.00 | -0.84 | -0.001 | 0.1 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | False | False | False |
| gbm_montecarlo | False | False | False | False | True |
| logit | False | False | False | False | False |
| hgb | False | False | False | False | False |
| rf | True | False | False | False | False |
| ensemble | False | False | False | False | False |

## Calibrazione OOS — rf

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 0 | n/a | n/a |
| 0.2-0.3 | 0 | n/a | n/a |
| 0.3-0.4 | 614 | 0.379 | 0.508 |
| 0.4-0.5 | 237 | 0.430 | 0.363 |
| 0.5-0.6 | 0 | n/a | n/a |
| 0.6-0.7 | 0 | n/a | n/a |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (rf): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| xs_ | 6 | 0.00178 |
| reg_ | 4 | 0.00175 |
| trend_ | 14 | 0.00173 |
| volu_ | 2 | 0.00154 |
| cal_ | 4 | 0.00146 |
| vol_ | 7 | 0.00065 |
| rev_ | 8 | 0.00059 |
| meta_ | 1 | 0.00042 |
| struct_ | 16 | 0.00029 |

## Permutation importance per famiglia (ultimo fold, train, OOF)

| famiglia | Δ log-loss |
|---|---|
| struct_ | 0.00159 |
| meta_ | 0.00012 |
| vol_ | 0.00005 |
| volu_ | -0.00017 |
| xs_ | -0.00021 |
| reg_ | -0.00028 |
| trend_ | -0.00066 |
| rev_ | -0.00078 |
| cal_ | -0.00082 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2025-10-09 15:30 | 2025-12-08 19:30 | 732 | 128 | 0 | 0.518 | 0.93 |
| 2025-12-08 20:30 | 2026-02-09 16:30 | 788 | 135 | 0 | 0.533 | 0.88 |
| 2026-02-09 17:30 | 2026-04-09 15:30 | 736 | 122 | 0 | 0.510 | 0.96 |
| 2026-04-09 16:30 | 2026-06-08 15:30 | 717 | 230 | 0 | 0.526 | 0.90 |
| 2026-06-08 16:30 | 2026-08-06 15:30 | 758 | 146 | 0 | 0.548 | 0.82 |
| 2026-08-06 16:30 | 2026-10-05 15:30 | 745 | 90 | 0 | 0.538 | 0.86 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
