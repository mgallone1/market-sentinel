# Test "fare l'opposto": segnali originali e invertiti (10 USDT perps, 2023-11 → 2026-11, costi Bybit)

Script: `quant/research/experiments/inverse_signals.py`. Stesse uscite e stessi costi per il segnale originale e per quello invertito (side × −1).

| strategia | verso | trade | win | lordo/trade | netto/trade (±SE) |
|---|---|---|---|---|---|
| legacy (bot) 1h | originale | 5012 | 43.3% | +0.025% | −0.153% (±0.025) |
| legacy (bot) 1h | inversa | 6277 | 43.7% | −0.013% | −0.186% (±0.021) |
| donchian 1h | originale | 5170 | 36.3% | +0.102% | −0.073% (±0.046) |
| donchian 1h | inversa | 6607 | 32.9% | −0.074% | −0.238% (±0.040) |
| tsmom 4h | originale | 4814 | 37.5% | +0.164% | −0.019% (±0.086) |
| tsmom 4h | inversa | 5202 | 34.2% | −0.145% | −0.302% (±0.082) |
| meanrev_z 1h | originale | 1897 | 31.7% | −0.138% | −0.305% (±0.067) |
| meanrev_z 1h | inversa | 1854 | 36.2% | +0.093% | −0.080% (±0.070) |

Lettura:
- Invertire cambia il segno del **lordo** ma non dei **costi**, che si pagano in entrambi i versi: netto(originale) = g − c, netto(inversa) = −g − c. Conviene invertire solo se g < −c, mai osservato qui.
- Il win rate dell'inversa **non** è 1 − p: con stop a 1× e target a 3× (uscite asimmetriche) entrambi i versi vincono meno del 50%.
- In tutti e quattro i casi il verso con lordo positivo è quello **a favore del trend** (l'inversa del mean-reversion è un trend-following): coerente con gli altri report. Il lordo però resta sotto i costi.
