# Pre-registrazione v1.1: BYBIT_POST_LIQ_REVERSAL e ALPACA_IN_PLAY_MOMENTUM

Data: 2026-11-26. Scritto e committato **prima** di qualsiasi run della v1.1. Motivazione: l'audit della v1.0
(`reports/NEW_STRATEGIES_POTENTIAL_AUDIT.md`) ha concluso NON VALUTABILE per entrambe (6 e 22 trade) e ha mostrato
distanze di stop degeneri (rischio fino allo 0.006% del prezzo). La v1.0 resta nel codice per riproducibilità
(`POST_LIQ_PARAMS_V1_0`, `IN_PLAY_PARAMS_V1_0`). Tutto quanto non scritto qui è identico alla v1.0
(`reports/PREREG_NEW_STRATEGIES.md`). Queste sono prove aggiuntive: totale cumulato dichiarato più sotto.

## Modifiche comuni
- **Rischio minimo 0.5 ATR**: se la distanza entry-SL della regola è inferiore a 0.5 × ATR14 del timeframe della strategia,
  lo SL viene allontanato fino a 0.5 ATR (lo stesso lato). Il resto (TP1 a 1.5R, breakeven, trailing, time-stop) è calcolato
  sul rischio così corretto.

## BYBIT_POST_LIQ_REVERSAL v1.1
- Funding: percentile 30 giorni ≥ **90** (SHORT) / ≤ **10** (LONG) (era 95/5).
- Open interest: z-score della variazione sulla barra di spike ≤ **−1.5** (era −2.0).
- **Rischio massimo 3 ATR**: se la distanza entry-SL supera 3 × ATR14 il segnale è scartato (`RISK_TOO_WIDE`).
- Universo: i 10 perp della v1.0 **più** BNB, LTC, DOT, BCH, ATOM, APT, ARB, OP, INJ, UNI (USDT, tutti quotati anche su
  Bybit) = 20 simboli; stessi dati, periodo e costi della v1.0.
- Varianti (2 prove): (a) uscite attive, (b) uscite fisse TP 2R. Controllo: ingressi casuali con le stesse uscite (seed 0).
  Lettura della direzione: quella della specifica (la lettura speculare della v1.0 era peggiore e non viene ripetuta).

## ALPACA_IN_PLAY_MOMENTUM v1.1
- Solo il rischio minimo 0.5 ATR(5m). Filtro In Play, ingressi e uscite invariati.
- Varianti (2 prove): (a) uscite attive, (b) fisse; controlli: stesse regole v1.1 senza filtro (attive e fisse).
- Test su Yahoo 5m (~40 sedute, descrittivo) qui; **test decisivo** sul server Oracle con barre 5m Alpaca dal 2024-06-01
  al 2026-11-25 (stesse regole, eseguito da Antigravity con `docs/ANTIGRAVITY_PROMPT_AUTONOMO.md`), sia per la v1.0 sia per
  la v1.1.

## Criteri (invariati) e regola decisionale per il test Alpaca su 2 anni
I criteri di raccomandazione del paper sono quelli della v1.0 (n ≥ 100, E > 0 e PF > 1.10, DSR > 0.95 beta-adjusted per
Alpaca, E > controllo, stabilità per trimestre). In più, per il test Alpaca su 2 anni:
- se la v1.1 In Play **non** batte il controllo senza filtro in E per trade, il filtro In Play è **scartato** e la strategia
  viene disattivata nel lab;
- se lo batte e soddisfa tutti i criteri: si avviano i 6 mesi di paper come validazione formale (`docs/LAB.md`).

## Lab
Il lab adotta la v1.1 (`version = "1.1"`) per entrambe, in paper, indipendentemente dall'esito: serve a misurare fill e
costi reali senza rischio. La promozione a capitale reale resta soggetta a `docs/LAB.md`.

## Numero di prove cumulato
v1.0: 4 (Bybit) + 2 (Alpaca) + 1 extra = 7. v1.1: 2 (Bybit) + 2 (Alpaca) = 4. Test Alpaca su 2 anni (Oracle): 2 versioni
× 2 varianti = 4. **Totale dichiarato: 15.**
