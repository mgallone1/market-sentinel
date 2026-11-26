# Audit: Meta-Labeling L2 + Kelly frazionario vs benchmark beta-adjusted

Protocollo pre-registrato: `reports/PREREG_METALABELING_KELLY.md` (commit 2570b10, prima di ogni run). Codice: `quant/research/metakelly/` (commit b21bdea, prima del primo run). Dati grezzi per universo in `reports/metakelly/<eq|cr>/` (`results.json`, `events.csv.gz`, `oos_predictions.csv.gz`).

**Verdetto complessivo: Azioni Alpaca SCARTATO; Perpetui crypto Bybit SCARTATO**

## Azioni Alpaca (1h, benchmark SPY) — esito: **SCARTATO**

- Periodo OOS: 2025-01-11 16:30:00+00:00 → 2026-11-25 15:30:01+00:00; eventi etichettati 1704, OOS 1086, fold 8; motori: {'TREND_PULLBACK_4H': 1227, 'INTRADAY_MOMENTUM': 477}.
- Frequenza dell'etichetta y = 1 (TP prima di SL e T_end): **0.18%**.
- Feature: fp_p_tp_zero_drift, fp_p_tp_rs_zero_drift, fp_p_tp_bayes, ofi_bvc_short, ofi_bvc_med, side, idio_z_drift, idio_cs_rank, vrp_spread, session_frac_left, eng_INTRADAY_MOMENTUM, eng_TREND_PULLBACK_4H.
- PBO (CSCV, 6 configurazioni): beta-adjusted 1.000, netto 1.000. C migliore per log-loss: 0.01.

### Lettura (azioni)
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


### Rendimenti OOS (A baseline, B benchmark, C meta + Kelly, controlli random@)

| configurazione | trade | win% | expectancy | PF netto | PF excess | Sharpe netto | Sharpe beta-adj | DSR netto | DSR beta-adj | max DD | max esposizione | Brier | log-loss |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_baseline_all | 769 | 49.80% | 0.09% | 1.24 | 1.03 | 0.93 | 1.05 | 0.925 | 0.945 | -3.44% | 0.70 | n/a | n/a |
| A_INTRADAY_MOMENTUM | 292 | 52.40% | 0.14% | 1.36 | 0.95 | 1.18 | 1.23 | 0.953 | 0.958 | -1.71% | 0.40 | n/a | n/a |
| A_TREND_PULLBACK_4H | 502 | 48.21% | 0.06% | 1.16 | 1.05 | 0.48 | 0.57 | 0.765 | 0.807 | -2.81% | 0.70 | n/a | n/a |
| B1_always_long | 3791 | 47.03% | -0.05% | 0.89 | n/a | -0.99 | -1.67 | 0.092 | 0.013 | -21.84% | 0.70 | n/a | n/a |
| C_meta_C0.01_k0.15 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | 0.0028 | 0.0331 |
| random@C_meta_C0.01_k0.15 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | n/a | n/a |
| C_meta_C0.01_k0.25 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | 0.0028 | 0.0331 |
| random@C_meta_C0.01_k0.25 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | n/a | n/a |
| C_meta_C0.1_k0.15 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | 0.0028 | 0.0341 |
| random@C_meta_C0.1_k0.15 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | n/a | n/a |
| C_meta_C0.1_k0.25 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | 0.0028 | 0.0341 |
| random@C_meta_C0.1_k0.25 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | n/a | n/a |
| C_meta_C1.0_k0.15 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | 0.0028 | 0.0381 |
| random@C_meta_C1.0_k0.15 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | n/a | n/a |
| C_meta_C1.0_k0.25 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | 0.0028 | 0.0381 |
| random@C_meta_C1.0_k0.25 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.00% | 0.00 | n/a | n/a |
| B2_passive_SPY | 0 | n/a | n/a | n/a | n/a | 0.75 | n/a | 0.848 | n/a | -18.95% | n/a | n/a | n/a |

### Calibrazione OOS

