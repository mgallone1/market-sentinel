"""
Opportunity Scanner Service
Scanner quantitativo che analizza i titoli in tempo reale,
calcola lo sconto statistico (Z-Score & RSI) e seleziona le migliori occasioni.
"""

from typing import List, Dict, Any
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
    ("RACE.MI", "Ferrari")
]

class OpportunityScannerService:
    @staticmethod
    def scan_best_opportunities(top_n: int = 3) -> List[Dict[str, Any]]:
        """
        Scansiona i mercati e individua le migliori asimmetrie di prezzo in Euro (€).
        """
        results = []
        eur_rate = MarketDataService.get_eur_usd_rate()

        for ticker, name in CANDIDATES:
            df = MarketDataService.get_ticker_history(ticker, period="3mo", interval="1d")
            if df.empty or len(df) < 20:
                continue

            fund = MarketDataService.get_ticker_fundamentals(ticker)
            is_usd = fund.get("currency", "USD").upper() == "USD"
            rate = eur_rate if is_usd else 1.0

            df_tech = TechnicalAnalysisService.calculate_indicators(df)
            tech_sum = TechnicalAnalysisService.get_latest_technical_summary(df_tech)
            pred = PredictiveTradingEngine.generate_prediction_and_trade_plan(df, ticker, currency="USD" if is_usd else "EUR")

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
                "rsi": rsi,
                "z_score": z_score,
                "rebound_prob": pred.get("mean_reversion_probability", "50%"),
                "tp1_eur": pred.get("take_profit_1_eur", 0.0),
                "sl_eur": pred.get("stop_loss_eur", 0.0),
                "rr_ratio": pred.get("risk_reward_tp1", "1:1"),
                "discount_score": discount_score,
                "primary_action": pred.get("primary_action", "")
            })

        # Ordina per punteggio di sconto decrescente
        results.sort(key=lambda x: x["discount_score"], reverse=True)
        return results[:top_n]
