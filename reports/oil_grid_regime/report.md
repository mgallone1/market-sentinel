# Griglia coperta sul petrolio con filtro di regime — test pre-registrato

Valori in $ per 1 barile per livello (moltiplicare per il lotto). Parametri fissi, nessun tuning. Regime e range da chiusure giornaliere fino al giorno precedente (causale): sigma_d = dev. std. rendimenti log 20g; VR5 su 60g; z trend = |ln(Pt/Pt-60)|/(sigma60*sqrt60); ON se VR5<0,8 e z<1; range = media 20g ±2*sigma_d*sqrt(20); passo = 0,25*sigma_d*prezzo (min 0,05 $). Spread 0,04 $ per posizione; finanziamento 5% annuo (e 0%) sul nozionale di ogni posizione aperta, pro-rata per barra (giorni di calendario). G1: coppie solo se ON e prezzo nel range, cap |inventario netto| 10, kill switch (chiusura di tutto alla chiusura della barra se il prezzo chiude fuori range o il regime passa a OFF al cambio giorno). G2 = G1 sempre ON (con parametri validi). C = G1 con giorni ON casuali (stessa frazione ON di G1, 20 seed). G0 = oil_grid.simulate (sempre ON, perdenti tenute) con passo fisso = mediana dei passi dei giorni ON di G1.

Limiti: simulazione sulle chiusure di barra (attraversamenti intra-barra non visti); sui dati giornalieri il 'percorso intraday' e' la sola chiusura giornaliera. Giorni con prezzi <=0 o finestre con NaN (aprile 2020 WTI) risultano OFF. Posizioni aperte a fine dati valutate a mercato (senza spread di chiusura). Il livello di griglia resta ancorato tra un giorno e l'altro (si ri-ancora solo dopo OFF/kill); una prima versione che ri-ancorava ogni giorno non apriva mai posizioni sui dati giornalieri ed e' stata scartata prima di guardare i risultati orari. 'Profitti lordi' = somma delle chiusure positive (take profit netti di spread e kill switch positivi).

## WTI_h (2024-07-05 → 2026-11-24, 13588 barre, 614 giorni, ON G1 21.3%, passo G0 0.30 $)

Finanziamento 5%

| var | P&L totale | realizzato | peggior equity | max drawdown | n kill | % giorni ON | finanz. | peggior kill | profitti lordi |
|---|---|---|---|---|---|---|---|---|---|
| G0 | -1'687 | 1'516 | -5'555 | 5'559 | n/d | 100.0 | 753 | n/d | n/d |
| G1 | -703 | -703 | -715 | 715 | 18 | 21.3 | 28 | -355 | 332 |
| G2 | -2'305 | -1'861 | -2'358 | 2'358 | 5 | 100.0 | 441 | -1'351 | 1'785 |
| C (media, 5°–95° pct) | -388 (-496 … -279) | n/d | -396 | 397 | 102.0 | 21.3 | 8 | -113 | n/d |

Finanziamento 0%

| var | P&L totale | realizzato | peggior equity | max drawdown | n kill | % giorni ON | finanz. | peggior kill | profitti lordi |
|---|---|---|---|---|---|---|---|---|---|
| G0 | -933 | 2'269 | -5'239 | 5'395 | n/d | 100.0 | 0 | n/d | n/d |
| G1 | -676 | -676 | -687 | 687 | 18 | 21.3 | 0 | -355 | 332 |
| G2 | -1'864 | -1'419 | -1'917 | 1'918 | 5 | 100.0 | 0 | -1'351 | 1'785 |
| C (media, 5°–95° pct) | -380 (-488 … -271) | n/d | -389 | 390 | 102.0 | 21.3 | 0 | -113 | n/d |

## BRENT_h (2024-07-05 → 2026-11-24, 13703 barre, 614 giorni, ON G1 18.9%, passo G0 0.33 $)

Finanziamento 5%

