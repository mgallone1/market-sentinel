# Pre-registrazione: Meta-Labeling L2 + Kelly frazionario contro benchmark beta-adjusted

Data: 2026-11-26. Branch `feat/quant-metalabeling-kelly` (da `main` @ 3fd90b3).
Questo documento è scritto e committato **prima** di qualsiasi backtest dell'esperimento. Dopo il commit
nessuna soglia, finestra, griglia o regola verrà modificata alla luce dei risultati. Qualsiasi run aggiuntivo
sarà dichiarato come prova in più nel report. Codice: `quant/research/metakelly/`.

## 1. Ipotesi
- **H1**: un meta-classificatore logistico L2, addestrato point-in-time sugli esiti triple-barrier dei candidati
  generati dai motori live, con sizing Kelly frazionario continuo, produce rendimenti OOS netti **e**
  beta-adjusted superiori alle strategie baseline e al benchmark, con DSR > 0.95 e PBO < 0.20, e probabilità
  meglio calibrate (Brier e log-loss) del base rate.
- **H0**: nessun miglioramento: le probabilità del meta-modello non battono il base rate e/o il rendimento
  beta-adjusted non è positivo.

Priore dichiarato: basso (`reports/SETUPS_SUMMARY.md`, `reports/HORIZON_SUMMARY.md`: nessun meta-labeling
finora ha battuto il base rate in modo significativo).

## 2. Universi e dati (analizzati separatamente, mai aggregati)
- **EQ — azioni Alpaca**: NVDA, AAPL, MSFT, TSLA, AMZN, META, GOOGL, AMD; benchmark SPY. Barre 1h Yahoo
  (sessione regolare), 2023-12-29 → 2026-11-25 (massimo storico 1h disponibile). VIX giornaliero (^VIX)
  per bias macro e VRP, usato solo dal giorno successivo (chiusura di ieri). Costi: preset `alpaca_equity`
  (slippage 2 bps per lato, stop slippage aggiuntivo 3 bps) → costo andata/ritorno 0.04%, 0.07% se esce a stop.
- **CR — perpetui crypto Bybit** (dati Binance Vision come proxy di ricerca, Bybit è geo-bloccato da qui):
  BTC, ETH, SOL, XRP, LINK, AVAX, ADA, DOGE, SUI, NEAR (USDT perp); benchmark BTCUSDT. Barre 15m,
  2024-11-01 → 2026-11-01. Costi: preset `bybit_perp` taker 0.055% per lato + slippage 2 bps per lato
  (+3 bps su stop) → 0.15% andata/ritorno, 0.18% se esce a stop; funding non incluso nell'etichetta (orizzonte ≤ 24h).

## 3. Stadio 1 — generatore di candidati (motori live, point-in-time)
I candidati sono prodotti chiamando **le funzioni live** di `services/strategy_engines_service.py`
(`regime_router`, `engine_trend_pullback_4h1d`, `engine_liquidity_sweep_mr`, `engine_intraday_momentum`)
su finestre di sole barre chiuse fino a t (nessun dato futuro), con la stessa scelta del miglior punteggio
per simbolo e un solo trade aperto per simbolo alla volta, come nel bot.
- **EQ**: ciclo orario; motori INTRADAY_MOMENTUM (1h, `is_equities=True`) e TREND_PULLBACK_4H (4h/1h);
  bias macro = replica di `_get_equities_macro_bias` (SPY daily EMA20/50 + 1h EMA20 + regole VIX su
  chiusura e variazione di ieri); `vix_unfavorable` come nel bot. Nessun ingresso a meno di 30 minuti
  dalla chiusura (regola live).
- **CR**: ciclo 15m; motori INTRADAY_MOMENTUM (15m), LIQUIDITY_SWEEP_MR (15m), TREND_PULLBACK_4H (4h/1h);
  bias macro = `classify_btc_bias` + `hysteresis_bias` del bot su BTC 4h/1h; funding = ultimo funding
  pubblicato (≤ t).
- **Input non ricostruibili storicamente, impostati a valori neutri e dichiarati**: order book (OBI = 0),
  cicli Hurst/Migliorino (`cycle_data = {}`: vincolo LIBERO, nessun tempo), sentiment fondamentale (non
  applicato), filtro Time Machine e gate di fine seduta probabilistico (non applicati: sono oggetto di
  valutazione separata). CVD crypto approssimato con il rapporto taker-buy/taker-sell dell'ultima barra 15m.
- **ORB_BREAKOUT_15M è escluso**: richiede barre 5m, disponibili solo per gli ultimi 60 giorni (≈ 40 sedute),
  insufficienti per addestramento e test. Viene dichiarato, non stimato.
- Ingresso al close della barra di segnale (anche per i motori che nel bot usano ordini limite: il fill maker
  non è modellato).

## 4. Etichette triple-barrier
SL e TP = `sl_pct`, `tp_pct` restituiti dal motore. Barriera temporale:
- EQ: chiusura forzata 8 minuti prima della fine della seduta del giorno di ingresso (16:00 ET o 13:00 ET nelle
  chiusure anticipate) → uscita al close dell'ultima barra 1h completata entro quell'orario;
- CR: 96 barre (24 h).
SL verificato prima del TP nella stessa barra. `y = 1` se il TP è toccato prima dello SL e prima di T_end
(il TP netto dei costi è sempre positivo), altrimenti `0`. Rendimento del trade = TP − costi, −SL − costi
(stop), oppure mark-to-market − costi a T_end.

