# Audit del potenziale: BYBIT_POST_LIQ_REVERSAL e ALPACA_IN_PLAY_MOMENTUM

Protocollo: `reports/PREREG_NEW_STRATEGIES.md` (commit 5aac5a2, prima di ogni backtest). Codice delle regole: `services/strategy_engines_service.py` §8 (solo lab/shadow); backtest: `quant/research/new_strategies/`; dati grezzi dei trade: `reports/new_strategies/*.csv.gz`; numeri: `reports/new_strategies/results.json`.

## Verdetto in breve

| strategia | trade nel periodo | frequenza | verdetto pre-registrato |
|---|---|---|---|
| BYBIT_POST_LIQ_REVERSAL | 6 in 2 anni (10 perp) | 0.26 trade/mese | **NON VALUTABILE** |
| ALPACA_IN_PLAY_MOMENTUM | 22 in 40 sedute | 12.2 trade/mese | **NON VALUTABILE** |

Nessuna delle due ha dati sufficienti per un giudizio statistico. I numeri **non** giustificano di per sé l'avvio dei
6 mesi di paper come validazione: per la strategia crypto il problema è strutturale (troppo rara, vedi sotto); per
quella azionaria serve prima un backtest su 2+ anni di barre 5m (script pronto, chiavi Alpaca sul server). Le due
strategie sono comunque installate nel lab in paper, senza capitale reale: raccolgono dati senza rischio.

## 1. BYBIT_POST_LIQ_REVERSAL (15m, 10 perp, 2024-11-10 → 2026-10-07)

Costi: taker 0.055% per lato + slippage 5 bps in ingresso (dopo uno spike), 2 bps in uscita, 5 bps sugli stop.

| variante | trade | win% | payoff | E/trade | E (R) | PF | Sharpe netto | Sharpe beta-adj | max DD | DSR | TP1% | uscite |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a_spec_active | 6 | 33.3% | 1.44 | -0.208% | -1.10 | 0.72 | -0.27 | — | -0.27% | 0.037 | 33% | STOP_LOSS 3, TIME_STOP 1, VWAP_TARGET 1, TRAILING_ATR 1 |
| b_spec_fixed | 6 | 50.0% | 2.06 | 0.642% | -0.92 | 2.06 | 0.54 | — | -0.19% | 0.218 | 0% | STOP_LOSS 3, FIXED_TP 2, MAX_HOLD 1 |
| c_mirror_active | 10 | 20.0% | 0.39 | -0.747% | -1.13 | 0.10 | -1.74 | — | -0.56% | 0.000 | 20% | STOP_LOSS 8, VWAP_TARGET 1, BREAKEVEN_STOP 1 |
| d_mirror_fixed | 10 | 20.0% | 0.65 | -0.694% | -0.98 | 0.16 | -1.71 | — | -0.53% | 0.000 | 0% | STOP_LOSS 8, FIXED_TP 2 |
| control_random | 6 | 50.0% | 1.60 | 0.305% | -0.80 | 1.60 | 0.36 | — | -0.31% | n/a | 50% | STOP_LOSS 2, VWAP_TARGET 2, TIME_STOP 1, TRAILING_ATR 1 |

### Imbuto dei segnali (variante a)

Su ogni barra 15m con spike ≥ 2.5 ATR (condizione necessaria) si valuta il resto della regola:

| esito | barre |
|---|---|
| FUNDING_NOT_EXTREME | 13773 |
| SPIKE_WRONG_DIRECTION | 637 |
| OI_NOT_COLLAPSING | 534 |
| NO_REABSORPTION | 147 |
| NO_FUNDING_DATA | 8 |
| **TRIGGERED** | **6** |

- **Il funding estremo è il filtro che decide**: il 91% degli spike cade fuori dal 5% estremo del funding a 30 giorni.
  Il funding Binance resta spesso fermo al valore base (0.01%), quindi molti print sono identici e il percentile
  supera 95 solo quando il funding si discosta davvero dal valore base.
