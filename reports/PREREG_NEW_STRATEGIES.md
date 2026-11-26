# Pre-registrazione: BYBIT_POST_LIQ_REVERSAL e ALPACA_IN_PLAY_MOMENTUM

Data: 2026-11-26. Branch `feat/strategies-inplay-liquidation` (da `main` @ 3fd90b3). Scritto e committato **prima** di
qualsiasi backtest. Le regole e i parametri numerici sono quelli della specifica ricevuta; qui sono fissate anche le
scelte interpretative dove la specifica lascia margine. Dopo il commit nessun parametro verrà cambiato alla luce dei
risultati; ogni variante aggiuntiva sarà dichiarata come prova in più. Codice: `services/strategy_engines_service.py`
(sezione 8, solo lab/shadow) e `quant/research/new_strategies/`.

Nessun parametro viene stimato sui dati: l'intero campione è fuori campione rispetto alla scelta dei parametri. La
"validazione walk-forward" consiste quindi nel riportare le metriche per sotto-periodi (trimestri) per verificarne la
stabilità, oltre al totale.

## 1. BYBIT_POST_LIQ_REVERSAL
- **Dati**: perpetui USDT BTC, ETH, SOL, XRP, LINK, AVAX, ADA, DOGE, SUI, NEAR; barre 15m 2024-11-01 → 2026-11-01
  (Binance Vision come proxy di Bybit, geo-bloccato da qui); funding storico Binance (print ogni 8h); open interest
  storico Binance Vision `metrics` (snapshot ogni 5 minuti, valore alla fine di ogni barra 15m).
- **Timeframe**: 15m (la specifica ammette 5m o 15m; si sceglie 15m, coerente con il ciclo Bybit del bot).
- **Ingresso** (barra di conferma i, spike = barra i-1, tutto point-in-time):
  1. percentile del funding più recente (≤ fine barra i) tra i print degli ultimi 30 giorni: ≥ 95 → setup SHORT,
     ≤ 5 → setup LONG;
  2. spike: range della barra i-1 ≥ 2.5 × ATR14 calcolato sulla barra **precedente** allo spike (misura lo spike
     rispetto alla volatilità pre-esistente); direzione dell'affollamento = rialzista (close > open) per il setup SHORT,
     ribassista per il setup LONG;
  3. variazione % dell'OI sulla barra di spike, z-score ≤ −2 rispetto alle variazioni 15m delle 48 ore precedenti
     (192 barre, esclusa la corrente);
  4. riassorbimento: la barra i chiude dentro il range precedente (sotto il massimo delle 12 barre prima dello spike per
     lo SHORT, sopra il minimo per il LONG), con ombra nella direzione dello spike ≥ 50% del proprio range e volume
     inferiore a quello dello spike. Ingresso al close della barra i.
- **Uscite attive**: SL = estremo dello spike ± 0.25 ATR; 50% a +1.5R e stop a breakeven + fee andata/ritorno; il restante
  50% esce al tocco del VWAP rolling a 4 ore (16 barre, solo se oltre il livello TP1) oppure con trailing 1.5 ATR
  dall'estremo favorevole raggiunto, quello che arriva prima; time-stop alla chiusura della 6ª barra se il massimo
  favorevole non ha raggiunto +0.5R (e TP1 non è scattato). Tenuta massima di sicurezza 96 barre (24 h), uscita MAX_HOLD.
  Un solo trade aperto per simbolo.
- **Costi**: taker 0.055% per lato (0.11% andata/ritorno) + slippage 5 bps sull'ingresso (barra di conferma dopo uno spike),
  2 bps sulle uscite normali, 5 bps sugli stop.
- **Varianti dichiarate (4 prove)**: (a) specifica, uscite attive; (b) specifica, uscite fisse tradizionali (stesso SL,
  TP unico a 2R, nessun parziale/trailing/time-stop, tenuta massima 96 barre); (c) interpretazione speculare della
  direzione (funding ≥ 95 + spike ribassista → LONG, cioè rimbalzo dopo la liquidazione dei long affollati; ≤ 5 + spike
  rialzista → SHORT), uscite attive; (d) come (c) con uscite fisse. La (c) esiste perché la direzione "dell'affollamento"
  nella specifica ammette due letture economiche; il verdetto principale riguarda (a).