| var | P&L totale | realizzato | peggior equity | max drawdown | n kill | % giorni ON | finanz. | peggior kill | profitti lordi |
|---|---|---|---|---|---|---|---|---|---|
| G0 | -689 | 1'868 | -4'350 | 4'402 | n/d | 100.0 | 690 | n/d | n/d |
| G1 | -805 | -805 | -807 | 819 | 16 | 18.9 | 29 | -514 | 324 |
| G2 | -2'371 | -1'881 | -2'421 | 2'421 | 4 | 100.0 | 481 | -1'283 | 1'995 |
| C (media, 5°–95° pct) | -394 (-580 … -276) | n/d | -403 | 403 | 93.5 | 18.9 | 7 | -161 | n/d |

Finanziamento 0%

| var | P&L totale | realizzato | peggior equity | max drawdown | n kill | % giorni ON | finanz. | peggior kill | profitti lordi |
|---|---|---|---|---|---|---|---|---|---|
| G0 | 1 | 2'558 | -4'043 | 4'396 | n/d | 100.0 | 0 | n/d | n/d |
| G1 | -776 | -776 | -779 | 794 | 16 | 18.9 | 0 | -514 | 324 |
| G2 | -1'890 | -1'400 | -1'941 | 1'941 | 4 | 100.0 | 0 | -1'283 | 1'995 |
| C (media, 5°–95° pct) | -387 (-573 … -268) | n/d | -396 | 396 | 93.5 | 18.9 | 0 | -161 | n/d |

## WTI_d (2005-01-03 → 2026-11-23, 5507 barre, 5507 giorni, ON G1 23.2%, passo G0 0.32 $)

Finanziamento 5%

| var | P&L totale | realizzato | peggior equity | max drawdown | n kill | % giorni ON | finanz. | peggior kill | profitti lordi |
|---|---|---|---|---|---|---|---|---|---|
| G0 | -44'857 | -16'529 | -62'769 | 62'769 | n/d | 100.0 | 21'771 | n/d | n/d |
| G1 | -3'763 | -3'763 | -3'771 | 3'771 | 118 | 23.2 | 229 | -521 | 1'110 |
| G2 | -30'362 | -29'961 | -30'362 | 30'362 | 9 | 99.2 | 13'135 | -10'904 | 5'474 |
| C (media, 5°–95° pct) | -682 (-846 … -470) | n/d | -688 | 688 | 190.4 | 23.2 | 18 | -164 | n/d |

Finanziamento 0%

| var | P&L totale | realizzato | peggior equity | max drawdown | n kill | % giorni ON | finanz. | peggior kill | profitti lordi |
|---|---|---|---|---|---|---|---|---|---|
| G0 | -23'086 | 5'242 | -49'034 | 49'034 | n/d | 100.0 | 0 | n/d | n/d |
| G1 | -3'534 | -3'534 | -3'542 | 3'542 | 118 | 23.2 | 0 | -521 | 1'110 |
| G2 | -17'227 | -16'826 | -17'227 | 17'227 | 9 | 99.2 | 0 | -10'904 | 5'474 |
| C (media, 5°–95° pct) | -663 (-826 … -452) | n/d | -670 | 670 | 190.4 | 23.2 | 0 | -164 | n/d |

P&L per anno, finanziamento 5%

| anno | G0 | G1 | G2 |
|---|---|---|---|
| 2005 | -627 | -77 | -508 |
| 2006 | -305 | -117 | -898 |
| 2007 | -3'650 | -76 | -1'234 |
| 2008 | -11'865 | -193 | -4'044 |
| 2009 | 5'197 | -132 | -858 |
| 2010 | -555 | -27 | -1'328 |
| 2011 | -1'035 | -196 | -1'508 |
| 2012 | -613 | -361 | -987 |
| 2013 | -1'144 | -132 | -1'260 |
| 2014 | -4'797 | -0 | -2'965 |
| 2015 | -5'380 | -411 | -2'917 |
| 2016 | 3'116 | -160 | 468 |
| 2017 | 204 | -118 | -1'005 |
| 2018 | -4'021 | -129 | -1'836 |
| 2019 | 2'232 | -91 | -453 |
| 2020 | -14'134 | -107 | -2'566 |
| 2021 | -2'333 | -173 | -962 |
| 2022 | -1'506 | -457 | -1'951 |
| 2023 | 229 | -196 | -822 |
| 2024 | -1'023 | -66 | -738 |
| 2025 | -90 | -82 | -445 |
| 2026 | -2'756 | -461 | -1'543 |

