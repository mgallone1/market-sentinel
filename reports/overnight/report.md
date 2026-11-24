# Test pre-registrato: anomalia overnight (SPY, QQQ, IWM)

Periodo 2000-01-01 (o inizio serie)..2026-11-23 (barra del 24/11 esclusa perche' potenzialmente in formazione). Dati Yahoo giornalieri, `auto_adjust=False`; 3 prove, nessun tuning.

## Metodo
- Overnight = close(t-1)->open(t) piu' dividendo alla ex-date (reinvestito all'open); intraday = open->close. Identita' (1+on)(1+id)=1+cc verificata nei test. Buy&hold = cc (total return con dividendo reinvestito all'open ex-date).
- Split: fattori yfinance applicati solo se i prezzi risultano non aggiustati; in questi dati i prezzi sono gia' aggiustati (split applicati: 0 su tutti gli asset).
- Strategia O: acquisto MOC, vendita MOO ogni giorno. Costo per lato su entrambe le operazioni (giro = 2 lati). Cassa a rendimento zero durante la sessione.
- Assunzione costi: 1,0 bp one-way + 0,5 bp half-spread = 1,5 bp/lato (spread SPY/QQQ ~0,3 bp). La regola KEEP e' valutata a 1,0 bp/lato come da pre-registrazione; 1,5 bp compare nella sensibilita'.
- Versione eccesso T-bill: ^IRX (noto a t-1) pro-rata sulla frazione di tempo; frazione intraday = 6,5/24 del giorno di calendario, resto overnight (weekend inclusi), base 360.
- Bootstrap a blocchi (media 20 giorni, 2000 ricampionamenti, seed 0) sulla differenza di Sharpe O netto - B&H. DSR: var_sr_trials = varianza tra i 3 asset dello Sharpe per-periodo netto (1.68e-04).

## Verdetto KEEP/DISCARD

| Asset | Sharpe O netto 1bp | Sharpe B&H | diff Sharpe [IC95 bootstrap] | 2000-12 / 2013-26 Sharpe O | DSR n=3 | DSR n=80 | Verdetto |
|---|---|---|---|---|---|---|---|
| SPY | 0.24 | 0.50 | -0.26 [-0.57, +0.05] | 0.02 / 0.46 | 0.627 | 0.086 | **DISCARD** |
| QQQ | 0.48 | 0.43 | +0.06 [-0.29, +0.38] | 0.32 / 0.66 | 0.942 | 0.452 | **DISCARD** |
| IWM | 0.65 | 0.45 | +0.20 [-0.13, +0.54] | 0.62 / 0.67 | 0.992 | 0.768 | **DISCARD** |

Condizioni non soddisfatte: SPY: sharpe_gt_bh, ci_lo_gt0, dsr3_gt_095; QQQ: ci_lo_gt0, dsr3_gt_095; IWM: ci_lo_gt0.

## SPY

| Periodo | Serie | CAGR | Vol | Sharpe | MaxDD |
|---|---|---|---|---|---|
| full | O netto 1bp | 2.1% | 11.2% | 0.24 | -38.9% |
| full | O lordo | 7.3% | 11.2% | 0.69 | -32.8% |
| full | Buy&hold | 8.0% | 19.3% | 0.50 | -55.2% |
| full | Solo intraday | 0.6% | 15.5% | 0.12 | -57.0% |
| 2000-2012 | O netto 1bp | -0.4% | 11.6% | 0.02 | -38.9% |
| 2000-2012 | O lordo | 4.7% | 11.6% | 0.45 | -32.8% |
| 2000-2012 | Buy&hold | 1.7% | 21.6% | 0.18 | -55.2% |
| 2000-2012 | Solo intraday | -2.9% | 17.9% | -0.07 | -57.0% |
| 2013-2026 | O netto 1bp | 4.5% | 10.8% | 0.46 | -29.8% |
| 2013-2026 | O lordo | 9.8% | 10.8% | 0.92 | -29.4% |
| 2013-2026 | Buy&hold | 14.3% | 16.8% | 0.88 | -33.7% |
| 2013-2026 | Solo intraday | 4.1% | 12.8% | 0.38 | -24.6% |

Quota del rendimento log buy&hold maturata overnight (lordo): full 92%, 2000-2012 277%, 2013-2026 70% (valori >100% o negativi indicano che l'intraday e' stato negativo / il B&H quasi nullo nel periodo).

Break-even per lato (bp):

Break-even per lato (bp): | Periodo | Sharpe netto=0 | CAGR netto=CAGR B&H |
|---|---|---|
| full | 1.53 | non raggiungibile |
| 2000-2012 | 1.05 | 0.58 |
| 2013-2026 | 1.98 | non raggiungibile |

Sensibilita' ai costi (periodo intero, bp/lato -> Sharpe / CAGR netti): 0.5: 0.46 / 4.7%; 1.0: 0.24 / 2.1%; 1.5: 0.01 / -0.5%; 2.0: -0.21 / -3.0%; 3.0: -0.66 / -7.7%.
Eccesso T-bill (intero, Sharpe): O_net1bp 0.10, BH 0.39, INTRADAY 0.09 (O netto 1bp, B&H, intraday).

## QQQ

