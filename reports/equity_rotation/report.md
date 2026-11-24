# Rotazione azionaria E1-E4 (pre-registrata, 4 prove)

Dati: yfinance chiusure adjusted giornaliere fino al 2026-11-23; cash = T-bill ^IRX; costi 2 bps per lato; Sharpe/Sortino sono in eccesso sul T-bill. Pesi decisi al close t, applicati t->t+1.

## Metriche

| Serie | Inizio | CAGR | Vol | Sharpe ecc. | Sortino | MaxDD | % inv. | Sharpe post-2013 | Corr SPY | Turnover/anno | Costi/anno |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 TOM SPY | 1995-01-03 | 5.4% | 8.0% | 0.39 | 0.24 | -18.0% | 19% | 0.28 | 0.42 | 24.0 | 0.48% |
| SPY buy&hold | 1995-01-03 | 11.0% | 19.0% | 0.52 | 0.66 | -55.2% | 100% | 0.77 | 1.00 | 0.0 | 0.00% |
| E2 TOM basket | 2002-01-02 | 3.1% | 8.5% | 0.20 | 0.12 | -21.6% | 19% | 0.15 | 0.40 | 24.1 | 0.48% |
| Basket EW mensile | 2002-01-02 | 9.8% | 20.1% | 0.48 | 0.62 | -56.2% | 100% | 0.67 | 0.97 | 0.0 | 0.00% |
| E3 settori | 1999-12-31 | 8.7% | 17.2% | 0.46 | 0.58 | -35.7% | 94% | 0.70 | 0.77 | 5.2 | 0.10% |
| Settori EW | 1999-12-31 | 8.8% | 18.1% | 0.45 | 0.56 | -52.5% | 100% | 0.72 | 0.96 | 0.1 | 0.00% |
| E4 paesi | 1997-03-31 | 7.7% | 20.6% | 0.36 | 0.44 | -50.9% | 90% | 0.23 | 0.63 | 5.6 | 0.11% |
| Paesi EW | 1997-03-31 | 8.0% | 21.7% | 0.36 | 0.47 | -61.0% | 100% | 0.36 | 0.84 | 0.1 | 0.00% |

60/40 (SPY/IEF, dal 2002-07) Sharpe ecc. 0.59; TSMOM long_only mensile Sharpe ecc. 0.74.

## Regola KEEP

DSR con n_trials=100, varianza Sharpe tra le 4 prove = 4.85e-05. Bootstrap a blocchi 20 giorni, 2000 repliche. Ramo (b) E1/E2: Sharpe ecc. > 0.5, CI95 inferiore del proprio Sharpe ecc. > 0 e maxDD ridotto di almeno 40% rispetto al buy&hold.

| Strategia | Diff Sharpe vs bench | CI95 diff | CI95 proprio Sharpe ecc. | Riduzione maxDD | (a) | (b) | post-2013>0 | DSR | Esito |
|---|---|---|---|---|---|---|---|---|---|
| E1 | -0.13 | [-0.47, 0.21] | [0.08, 0.74] | 67% | False | False | True | 0.73 | DISCARD |
| E2 | -0.28 | [-0.70, 0.09] | [-0.17, 0.59] | 62% | False | False | True | 0.34 | DISCARD |
| E3 | 0.01 | [-0.22, 0.23] | [0.16, 0.79] | 32% | False | False | True | 0.82 | DISCARD |
| E4 | -0.00 | [-0.24, 0.23] | [0.05, 0.70] | 17% | False | False | True | 0.66 | DISCARD |

## Combinazione

Nessuna strategia E1-E4 ha superato la regola KEEP: combinazione inverse-vol non eseguita (resterebbe il solo TSMOM long_only mensile).

## Rendimenti per anno

Per anno (netto) in `report.json`, campo `metrics.<serie>.by_year`.

## Note
- Finestra E1: segnale su penultimo e ultimo giorno del mese e primi due giorni del successivo, uscita al close del 3o giorno, calendario reale dei dati.
- Benchmark E3/E4: equal-weight dell'universo eleggibile (13 mesi di storia), ribilanciato a fine mese, stessi costi.
- Verdetto: tutte DISCARD.
