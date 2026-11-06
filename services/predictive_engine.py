"""
Predictive & Quantitative Trading Engine
Modelli matematici e previsionali per il trading:
- Cono di Volatilità e Range Previsionale (ATR & Volatilità Storica)
- Z-Score & Probabilità di Mean Reversion (Rimbalzo Statistico)
- Breakout & Trend Probability
- Target Dinamici R/R e Stop Loss Strutturali
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from services.market_data import MarketDataService

class PredictiveTradingEngine:
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calcola l'Average True Range (ATR) per stimare la volatilità reale."""
        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return true_range.ewm(alpha=1/period, adjust=False).mean()

    @classmethod
    def generate_prediction_and_trade_plan(cls, df: pd.DataFrame, ticker: str, currency: str = "USD") -> Dict[str, Any]:
        """
        Genera previsioni statistiche a 1-5 giorni e piano di trade completo interamente convertito in EURO (€).
        """
        if df.empty or len(df) < 20:
            return {"error": "Dati insufficienti per il modello predittivo"}

        data = df.copy()
        raw_price = float(data["Close"].iloc[-1])
        
        # Tasso di conversione in Euro: solo se lo strumento è in USD e NON è già in Euro
        is_eur = (currency.upper() == "EUR") or MarketDataService.is_euro_asset(ticker)
        eur_rate = 1.0 if is_eur else MarketDataService.get_eur_usd_rate()
        
        # Prezzo convertito in Euro (€)
        current_price_eur = raw_price / eur_rate if eur_rate > 0 else raw_price
        
        # 1. Calcolo ATR e Volatilità Giornaliera (convertito in Euro)
        atr_series = cls.calculate_atr(data, 14)
        raw_atr = float(atr_series.iloc[-1])
        daily_atr_eur = raw_atr / eur_rate
        daily_vol_pct = (raw_atr / raw_price) * 100

        # Cono di volatilità stimato (Expected Move a 5 giorni: ATR * sqrt(5))
        expected_move_5d_eur = daily_atr_eur * np.sqrt(5)
        high_projection_5d_eur = round(current_price_eur + expected_move_5d_eur, 2)
        low_projection_5d_eur = round(max(current_price_eur - expected_move_5d_eur, 0.01), 2)

        # 2. Z-Score (Distanza statistica dalla media a 20 periodi)
        sma20 = float(data["Close"].rolling(20).mean().iloc[-1])
        std20 = float(data["Close"].rolling(20).std().iloc[-1])
        z_score = (raw_price - sma20) / std20 if std20 > 0 else 0.0

        # 3. Momentum & Trend
        sma50 = float(data["Close"].rolling(50).mean().iloc[-1]) if len(data) >= 50 else sma20
        trend_direction = "Rialzista" if raw_price > sma50 else "Ribassista"

        # 4. Probabilità di Rimbalzo Statistico (Mean Reversion Probability)
        if z_score <= -2.0:
            rebound_prob = min(88, int(60 + abs(z_score) * 10))
            forecast_summary = f"Prezzo in forte ipervenduto statistico (Z-Score {z_score:.2f}). Probabilità di rimbalzo a 3-5 sedute stimata all'{rebound_prob}%."
            primary_action = "ACCUMULO PER RIMBALZO (LONG STATISTICO)"
        elif z_score >= 2.0:
            rebound_prob = min(85, int(60 + z_score * 10))
            forecast_summary = f"Prezzo in ipercomprato estremo (Z-Score {z_score:.2f}). Probabilità di ritracciamento all'{rebound_prob}%."
            primary_action = "PRESE DI PROFITTO / ATTESA PULLBACK"
        else:
            rebound_prob = 50
            forecast_summary = f"Prezzo in fascia di oscillazione fisiologica (Z-Score {z_score:.2f})."
            primary_action = "TREND FOLLOWING / MONITORAGGIO"

        # 5. Struttura Operativa del Trade (Prezzi rigorosamente in €)
        stop_distance_eur = daily_atr_eur * 1.5
        stop_loss_eur = round(current_price_eur - stop_distance_eur, 2) if primary_action.startswith("ACCUMULO") else round(current_price_eur * 0.95, 2)

        tp1_eur = round(current_price_eur + (daily_atr_eur * 1.2), 2)
        tp2_eur = round(current_price_eur + (daily_atr_eur * 2.4), 2)

        risk_eur = current_price_eur - stop_loss_eur if current_price_eur > stop_loss_eur else current_price_eur * 0.03
        reward1_eur = tp1_eur - current_price_eur
        reward2_eur = tp2_eur - current_price_eur

        rr_tp1 = round(reward1_eur / risk_eur, 2) if risk_eur > 0 else 1.0
        rr_tp2 = round(reward2_eur / risk_eur, 2) if risk_eur > 0 else 2.0

        return {
            "ticker": ticker.upper(),
            "raw_price": round(raw_price, 2),
            "current_price_eur": round(current_price_eur, 2),
            "currency": "EUR",
            "daily_atr_eur": round(daily_atr_eur, 2),
            "volatility_daily_pct": round(daily_vol_pct, 2),
            "expected_move_5d_eur": round(expected_move_5d_eur, 2),
            "forecast_cone_5d_eur": f"{low_projection_5d_eur} € - {high_projection_5d_eur} €",
            "z_score": round(z_score, 2),
            "mean_reversion_probability": f"{rebound_prob}%",
            "trend_macro": trend_direction,
            "forecast_summary": forecast_summary,
            "primary_action": primary_action,
            "take_profit_1_eur": tp1_eur,
            "take_profit_2_eur": tp2_eur,
            "stop_loss_eur": stop_loss_eur,
            "risk_reward_tp1": f"1:{rr_tp1}",
            "risk_reward_tp2": f"1:{rr_tp2}"
        }
