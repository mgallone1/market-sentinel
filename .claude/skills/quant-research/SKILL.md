---
name: quant-research
description: >-
  Market Sentinel quantitative engine (package `quant/`): download market data, backtest a strategy,
  run purged walk-forward meta-labeling research comparing predictive models, read the verdict, and
  train/use the live MetaGate. Works on crypto perps (Bybit, Binance data), equities, ETFs and indices.
  Use when asked to backtest, evaluate a strategy, compare models, check whether a signal has edge,
  improve win probability, retrain the gate, or add a new strategy/feature.
---

# quant-research

Read this file instead of exploring `quant/`; open source files only for the module you change.

## Layout (contracts in `quant/core.py`)
- Bars: UTC DatetimeIndex = bar OPEN time; cols open/high/low/close/volume (+ taker_buy_volume, funding_rate, open_interest). Closed bars only. Decision at close t -> execution at open t+1.
- `AssetSpec` helpers: `crypto_perp(sym, venue)`, `equity(sym)`, `index(sym)`; cost presets in `COST_PRESETS` (fees, slippage, stop slippage, funding, borrow).
- `quant/data`: `load_bars(spec, interval, start, end)`; Bybit (production) -> falls back to Binance Vision perps when geo-blocked; Yahoo for equities/indices; cache in `data/cache/`.
- `quant/features`: `build_features` (families trend_, rev_, vol_, volu_, deriv_, xs_, cal_, struct_), `GaussianHMM`, `TrendRegime` (hysteresis).
- `quant/strategies`: `STRATEGIES` registry; signature `fn(bars, spec, interval, context) -> Series{-1,0,1}`. `legacy` = replica of the live bot crypto entries (15m), `legacy_equity`, baselines `tsmom`, `donchian_breakout`, `meanrev_z`, `ema_cross`, `always_long`, `random`.
- `quant/backtest`: `run_backtest(bars, signals_df_with_side, spec, rules, interval)`, `run_portfolio`, `ExitRules`, `LEGACY_BOT_RULES`, `triple_barrier_labels` (same exit engine as backtest).
- `quant/models` + `quant/research`: meta-labeling, kinds `base_rate, gbm_montecarlo, logit, hgb, rf, ensemble`; purged walk-forward; DSR + PBO verdict.
- `quant/live/gate.py`: `MetaGate.load(path).decide(bars, spec, interval, side)`.

## Commands
```bash
python -m pytest quant/tests tests -q                     # must be green before any commit
python -m quant.cli fetch --universe crypto --interval 1h --start 2023-11-01 --end 2026-11-01
python -m quant.cli backtest --strategy legacy --universe BTCUSDT,SOLUSDT --interval 15m --rules legacy
python -m quant.cli research --strategy donchian_breakout --universe crypto --interval 1h \
  --start 2023-11-01 --end 2026-11-01 --kinds base_rate,gbm_montecarlo,logit,hgb,rf,ensemble \
  --train-days 365 --test-days 90 --out reports/crypto_donchian_1h      # add --no-ablation to go faster
python -m quant.cli train-gate --strategy donchian_breakout --kind logit \
  --report reports/crypto_donchian_1h/report.json --out models/crypto_donchian.pkl
```
Universes: `crypto` (10 USDT perps, benchmark BTCUSDT), `equities` (10 US large caps, SPY), `indices` (^GSPC, ^NDX, ^STOXX50E, daily) or a comma list. `--synthetic` runs offline.

## Reading results
`reports/<name>/report.md`: ranking by OOS log-loss vs base rate, AUC, IC, expectancy after costs, DSR, PBO, verdict. A config is deployable only if: log-loss < base_rate, DSR > 0.95, PBO < 0.2, expectancy > 0, n_trades >= 200. Otherwise "NO EDGE — do not deploy": report it as is, never tune thresholds on the test set to flip it (each extra configuration tried is an extra trial in the DSR).

## Rules when extending
- New feature: add to a family in `quant/features/families.py`, keep it causal (test_features causality test must pass).
- New strategy: register in `quant/strategies/__init__.py`; add it to the causality test list.
- Never use the forming bar; never fit HMM/models/calibration on test folds.
- Known engine checks: exit rules give zero gross PnL on a martingale (`test_legacy_rules_gross_pnl_zero_on_martingale`).
