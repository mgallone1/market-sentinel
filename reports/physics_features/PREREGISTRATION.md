# Pre-registrazione: feature "fluidodinamiche" (famiglia `phys_`) nel meta-labeling

Data: 2026-11-26. Scritto e versionato **prima** di eseguire qualsiasi run. Nessuna soglia, finestra o
parametro verrà modificato dopo aver visto i risultati; ogni run aggiuntivo verrà dichiarato come prova in più.

## Ipotesi
H1: aggiungere la famiglia `phys_` alle feature esistenti migliora la previsione OOS dell'esito dei segnali
primari (meta-labeling). H0: nessun miglioramento.

Priore dichiarato (prima del test): basso. `phys_pe_<h>h` = z_drift * 2dx/(sigma*sqrt(n)) è una
riparametrizzazione di `trend_ret_<h>h` (già drift z-score); `phys_fp_ptp0` dipende solo da sigma/ATR;
la media DEMA+minmod è un compromesso ritardo/rumore noto.

## Feature (quant/features/families.py::physics_features, parametri fissi)
- `phys_pe_{24,72,168}h`: Pe = 2 nu dx / s2, nu e s2 per barra su 24/72/168 ore, dx = 3*ATR14/close.
- `phys_fp_ptp0`: P(TP prima di SL entro 48 barre) senza drift, Fokker-Planck in forma chiusa,
  SL = 1.5 ATR, TP = 3 ATR, varianza su 168 ore.
- `phys_fp_edge`: P(TP) con drift (168 ore) per un LONG meno `phys_fp_ptp0`.
- `phys_drift_tvd_{12,48}`: minmod(dlog EMA, dlog DEMA) / sigma, span 12 e 48 barre.
Le feature direzionali ricevono la copia allineata al lato (`_sa`) come le altre.

## Dati e protocollo (identici agli studi già pubblicati, per confronto diretto)
- Universo: 10 perpetui USDT (BTC, ETH, SOL, XRP, LINK, AVAX, ADA, DOGE, SUI, NEAR), 1h,
  2023-11-01 -> 2026-11-01, Binance Vision (fallback dei dati Bybit), benchmark BTCUSDT.
- Dataset A: primario `donchian_breakout`, ExitRules default (SL 1.5 ATR, TP 3 ATR, hold 48)
  — confronto con `reports/crypto_donchian_1h`.
- Dataset B: primario `legacy` (replica degli ingressi crypto del bot), `LEGACY_BOT_RULES`
  — confronto con `reports/crypto_legacy_1h`.
- Walk-forward purged: train 365 gg, test 90 gg, embargo max(2 gg, 48 barre), seed 0, sizing kelly,
  soglia breakeven. Modelli: `base_rate` (riferimento), `logit`, `hgb`.
- Due bracci per dataset con fold, eventi e seed identici: BASE (feature attuali) e PHYS (attuali + `phys_`).

## Numero di prove
2 dataset x 2 bracci x 2 modelli ML = 8 configurazioni (base_rate escluso). DSR calcolato con n_trials
interno al run (2); il conteggio complessivo (8) va considerato nella lettura.

## Criteri di successo (tutti richiesti, su ENTRAMBI i dataset, per il modello ML migliore del braccio PHYS)
1. Δ log-loss OOS (PHYS − BASE, stesso modello) <= −0.001;
2. Δ AUC (PHYS − BASE) >= +0.005;
3. differenza di log-loss per fold (8 fold appaiati) con t <= −2;
4. ablazione nel braccio PHYS: rimuovere `phys_` peggiora la log-loss (Δ > 0).
Se 1–4 sono soddisfatti: "PHYS MIGLIORA LA PREVISIONE". Questo NON rende deployabile nulla: per il deploy
valgono i criteri standard (log-loss < base_rate, DSR > 0.95, PBO < 0.2, expectancy > 0, n >= 200,
AUC > 0.52, expectancy sopra primary_only e random@kind). Altrimenti: "NESSUN MIGLIORAMENTO".

## Riproducibilità
`python reports/physics_features/run_physics.py` (scrive `results.json` e `RESULTS.md` in questa cartella).