| Periodo | Serie | CAGR | Vol | Sharpe | MaxDD |
|---|---|---|---|---|---|
| full | O netto 1bp | 6.0% | 14.3% | 0.48 | -39.0% |
| full | O lordo | 11.5% | 14.3% | 0.83 | -33.5% |
| full | Buy&hold | 8.1% | 26.8% | 0.43 | -83.0% |
| full | Solo intraday | -3.0% | 22.9% | -0.02 | -86.7% |
| 2000-2012 | O netto 1bp | 3.9% | 15.5% | 0.32 | -39.0% |
| 2000-2012 | O lordo | 9.3% | 15.5% | 0.65 | -33.5% |
| 2000-2012 | Buy&hold | -2.4% | 31.8% | 0.08 | -83.0% |
| 2000-2012 | Solo intraday | -10.7% | 28.1% | -0.26 | -86.7% |
| 2013-2026 | O netto 1bp | 8.1% | 13.1% | 0.66 | -30.8% |
| 2013-2026 | O lordo | 13.6% | 13.1% | 1.04 | -27.4% |
| 2013-2026 | Buy&hold | 19.0% | 21.1% | 0.93 | -35.1% |
| 2013-2026 | Solo intraday | 4.7% | 16.6% | 0.36 | -24.7% |

Quota del rendimento log buy&hold maturata overnight (lordo): full 139%, 2000-2012 -365%, 2013-2026 74% (valori >100% o negativi indicano che l'intraday e' stato negativo / il B&H quasi nullo nel periodo).

Break-even per lato (bp):

Break-even per lato (bp): | Periodo | Sharpe netto=0 | CAGR netto=CAGR B&H |
|---|---|---|
| full | 2.37 | 0.61 |
| 2000-2012 | 2.00 | 2.24 |
| 2013-2026 | 2.71 | non raggiungibile |

Sensibilita' ai costi (periodo intero, bp/lato -> Sharpe / CAGR netti): 0.5: 0.66 / 8.7%; 1.0: 0.48 / 6.0%; 1.5: 0.31 / 3.4%; 2.0: 0.13 / 0.8%; 3.0: -0.22 / -4.1%.
Eccesso T-bill (intero, Sharpe): O_net1bp 0.37, BH 0.35, INTRADAY -0.04 (O netto 1bp, B&H, intraday).

## IWM

| Periodo | Serie | CAGR | Vol | Sharpe | MaxDD |
|---|---|---|---|---|---|
| full | O netto 1bp | 8.0% | 13.2% | 0.65 | -30.5% |
| full | O lordo | 13.6% | 13.2% | 1.03 | -28.8% |
| full | Buy&hold | 8.3% | 23.8% | 0.45 | -58.6% |
| full | Solo intraday | -4.7% | 20.1% | -0.14 | -75.9% |
| 2000-2012 | O netto 1bp | 7.7% | 13.3% | 0.62 | -30.5% |
| 2000-2012 | O lordo | 13.2% | 13.3% | 1.00 | -28.7% |
| 2000-2012 | Buy&hold | 6.4% | 26.2% | 0.37 | -58.6% |
| 2000-2012 | Solo intraday | -6.1% | 23.0% | -0.16 | -70.8% |
| 2013-2026 | O netto 1bp | 8.3% | 13.2% | 0.67 | -29.3% |
| 2013-2026 | O lordo | 13.9% | 13.2% | 1.06 | -28.8% |
| 2013-2026 | Buy&hold | 10.0% | 21.4% | 0.55 | -41.1% |
| 2013-2026 | Solo intraday | -3.4% | 17.0% | -0.12 | -59.9% |

Quota del rendimento log buy&hold maturata overnight (lordo): full 160%, 2000-2012 202%, 2013-2026 136% (valori >100% o negativi indicano che l'intraday e' stato negativo / il B&H quasi nullo nel periodo).

Break-even per lato (bp):

Break-even per lato (bp): | Periodo | Sharpe netto=0 | CAGR netto=CAGR B&H |
|---|---|---|
| full | 2.70 | 0.95 |
| 2000-2012 | 2.64 | 1.24 |
| 2013-2026 | 2.75 | 0.68 |

Sensibilita' ai costi (periodo intero, bp/lato -> Sharpe / CAGR netti): 0.5: 0.84 / 10.7%; 1.0: 0.65 / 8.0%; 1.5: 0.46 / 5.3%; 2.0: 0.27 / 2.7%; 3.0: -0.11 / -2.3%.
Eccesso T-bill (intero, Sharpe): O_net1bp 0.53, BH 0.37, INTRADAY -0.16 (O netto 1bp, B&H, intraday).

## Caveat
- Esecuzione MOC/MOO assunta ai prezzi di apertura/chiusura ufficiali senza impatto, mancati fill o imbalance; i costi reali di una strategia con 2 operazioni al giorno possono superare 1-1,5 bp/lato, e i break-even sono 1,5-2,7 bp/lato (Sharpe=0): margine ridotto.
- Qualita' del prezzo open di Yahoo: puo' essere la prima transazione/auction non filtrata; massimi |intraday| QQQ 19,6% e |overnight| ~10% vanno trattati con cautela, non verificati su fonte indipendente.
- Tasse ignorate (2 operazioni al giorno, tutte a breve termine). Cassa intraday a rendimento zero nella versione principale (conservativa); l'eccesso T-bill e' riportato a parte.
- Il dividendo e' accreditato all'open ex-date e reinvestito li'; ^IRX e' un tasso a 13 settimane usato come proxy del tasso overnight.
- DSR: la varianza tra prove e' stimata su soli 3 asset (molto rumorosa); le prove sono altamente correlate.
- Barra del 2026-11-24 esclusa (sessione possibilmente incompleta).
