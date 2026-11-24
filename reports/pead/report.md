# PEAD pre-registrato (S&P100, yfinance)

## Dati e limiti
- Universo = S&P100 odierno hardcoded: survivorship bias (nomi vincenti ex-post).
- Ticker con prezzi: 99/100; con eventi usabili: 99; mancanti: BK
- Eventi con surprise valida: 9136; usabili (finestra completa): 5780
- Copertura annunci: 2012-01-13 06:00:00-05:00 -> 2026-10-27 07:00:00-04:00 (yfinance limit=60 per ticker; storia limitata)
- Timing: giorno 1 = primo open dopo l'annuncio (pre-market 09:30 ET stesso giorno; dopo chiusura/ignoto/in seduta giorno di borsa dopo); entrata open giorno 2, uscita close giorno 21 (20 giorni).
- Costi: 5 bp per gamba x2, borrow 1%/anno sugli short; aggiustamento = ritorno titolo - SPY stessa finestra (nessun costo sulla gamba SPY).
- Serie giornaliera: media equal-weight delle posizioni aperte, solo giorni con posizioni (giorni a poche posizioni pesano come quelli affollati: la media giornaliera puo divergere dalla media per evento); DSR con var Sharpe tra i 2 trial.

## long_short: **DISCARD**
- Eventi: 3143; criteri falliti: mean_net_adj>0 e CI95 low>0, batte controllo random (diff CI low>0), >=2/3 anni positivi (anni con >=30 eventi), DSR(n=2)>0.95
- Media netta agg. mercato: 0.19% (lordo 0.30%); grezza netta: 1.10%
- t cluster-mese: 1.32; bootstrap CI95 (mesi): [-0.08%, 0.47%]; hit rate 50.0%
- Controllo random (20 rep): media 0.07%; differenza 0.12% CI95 [-0.16%, 0.41%]
- Anni con >=30 eventi: 15, frazione positivi 53%

| Anno | n | media netta agg. |
|---|---|---|
| 2012 | 179 | -0.48% |
| 2013 | 176 | 1.04% |
| 2014 | 172 | -0.11% |
| 2015 | 194 | 0.45% |
| 2016 | 198 | -0.43% |
| 2017 | 194 | -0.05% |
| 2018 | 204 | 0.47% |
| 2019 | 192 | 0.54% |
| 2020 | 267 | -0.26% |
| 2021 | 288 | 0.39% |
| 2022 | 227 | 0.55% |
| 2023 | 235 | -0.56% |
| 2024 | 216 | 0.36% |
| 2025 | 203 | 1.43% |
| 2026 | 198 | -0.41% |

Decili di surprise (1=piu negativo), ritorno 20g agg. mercato lordo senza segno:

- D1: -0.23%
- D2: -0.68%
- D3: 0.03%
- D4: 0.07%
- D5: 0.21%
- D6: -0.04%
- D7: 0.16%
- D8: -0.02%
- D9: 0.57%
- D10: 1.52%
- Spearman decile/ritorno: 0.73

- Serie giornaliera (3711 giorni): Sharpe ann. -0.21; DSR(n=2) 0.183; DSR(n=80) 0.111

## long_only: **DISCARD**
- Eventi: 2627; criteri falliti: mean_net_adj>0 e CI95 low>0, batte controllo random (diff CI low>0), >=2/3 anni positivi (anni con >=30 eventi), DSR(n=2)>0.95
- Media netta agg. mercato: 0.18% (lordo 0.28%); grezza netta: 1.53%
- t cluster-mese: 1.07; bootstrap CI95 (mesi): [-0.13%, 0.50%]; hit rate 49.3%
- Controllo random (20 rep): media 0.18%; differenza -0.01% CI95 [-0.33%, 0.33%]
- Anni con >=30 eventi: 15, frazione positivi 47%

| Anno | n | media netta agg. |
|---|---|---|
| 2012 | 136 | -0.45% |
| 2013 | 133 | 1.05% |
| 2014 | 142 | -0.27% |
| 2015 | 151 | 0.61% |
| 2016 | 166 | -0.10% |
| 2017 | 164 | -0.16% |
| 2018 | 179 | 0.20% |
| 2019 | 158 | 0.43% |
| 2020 | 216 | -0.08% |
| 2021 | 265 | 0.56% |
| 2022 | 185 | 0.93% |
| 2023 | 191 | -1.02% |
| 2024 | 179 | -0.10% |
| 2025 | 181 | 1.47% |
| 2026 | 181 | -0.51% |

Decili di surprise (1=piu negativo), ritorno 20g agg. mercato lordo senza segno:

- D1: -0.02%
- D2: -0.14%
- D3: -0.09%
- D4: 0.43%
- D5: -0.22%
- D6: 0.35%
- D7: 0.05%
- D8: 0.51%
- D9: 0.34%
- D10: 1.54%
- Spearman decile/ritorno: 0.66

- Serie giornaliera (3680 giorni): Sharpe ann. -0.15; DSR(n=2) 0.252; DSR(n=80) 0.162