- Con tutte e quattro le condizioni la strategia scatta **~3 volte l'anno su 10 simboli**: anche 6 mesi di paper
  produrrebbero 1-2 trade, cioè nessuna informazione. È il risultato principale: la specifica è troppo restrittiva
  per essere validata, sia sul passato sia in paper.
- Le 4 varianti (specifica / speculare × uscite attive / fisse) hanno tutte meno di 11 trade; il controllo casuale
  con le stesse uscite ne ha 6. Nessun confronto è informativo. PBO = 0.029 su 4 varianti: con così pochi trade non significa nulla.
- **Rischio per trade molto disomogeneo**: SL = estremo dello spike ± 0.25 ATR dà rischi da 0.03% (BTC, con costi
  ~0.2% il trade vale -7.4R) a 7.1% (DOGE). La media in R è quindi distorta; vale il rendimento %. Rifinitura
  proposta: rischio minimo 0.5 ATR e massimo 3 ATR.
- Riferimento passivo: BTC sullo stesso periodo +9.95%, Sharpe 0.34, max DD -53%. Riferimento strategie live attuali:
  la replica dei motori crypto del bot sul periodo nov 2025 → ott 2026 perde il 52% (Sharpe -2.97,
  `reports/METALABELING_KELLY_AUDIT.md`, branch `feat/quant-metalabeling-kelly`).

**Cosa rifinire (nuova pre-registrazione, conta come prova in più)**: percentile del funding 90/10 invece di 95/5,
OI z ≤ -1.5, timeframe 5m, universo più ampio (es. i 30 perp più liquidi) per arrivare ad almeno 100 eventi in 2 anni;
in alternativa sostituire il funding con il rapporto long/short dei top trader (disponibile nello stesso file metrics).

## 2. ALPACA_IN_PLAY_MOMENTUM (5m, 8 titoli, 2026-10-01 → 2026-11-25)

Dati Yahoo 5m: 40 sedute valutabili dopo 20 di riscaldamento per l'RVOL; giorni con almeno un titolo In Play: 17. Costi: spread + slippage 3 bps per lato, +3 bps sugli stop.

| variante | trade | win% | payoff | E/trade | E (R) | PF | Sharpe netto | Sharpe beta-adj | max DD | DSR | TP1% | uscite |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a_active | 22 | 36.4% | 1.78 | 0.009% | -0.76 | 1.02 | 0.07 | -0.36 | -0.36% | 0.445 | 32% | STOP_LOSS 9, TRAILING_ATR 7, EOD_FORCE_CLOSE 4, TIME_STOP 2 |
| b_fixed | 22 | 31.8% | 2.41 | 0.067% | -0.75 | 1.13 | 0.43 | -0.36 | -0.40% | 0.445 | 0% | STOP_LOSS 11, EOD_FORCE_CLOSE 6, FIXED_TP 5 |
| control_no_filter | 302 | 49.7% | 1.27 | 0.088% | 0.12 | 1.25 | 3.25 | 2.26 | -1.19% | n/a | 45% | TRAILING_ATR 134, STOP_LOSS 129, EOD_FORCE_CLOSE 27, TIME_STOP 12 |
| control_no_filter_fixed | 302 | 45.0% | 1.52 | 0.097% | 0.12 | 1.25 | 3.18 | 2.35 | -1.12% | n/a | 0% | STOP_LOSS 150, FIXED_TP 102, EOD_FORCE_CLOSE 50 |

- **22 trade in 40 sedute: NON VALUTABILE.** E ≈ 0 (+0.01%/trade), PF 1.02, Sharpe beta-adjusted negativo.
- **Il filtro In Play non migliora il controllo senza filtro** (stesse regole di ingresso/uscita su tutti gli 8 titoli,
  302 trade): E +0.09%/trade, PF 1.25, Sharpe 3.25 netto / 2.26 beta-adjusted. Ma il periodo è di sole 8 settimane
  e SPY ha perso il 6.2% (Sharpe -1.63): i numeri del controllo non sono generalizzabili.