| previsore di P(TP prima di SL e di T_end) | n | Brier | log-loss | Δ log-loss vs base rate | t fold (log-loss) | Δ Brier vs base | t fold (Brier) |
|---|---|---|---|---|---|---|---|
| `p_base` | 1086 | 0.0028 | 0.0330 | 0.0000 | n/a | 0.00000 | n/a |
| `p_C0.01` | 1086 | 0.0028 | 0.0331 | 0.0001 | 0.83 | 0.00000 | 0.82 |
| `p_C0.1` | 1086 | 0.0028 | 0.0341 | 0.0010 | 0.85 | 0.00000 | 0.98 |
| `p_C1.0` | 1086 | 0.0028 | 0.0381 | 0.0051 | 0.95 | 0.00001 | 1.78 |
| `fp_p_tp` | 1086 | 0.0029 | 0.0280 | -0.0051 | -0.21 | 0.00014 | 1.45 |
| `fp_p_tp_zero_drift` | 1086 | 0.0029 | 0.0278 | -0.0052 | -0.23 | 0.00011 | 1.41 |
| `fp_p_tp_rs_zero_drift` | 1086 | 0.0034 | 0.0253 | -0.0077 | -0.25 | 0.00060 | 1.49 |
| `fp_p_tp_bayes` | 1086 | 0.0029 | 0.0278 | -0.0052 | -0.23 | 0.00011 | 1.41 |

### Criteri di promozione (migliore C per log-loss)

| configurazione | criterio | esito |
|---|---|---|
| C_meta_C0.01_k0.15 | 1_logloss_brier_below_base_t<=-2 | NO |
| C_meta_C0.01_k0.15 | 2_dsr_excess>0.95 | NO |
| C_meta_C0.01_k0.15 | 3_pbo<0.20 | NO |
| C_meta_C0.01_k0.15 | 4_excess>0_and_sharpe_excess>baseline | NO |
| C_meta_C0.01_k0.15 | 5_expectancy>random_and_baseline | NO |
| C_meta_C0.01_k0.15 | 6_n_trades>=100 | NO |
| C_meta_C0.01_k0.25 | 1_logloss_brier_below_base_t<=-2 | NO |
| C_meta_C0.01_k0.25 | 2_dsr_excess>0.95 | NO |
| C_meta_C0.01_k0.25 | 3_pbo<0.20 | NO |
| C_meta_C0.01_k0.25 | 4_excess>0_and_sharpe_excess>baseline | NO |
| C_meta_C0.01_k0.25 | 5_expectancy>random_and_baseline | NO |
| C_meta_C0.01_k0.25 | 6_n_trades>=100 | NO |

### Fold

| fold | test | n train | n test | purgati | in embargo | base rate train |
|---|---|---|---|---|---|---|
| 0 | 2025-01-11 → 2025-04-12 | 618 | 179 | 0 | 0 | 0.0000 |
| 1 | 2025-04-12 → 2025-07-12 | 797 | 132 | 0 | 0 | 0.0025 |
| 2 | 2025-07-12 → 2025-10-11 | 927 | 152 | 0 | 2 | 0.0032 |
| 3 | 2025-10-11 → 2026-01-10 | 1081 | 117 | 0 | 0 | 0.0028 |
| 4 | 2026-01-10 → 2026-04-11 | 1198 | 180 | 0 | 0 | 0.0025 |
| 5 | 2026-04-11 → 2026-07-11 | 1378 | 115 | 0 | 0 | 0.0022 |
| 6 | 2026-07-11 → 2026-10-10 | 1491 | 114 | 0 | 2 | 0.0020 |
| 7 | 2026-10-10 → 2026-11-25 | 1606 | 97 | 0 | 1 | 0.0019 |

## Perpetui crypto Bybit (15m, benchmark BTCUSDT) — esito: **SCARTATO**

- Periodo OOS: 2025-11-01 21:15:00+00:00 → 2026-10-31 21:15:01+00:00; eventi etichettati 31527, OOS 15002, fold 6; motori: {'TREND_PULLBACK_4H': 13413, 'LIQUIDITY_SWEEP_MR': 11783, 'INTRADAY_MOMENTUM': 6331}.
- Frequenza dell'etichetta y = 1 (TP prima di SL e T_end): **21.48%**.
- Feature: fp_p_tp_zero_drift, fp_p_tp_rs_zero_drift, fp_p_tp_bayes, ofi_bvc_short, ofi_bvc_med, side, eng_INTRADAY_MOMENTUM, eng_LIQUIDITY_SWEEP_MR, eng_TREND_PULLBACK_4H.
- PBO (CSCV, 6 configurazioni): beta-adjusted 0.623, netto 0.611. C migliore per log-loss: 0.01.

