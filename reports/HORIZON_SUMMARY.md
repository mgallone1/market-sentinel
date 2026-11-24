# Riepilogo orizzonti temporali (walk-forward purged, meta-labeling)

Universo crypto: 10 perp USDT (proxy Binance Vision), 2023-11-01..2026-11-01, regole di uscita `default` (SL 1.5 ATR, TP 3 ATR, max_hold 48/30/20 barre per 1h/4h/1d). Kinds: base_rate, gbm_montecarlo, logit, hgb, rf, ensemble. Equities/indices: report preesistenti. "Miglior ML" = kind tra logit/hgb/rf/ensemble con minor log-loss OOS; "exp." e PF sono dopo i costi; "n/d" = nessun trade accettato (p mai > p*). Δlog-loss < 0 = meglio del base_rate.

| Esperimento | n eventi | primary exp. | primary PF | miglior ML | AUC OOS | Δlog-loss vs base | exp. | PF | DSR | PBO | n trade | verdetto |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 crypto tsmom 4h | 39759 | 0.06% | 1.03 | rf | 0.521 | -0.0000 | 0.16% | 1.07 | 0.54 | 0.91 | 754 | NO EDGE — do not deploy |
| E2 crypto donchian 4h | 2286 | 0.46% | 1.18 | rf | 0.468 | 0.0074 | -0.53% | 0.78 | 0.01 | 0.17 | 76 | NO EDGE — do not deploy |
| E3 crypto tsmom 1d | 6879 | 0.55% | 1.13 | rf | 0.504 | -0.0000 | n/d | n/d | n/d | 0.47 | 0 | NO EDGE — do not deploy |
| E4 crypto donchian 1d | 316 | 1.37% | 1.27 | hgb | 0.535 | -0.0059 | 2.51% | 1.67 | 0.40 | 0.55 | 36 | NO EDGE — do not deploy |
| equities donchian 1h | 1758 | -0.11% | 0.76 | rf | 0.467 | -0.0007 | n/d | n/d | n/d | 0.41 | 0 | NO EDGE — do not deploy |
| indices tsmom 1d | 10094 | -0.04% | 0.97 | rf | 0.584 | -0.0122 | 0.71% | 1.56 | 0.74 | 0.16 | 328 | NO EDGE — do not deploy |

Ablation (Δlog-loss togliendo la famiglia, miglior ML; positivo = la famiglia aiuta):
- E1 crypto tsmom 4h: reg_ +0.0041, struct_ +0.0038, meta_ +0.0029, vol_ +0.0027, cal_ +0.0025, xs_ +0.0023, trend_ +0.0023, rev_ +0.0018, volu_ +0.0017, deriv_ +0.0014
- E2 crypto donchian 4h: meta_ -0.0013, rev_ -0.0019, reg_ -0.0019, struct_ -0.0021, vol_ -0.0024, deriv_ -0.0026, volu_ -0.0029, trend_ -0.0035, xs_ -0.0041, cal_ -0.0067
- E3 crypto tsmom 1d: xs_ +0.0191, meta_ +0.0151, vol_ +0.0106, trend_ +0.0084, rev_ +0.0050, deriv_ +0.0034, cal_ +0.0025, volu_ +0.0023, reg_ +0.0022, struct_ +0.0001
- E4 crypto donchian 1d: xs_ +0.1397, deriv_ +0.1316, volu_ +0.1109, trend_ +0.0356, reg_ +0.0320, rev_ +0.0162, meta_ +0.0148, struct_ +0.0112, vol_ +0.0078, cal_ -0.0025
- equities donchian 1h: xs_ +0.0018, reg_ +0.0017, trend_ +0.0017, volu_ +0.0015, cal_ +0.0015, vol_ +0.0007, rev_ +0.0006, meta_ +0.0004, struct_ +0.0003
- indices tsmom 1d: volu_ +0.0272, trend_ +0.0203, rev_ +0.0169, meta_ +0.0126, struct_ +0.0084, cal_ +0.0032, vol_ +0.0028, reg_ +0.0013

gbm_montecarlo:
- E1 crypto tsmom 4h: gbm_montecarlo AUC 0.513, Δlog-loss 0.2025, expectancy 0.11%, DSR 0.67
- E2 crypto donchian 4h: gbm_montecarlo AUC 0.527, Δlog-loss 0.2946, expectancy 0.35%, DSR 0.53
- E3 crypto tsmom 1d: gbm_montecarlo AUC 0.490, Δlog-loss 0.1096, expectancy 1.23%, DSR 0.49
- E4 crypto donchian 1d: gbm_montecarlo AUC 0.471, Δlog-loss 0.1439, expectancy 1.23%, DSR 0.15
- equities donchian 1h: gbm_montecarlo AUC 0.523, Δlog-loss 0.2742, expectancy -0.11%, DSR 0.19
- indices tsmom 1d: gbm_montecarlo AUC 0.512, Δlog-loss 0.1137, expectancy -0.02%, DSR 0.10

## Fatti
- Nessuno dei 6 esperimenti supera i criteri (log-loss < base_rate, DSR > 0.95, PBO < 0.2, exp. > 0, n_trade >= 200): verdetto NO EDGE in tutti.
- Orizzonte: l'espettanza del primario cresce con l'orizzonte nei dati crypto (donchian 4h 0.46% -> 1d 1.37%; tsmom 4h 0.06% -> 1d 0.55%), ma i campioni 1d sono piccoli (316 eventi donchian, 36 trade del miglior ML; 4 fold) e il PF del primario resta <= 1.27. Il miglior ML ha Δlog-loss ~0 in E1/E3 (tsmom), peggiora in E2 (+0.0074) e migliora leggermente in E4 (-0.0059, AUC 0.535, 36 trade, DSR 0.40). L'AUC non e' monotona con l'orizzonte (E2 0.468 sotto 0.5).
- Famiglie di feature (ablation sul miglior ML, delta log-loss togliendo la famiglia): in E1 e E3 tutte le famiglie hanno delta positivo ma piccolo (E1 max +0.004 reg_; E3 max +0.019 xs_, +0.015 meta_). In E2 tutti i delta sono negativi (togliere qualunque famiglia migliora il log-loss: le feature non aiutano). In E4 i delta enormi (xs_ +0.14, deriv_ +0.13, volu_ +0.11) provengono da un training di ~100-200 eventi per fold: non interpretabili come segnale. Sugli indici 1d: volu_ +0.027, trend_ +0.020.
- gbm_montecarlo: AUC 0.47-0.53, Δlog-loss sempre positivo (+0.11..+0.29, cioe' peggiore del base_rate, probabilita' mal calibrate), DSR <= 0.67 (E1 0.67 la piu' alta); non supera i modelli ML in log-loss in nessun esperimento.
- Configurazioni provate: ogni report ha 6 configurazioni modello (n_trials=6, DSR calcolato su 6). I 6 report qui sommati = 36 configurazioni; a queste si aggiungono le due ricerche crypto 1h in corso al momento della scrittura (altre 12 se concluse, per 48 totali) ed eventuali run precedenti non presenti in reports/. Le soglie DSR di ogni report non includono i trial degli altri report: il numero di trial cumulato e' maggiore di quello usato nel DSR per singolo report.
- Note: E4 ha richiesto un rerun dopo un crash in `family_importance` (ValueError sklearn su campione piccolo; diagnostica ora saltata con warning), stessi parametri, nessuna nuova configurazione. tsmom produce un evento per ogni barra con posizione (E1 39759 eventi, sotto soglia 60k), nessuna modifica ai parametri.
