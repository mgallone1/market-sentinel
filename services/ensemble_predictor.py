"""
Ensemble Predictive Intelligence Engine for Market Sentinel.
Integrates 4 institutional-grade predictive pillars:
1. Monte Carlo Stochastic Simulation (10,000 geometric Brownian motion paths with 1-Sigma & 2-Sigma confidence bands).
2. Hurst Harmonic Cycle & FLD (Future Line of Demarcation) Projections.
3. Statistical Z-Score, Volatility Cone (ATR expected move), & Mean Reversion Probabilities.
4. Elliott Wave Fractal Phase & Institutional Macro Filter (VIX, 10Y Yields).

Outputs a unified Composite Forecast, Directional Conviction Score (0-100%), and exact Euro (€) targets.
"""

import math
import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

from services.market_data import MarketDataService
from services.predictive_engine import PredictiveTradingEngine
from services.advanced_predictive_system import AdvancedPredictiveSystem
from services.hurst_migliorino_cycles import HurstMigliorinoCycleService
from services.technical_analysis import TechnicalAnalysisService

logger = logging.getLogger(__name__)


class EnsemblePredictorEngine:
    @classmethod
    def generate_ensemble_forecast(cls, ticker: str) -> Dict[str, Any]:
        """
        Elabora la previsione multi-modello quantitativa ad alta precisione per un asset.
        Tutti i valori sono rigorosamente convertiti e calcolati in Euro (€).
        """
        symbol = ticker.strip().upper()
        # Normalizzazione ticker crypto per Yahoo Finance
        yf_symbol = f"{symbol}-EUR" if symbol in ["BTC", "ETH", "SOL", "ADA", "XRP"] else symbol

        df = MarketDataService.get_ticker_history(yf_symbol, period="6mo", interval="1d")
        if df.empty or len(df) < 25:
            # Prova con ticker originale
            df = MarketDataService.get_ticker_history(symbol, period="6mo", interval="1d")
            yf_symbol = symbol

        if df.empty or len(df) < 25:
            return {"error": f"Dati storici insufficienti per generare la previsione di {ticker}."}

        fund = MarketDataService.get_ticker_fundamentals(yf_symbol)
        is_already_eur = MarketDataService.is_euro_asset(yf_symbol, fund)
        eur_rate = 1.0 if is_already_eur else MarketDataService.get_eur_usd_rate()

        raw_price = float(df["Close"].iloc[-1])
        current_price_eur = raw_price / eur_rate if eur_rate > 0 else raw_price
        asset_name = fund.get("shortName") or symbol

        # 1. Modello Stocastico Monte Carlo (10.000 iterazioni a 20 giorni)
        mc_data = AdvancedPredictiveSystem.run_monte_carlo_simulation(
            df, days_ahead=20, num_simulations=10000, eur_rate=eur_rate
        )

        # 2. Modello Predittivo Z-Score, ATR & Cono di Volatilità a 5 giorni
        pred_engine = PredictiveTradingEngine.generate_prediction_and_trade_plan(
            df, yf_symbol, currency="EUR" if is_already_eur else "USD"
        )

        # 3. Analisi Ciclica di Hurst & FLD
        hurst_data = HurstMigliorinoCycleService.calculate_cycle_metrics(df)

        # 4. Analisi Frattale delle Onde di Elliott
        elliott_data = AdvancedPredictiveSystem.detect_elliott_wave_phase(df)

        # 5. Macro Regime (VIX & Tassi)
        macro_data = AdvancedPredictiveSystem.get_macro_market_context()

        # 6. Indicatori Tecnici (RSI, SMA, Bande)
        df_tech = TechnicalAnalysisService.calculate_indicators(df)
        rsi_val = float(df_tech["RSI"].iloc[-1]) if "RSI" in df_tech else 50.0

        # --- ALGORITMO DI CONFLUENZA & CALCOLO CONVICTION SCORE ---
        z_score = pred_engine.get("z_score", 0.0)
        prob_pos_mc_str = mc_data.get("probability_positive_trend", "50%").replace("%", "")
        try:
            prob_pos_mc = float(prob_pos_mc_str)
        except Exception:
            prob_pos_mc = 50.0

        # Punteggio Confluenza Direzionale (0 = Ribassista estremo, 100 = Rialzista estremo)
        bullish_score = 50.0

        # Fattore Z-Score & Mean Reversion (ipervenduto spinge per rimbalzo rialzista)
        if z_score <= -2.0:
            bullish_score += 20.0
        elif z_score <= -1.0:
            bullish_score += 10.0
        elif z_score >= 2.0:
            bullish_score -= 20.0
        elif z_score >= 1.0:
            bullish_score -= 10.0

        # Fattore Monte Carlo
        if prob_pos_mc >= 60:
            bullish_score += 15.0
        elif prob_pos_mc <= 40:
            bullish_score -= 15.0

        # Fattore RSI
        if rsi_val <= 30:
            bullish_score += 15.0
        elif rsi_val >= 70:
            bullish_score -= 15.0

        # Fattore Cicli di Hurst
        battleplan_text = hurst_data.get("descrizione_battleplan", "")
        fld_signal = hurst_data.get("hurst_fld_signal", "")
        if "pavimento" in battleplan_text.lower() or "SOPRA" in fld_signal:
            bullish_score += 10.0
        elif "morirà" in battleplan_text.lower() and "SOTTO" in fld_signal:
            bullish_score -= 10.0

        bullish_score = max(5.0, min(95.0, bullish_score))

        # Determinazione del Bias e della Convinzione
        if bullish_score >= 68.0:
            bias = "RIALZISTA (Accumulo / Spinta Direzionale)"
            conviction_pct = int(bullish_score)
            horizon = "5-15 sedute (Target Swing)"
        elif bullish_score <= 35.0:
            bias = "RIBASSISTA (Distribuzione / Attesa Pullback)"
            conviction_pct = int(100 - bullish_score)
            horizon = "3-10 sedute (Fase Correttiva)"
        else:
            bias = "LATERALE / EQUILIBRIO (Consolidamento)"
            conviction_pct = int(max(bullish_score, 100 - bullish_score))
            horizon = "Fase di attesa breakout"

        # Livelli di prezzo e Target proiettati in Euro (€)
        daily_atr_eur = pred_engine.get("daily_atr_eur", current_price_eur * 0.02)
        median_mc_eur = mc_data.get("median_price_eur", current_price_eur)
        ci_68 = mc_data.get("ci_68_range_eur", "")
        ci_95 = mc_data.get("ci_95_range_eur", "")

        tp1_eur = pred_engine.get("take_profit_1_eur", round(current_price_eur + daily_atr_eur * 1.5, 2))
        tp2_eur = pred_engine.get("take_profit_2_eur", round(current_price_eur + daily_atr_eur * 3.0, 2))
        sl_eur = pred_engine.get("stop_loss_eur", round(current_price_eur - daily_atr_eur * 1.5, 2))

        # Expected Move a 5 giorni
        expected_move_5d_eur = pred_engine.get("expected_move_5d_eur", round(daily_atr_eur * np.sqrt(5), 2))

        return {
            "symbol": symbol,
            "asset_name": asset_name,
            "current_price_eur": round(current_price_eur, 2),
            "currency": "EUR",
            "bias_direction": bias,
            "conviction_score": f"{conviction_pct}%",
            "time_horizon": horizon,
            "target_tp1_eur": tp1_eur,
            "target_tp2_eur": tp2_eur,
            "stop_loss_eur": sl_eur,
            "risk_reward_ratio": pred_engine.get("risk_reward_tp1", "1:1.5"),
            "daily_atr_eur": daily_atr_eur,
            "expected_move_5d_eur": expected_move_5d_eur,
            "volatility_cone_5d": pred_engine.get("forecast_cone_5d_eur", ""),
            "monte_carlo": {
                "median_price_20d_eur": median_mc_eur,
                "ci_68_range_eur": ci_68,
                "ci_95_range_eur": ci_95,
                "prob_positive_trend": f"{prob_pos_mc:.1f}%",
                "var_95_eur": mc_data.get("var_95_eur", 0.0)
            },
            "statistical_metrics": {
                "z_score": z_score,
                "rsi_14": round(rsi_val, 1),
                "mean_reversion_prob": pred_engine.get("mean_reversion_probability", "50%"),
                "trend_macro": pred_engine.get("trend_macro", "Neutrale")
            },
            "cycles_and_waves": {
                "hurst_phase": hurst_data.get("descrizione_battleplan", "Fase ciclica neutrale"),
                "tempo_battleplan": hurst_data.get("tempo_battleplan", ""),
                "elliott_phase": elliott_data.get("wave_label", "Fase non determinabile"),
                "fld_target": hurst_data.get("hurst_fld_signal", "")
            },
            "macro_backdrop": {
                "vix": macro_data.get("vix_value"),
                "vix_regime": macro_data.get("vix_regime"),
                "tnx_10y_yield": macro_data.get("tnx_10y_yield")
            }
        }