- **Confronti**: ingressi casuali con le stesse uscite (stesso numero di trade, stessi simboli e lati, istanti casuali,
  seed 0); BTC passivo. Per le strategie live attuali si rimanda alla replica in `reports/METALABELING_KELLY_AUDIT.md`
  (branch `feat/quant-metalabeling-kelly`).

## 2. ALPACA_IN_PLAY_MOMENTUM
- **Dati**: NVDA, AAPL, MSFT, TSLA, AMZN, META, GOOGL, AMD + SPY, barre 5m Yahoo: disponibili **solo gli ultimi ~60 giorni**
  (~40 sedute). Con 20 sedute di warm-up per l'RVOL restano ~20 sedute valutabili: **campione insufficiente per
  qualsiasi inferenza**, dichiarato in anticipo. Il codice accetta anche barre 5m dall'API dati Alpaca (`--source alpaca`,
  richiede le chiavi sul server Oracle) per ripetere il test su 2+ anni senza modifiche.
- **Selezione alle 09:45 NY**: RVOL = volume 09:30–09:45 / media dello stesso intervallo nelle 20 sedute precedenti ≥ 2.0;
  e (|gap apertura vs close precedente| ≥ 1.5% oppure |residuo vs SPY del movimento close precedente → 09:45| > 2σ, con β
  dai rendimenti giornalieri close-to-close fino a 60 sedute precedenti e σ dello stesso residuo nelle 20 sedute precedenti).
  Massimo 2 titoli per RVOL; nessun titolo qualificato → nessun ingresso. Direzione = segno del gap (o del residuo se
  qualifica solo il residuo).
- **Ingresso**: prima barra 5m, completata dopo le 09:45 e almeno 30 minuti prima della chiusura (calendario NYSE,
  chiusure anticipate incluse), che chiude oltre l'opening range nella direzione (ORB) oppure primo pullback ordinato:
  minimo/massimo che tocca l'EMA9 5m, chiusura oltre l'EMA9 nella direzione, candela nella direzione e close precedente
  già dal lato giusto dell'EMA9. Un trade per titolo al giorno.
- **Uscite attive**: SL = lato opposto dell'opening range, limitato a 1.5 × ATR14(5m); 50% a +1.5R e stop a breakeven +
  fee; trailing 1.5 ATR fino alla chiusura forzata (ultima barra completata entro chiusura − 8 minuti); time-stop alla
  chiusura della 9ª barra (45 minuti) se il massimo favorevole non ha superato +0.4R.
- **Costi**: spread + slippage 3 bps per lato, +3 bps sugli stop; commissioni 0.
- **Varianti dichiarate (2 prove + 2 controlli)**: (a) uscite attive; (b) uscite fisse (stesso SL, TP 2R, uscita a fine
  seduta). Controlli: stessa regola di ingresso e uscite **senza filtro In Play** (tutti gli 8 titoli ogni giorno,
  direzione = primo lato dell'opening range rotto) per misurare il valore del filtro; benchmark beta-adjusted
  R_strat − β̂ R_SPY (β̂ rolling sui rendimenti giornalieri, stimato fino al giorno precedente).

## 3. Metriche e criteri
Per ogni variante: numero di trade e frequenza, win rate, payoff (AvgWin/AvgLoss), E per trade (netta), profit factor,
Sharpe netto e beta-adjusted (giornalieri annualizzati), max drawdown, DSR (n_trials = numero di varianti della strategia:
4 Bybit, 2 Alpaca), PBO (CSCV tra le varianti, solo se il numero di giorni lo consente), distribuzione dei motivi di uscita,
metriche per trimestre.

**Raccomandazione di avvio dei 6 mesi di paper** (per strategia, sulla variante principale (a)) se tutti veri:
1. almeno 100 trade nel periodo testato;
2. E netta > 0 e profit factor > 1.10;
3. DSR > 0.95 (beta-adjusted per Alpaca);
4. E > controllo casuale (Bybit) / > controllo senza filtro (Alpaca);
5. nessun trimestre con perdita superiore al 50% del profitto totale (stabilità).
Se n < 30: **NON VALUTABILE** (si raccomanda di raccogliere dati, non di dedurne qualcosa). L'avvio in paper non è
comunque un via libera al capitale reale: valgono i criteri di promozione di `docs/LAB.md`.
