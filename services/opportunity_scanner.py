"""
Opportunity Scanner Service
Scanner quantitativo che analizza i titoli in tempo reale,
calcola lo sconto statistico (Z-Score & RSI) e seleziona le migliori occasioni.
"""

from typing import List, Dict, Any
import yfinance as yf
import pandas as pd
from services.market_data import MarketDataService
from services.technical_analysis import TechnicalAnalysisService
from services.predictive_engine import PredictiveTradingEngine

CANDIDATES = [
    ("NVDA", "NVIDIA Corp"),
    ("TSM", "Taiwan Semiconductor"),
    ("ASML", "ASML Holding"),
    ("AMD", "Advanced Micro Devices"),
    ("AVGO", "Broadcom Inc"),
    ("ARM", "ARM Holdings"),
    ("MRVL", "Marvell Technology"),
    ("TSLA", "Tesla Inc"),
    ("AAPL", "Apple Inc"),
    ("MSFT", "Microsoft Corp"),
    ("AMZN", "Amazon.com"),
    ("GOOGL", "Alphabet Inc"),
    ("META", "Meta Platforms"),
    ("SMH", "VanEck Semiconductor ETF"),
    ("XDEM.DE", "Xtrackers MSCI World Momentum ETF"),
    ("XDWD.DE", "Xtrackers MSCI World ETF"),
    ("BY6.F", "BYD Company"),
    ("UCG.MI", "UniCredit"),
    ("ISP.MI", "Intesa Sanpaolo"),
    ("RACE.MI", "Ferrari"),
    ("BTC-EUR", "Bitcoin"),
    ("PLTR", "Palantir Technologies"),
    ("CRWD", "CrowdStrike Holdings"),
    ("QCOM", "Qualcomm Inc")
]

class OpportunityScannerService:
    @staticmethod
    def scan_best_opportunities(top_n: int = 10) -> List[Dict[str, Any]]:
        """
        Scansiona i mercati in modalità batch ultra-rapida e individua le migliori 10 asimmetrie di prezzo in Euro (€).
        """
        results = []
        eur_rate = MarketDataService.get_eur_usd_rate()
        tickers = [c[0] for c in CANDIDATES]

        try:
            # Scaricamento parallelo batch di tutto il paniere in 2-3 secondi
            batch_df = yf.download(tickers, period="3mo", interval="1d", group_by="ticker", threads=True, progress=False)
        except Exception as e:
            print(f"[OpportunityScannerService] Errore batch download: {e}")
            batch_df = None

        for ticker, name in CANDIDATES:
            try:
                if batch_df is not None and ticker in batch_df:
                    df = batch_df[ticker].dropna().copy()
                else:
                    df = MarketDataService.get_ticker_history(ticker, period="3mo", interval="1d")

                if df.empty or len(df) < 20:
                    continue

                fund = MarketDataService.get_ticker_fundamentals(ticker)
                is_eur = MarketDataService.is_euro_asset(ticker, fund)
                rate = 1.0 if is_eur else eur_rate

                df_tech = TechnicalAnalysisService.calculate_indicators(df)
                tech_sum = TechnicalAnalysisService.get_latest_technical_summary(df_tech)
                pred = PredictiveTradingEngine.generate_prediction_and_trade_plan(df, ticker, currency="EUR" if is_eur else "USD")

                price_eur = tech_sum.get("current_price", 0.0) / rate
                rsi = tech_sum.get("rsi", 50.0) or 50.0
                z_score = pred.get("z_score", 0.0)

                # Controllo quotazione Lang & Schwarz (Trade Republic) se disponibile
                tr_quote = MarketDataService.get_trade_republic_ls_quote(ticker)
                tr_bid = round(tr_quote["bid"], 2) if "bid" in tr_quote else None
                tr_ask = round(tr_quote["ask"], 2) if "ask" in tr_quote else None

                # Score di sconto statistico: più l'RSI e lo Z-Score sono bassi, più l'occasione è forte
                discount_score = (70 - rsi) + (abs(z_score) * 15 if z_score < 0 else -10)

                results.append({
                    "ticker": ticker,
                    "name": name,
                    "price_eur": round(price_eur, 2),
                    "tr_bid": tr_bid,
                    "tr_ask": tr_ask,
                    "change_pct": tech_sum.get("change_pct", 0.0),
                    "rsi": round(rsi, 2),
                    "z_score": round(z_score, 2),
                    "rebound_prob": pred.get("mean_reversion_probability", "50%"),
                    "tp1_eur": pred.get("take_profit_1_eur", 0.0),
                    "sl_eur": pred.get("stop_loss_eur", 0.0),
                    "rr_ratio": pred.get("risk_reward_tp1", "1:1"),
                    "discount_score": round(discount_score, 2),
                    "primary_action": pred.get("primary_action", "")
                })
            except Exception as e:
                print(f"[OpportunityScannerService] Errore analisi {ticker}: {e}")

        # Ordina per punteggio di sconto decrescente
        results.sort(key=lambda x: x["discount_score"], reverse=True)
        return results[:top_n]
