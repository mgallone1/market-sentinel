# Test pre-registrato del volatility risk premium (V1, V2)

Esattamente 2 trial, nessun tuning. Codice: `quant/portfolio/vrp.py`; numeri completi in `report.json`. Dati Yahoo giornalieri (auto-adjust), fino al 2026-11-24.

## Ipotesi operative
- Decisione alla chiusura t, esposizione da close t a close t+1 (`run_weights`). Cash = T-bill: ^IRX/100/252 (tasso del giorno precedente), modellato come asset CASH a costo 0. Sharpe = eccesso sul T-bill.
- V1: se VIX/VIX3M < 1 (contango) SVXY peso 1.0, altrimenti cash. Costo 5 bps one-way sul turnover. Dato mancante => cash.
- V2: a fine mese VRP = (VIX/100)^2/12 - RV21^2*21 (RV = std rendimenti giornalieri SPY); SPY nel mese successivo se VRP > mediana dei 60 mesi PRECEDENTI (mese corrente escluso), altrimenti IEF. Costo 2 bps. Valutazione da 2002-07-31 (primo dato IEF; la storia per la mediana parte dal 1993).
- Benchmark: SPY buy&hold, SVXY buy&hold, 60/40 SPY/IEF ribilanciato mensilmente (senza costi).
- DSR: var_sr_trials = varianza dei Sharpe per-periodo dei 2 trial (7.5e-5), n_trials=2 e 80. Bootstrap: blocchi geometrici medi 20gg, 2000 repliche, su rendimenti in eccesso, Sharpe(V) - Sharpe(benchmark), campione completo.

## Range dati
SPY 1993-01-29, IEF 2002-07-30, SVXY 2011-10-04, VXX 2018-01-25 (Yahoo ha lo storico solo del nuovo ticker VXX; non usato nei trial), ^VIX 1990-01-02, ^VIX3M 2006-07-17 (^VXV non disponibile, non necessario), ^IRX 1990-01-02. Ultimo dato 2026-11-24.

## Metriche (rendimenti netti; Sharpe/Sortino in eccesso sul T-bill)
| Serie | Periodo | CAGR | Vol | Sharpe | Sortino | MaxDD | Peggior giorno | Peggior mese | Skew | % investito |
|---|---|---|---|---|---|---|---|---|---|---|
| V1 | pieno da 2011-10 | 26.6% | 44.5% | 0.72 | 0.78 | -49.5% | -26.5% | -31.7% | -1.19 | 93% |
| V1 | pre 2018-03 | 51.7% | 57.7% | 1.01 | 1.17 | -49.5% | -26.5% | -31.7% | -0.99 | 95% |
| V1 | post 2018-03 | 10.9% | 31.3% | 0.40 | 0.42 | -35.0% | -16.9% | -18.7% | -1.62 | 92% |
| V2 | pieno da 2002-07 | 7.2% | 13.9% | 0.45 | 0.54 | -33.7% | -10.9% | -12.5% | -0.44 | 44% SPY |
| V2 | post 2013 | 5.9% | 13.2% | 0.36 | 0.42 | -33.7% | -10.9% | -12.5% | -0.94 | 43% SPY |
| SPY B&H | pieno da 1993 | 10.6% | 18.6% | 0.50 | 0.64 | -55.2% | -10.9% | -16.5% | -0.01 | 100% |
| SPY B&H | post 2013 | 14.3% | 16.8% | 0.77 | 0.95 | -33.7% | -10.9% | -12.5% | -0.32 | 100% |
| SVXY B&H | pieno da 2011-10 | 10.9% | 54.9% | 0.51 | 0.49 | -95.2% | -83.0% | -89.6% | -4.74 | 100% |
| SVXY B&H | pre 2018-03 | 14.1% | 72.3% | 0.68 | 0.66 | -93.1% | -83.0% | -89.6% | -4.60 | 100% |
| SVXY B&H | post 2018-03 | 8.5% | 37.2% | 0.34 | 0.35 | -62.2% | -21.4% | -38.9% | -1.84 | 100% |
| 60/40 | pieno da 2002-08 | 8.2% | 10.6% | 0.64 | 0.81 | -32.6% | -5.5% | -10.3% | -0.06 | 100% |
| 60/40 | post 2013 | 9.1% | 9.9% | 0.75 | 0.94 | -21.3% | -5.5% | -7.4% | -0.30 | 100% |

## Tabella di coda (rendimento cumulato nel periodo)
| Periodo | V1 | V2 | SPY | SVXY | 60/40 |
|---|---|---|---|---|---|
| 2018-02-01..02-28 | -7.5% | -3.7% | -3.6% | -89.6% | -2.6% |
| 2020-02-15..03-31 | -14.1% | -23.2% | -23.2% | -54.3% | -11.8% |
| 2008-09..2009-03 | n/d (SVXY non esiste) | -0.5% | -36.9% | n/d | -20.3% |
| 2022 | -8.6% | -7.3% | -18.2% | -4.7% | -16.7% |

## Verdetti (regola KEEP)
| | DSR n=2 | DSR n=80 | Sharpe post-split | Diff. Sharpe vs bench (obs; CI95) | Peggior giorno | Verdetto |
|---|---|---|---|---|---|---|
| V1 (bench SVXY B&H) | 0.993 OK | 0.927 | 0.40 OK (post 2018-03) | +0.21 ; [-0.19, +0.62] FAIL | -26.5% FAIL (soglia -25%) | **DISCARD** |
| V2 (bench SPY B&H) | 0.966 OK | 0.702 | 0.36 OK (post 2013) | -0.11 ; [-0.44, +0.21] FAIL | n/a | **DISCARD** |

Criteri falliti: V1 = limite inferiore del bootstrap <= 0 e peggior giorno < -25%; V2 = limite inferiore del bootstrap <= 0 (Sharpe osservato inferiore a SPY B&H sullo stesso periodo). Con n_trials=80 (tutta la ricerca del repo) entrambi scendono sotto 0.95 (V1 0.927, V2 0.702).

## Avvertenze
- SVXY: dal 2018-02-28 esposizione passata da -1x a -0.5x dei futures VIX; il campione pre-split (CAGR 52%) non e' replicabile oggi, il post-split e' il rilevante. Il peggior giorno di V1 (-26.5%) cade nel pre-split.
- Sopravvivenza: l'ETP inverso XIV (-1x VIX) e' stato terminato dall'emittente dopo -96% il 2018-02-05; non e' nel campione. SVXY sopravvive solo perche' ha ridotto la leva. Il campione e' quindi viziato da sopravvivenza, a favore dei risultati short-vol.
- Decadimento ETP: roll dei futures VIX, rebalancing giornaliero e TER incidono; auto-adjust di Yahoo include split inversi/dividendi. SVXY ha avuto split/reverse split: fidarsi della serie adjusted.
- VIX3M disponibile solo dal 2006-07; V1 inizia con SVXY (2011-10), quindi il campione contiene pochissimi episodi di stress (2015-08, 2018-02, 2020-03, 2022).
- Esecuzione ipotizzata alla chiusura t del segnale (VIX e ETP quotati a orari diversi, slippage ignorato oltre ai costi dichiarati). V1 e' sensibile a gap overnight in regime di backwardation improvviso.
- Il DSR riflette il numero di trial dichiarato; la varianza dei Sharpe tra soli 2 trial e' una stima molto rumorosa.
- V2 e' investito in SPY solo il 44% del tempo; il confronto con SPY B&H penalizza il timing nel campione 2002-2026 (bull market).
