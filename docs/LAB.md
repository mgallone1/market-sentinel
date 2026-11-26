# Lab di paper trading

Il lab fa girare in parallelo piu' strategie in **paper** (nessun ordine reale), registra ogni decisione con le sue
motivazioni, esegue con lo stesso modello di costi dei backtest e ogni settimana confronta il live con le attese
della ricerca. Serve a misurare cio' che il backtest non puo' misurare: fill reali, costi, deriva dei parametri.
Codice: `quant/lab/` (contratti in `base.py`), strategie in `quant/lab/strategies/`. Si disattiva con `LAB_ENABLED=false`;
`LAB_STRATEGIES=funding_carry,tsmom_monthly` ne seleziona un sottoinsieme.

## Le 4 strategie validate + 2 candidate (tutte v1.0, senza leva: gross <= 1.0)
| Nome | Regole | Perche' |
|---|---|---|
| `tsmom_monthly` (100k, cron 21:15 UTC lun-ven) | TSMOM 1/3/12 mesi su 21 ETF + BTC/ETH, peso inverso alla vol, vol target 10%, solo long, ribilancia solo l'ultimo giorno di borsa del mese; altrimenti "hold". Gross capato a 1 | Unica variante KEEP del test pre-registrato (Sharpe 0.90 lordo leva 1.47). Attese mensili derivate dal report e scalate per il taglio della leva |
| `brent_wti_grid` (50k, 20:45 UTC) | Griglia sullo spread futures BZ=F-CL=F: z60, passo 0.25 std, max 8 unita' per lato, kill |z|>4, ogni unita' chiude a +1 passo. Segnale di ieri agito oggi (lag 1g). 1 unita' = 1 contratto/gamba (1000 bbl), costo assunto 10 $/unita'/lato | Residuo piu' consistente della ricerca (Sharpe 0.54 con esecuzione il giorno dopo, DSR 0.40: non confermato). La versione "stessa chiusura" era un artefatto |
| `funding_carry` (100k, 00:10/08:10/16:10 UTC) | Short perp + long spot Bybit, nozionale uguale, su BTC/ETH/SOL/XRP/DOGE. Entra se media 9 print annualizzata > 10%, esce < 3%. Gamba 0.5/N per simbolo attivo | Carry delta-neutral: incassa il funding. Nessuna attesa numerica nei report: misurarla |
| `crypto_breakout_4h` (100k, ogni 4h) | Donchian 96 barre 4h long/short su 10 perp, 1/10 del capitale per segnale, uscita SL 1.5 ATR / TP 3 ATR / 30 barre gestita dalla strategia | Baseline primaria (expectancy +0.46%/trade, PF 1.18) ma NO EDGE come meta-labeling; il fill maker NON e' modellato dal paper (riempie all'ultimo prezzo): va misurato |

### Strategie candidate (dal 2026-11-26, v1.0, paper only, nessun capitale reale)
| Nome | Regole | Stato della ricerca |
|---|---|---|
| `bybit_post_liq_reversal` (100k, ogni 15 min) | `BYBIT_POST_LIQ_REVERSAL`: funding al 95°/5° percentile 30g + spike ≥ 2.5 ATR nella direzione dell'affollamento + crollo OI (z ≤ −2 su 48h) + barra di riassorbimento; SL estremo spike ± 0.25 ATR, 50% a 1.5R e stop a breakeven, runner a VWAP 4h o trailing 1.5 ATR, time-stop 6 barre < 0.5R | Backtest 2 anni: 6 trade su 10 perp → NON VALUTABILE (`reports/NEW_STRATEGIES_POTENTIAL_AUDIT.md`) |
| `alpaca_in_play_momentum` (100k, ogni 5 min in sessione) | `ALPACA_IN_PLAY_MOMENTUM`: RVOL 09:30-09:45 ≥ 2 e (gap ≥ 1.5% o residuo vs SPY > 2σ), max 2 titoli; ORB 15m o pullback EMA9; SL lato opposto dell'OR (max 1.5 ATR), 50% a 1.5R e breakeven, trailing 1.5 ATR fino alla chiusura forzata −8 min, time-stop 45 min < 0.4R | 40 sedute Yahoo: 22 trade → NON VALUTABILE; ripetere con barre 5m Alpaca su 2+ anni |

Ogni segnale (aperto, chiuso o scartato con motivo) e' scritto anche nel journal del bot (`data/market_sentinel.db`,
tabella `lab_strategy_trades`) con `strategy_version`, `ruleset_version` (= `STRATEGY_RULESET_VERSION`) e diagnostica
(`rvol`, `gap_pct`, `idio_ret`, `funding_pct`, `oi_delta_z`, motivo di uscita). `/lab` e la dashboard mostrano E, win rate,
payoff, profit factor, max drawdown e distribuzione delle uscite; `/lab_log alpaca_in_play_momentum` gli ultimi segnali.

Lo stato (griglia, carry, posizioni breakout) e' ricostruito a ogni esecuzione dallo storico: non serve persistenza.
La griglia scrive solo uno snapshot di audit in `$LAB_STATE_DIR` (default `data/lab_state`).

## Dove finiscono i log
SQLite locale (default) oppure Supabase (`SUPABASE_URL`/`SUPABASE_KEY`, schema in `quant/lab/sql/supabase_lab.sql`).
Tabelle: `decisions` (target, motivazioni, feature), `fills`, `marks`, `reviews`, posizioni e cassa. Ogni riga e'
chiave `(strategia, versione)`: cambiare versione separa i log.

## Come leggere /lab e la review
- `/lab`: scorecard per strategia (equity, rendimento, drawdown, live vs attese).
- `/lab_log [strategia]`: ultime 10 decisioni con nota e motivazioni dei target.
- Review settimanale (domenica 18:00 Roma): metriche live contro `expected` della ricerca, costi osservati contro
  assunti, lezioni. Uno Sharpe live molto sotto l'atteso con pochi periodi e' rumore: guardare lo z-score, non il numero.

## Come iterare
Cambia le regole -> incrementa `version` nella classe -> lascia girare -> confronta le review di v1.0 e v1.1.
Ogni variante provata e' una prova in piu' per il DSR: annotarla. Non ritoccare soglie sui dati live.

## Criteri di promozione a denaro reale (pre-registrati)
1. almeno 6 mesi di paper;
2. Sharpe live non significativamente sotto l'atteso (z > -1);
3. costi misurati <= costi assunti (per il breakout: fill maker reali verificati);
4. approvazione esplicita di Michele.
Fino ad allora il lab non puo' inviare ordini reali.
