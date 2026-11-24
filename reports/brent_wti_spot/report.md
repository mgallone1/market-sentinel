# Spread Brent–WTI con dati corretti (spot EIA da FRED) e verifiche anti-artefatto

Script: `quant/research/experiments/brent_wti_spot.py` e `brent_wti_checks.py`. Regole identiche al test precedente (`quant/research/spreads.py`), dati spot EIA 1990–2026 (nessun salto da roll). Due scenari di costo fissati prima: CFD ($0,03/bbl/gamba/lato + 5%/anno su entrambi i nozionali) e FUTURES ($0,01/bbl/gamba/lato + rinnovo ≈ 0,35%/anno). DSR con 110 prove.

## Primo risultato (esecuzione alla stessa chiusura del segnale)
| strategia | Sharpe lordo | Sharpe netto | 1990–07 | 2008–26 | post-2018 | IC95% | trade | win | DSR | verdetto |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 z-score, CFD | 0,33 | 0,10 | 0,07 | 0,12 | 0,38 | [−0,12; 0,31] | 223 | 50% | 0,02 | scartato |
| S1 z-score, futures | 0,33 | 0,29 | 0,31 | 0,31 | 0,54 | [0,08; 0,51] | 223 | 60% | 0,18 | scartato |
| Griglia, CFD | 1,14 | 0,44 | 0,95 | 0,27 | 0,23 | [0,17; 0,73] | 5338 | 83% | 0,44 | scartato |
| Griglia, futures | 1,14 | **1,05** | 1,63 | 0,89 | 0,73 | [0,76; 1,38] | 5338 | **97%** | 0,999 | supera i criteri… |

## Verifiche: il risultato della griglia era un artefatto
1. **Chiusure non sincrone.** Autocorrelazione delle variazioni giornaliere dello spread (lag 1): spot EIA **−0,285**, futures (chiusure quasi sincrone) **−0,018** negli stessi giorni. Lo spot Brent e lo spot WTI sono rilevati in orari diversi: la differenza di orario genera un rientro giornaliero che non si può negoziare.
2. **Esecuzione al giorno dopo il segnale** (decisione sulla chiusura di oggi, prezzo di domani):

| griglia, costi futures | Sharpe netto | post-2018 | IC95% | win | trade | DSR(110) |
|---|---|---|---|---|---|---|
| spot, stessa chiusura (sopra) | 1,05 | 0,73 | [0,76; 1,38] | 97% | 5338 | 0,999 |
| **spot, esecuzione giorno dopo** | **0,34** | 0,57 | [0,15; 0,57] | 63% | 4718 | 0,26 |
| **futures Yahoo 2008–26, esecuzione giorno dopo** | **0,54** | 0,85 | [0,22; 0,91] | 80% | 1961 | 0,40 |

**Verdetto: scartato secondo le regole** (Sharpe 0,34 < 0,5 sull'intero periodo; DSR sotto 0,95). Il risultato di Sharpe 1,05 era dovuto all'asincronia dei prezzi spot e all'esecuzione sulla chiusura del segnale.

**Cosa resta:** dopo le correzioni, la griglia sullo spread mantiene in entrambi i dataset un rendimento netto positivo con intervallo di confidenza sopra zero (Sharpe 0,34–0,54, più alto dopo il 2018). È il residuo più consistente trovato nella ricerca, ma non abbastanza forte da escludere la fortuna dopo 110 prove. Test minimo per decidere: futures con la stessa scadenza o serie continue aggiustate per il roll (CME/ICE settlement, fornitori a pagamento), esecuzione al settlement del giorno dopo, costi reali del broker, più 6 mesi di paper trading.
