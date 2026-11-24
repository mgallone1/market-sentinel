# Report ricerca meta-labeling — always_long

**Verdetto: NO EDGE — do not deploy**

- Simboli: SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM | intervallo 1d | dati 2010-01-04 00:00:00+00:00 -> 2026-11-23 00:00:00+00:00
- Eventi: 41629 | fold OOS: 11 | configurazioni (n_trials DSR): 1 | PBO (CSCV): 0.0002
- Criteri di deploy: log-loss OOS < base_rate; DSR > 0.95; PBO < 0.2; expectancy netta > 0; n_trades >= 200. Fallire un criterio = NO EDGE.

## Classifica modelli (OOS, dopo costi)

| config | n_trades | win% | expectancy | PF | Sharpe | maxDD | accept% | logloss | Δ vs base | AUC | IC | Brier | DSR | deploy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base_rate | 2143 | 50.3 | 0.01224 | 1.50 | 0.52 | -0.175 | 100.0 | 0.7017 | 0.00000 | 0.437 | -0.122 | 0.2543 | 0.981 | no |
| primary_only | 1846 | 51.0 | 0.01264 | 1.54 | 0.83 | -0.312 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |
| random@base_rate | 2143 | 50.3 | 0.01224 | 1.50 | 0.59 | -0.188 | 100.0 | n/a | n/a | n/a | n/a | n/a | n/a | (controllo) |

## Criteri per configurazione

| config | logloss<base | DSR>0.95 | PBO<0.2 | expectancy>0 | n>=200 |
|---|---|---|---|---|---|
| base_rate | False | True | True | True | True |

## Fold

| test_start | test_end | n_train | n_test | purged | p* | payoff |
|---|---|---|---|---|---|---|
| 2015-01-30 00:00 | 2016-01-28 00:00 | 11719 | 2510 | 0 | 0.406 | 1.46 |
| 2016-01-29 00:00 | 2017-01-26 00:00 | 12209 | 2510 | 0 | 0.399 | 1.51 |
| 2017-01-27 00:00 | 2018-01-25 00:00 | 12460 | 2510 | 0 | 0.392 | 1.55 |
| 2018-01-26 00:00 | 2019-01-25 00:00 | 12570 | 2510 | 0 | 0.390 | 1.57 |
| 2019-01-28 00:00 | 2020-01-24 00:00 | 12570 | 2510 | 0 | 0.413 | 1.42 |
| 2020-01-27 00:00 | 2021-01-22 00:00 | 12570 | 2510 | 0 | 0.414 | 1.41 |
| 2021-01-25 00:00 | 2022-01-20 00:00 | 12570 | 2510 | 0 | 0.399 | 1.51 |
| 2022-01-21 00:00 | 2023-01-20 00:00 | 12570 | 2510 | 0 | 0.397 | 1.52 |
| 2023-01-23 00:00 | 2024-01-22 00:00 | 12570 | 2510 | 0 | 0.413 | 1.42 |
| 2024-01-23 00:00 | 2025-01-22 00:00 | 12570 | 2510 | 0 | 0.401 | 1.49 |
| 2025-01-23 00:00 | 2026-01-22 00:00 | 12570 | 2510 | 0 | 0.396 | 1.53 |

> **NO EDGE — do not deploy.** Nessuna configurazione soddisfa tutti i criteri; i numeri sopra sono riportati senza arrotondamenti favorevoli.