## 5. Stadio 2 — meta-classificatore
`Pipeline(StandardScaler, LogisticRegression(penalty="l2", C, solver="lbfgs", max_iter=2000))`, entrambi
fittati **solo** sugli eventi di train del fold (dopo purging ed embargo). Feature (point-in-time a t):
- `fp_p_tp_zero_drift`, `fp_p_tp_rs_zero_drift`, `fp_p_tp_bayes`: prima passata Fokker-Planck in forma
  chiusa con le barriere del trade e orizzonte = barre fino a T_end; varianza close-to-close / Rogers-Satchell
  sulle ultime 500 barre; drift con shrinkage empirical-Bayes (SR0 = 0.4, barre/anno: 24/7 crypto,
  252 x 6.5 h azioni);
- `idio_z_drift`, `idio_cs_rank` (solo EQ): residuo ortogonale vs SPY su 140 barre 1h e rango tra gli 8 titoli;
- `ofi_bvc_short` (15 barre), `ofi_bvc_med` (60 barre): Bulk Volume Classification;
- `vrp_spread` (solo EQ): VIX di ieri / 100 − volatilità realizzata SPY sulle ultime 5 sedute;
- `session_frac_left` (solo EQ): minuti alla chiusura / 390;
- `side` (+1/−1) e indicatori del motore (one-hot): il meta-modello deve sapere quale scommessa valuta.
NaN → mediana del train del fold (imputazione fittata nel fold).

## 6. Validazione
Walk-forward **espansivo** con purging ed embargo sugli eventi:
- EQ: primo train 12 mesi, poi blocchi di test di 3 mesi; CR: primo train 12 mesi, test di 2 mesi.
- Purging: esclusi dal train gli eventi con fine etichetta t1 ≥ inizio test.
- Embargo: esclusi dal train anche gli eventi con t0 > inizio test − durata massima del trade
  (EQ: 1 seduta; CR: 24 h).
- Il fold di test non contribuisce mai allo scaler, all'imputazione o al modello.

## 7. Sizing Kelly frazionario
Per ogni candidato OOS: `R_i = (TP_i − costo) / (SL_i + costo_stop)`, `f* = (p̂ R − (1 − p̂)) / R`,
`w = clip(c · f*, 0, w_max)` con `w_max = 0.10` (la size base live). Se `f* ≤ 0` il trade non si fa.
Vincolo di portafoglio: la somma dei pesi aperti non supera 0.70; un nuovo trade riceve
`min(w, 0.70 − aperto)` e viene saltato se il residuo è < 0.01.

## 8. Configurazioni (numero di prove dichiarato)
Griglia: `C ∈ {0.01, 0.1, 1.0}` × `c ∈ {0.15, 0.25}` = **6 configurazioni per universo, 12 in totale**.
DSR calcolato con `n_trials = 6` per universo (varianza degli Sharpe tra le 6); il conteggio complessivo (12) va
considerato nella lettura. PBO con CSCV sulla matrice dei rendimenti giornalieri delle 6 configurazioni.

Confronti (stesse finestre OOS):
- **A — baseline**: tutti i candidati del motore, size fissa 0.10, cap 0.70 (come il bot); anche per motore.
- **B — benchmark**: B1 "sempre long" con le stesse uscite (a ogni barra di ciclo con simbolo libero, long con
  SL/TP del motore momentum e la stessa T_end, size 0.10, cap 0.70); B2 passivo SPY (EQ) / BTC (CR).
- **C — meta-labeling + Kelly**: le 6 configurazioni; controllo casuale con lo stesso numero di trade accettati
  e gli stessi pesi permutati (`random@C`).

## 9. Benchmark beta-adjusted
Rendimenti giornalieri realizzati della strategia (P&L dei trade chiusi quel giorno, pesati). Beta di portafoglio
`β̂_t` = OLS rolling su 60 giorni (minimo 20) dei rendimenti della strategia su quelli del benchmark, stimato
con dati fino a t−1. `R_excess,t = R_strat,t − β̂_t · R_bench,t` (i costi sono già nei rendimenti netti).
Per trade: `r_excess,i = r_i − side_i · β̂_sym,i · R_bench[t0,t1]`, con β̂_sym dalle 140 barre prima
dell'ingresso. Profit Factor, Sharpe, DSR e PBO sono riportati sia sui rendimenti netti sia su quelli in eccesso.

## 10. Criteri di promozione (tutti richiesti, per universo, sulla migliore delle 6 configurazioni per log-loss)
1. Log-loss **e** Brier OOS inferiori al base rate del train, con differenza per fold appaiata t ≤ −2 per entrambi;
2. DSR (rendimenti beta-adjusted) > 0.95;
3. PBO < 0.20;
4. rendimento beta-adjusted cumulato OOS > 0 al netto dei costi e Sharpe beta-adjusted > baseline A;
5. expectancy per trade > `random@C` e > baseline A;
6. almeno 100 trade OOS.
Esito: **PROMUOVIBILE AL PAPER LAB** se 1–6 sono veri, altrimenti **SCARTATO**. In nessun caso l'esito modifica
il bot live: la promozione significa solo l'ingresso nel lab paper con le regole di `docs/LAB.md`.

## 11. Calibrazione (riportata, non usata per la promozione)
Brier e log-loss OOS di: base rate, p̂ del meta-modello (3 valori di C), `fp_p_tp` (drift stimato),
`fp_p_tp_zero_drift`, `fp_p_tp_rs_zero_drift`, `fp_p_tp_bayes`.

## Riproducibilità
`python -m quant.research.metakelly.run --universe eq|cr` → `reports/metakelly/<universo>/results.json`;
report finale `reports/METALABELING_KELLY_AUDIT.md`. Seed 0 per il controllo casuale.
