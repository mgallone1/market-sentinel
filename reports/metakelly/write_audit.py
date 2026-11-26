import sys; sys.path.insert(0, '.')
from quant.research.metakelly.report import write

eq = """### Lettura (azioni)
- **L'etichetta pre-registrata è degenere sulle azioni**: i motori live fissano TP = 3 x SL (TP mediano ~3.9%, minimo 2.7%)
  e la barriera temporale è la chiusura forzata della stessa seduta (durata media 2.7-4.3 barre 1h). Esiti su 1704 eventi:
  TP **3**, SL 179, uscita a tempo 1522 (89%). Con un tasso di y = 1 dello 0.18% il meta-modello non ha nulla da imparare,
  p̂ ≈ 0.002, f* < 0 per ogni candidato e **nessuna configurazione C apre un trade**. Il protocollo non viene modificato a
  posteriori: l'esito è SCARTATO per assenza di informazione nell'etichetta, non per un modello cattivo. Il PBO = 1.000
  è un artefatto: le 6 configurazioni hanno tutte rendimento identicamente nullo.
- **Implicazione operativa (fatto, non ipotesi)**: sul bot Alpaca il TP 3R è praticamente irraggiungibile entro la chiusura;
  il P&L dei trade azionari è quasi interamente determinato dall'uscita a tempo (8 minuti prima della campanella) e dallo stop.
  È coerente con `fp_p_tp` ≈ 0 della telemetria e con il gate di fine seduta.
- **Baseline A (motori live replicati)**: Sharpe netto 0.93, beta-adjusted 1.05, PF 1.24, DSR 0.93 (n_trials = 1, quindi
  ottimistico: le configurazioni baseline riportate sono 3), contro B1 "sempre long" con le stesse uscite: -19%, Sharpe -0.99.
  È il primo segnale non negativo dei motori azionari, ma è su ~2 anni OOS, con filtri ciclici/sentiment/Time Machine neutralizzati
  e senza ratchet: va verificato sul journal live prima di trarre conclusioni.
"""

cr = """### Lettura (crypto)
- **Calibrazione**: il meta-modello L2 batte il base rate in modo significativo (C = 0.01: Δ log-loss -0.0060, t = -2.65;
  Δ Brier -0.0019, t = -3.14, 6 fold), criterio 1 soddisfatto per tutti i C. Il miglioramento è piccolo in valore assoluto
  (log-loss 0.505 vs 0.511).
- **`fp_p_tp` con drift stimato è calibrato PEGGIO del base rate (t = +3.2)**; le versioni a drift nullo no (RS a drift nullo
  è la migliore delle quattro, non significativa). È la conferma empirica dell'effetto Jensen del drift rumoroso previsto
  analiticamente: per la decisione "TP raggiungibile" va usata la versione a drift nullo.
- **Economia**: con R netto ≈ 2.4 il break-even è p ≈ 0.29; p̂ supera la soglia solo nel 4-6% dei casi, quindi il Kelly
  frazionario fa 1-60 trade (< 100), con esposizione massima 2-6%. Expectancy per trade positiva (+0.27…+0.61%) e sopra sia il
  baseline (-0.15%) sia i controlli random@ (negativi), ma DSR beta-adjusted 0.66-0.86 e PBO 0.62: **non distinguibile dal caso**.
- **Baseline A (motori live replicati) fortemente negativo**: -52% sul periodo OOS, Sharpe -2.97, PF 0.83, con
  LIQUIDITY_SWEEP_MR il peggiore (Sharpe -4.8). Avvertenze di fedeltà: CVD approssimato con il volume taker, OBI neutro,
  ingresso al close invece del fill maker, nessun ratchet; B1 "sempre long" è comunque peggiore (-90%). Da confrontare con il
  journal Bybit live prima di qualsiasi decisione.
"""

general = """## Avvertenze comuni
- Replica dei motori live con input non ricostruibili neutralizzati (OBI, cicli Hurst/Migliorino, sentiment, Time Machine,
  gate di fine seduta probabilistico) e senza ratchet dinamico: i baseline A misurano le regole di ingresso con uscite SL/TP/tempo,
  non il bot esatto.
- ORB_BREAKOUT_15M escluso: solo 60 giorni di barre 5m disponibili.
- DSR delle configurazioni C con n_trials = 6 per universo (12 in totale); i baseline A e B riportano DSR con n_trials = 1.
- PF excess di B1 non calcolato (beta per trade non stimato per il benchmark): usare lo Sharpe beta-adjusted.
- P&L giornaliero su base realizzata (data di chiusura del trade); le azioni sono flat a fine seduta, le crypto tengono ≤ 24 h.
- Un errore tecnico (confronto di timestamp con/senza fuso) ha interrotto il primo run crypto prima di produrre risultati;
  corretto senza cambiare il protocollo e rilanciato. Nessun altro run è stato eseguito.

## Conclusione
H0 non è rifiutata su nessuno dei due universi: **nessuna configurazione è promuovibile al paper lab**. Risultati utili emersi:
(1) sulle azioni il TP 3R non è raggiungibile entro la chiusura forzata: l'etichetta e, di fatto, il target live vanno ripensati;
(2) sulle crypto il meta-modello migliora la calibrazione in modo statisticamente significativo ma il vantaggio è troppo piccolo
per il sizing Kelly con R ≈ 2.4; (3) la probabilità Fokker-Planck con drift stimato è peggio del base rate, a drift nullo no.
Eventuali varianti (etichetta "trade in profitto", TP raggiungibile in seduta, sizing diverso) richiedono una nuova
pre-registrazione e contano come prove aggiuntive.
"""
print(write({"eq": eq, "cr": cr, "general": general}))