- Nel controllo gli ingressi PULLBACK rendono in media +0.36%/trade (106 trade), gli ORB -0.06% (196): indizio, non
  prova, che il pullback sull'EMA9 sia la parte utile della regola di ingresso.
- **E in R distorta**: la regola "SL al lato opposto dell'opening range" produce, sui pullback vicini al bordo del
  range, rischi minuscoli (fino a 0.006% del prezzo, un trade a -15R). Il rendimento % è affidabile, la media in R no.
  Rifinitura proposta: rischio minimo pari a 0.5 ATR(5m).

## 3. Uscite attive contro uscite fisse (ablazione)

| campione | uscite attive (50% a 1.5R + BE + trailing + time-stop) | uscite fisse (TP 2R) |
|---|---|---|
| Bybit specifica | E -0.208%, PF 0.72, WR 33%, n 6 | E 0.642%, PF 2.06, WR 50%, n 6 |
| Alpaca In Play | E 0.009%, PF 1.02, WR 36%, n 22 | E 0.067%, PF 1.13, WR 32%, n 22 |
| Alpaca senza filtro (prova extra dichiarata) | E 0.088%, PF 1.25, WR 50%, n 302 | E 0.097%, PF 1.25, WR 45%, n 302 |

Sull'unico campione con numerosità sufficiente (302 trade) le uscite attive **non aggiungono valore atteso** rispetto
al TP fisso a 2R: cambiano la forma della distribuzione (più vincenti piccoli, meno TP pieni) ma non l'aspettativa.

## 4. Autopsia del journal esistente

`quant/analyze_existing_journal.py` (sola lettura) raggruppa trade chiusi e segnali shadow per motore, broker, ora
NY/Roma, VIX e regime macro, e i trade del lab per motivo di uscita. **La copia locale di `data/market_sentinel.db` è
vuota** (creata dalla suite di test): il journal reale è sul server Oracle. Comando da eseguire lì:
`python -m quant.analyze_existing_journal --db /app/data/market_sentinel.db --out reports/JOURNAL_AUTOPSY.md`.

## 5. Cosa fare adesso

1. **Alpaca**: rieseguire il backtest su 2+ anni di barre 5m dal server Oracle (le chiavi Alpaca sono lì):
   `python -m quant.research.new_strategies.run --only alpaca --alpaca-source alpaca --start 2024-06-01 --end 2026-11-25`.
   È l'unico modo per valutare davvero il filtro In Play. Se in quel test non batte il controllo senza filtro, va scartato.
2. **Bybit**: con la specifica attuale non è validabile in tempi utili; se interessa, pre-registrare una versione meno
   restrittiva (sopra) e testarla sugli stessi dati prima di qualsiasi paper.
3. Il lab le fa già girare in paper (nessun capitale reale), con ogni segnale e ogni scarto nel journal: costa poco e
   misura fill e costi reali. Promozione a capitale reale solo con i criteri di `docs/LAB.md`.

## 6. Versione 1.1 (pre-registrata in `reports/PREREG_NEW_STRATEGIES_V1_1.md`, prima di ogni run)

Modifiche: stop minimo 0.5 ATR per entrambe; Bybit funding 90/10, OI z ≤ -1.5, stop massimo 6 ATR, 20 perp.

### BYBIT_POST_LIQ_REVERSAL v1.1 (20 perp, 2 anni)

