# TSMOM multi-asset: test pre-registrato

Finestra 'full': 2006-01-03 .. 2026-11-23 (prima data con >=10 asset attivi, cioe' con 252 giorni di storia). Post-pubblicazione: 2013-01-01 .. fine. Parametri fissi dalla letteratura (Moskowitz-Ooi-Pedersen 2012, Hurst-Ooi-Pedersen 2017), nessuna calibrazione. Codice: `quant/portfolio/` (`python -m quant.portfolio.run_experiment`).

## Ipotesi e specifiche
- Segnale: media dei segni dei rendimenti 21/63/252 giorni (chiusure fino a t); 0 se storia < 252 giorni.
- Peso: segnale x (0,40/sigma) / N_attivi; sigma = vol EWMA (com=60), annualizzata sqrt(252) per ETF e sqrt(365) per crypto, calcolata su rendimenti dei giorni lavorativi come da specifica (per le crypto sovrastima la vol di circa sqrt(365/252); il vol targeting di portafoglio riporta il livello totale al 10% ma i pesi relativi restano sottopesati sulle crypto).
- Vol targeting: scala i pesi per vol ex-ante di portafoglio 10% con covarianza campionaria a 252g (as of t); leva lorda massima 2,0.
- Ribilanciamento: settimanale (ultimo giorno lavorativo della settimana) o mensile; pesi target costanti tra i ribilanciamenti (senza drift); banda no-trade: salta se |dw| < 0,10 |w_nuovo|.
- Esecuzione: pesi decisi a close t, applicati da close t a close t+1. Calendario: unione dei giorni lavorativi lun-ven; festivi ETF = rendimento 0; i rendimenti crypto del weekend si compongono nel lunedi'.
- Costi: ETF 2 bps one-way su |dw| + borrow 1%/anno sui corti; crypto 10 bps one-way, costo di short 0 (gli short su perp spesso RICEVONO funding: ignorato, nota). Tasso cash/finanziamento: 0.
- Benchmark: risk_parity (solo long, segnale +1, stesso sizing, settimanale); 60/40 SPY/IEF ribilanciato a fine mese con drift (2 bps); SPY buy&hold (senza costi).
- Regola KEEP (tutte): (a) DSR > 0,95 sulla finestra full con n_trials=4 (varianza dello Sharpe giornaliero tra le 4 varianti = 2.17e-04); (b) Sharpe > 0 post-2013; (c) blend 50/50 giornaliero variante/risk_parity con Sharpe maggiore di risk_parity da solo, CI95 bootstrap (blocchi stazionari, media 20gg, 2000 repliche) della differenza > 0.

## Universo effettivamente usato
SPY, QQQ, IWM, EFA, EEM, VGK, EWJ, TLT, IEF, LQD, HYG, TIP, GLD, SLV, USO, DBC, DBA, UUP, FXE, FXY, VNQ, BTC-USD, ETH-USD. Asset scartati per errore di download: nessuno.
Prime date Yahoo successive al 2005: HYG 2007-04-11, SLV 2006-04-28, USO 2006-04-10, DBC 2006-02-06, DBA 2007-01-05, UUP 2007-03-01, FXE 2005-12-12, FXY 2007-02-13, BTC-USD 2014-09-17, ETH-USD 2017-11-09.

## Metriche, finestra full (netto)
| Strategia | CAGR | Vol | Sharpe | Sortino | MaxDD | Calmar | Skew | Peggior mese | % mesi+ | Corr SPY |
|---|---|---|---|---|---|---|---|---|---|---|
| long_short_weekly | 3.0% | 9.8% | 0.35 | 0.46 | -24.4% | 0.12 | -0.11 | -7.4% | 51.8% | -0.27 |
| long_short_monthly | 5.0% | 9.9% | 0.55 | 0.72 | -22.0% | 0.23 | -0.30 | -7.3% | 55.4% | -0.17 |
| long_only_weekly | 6.2% | 9.4% | 0.69 | 0.90 | -17.3% | 0.36 | -0.61 | -9.1% | 57.8% | 0.16 |
| long_only_monthly | 8.8% | 9.9% | 0.90 | 1.21 | -17.1% | 0.52 | -0.39 | -6.9% | 63.3% | 0.27 |
| risk_parity_weekly | 6.4% | 10.3% | 0.65 | 0.81 | -29.9% | 0.21 | -0.78 | -13.1% | 63.3% | 0.75 |
| 60_40_monthly | 7.8% | 10.7% | 0.76 | 0.95 | -32.6% | 0.24 | -0.06 | -10.3% | 66.9% | 0.97 |
| SPY_buy_hold | 10.5% | 19.0% | 0.62 | 0.75 | -55.2% | 0.19 | -0.00 | -16.5% | 66.5% | 1.00 |

## Metriche, post-2013
| Strategia | CAGR | Vol | Sharpe | Sortino | MaxDD | Calmar | Skew | Peggior mese | % mesi+ | Corr SPY |
|---|---|---|---|---|---|---|---|---|---|---|
| long_short_weekly | 2.0% | 9.3% | 0.26 | 0.35 | -24.4% | 0.08 | -0.14 | -7.4% | 53.3% | -0.18 |
| long_short_monthly | 4.6% | 9.4% | 0.53 | 0.70 | -22.0% | 0.21 | -0.31 | -7.3% | 56.9% | -0.02 |
| long_only_weekly | 5.4% | 9.2% | 0.62 | 0.77 | -17.3% | 0.31 | -0.92 | -9.1% | 59.3% | 0.32 |
| long_only_monthly | 8.3% | 9.8% | 0.86 | 1.11 | -17.1% | 0.49 | -0.56 | -6.9% | 65.3% | 0.44 |
| risk_parity_weekly | 5.8% | 10.1% | 0.61 | 0.75 | -26.7% | 0.22 | -1.12 | -12.6% | 61.7% | 0.75 |
| 60_40_monthly | 8.8% | 9.8% | 0.92 | 1.14 | -21.3% | 0.42 | -0.30 | -7.4% | 68.9% | 0.97 |
| SPY_buy_hold | 13.8% | 16.6% | 0.87 | 1.04 | -33.7% | 0.41 | -0.32 | -12.5% | 68.9% | 1.00 |

## Turnover e costi (finestra full)
| Variante | Turnover annuo (somma abs dw) | Costi+borrow annui | Sharpe lordo | Sharpe netto | Leva lorda media |
|---|---|---|---|---|---|
| long_short_weekly | 38.3 | 1.3% | 0.48 | 0.35 | 1.68 |
| long_short_monthly | 16.2 | 0.9% | 0.63 | 0.55 | 1.68 |
| long_only_weekly | 32.2 | 0.7% | 0.76 | 0.69 | 1.46 |
| long_only_monthly | 13.4 | 0.3% | 0.93 | 0.90 | 1.47 |
| risk_parity_weekly | 1.1 | 0.0% | 0.65 | 0.65 | 1.63 |

## Finestre di crisi (rendimento cumulato)
| Strategia | 2008-09..2009-03 | 2020-02..2020-04 | 2022 |
|---|---|---|---|
| long_short_weekly | 13.1% | 0.7% | 9.4% |
| long_short_monthly | 11.5% | 6.8% | 14.6% |
| long_only_weekly | 4.9% | -9.9% | -0.4% |
| long_only_monthly | 2.6% | -1.5% | 2.7% |
| risk_parity_weekly | -18.7% | -13.0% | -20.3% |
| 60_40_monthly | -20.3% | -2.4% | -16.7% |
| SPY_buy_hold | -36.9% | -9.2% | -18.2% |

## Rendimenti per anno solare (2006 e 2026 parziali)
| Anno | long_short_weekly | long_short_monthly | long_only_weekly | long_only_monthly | risk_parity_weekly | 60_40_monthly | SPY_buy_hold |
|---|---|---|---|---|---|---|---|
| 2006 | 3.0% | 5.2% | 10.1% | 9.5% | 12.6% | 10.4% | 15.8% |
| 2007 | 7.0% | 10.5% | 13.2% | 17.1% | 20.6% | 7.4% | 5.1% |
| 2008 | 20.6% | 20.2% | 18.6% | 15.7% | -14.4% | -18.0% | -36.8% |
| 2009 | 2.6% | -5.3% | -1.0% | -1.2% | 6.9% | 12.6% | 26.4% |
| 2010 | 3.5% | 6.3% | 12.7% | 16.3% | 17.3% | 13.5% | 15.1% |
| 2011 | -5.0% | 0.7% | -3.5% | 3.9% | 5.8% | 7.7% | 1.9% |
| 2012 | 4.4% | 5.4% | 5.8% | 8.7% | 7.9% | 11.2% | 16.0% |
| 2013 | 10.8% | 14.8% | 9.0% | 11.6% | 0.3% | 15.6% | 32.3% |
| 2014 | 7.0% | 3.0% | 7.7% | 5.6% | 0.8% | 11.8% | 13.5% |
| 2015 | -2.8% | -5.2% | -5.2% | -5.0% | -6.8% | 1.7% | 1.2% |
| 2016 | -4.9% | 4.2% | 5.2% | 10.1% | 14.3% | 7.7% | 12.0% |
| 2017 | 6.7% | 16.0% | 17.2% | 23.1% | 21.7% | 13.7% | 21.7% |
| 2018 | -3.1% | -0.2% | -9.7% | -7.8% | -7.9% | -2.0% | -4.6% |
| 2019 | 6.2% | 3.7% | 20.6% | 20.9% | 27.0% | 21.8% | 31.2% |
| 2020 | 3.5% | 6.5% | 4.4% | 13.2% | 3.1% | 16.0% | 18.3% |
| 2021 | 2.8% | 3.5% | 7.1% | 8.9% | 10.9% | 15.1% | 28.7% |
| 2022 | 9.4% | 14.6% | -0.4% | 2.7% | -20.3% | -16.7% | -18.2% |
| 2023 | -10.4% | -11.6% | 5.5% | 5.5% | 13.6% | 16.8% | 26.2% |
| 2024 | 7.7% | 10.0% | 13.5% | 15.4% | 13.7% | 14.1% | 24.9% |
| 2025 | 2.1% | 10.1% | 12.7% | 18.7% | 18.9% | 13.9% | 17.7% |
| 2026 | -3.3% | 0.6% | -4.6% | 1.6% | 4.4% | 3.6% | 6.7% |

## DSR, bootstrap e verdetto (4 prove)
| Variante | DSR (a: >0,95) | Sharpe post-2013 (b: >0) | Sharpe blend con RP | Delta Sharpe blend-RP | CI95 (c: >0) | CI95 Delta Sharpe variante-SPY | Verdetto | Criteri falliti |
|---|---|---|---|---|---|---|---|---|
| long_short_weekly | 0.680 | 0.26 | 0.74 | 0.09 | [-0.23, 0.41] | [-0.89, 0.25] | DISCARD | a,c |
| long_short_monthly | 0.917 | 0.53 | 0.84 | 0.19 | [-0.15, 0.51] | [-0.68, 0.45] | DISCARD | a,c |
| long_only_weekly | 0.977 | 0.62 | 0.77 | 0.12 | [-0.08, 0.32] | [-0.40, 0.50] | DISCARD | c |
| long_only_monthly | 0.999 | 0.86 | 0.87 | 0.22 | [0.02, 0.41] | [-0.17, 0.69] | KEEP | - |

## Lettura (solo fatti)
- Regola pre-registrata: una sola variante su 4 (long_only_monthly) soddisfa tutti i criteri; long_only_weekly passa (a) e (b) ma non (c); le due long_short falliscono (a) e (c).
- Le long_short hanno Sharpe netto inferiore a risk_parity sull'intera finestra (0,35 e 0,55 vs 0,65), correlazione con SPY negativa e rendimenti positivi in tutte e tre le finestre di crisi; Sharpe post-2013 0,26 e 0,53.
- Nessuna variante ha uno Sharpe significativamente diverso da SPY buy&hold (CI95 della differenza include 0 in tutti i casi). Post-2013: SPY 0,87; 60/40 0,92; long_only_monthly 0,86.
- Mensile > settimanale in entrambe le coppie; il turnover settimanale costa piu' del mensile (vedi tabella costi). Il verdetto KEEP e' ottenuto su un solo campione storico; il limite inferiore del CI95 del blend e' 0,02, vicino a 0; long_only_monthly ha correlazione con SPY 0,27 (full) e 0,44 (post-2013).

## Caveat
- Sopravvivenza/inception: ETF attuali scelti con conoscenza ex post; entrano alle date di lancio (HYG, UUP, FXY nel 2007, ecc.), quindi 2006-2007 usa un universo ristretto; le crypto entrano dal 2014/2017 e la loro inclusione e' una scelta ex post.
- Yahoo adjusted close: serie aggiustate per dividendi/split, non esattamente tradabili, soggette a revisioni. Futures veri (roll, margini) non modellati: ETF come proxy (USO/DBC/DBA hanno roll/contango interno).
- Tasso di finanziamento/cash = 0 e leva fino a 2x senza costo di finanziamento: sovrastima i rendimenti, in particolare dal 2022 con tassi alti.
- Crypto: costo short 0 (il funding reale puo' essere positivo o negativo); 10 bps one-way possono essere ottimistici in stress; vol annualizzata con sqrt(365) su rendimenti dei soli giorni lavorativi (specifica).
- Pesi senza drift infra-periodo; esecuzione a close senza slippage di apertura ne' impatto di mercato.
- Potenza limitata del bootstrap (circa 21 anni); i DSR contano 4 prove, non la ricerca storica da cui provengono i parametri.

## Revisione: finanziamento della leva e Sharpe in eccesso sul T-bill (aggiunta dall'orchestratore)

Il backtest originale usava `cash_rate=0`: la leva (fino a 2x) era gratuita e la liquidità non rendeva. Ricalcolo (`quant/portfolio/financing_check.py`) con: liquidità che rende il T-bill a 13 settimane (^IRX), leva che paga T-bill + 0,5%, Sharpe calcolato sull'**eccesso rispetto al T-bill** per tutte le strategie e i benchmark.

| strategia | CAGR | Sharpe in eccesso | Sharpe post-2013 | maxDD | leva lorda media | esposizione netta media |
|---|---|---|---|---|---|---|
| long_short_weekly | 3.4% | 0.21 | 0.14 | -19.9% | 1.68 | 0.60 |
| long_short_monthly | 5.5% | 0.42 | 0.40 | -17.4% | 1.68 | 0.60 |
| long_only_weekly | 5.1% | 0.39 | 0.30 | -18.9% | 1.46 | 1.46 |
| **long_only_monthly** | **7.7%** | **0.62** | **0.56** | **-17.2%** | 1.47 | 1.47 |
| risk_parity_weekly | 4.9% | 0.35 | 0.29 | -30.3% | 1.63 | 1.63 |
| 60/40 mensile | 7.8% | 0.60 | 0.73 | -32.6% | | |
| SPY buy&hold | 10.5% | 0.53 | 0.76 | -55.2% | | |

| variante | DSR (n=4) | Sharpe post-2013 | Δ Sharpe blend 50/50 − risk parity, IC95% | verdetto |
|---|---|---|---|---|
| long_short_weekly | 0.613 | 0.14 | +0.071 [-0.243, +0.373] | SCARTARE |
| long_short_monthly | 0.887 | 0.40 | +0.185 [-0.141, +0.484] | SCARTARE |
| long_only_weekly | 0.864 | 0.30 | +0.076 [-0.112, +0.267] | SCARTARE |
| long_only_monthly | 0.984 | 0.56 | +0.193 [+0.005, +0.371] | **TENERE (al limite)** |

Lettura senza abbellimenti: long_only_monthly supera le tre regole pre-registrate, ma il margine è minimo (limite inferiore +0.005). Dopo il 2013 il suo Sharpe in eccesso (0.56) è **inferiore** a quello di 60/40 (0.73) e di SPY (0.76): il valore sta nel drawdown dimezzato rispetto al 60/40 e nella bassa correlazione con l'azionario (0.27), non in un rendimento superiore. Con tutte le prove fatte in questa ricerca (oltre 70 configurazioni tra tutti i report) il DSR calcolato su 4 prove è ottimistico.
