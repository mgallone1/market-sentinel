# Report ricerca meta-labeling — donchian_breakout

**Verdetto: NO EDGE — do not deploy**

- Simboli: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, LINKUSDT, AVAXUSDT, ADAUSDT, DOGEUSDT, SUIUSDT, NEARUSDT | intervallo 1d | dati 2023-11-01 00:00:00+00:00 -> 2026-11-01 00:00:00+00:00
- Eventi: 316 | fold OOS: 4 | configurazioni (n_trials DSR): 6 | PBO (CSCV): 0.5454
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hgb | 36 | 50.0 | 0.02507 | 1.67 | 0.60 | -0.007 | 45.0 | 0.7138 | -0.00585 | 0.535 | 0.094 | 0.2574 | 0.399 | no |
| ensemble | 27 | 48.1 | 0.02444 | 1.65 | 0.33 | -0.021 | 32.6 | 0.7190 | -0.00063 | 0.553 | 0.153 | 0.2614 | 0.284 | no |
| base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | 0.7197 | 0.00000 | 0.599 | 0.153 | 0.2620 | n/a | no |
| logit | 26 | 46.2 | 0.02087 | 1.53 | 0.36 | -0.038 | 31.0 | 0.7481 | 0.02844 | 0.573 | 0.170 | 0.2746 | 0.295 | no |
| rf | 7 | 0.0 | -0.08880 | 0.00 | -1.19 | -0.027 | 5.4 | 0.8070 | 0.08735 | 0.447 | -0.087 | 0.2919 | 0.000 | no |
| gbm_montecarlo | 73 | 45.2 | 0.01231 | 1.23 | -0.06 | -0.086 | 100.0 | 0.8636 | 0.14395 | 0.471 | -0.107 | 0.3206 | 0.155 | no |
| primary_only | 68 | 45.6 | 0.01374 | 1.27 | 0.25 | -0.104 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 0 | n/a | n/a | n/a | n/a | 0.000 | 0.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@gbm_montecarlo | 73 | 45.2 | 0.01231 | 1.23 | 0.39 | -0.075 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@logit | 28 | 46.4 | 0.01326 | 1.28 | 0.33 | -0.033 | 31.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@hgb | 38 | 52.6 | 0.03855 | 2.00 | 0.80 | -0.011 | 45.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@rf | 6 | 33.3 | 0.00862 | 1.15 | -0.03 | -0.022 | 5.4 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@ensemble | 26 | 57.7 | 0.03500 | 1.90 | 0.96 | -0.019 | 32.6 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | False | False | False | False |
| gbm_montecarlo | False | False | False | True | False |
| logit | False | False | False | True | False |
| hgb | True | False | False | True | False |
| rf | False | False | False | False | False |
| ensemble | True | False | False | True | False |

## Calibrazione OOS — hgb

| bin | n | p media | frazione vincenti |
|---|---|---|---|
| 0.0-0.1 | 1 | 0.070 | 1.000 |
| 0.1-0.2 | 0 | n/a | n/a |
| 0.2-0.3 | 33 | 0.272 | 0.242 |
| 0.3-0.4 | 36 | 0.336 | 0.611 |
| 0.4-0.5 | 52 | 0.454 | 0.500 |
| 0.5-0.6 | 7 | 0.500 | 0.143 |
| 0.6-0.7 | 0 | n/a | n/a |
| 0.7-0.8 | 0 | n/a | n/a |
| 0.8-0.9 | 0 | n/a | n/a |
| 0.9-1.0 | 0 | n/a | n/a |

## Ablazione per famiglia (hgb): Δ log-loss quando la famiglia viene rimossa
(>0 = la famiglia aiuta; <0 = peggiora il modello)

| famiglia | colonne | Δ log-loss |
|---|---|---|
| xs_ | 6 | 0.13972 |
| deriv_ | 3 | 0.13161 |
| volu_ | 8 | 0.11087 |
| trend_ | 10 | 0.03562 |
| reg_ | 4 | 0.03201 |
| rev_ | 8 | 0.01619 |
| meta_ | 1 | 0.01485 |
| struct_ | 16 | 0.01124 |
| vol_ | 7 | 0.00784 |
| cal_ | 3 | -0.00253 |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2025-05-14 00:00 | 2025-09-10 00:00 | 164 | 34 | 0 | 0.434 | 1.30 |
| 2025-09-11 00:00 | 2026-01-08 00:00 | 177 | 23 | 0 | 0.410 | 1.44 |
| 2026-01-09 00:00 | 2026-05-08 00:00 | 175 | 32 | 0 | 0.413 | 1.42 |
| 2026-05-09 00:00 | 2026-09-05 00:00 | 181 | 40 | 0 | 0.401 | 1.49 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
