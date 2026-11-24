# Spread / pairs trading — report (pre-registrato, nessun tuning)

Dati: yfinance adjusted close giornalieri. Esecuzione al close t+1 dopo il segnale; uscita su z con side*z >= -exit.
Costi: S1/S1-grid 0.03 $/barile/gamba/lato + 5%/anno finanziamento su entrambe le gambe; S2/S3 5 bps/gamba/lato + 1%/anno borrow sulla gamba corta.
Capitale: S1 10000 $ per unita' di spread; S1-grid 160000 $ (16 unita' massime); S2/S3 capitale impegnato = 1 (gross 1x per slot).
Nota: il Sharpe vs T-bill per S1/S1-grid e' non significativo (rendimento % su 10.000 $/unita' di spread dollar-neutral molto piccolo rispetto al tasso risk-free). Ticker senza dati yfinance (es. BK) esclusi.
Rischi dichiarati: BZ=F/CL=F sono futures continui (salti di roll nello spread); S2 usa la lista S&P 100 corrente (survivorship bias, dichiarato); DSR con n_trials=100 e var_sr = varianza degli Sharpe giornalieri tra 11 serie candidate; bootstrap a blocchi (20) dello Sharpe contro zero.

| Famiglia | Sharpe netto | Sharpe lordo | Sharpe vs T-bill | Sharpe post-2018 | CAGR | MaxDD | n trade | win | giorni medi | anni>0 | DSR(100) | CI95 Sharpe | corr SPY | % P&L peggior 5% | KEEP |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | 0.16 | 0.49 | -9.82 | 0.73 | 0.01% | -0.5% | 116 | 62% | 11.1 | 53% | 0.01 | [-0.23, 0.50] | -0.01 | -137% | DISCARD |
| S1_grid | -0.34 | 0.77 | -11.74 | 0.13 | -0.02% | -0.5% | 1969 | 71% | 23.5 | 26% | 0.00 | [-0.77, 0.09] | 0.01 | 254% | DISCARD |
| S2 | -0.45 | -0.21 | -1.07 | -0.34 | -1.11% | -21.4% | 840 | 52% | 66.5 | 24% | 0.00 | [-0.87, -0.07] | 0.02 | 168% | DISCARD |
| S3 | -0.00 | 0.32 | -0.61 | -0.14 | -0.03% | -8.4% | 666 | 62% | 17.6 | 56% | 0.00 | [-0.44, 0.47] | 0.21 | -2785% | DISCARD |

## Rendimenti per anno
- S1: 2008: 0.1%, 2009: 0.0%, 2010: -0.1%, 2011: -0.2%, 2012: 0.0%, 2013: -0.1%, 2014: 0.1%, 2015: -0.0%, 2016: 0.0%, 2017: -0.0%, 2018: -0.0%, 2019: 0.1%, 2020: 0.0%, 2021: -0.0%, 2022: 0.2%, 2023: -0.0%, 2024: 0.0%, 2025: -0.0%, 2026: 0.2%
- S1_grid: 2008: -0.1%, 2009: 0.0%, 2010: -0.0%, 2011: -0.1%, 2012: -0.1%, 2013: -0.0%, 2014: -0.0%, 2015: -0.0%, 2016: 0.1%, 2017: -0.0%, 2018: -0.0%, 2019: -0.0%, 2020: 0.0%, 2021: -0.0%, 2022: 0.0%, 2023: -0.1%, 2024: -0.0%, 2025: -0.0%, 2026: 0.2%
- S2: 2010: -1.3%, 2011: -1.5%, 2012: 0.5%, 2013: -1.6%, 2014: -1.6%, 2015: -0.8%, 2016: -0.4%, 2017: -1.9%, 2018: -2.1%, 2019: -1.7%, 2020: -2.8%, 2021: -3.0%, 2022: -1.5%, 2023: 3.2%, 2024: -4.2%, 2025: 0.7%, 2026: 1.5%
- S3: 2009: 0.5%, 2010: -0.4%, 2011: 0.1%, 2012: -0.1%, 2013: -1.6%, 2014: 1.1%, 2015: 2.3%, 2016: 1.4%, 2017: -2.4%, 2018: 2.0%, 2019: 1.0%, 2020: -1.1%, 2021: -0.3%, 2022: 0.4%, 2023: 1.4%, 2024: -3.0%, 2025: 1.5%, 2026: -3.3%

Regola KEEP: Sharpe netto > 0.5; anni positivi >= 70%; Sharpe post-2018 > 0.3; DSR > 0.95; CI95 inf > 0. Altrimenti DISCARD.
