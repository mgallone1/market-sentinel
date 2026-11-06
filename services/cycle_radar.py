"""
Cycle Radar & Multi-Timeframe Predictive Sentinel (Ultra-Fast Batch Mode)
Scansiona in parallelo tramite download batch (tempo < 2s)
i cicli Settimanale (T), Mensile (T+2) e Semestrale (T+4) con modelli predittivi in Euro (€).
"""

import numpy as np
import pandas as pd
import yfinance as yf
from typing import List, Dict, Any

from services.market_data import MarketDataService
from services.technical_analysis import TechnicalAnalysisService
from services.predictive_engine import PredictiveTradingEngine

WATCHED_ASSETS = [
    ("SPY", "S&P 500"),
    ("QQQ", "Nasdaq 100"),
    ("SMH", "Semiconduttori VanEck"),
    ("NVDA", "NVIDIA Corp"),
    ("TSLA", "Tesla Inc"),
    ("XDWD.DE", "MSCI World ETF (XDWD)"),
    ("XDEM.DE", "MSCI World Momentum ETF (XDEM)")
]

class CycleRadarService:
    @staticmethod
    def scan_active_cycles() -> List[Dict[str, Any]]:
        """
        Scansione batch ad alta velocità (< 2 secondi) per tutti gli indici chiave.
        """
        radar_results = []
        eur_rate = MarketDataService.get_eur_usd_rate()
        tickers = [item[0] for item in WATCHED_ASSETS]

        try:
            batch_data = yf.download(
                tickers,
                period="1y",
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False
            )
        except Exception as e:
            print(f"[CycleRadarService] Errore batch download: {e}")
            return []

        for ticker, name in WATCHED_ASSETS:
            try:
                df = batch_data[ticker].dropna().copy()
            except Exception:
                continue

            if df.empty or len(df) < 70:
                continue

            is_eur = MarketDataService.is_euro_asset(ticker)
            rate = 1.0 if is_eur else eur_rate

            # 1. Modello Predittivo
            df_tech = TechnicalAnalysisService.calculate_indicators(df)
            pred = PredictiveTradingEngine.generate_prediction_and_trade_plan(df, ticker, currency="EUR" if is_eur else "USD")
            curr_price_eur = pred["current_price_eur"]

            prices = df["Close"].values

            # 2. Ciclo Settimanale (T / Tracy: ~7 barre)
            window_t = 10
            recent_t = prices[-window_t:]
            min_t_rel = int(np.argmin(recent_t))
            bars_settimanale = len(recent_t) - 1 - min_t_rel
            bars_left_settimanale = max(1, 7 - bars_settimanale)

            # 3. Ciclo Semestrale (T+4: ~138 barre)
            window_t4 = 145
            recent_t4 = prices[-window_t4:] if len(prices) >= window_t4 else prices
            min_t4_rel = int(np.argmin(recent_t4))
            bars_semestrale = len(recent_t4) - 1 - min_t4_rel
            bars_left_semestrale = max(1, 138 - bars_semestrale)

            # Sintesi ciclica incisiva
            if bars_left_settimanale <= 2 and bars_left_semestrale <= 3:
                confluence = f"🚨 DOPPIO MINIMO IN ARRIVO: Chiusura simultanea T e T+4 (mancano ~{bars_left_settimanale} candele)."
            elif bars_settimanale <= 2:
                confluence = f"🚀 RIPARTENZA SETTIMANALE: Barra {bars_settimanale}/7 in spinta rialzista."
            else:
                confluence = f"⏳ VERSO IL MINIMO SETTIMANALE: Barra {bars_settimanale}/7 (mancano ~{bars_left_settimanale} candele)."

            radar_results.append({
                "ticker": ticker,
                "name": name,
                "price_eur": curr_price_eur,
                "confluence": confluence,
                "bars_settimanale": bars_settimanale,
                "bars_left_settimanale": bars_left_settimanale,
                "bars_semestrale": bars_semestrale,
                "bars_left_semestrale": bars_left_semestrale,
                "rebound_prob": pred["mean_reversion_probability"],
                "z_score": pred["z_score"],
                "tp1_eur": pred["take_profit_1_eur"],
                "sl_eur": pred["stop_loss_eur"],
                "risk_reward": pred["risk_reward_tp1"]
            })

        return radar_results