| variante | trade | win% | payoff | E/trade | E (R) | PF | Sharpe netto | Sharpe beta-adj | max DD | DSR | TP1% | uscite |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a_spec_active | 24 | 50.0% | 1.64 | 0.364% | -0.11 | 1.64 | 0.53 | — | -0.39% | 0.782 | 50% | STOP_LOSS 11, TRAILING_ATR 7, VWAP_TARGET 3, BREAKEVEN_STOP 2, TIME_STOP 1 |
| b_spec_fixed | 24 | 41.7% | 2.71 | 0.608% | -0.17 | 1.93 | 0.70 | — | -0.47% | 0.876 | 0% | STOP_LOSS 14, FIXED_TP 9, MAX_HOLD 1 |
| control_random | 24 | 41.7% | 0.84 | -0.177% | -0.44 | 0.60 | -0.68 | — | -0.58% | n/a | 21% | STOP_LOSS 10, TIME_STOP 9, TRAILING_ATR 3, BREAKEVEN_STOP 1, VWAP_TARGET 1 |

Frequenza: 1.01 trade/mese. Verdetto pre-registrato: **NON VALUTABILE** (meno di 30 trade).

- 24 trade: E +0.36%/trade con uscite attive (errore standard 0.39%, t = 0.92) e +0.61% con TP fisso 2R
  (t = 1.21); il controllo casuale con le stesse uscite fa -0.18%. Direzione incoraggiante, **non significativa**.
- Ritmo ~1 trade/mese su 20 simboli: 6 mesi di paper ≈ 6 trade. Servono ~2 anni di paper o un universo più ampio
  per arrivare a 30-50 trade; la v1.1 è nel lab proprio per accumularli senza rischio.
- Ancora una volta il TP fisso 2R non è peggiore delle uscite attive.

### ALPACA_IN_PLAY_MOMENTUM v1.1 (Yahoo 40 sedute, descrittivo)

| variante | trade | win% | payoff | E/trade | E (R) | PF | Sharpe netto | Sharpe beta-adj | max DD | DSR | TP1% | uscite |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a_active | 22 | 36.4% | 1.39 | -0.116% | -0.25 | 0.79 | -0.92 | -1.45 | -0.50% | 0.257 | 32% | STOP_LOSS 11, TRAILING_ATR 6, TIME_STOP 2, EOD_FORCE_CLOSE 2, BREAKEVEN_STOP 1 |
| b_fixed | 22 | 36.4% | 1.85 | 0.034% | -0.13 | 1.06 | 0.22 | -0.46 | -0.41% | 0.391 | 0% | STOP_LOSS 13, FIXED_TP 6, EOD_FORCE_CLOSE 3 |
| control_no_filter | 302 | 50.0% | 1.25 | 0.090% | 0.13 | 1.25 | 3.29 | 2.32 | -1.19% | n/a | 45% | TRAILING_ATR 134, STOP_LOSS 128, EOD_FORCE_CLOSE 27, TIME_STOP 12, BREAKEVEN_STOP 1 |
| control_no_filter_fixed | 302 | 45.4% | 1.51 | 0.100% | 0.13 | 1.25 | 3.26 | 2.45 | -1.12% | n/a | 0% | STOP_LOSS 149, FIXED_TP 103, EOD_FORCE_CLOSE 50 |

- Con lo stop minimo la media in R diventa coerente (-0.25R invece di -0.76R); E -0.12%/trade su 22 trade,
  sotto il controllo senza filtro (+0.09%): `in_play_beats_no_filter` = False.
- Decisione rimandata al test su 2 anni di barre Alpaca (Fase 7 di `docs/ANTIGRAVITY_PROMPT_AUTONOMO.md`), che
  applica automaticamente la regola pre-registrata (filtro scartato se non batte il controllo).

## Avvertenze

- Bybit è geo-bloccato da qui: prezzi, funding e open interest sono di Binance (proxy di ricerca); su Bybit i valori
  differiscono (soprattutto funding e OI). Nel lab su Oracle si usano gli endpoint Bybit v5 con fallback Binance.
- Nessun parametro è stimato sui dati: l'intero campione è fuori campione rispetto ai parametri; le metriche per
  trimestre sono in `results.json`.
- Prove dichiarate: v1.0 7 (4 Bybit + 2 Alpaca + 1 extra), v1.1 4, test Alpaca 2 anni 4: totale 15.

