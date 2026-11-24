# Fattori cross-sectional cripto (Binance USD-M perp, 1d)

Periodo ribilanci: 2021-03-08 .. 2026-10-19 (settimanale, lunedi' 00:00 UTC). Simboli caricati: 40/40; non disponibili (404/vuoti): nessuno. Universo eleggibile per ribilancio: min 23, media 37.1, max 40.
Costi 7.5 bps per lato sul turnover; funding incluso. Prove pre-registrate: 3; DSR con n_trials=100, var Sharpe tra prove = 0.01138 (per-periodo, tra i 3 fattori).

| Fattore | CAGR | Vol | Sharpe | Sortino | MaxDD | %sett+ | Sharpe 2023+ | Corr BTC | DSR(100) | CI95 Sharpe | Verdetto |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 | 20.0% | 32.3% | 0.72 | 1.44 | -37.4% | 51.7% | 0.51 | -0.06 | 0.001 | [0.00, 1.39] | DISCARD |
| F2 | 51.2% | 26.2% | 1.71 | 2.93 | -26.5% | 60.5% | 1.70 | 0.03 | 0.263 | [0.88, 2.49] | DISCARD |
| F3 | 1.6% | 25.8% | 0.19 | 0.22 | -56.2% | 53.7% | 1.05 | 0.13 | 0.000 | [-0.59, 1.03] | DISCARD |
| COMBO | 25.1% | 15.3% | 1.55 | 2.38 | -13.4% | 58.5% | 1.91 | 0.06 | 0.159 | [0.76, 2.30] | DISCARD |

## Rendimento netto per anno (2026 parziale)

| Fattore | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | anni+ |
|---|---|---|---|---|---|---|---|
| F1 | 123.7% | -14.6% | 13.8% | 46.6% | -0.3% | -11.8% | 3 |
| F2 | 188.3% | 14.8% | 13.6% | 20.9% | 66.5% | 36.6% | 6 |
| F3 | -52.4% | 14.1% | -9.1% | 33.3% | 58.3% | 4.7% | 4 |
| COMBO | 46.8% | 5.1% | 6.0% | 37.6% | 42.8% | 10.5% | 6 |

## Turnover, costi e funding (annualizzati, frazione NAV)

| Fattore | Turnover | Gross | Funding | Costi |
|---|---|---|---|---|
| F1 | 43.7 | 25.6% | 0.9% | 3.3% |
| F2 | 47.4 | 37.9% | 10.4% | 3.6% |
| F3 | 14.1 | 7.3% | -1.3% | 1.1% |
| COMBO | 35.0 | - | - | - |

## Regola KEEP (tutte vere)

| Fattore | Sharpe>0.5 | >=4/6 anni+ | Sharpe 2023+>0 | DSR>0.95 | CI lo>0 |
|---|---|---|---|---|---|
| F1 | True | False | True | False | True |
| F2 | True | True | True | False | True |
| F3 | False | True | True | False | False |
| COMBO | True | True | True | False | True |

Note: pesi costanti nella settimana (nessun drift), turnover = somma |dw|; funding sommato sulle barre lun..dom; BTCUSDT incluso nell'universo; COMBO = pesi inverso-vol 52 settimane causali (equal-weight finche' < 13 settimane).