### Lettura (crypto)
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


### Rendimenti OOS (A baseline, B benchmark, C meta + Kelly, controlli random@)

| configurazione | trade | win% | expectancy | PF netto | PF excess | Sharpe netto | Sharpe beta-adj | DSR netto | DSR beta-adj | max DD | max esposizione | Brier | log-loss |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_baseline_all | 4801 | 29.35% | -0.15% | 0.83 | 0.73 | -2.97 | -2.93 | 0.003 | 0.003 | -54.43% | 0.70 | n/a | n/a |
| A_INTRADAY_MOMENTUM | 1795 | 27.86% | -0.11% | 0.87 | 0.72 | -1.39 | -1.35 | 0.100 | 0.103 | -20.64% | 0.70 | n/a | n/a |
| A_LIQUIDITY_SWEEP_MR | 3037 | 27.89% | -0.14% | 0.80 | 0.62 | -4.77 | -4.77 | 0.000 | 0.000 | -34.88% | 0.70 | n/a | n/a |
| A_TREND_PULLBACK_4H | 2068 | 32.93% | -0.13% | 0.88 | 0.75 | -1.28 | -1.22 | 0.107 | 0.118 | -34.58% | 0.70 | n/a | n/a |
| B1_always_long | 9185 | 25.80% | -0.23% | 0.75 | n/a | -4.97 | -7.62 | 0.000 | 0.000 | -89.64% | 0.70 | n/a | n/a |
| C_meta_C0.01_k0.15 | 1 | 100.00% | 2.55% | n/a | n/a | 1.00 | 0.65 | 0.938 | 0.688 | 0.00% | 0.02 | 0.1625 | 0.5047 |
| random@C_meta_C0.01_k0.15 | 1 | 0.00% | -1.08% | 0.00 | 0.00 | -1.00 | -0.97 | 0.024 | 0.031 | -0.02% | 0.02 | n/a | n/a |
| C_meta_C0.01_k0.25 | 8 | 50.00% | 0.61% | 1.92 | 1.82 | 1.00 | 0.65 | 0.841 | 0.657 | -0.03% | 0.03 | 0.1625 | 0.5047 |
| random@C_meta_C0.01_k0.25 | 8 | 25.00% | -0.25% | 0.77 | 0.16 | 0.40 | 0.16 | 0.683 | 0.568 | -0.08% | 0.03 | n/a | n/a |
| C_meta_C0.1_k0.15 | 10 | 50.00% | 0.48% | 1.80 | 1.03 | 1.07 | 0.96 | 0.860 | 0.785 | -0.06% | 0.03 | 0.1626 | 0.5049 |
| random@C_meta_C0.1_k0.15 | 15 | 26.67% | -0.24% | 0.76 | 0.72 | -0.10 | 0.14 | 0.461 | 0.556 | -0.09% | 0.03 | n/a | n/a |
| C_meta_C0.1_k0.25 | 42 | 45.24% | 0.36% | 1.54 | 1.62 | 1.45 | 1.24 | 0.928 | 0.858 | -0.09% | 0.05 | 0.1626 | 0.5049 |
| random@C_meta_C0.1_k0.25 | 55 | 36.36% | -0.01% | 0.98 | 0.66 | -0.54 | -0.17 | 0.297 | 0.434 | -0.24% | 0.06 | n/a | n/a |
| C_meta_C1.0_k0.15 | 13 | 46.15% | 0.40% | 1.65 | 1.70 | 1.13 | 1.03 | 0.876 | 0.810 | -0.06% | 0.03 | 0.1626 | 0.5050 |
| random@C_meta_C1.0_k0.15 | 19 | 15.79% | -0.66% | 0.43 | 0.27 | -1.22 | -1.07 | 0.150 | 0.174 | -0.19% | 0.03 | n/a | n/a |
| C_meta_C1.0_k0.25 | 60 | 43.33% | 0.27% | 1.38 | 1.31 | 1.35 | 1.13 | 0.905 | 0.822 | -0.14% | 0.05 | 0.1626 | 0.5050 |
| random@C_meta_C1.0_k0.25 | 76 | 31.58% | -0.09% | 0.90 | 0.82 | -0.47 | -0.38 | 0.326 | 0.354 | -0.28% | 0.04 | n/a | n/a |
| B2_passive_BTC | 0 | n/a | n/a | n/a | n/a | -0.57 | n/a | 0.286 | n/a | -46.96% | n/a | n/a | n/a |