## BRENT_d (2007-07-30 → 2026-11-23, 4810 barre, 4810 giorni, ON G1 22.5%, passo G0 0.34 $)

Finanziamento 5%

| var | P&L totale | realizzato | peggior equity | max drawdown | n kill | % giorni ON | finanz. | peggior kill | profitti lordi |
|---|---|---|---|---|---|---|---|---|---|
| G0 | -26'526 | -14'566 | -33'001 | 33'001 | n/d | 100.0 | 19'128 | n/d | n/d |
| G1 | -3'397 | -3'397 | -3'416 | 3'421 | 91 | 22.5 | 233 | -399 | 961 |
| G2 | -26'857 | -25'752 | -27'296 | 27'296 | 12 | 99.6 | 7'117 | -8'216 | 4'974 |
| C (media, 5°–95° pct) | -593 (-805 … -431) | n/d | -600 | 605 | 155.1 | 22.5 | 16 | -190 | n/d |

Finanziamento 0%

| var | P&L totale | realizzato | peggior equity | max drawdown | n kill | % giorni ON | finanz. | peggior kill | profitti lordi |
|---|---|---|---|---|---|---|---|---|---|
| G0 | -7'397 | 4'562 | -20'898 | 20'898 | n/d | 100.0 | 0 | n/d | n/d |
| G1 | -3'164 | -3'164 | -3'183 | 3'188 | 91 | 22.5 | 0 | -399 | 961 |
| G2 | -19'740 | -18'635 | -20'203 | 20'203 | 12 | 99.6 | 0 | -8'216 | 4'974 |
| C (media, 5°–95° pct) | -577 (-788 … -416) | n/d | -584 | 590 | 155.1 | 22.5 | 0 | -190 | n/d |

P&L per anno, finanziamento 5%

| anno | G0 | G1 | G2 |
|---|---|---|---|
| 2007 | -890 | 0 | -390 |
| 2008 | -14'233 | -243 | -4'272 |
| 2009 | 4'909 | -261 | -520 |
| 2010 | -324 | -15 | -1'650 |
| 2011 | -1'397 | -367 | -1'608 |
| 2012 | -1'151 | -251 | -1'943 |
| 2013 | -790 | -146 | -750 |
| 2014 | -3'134 | -132 | -1'978 |
| 2015 | -5'995 | -152 | -1'301 |
| 2016 | 3'452 | -150 | -687 |
| 2017 | 638 | -70 | -1'218 |
| 2018 | -2'880 | -262 | -639 |
| 2019 | 1'052 | -82 | -467 |
| 2020 | -3'918 | -91 | -2'287 |
| 2021 | 1'857 | -68 | -1'085 |
| 2022 | -560 | -325 | -2'260 |
| 2023 | -874 | -212 | -708 |
| 2024 | -973 | -42 | -672 |
| 2025 | -2'104 | -74 | -772 |
| 2026 | 790 | -455 | -1'651 |

## Verdetto

Regola KEEP (finanziamento 5%): G1 totale > 0 su tutti e 4 i dataset; G1 > G2 e G1 > 95° pct di C su entrambi gli orari; max drawdown G1 < 50% dei profitti lordi realizzati di G1 su ogni dataset.

**DISCARD**. Criteri non soddisfatti: G1 totale <= 0 su WTI_h; G1 maxDD >= 50% dei profitti lordi realizzati su WTI_h; G1 totale <= 0 su BRENT_h; G1 maxDD >= 50% dei profitti lordi realizzati su BRENT_h; G1 totale <= 0 su WTI_d; G1 maxDD >= 50% dei profitti lordi realizzati su WTI_d; G1 totale <= 0 su BRENT_d; G1 maxDD >= 50% dei profitti lordi realizzati su BRENT_d; G1 <= 95mo percentile di C su WTI_h; G1 <= 95mo percentile di C su BRENT_h.
