# Setup day-trader come strategie primarie: valutazione pre-registrata

Fonte regole: `day_trader/trader-scanner/scan.py` (daily) e `trader-entry/entry.py` (orb), portate in `quant/strategies/setups.py`. Nessun tuning: un run per setup, parametri fissati prima di vedere i dati.

## Daily, equities 1d (SPY,QQQ,AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,JPM; 2010-01-01..2026-11-24)

ExitRules: stop 2 ATR, target tp_atr=4 (2R), max_hold 20 barre. Walk-forward: train 1825 gg, test 365 gg, embargo max(2 gg, max_hold). Kinds: base_rate, logit, rf. Costi equity preset. OOS 2015-2026 (11 fold; oversold_bounce: 1 solo fold valido).

| setup | eventi | n_trades | win% | expectancy netta | PF | miglior ML (AUC) | Δ log-loss vs base | DSR | PBO | verdetto |
|---|---|---|---|---|---|---|---|---|---|---|
| breakout_20d_close_high | 7489 | 1038 | 51.1 | 1.35% | 1.64 | rf (0.446) | -0.00014 | 0.999 | 0.054 | NO EDGE (rivalutato: AUC < 0.52, non batte il filtro casuale) |
| bull_flag | 1486 | 298 | 50.0 | 1.26% | 1.43 | rf (0.446) | -0.00020 | 0.612 | 0.000 | NO EDGE — do not deploy |
| reclaim_20d_ma | 2334 | 888 | 54.2 | 1.34% | 1.58 | rf (0.455) | 0.00166 | 0.979 | 0.113 | NO EDGE — do not deploy |
| oversold | 788 | 198 | 51.0 | 1.84% | 1.53 | logit (0.528) | 0.03928 | 0.788 | 0.471 | NO EDGE — do not deploy |
| oversold_bounce | 455 | 10 | 70.0 | 4.44% | 3.63 | logit (0.500) | -0.00705 | 0.984 | 0.787 | NO EDGE — do not deploy |
| always_long (buy&hold con le stesse exit, solo base_rate) | 41629 | 2143 | 50.3 | 1.22% | 1.50 | n/a | n/a | 0.981 | 0.000 | NO EDGE — do not deploy |

Colonne n_trades/win/expectancy/PF = configurazione base_rate (tutti i segnali accettati, sizing Kelly 0.25) OOS; "miglior ML" = logit o rf con AUC piu' alta; DSR e Δ log-loss riferiti a quel modello (per always_long, a base_rate). Δ<0 = meglio del base rate.

### Controllo primary_only (segnale primario, size fissa)

| setup | n_trades | win% | expectancy | PF | Sharpe | maxDD |
|---|---|---|---|---|---|---|
| breakout_20d_close_high | 959 | 51.0 | 1.34% | 1.64 | 0.93 | -0.116 |
| bull_flag | 295 | 50.2 | 1.30% | 1.45 | 0.48 | -0.195 |
| reclaim_20d_ma | 804 | 54.2 | 1.23% | 1.54 | 0.79 | -0.283 |
| oversold | 194 | 50.5 | 1.68% | 1.48 | 0.33 | -0.142 |
| oversold_bounce | 10 | 70.0 | 4.44% | 3.63 | 1.48 | -0.015 |
| always_long | 1846 | 51.0 | 1.26% | 1.54 | 0.83 | -0.312 |

## ORB, equities 5m (backtest semplice, senza ML)

Dati Yahoo 5m: 2026-09-27..2026-11-24 (circa 40 sessioni), stessi 10 simboli. Regole: range 15 min (9:30-9:45 ET), entrata sulla prima barra completata che chiude sopra il massimo del range, entro le 15:30 ET, una per sessione, long-only, nessun filtro volume. Exit: sl_atr=1.0 (approssimazione del midpoint del range), target 2R (tp_rr=2), flatten a fine sessione. Costi equity preset.

| strategia | n_trades | win% | expectancy netta | expectancy R | PF | total return | max DD |
|---|---|---|---|---|---|---|---|
| orb | 222 | 32.9 | -0.108% | -0.25 | 0.62 | -2.38% | -2.44% |
| always_long (rientra a ogni barra libera, flatten eod; non e' un buy&hold puro) | 4091 | 29.3 | -0.098% | -0.47 | 0.56 | -30.5% | -30.9% |

Su 40 sessioni non e' possibile alcuna conclusione (nessun test di significativita', nessun walk-forward, nessun DSR/PBO). Il costo (cost_share 1.23) supera il PnL lordo. Lo stop a 1 ATR non e' il midpoint dell'opening range del tool originale: la prova non e' quella di trader-exit.

## Numero di configurazioni provate

- Walk-forward daily: 5 setup x 3 modelli (base_rate, logit, rf) = 15 configurazioni, piu' always_long (base_rate) = 16. Ogni run ha n_trials DSR = 3 (always_long: 1); il DSR non e' corretto per i 5 setup provati insieme (trials totali 16).
- Backtest ORB: 2 (orb, always_long 5m). Totale: 18 configurazioni, 8 run, un solo run per setup, nessuna soglia modificata dopo aver visto i risultati.

## Note

- Il verdetto iniziale "DEPLOYABLE: rf" (poi corretto in NO EDGE dopo l'aggiunta dei criteri di edge incrementale: AUC > 0.52, expectancy > primary_only e > filtro casuale) di breakout_20d_close_high non deriva dal setup: always_long con le stesse exit ha expectancy 1.22% e PF 1.50 contro 1.35% e 1.64; rf batte il base rate di soli 0.00014 in log-loss (AUC 0.446, sotto 0.5, IC negativo) e la sua expectancy coincide con quella di base_rate. Con 16 configurazioni provate il DSR 0.999 e' ottimistico. Il periodo 2015-2026 e' un mercato rialzista dei large cap.
- oversold_bounce: 455 eventi totali, 1 solo fold OOS valido, 10 trade: nessuna inferenza possibile.
- Nessun setup batte primary_only/always_long in modo distinguibile; nessun ML migliora in modo materiale il log-loss.
- Riproducibilita': `reports/setups_scripts/run_daily.py <strategia> [kinds]`, `reports/setups_scripts/run_orb.py`; report in `reports/setups_*_1d/`, `reports/setups_orb_5m.json`.