### Calibrazione OOS

| previsore di P(TP prima di SL e di T_end) | n | Brier | log-loss | Δ log-loss vs base rate | t fold (log-loss) | Δ Brier vs base | t fold (Brier) |
|---|---|---|---|---|---|---|---|
| `p_base` | 15002 | 0.1644 | 0.5107 | 0.0000 | n/a | 0.00000 | n/a |
| `p_C0.01` | 15002 | 0.1625 | 0.5047 | -0.0060 | -2.65 | -0.00190 | -3.14 |
| `p_C0.1` | 15002 | 0.1626 | 0.5049 | -0.0058 | -2.86 | -0.00182 | -3.45 |
| `p_C1.0` | 15002 | 0.1626 | 0.5050 | -0.0057 | -2.85 | -0.00180 | -3.44 |
| `fp_p_tp` | 15002 | 0.1678 | 0.5184 | 0.0078 | 3.23 | 0.00339 | 4.21 |
| `fp_p_tp_zero_drift` | 15002 | 0.1632 | 0.5098 | -0.0008 | -0.20 | -0.00118 | -0.62 |
| `fp_p_tp_rs_zero_drift` | 15002 | 0.1627 | 0.5075 | -0.0032 | -0.62 | -0.00168 | -1.10 |
| `fp_p_tp_bayes` | 15002 | 0.1632 | 0.5098 | -0.0008 | -0.21 | -0.00119 | -0.62 |

### Criteri di promozione (migliore C per log-loss)

| configurazione | criterio | esito |
|---|---|---|
| C_meta_C0.01_k0.15 | 1_logloss_brier_below_base_t<=-2 | OK |
| C_meta_C0.01_k0.15 | 2_dsr_excess>0.95 | NO |
| C_meta_C0.01_k0.15 | 3_pbo<0.20 | NO |
| C_meta_C0.01_k0.15 | 4_excess>0_and_sharpe_excess>baseline | OK |
| C_meta_C0.01_k0.15 | 5_expectancy>random_and_baseline | OK |
| C_meta_C0.01_k0.15 | 6_n_trades>=100 | NO |
| C_meta_C0.01_k0.25 | 1_logloss_brier_below_base_t<=-2 | OK |
| C_meta_C0.01_k0.25 | 2_dsr_excess>0.95 | NO |
| C_meta_C0.01_k0.25 | 3_pbo<0.20 | NO |
| C_meta_C0.01_k0.25 | 4_excess>0_and_sharpe_excess>baseline | OK |
| C_meta_C0.01_k0.25 | 5_expectancy>random_and_baseline | OK |
| C_meta_C0.01_k0.25 | 6_n_trades>=100 | NO |

### Fold

| fold | test | n train | n test | purgati | in embargo | base rate train |
|---|---|---|---|---|---|---|
| 0 | 2025-11-01 → 2026-01-01 | 16483 | 2596 | 22 | 20 | 0.2225 |
| 1 | 2026-01-01 → 2026-03-03 | 19092 | 2497 | 8 | 21 | 0.2202 |
| 2 | 2026-03-03 → 2026-05-03 | 21575 | 2410 | 7 | 36 | 0.2241 |
| 3 | 2026-05-03 → 2026-07-03 | 23998 | 2748 | 22 | 8 | 0.2179 |
| 4 | 2026-07-03 → 2026-09-02 | 26741 | 2323 | 17 | 18 | 0.2210 |
| 5 | 2026-09-02 → 2026-10-31 | 29025 | 2428 | 37 | 37 | 0.2161 |

## Avvertenze comuni
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


