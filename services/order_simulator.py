"""
Trade Republic Order Simulator Service
Calcolo preciso per ordini su Trade Republic / Lang & Schwarz:
- Frazionamento quote esatto
- Ordine Limite consigliato (protezione dallo spread L&S)
- Rischio monetario esatto in Euro (€) a fronte del potenziale guadagno
"""

from typing import Dict, Any
from services.market_data import MarketDataService
from services.predictive_engine import PredictiveTradingEngine

class OrderSimulatorService:
    @staticmethod
    def simulate_order(ticker: str, budget_eur: float) -> Dict[str, Any]:
        """
        Simula un ordine d'acquisto per Trade Republic in Euro (€).
        """
        df = MarketDataService.get_ticker_history(ticker, period="3mo", interval="1d")
        if df.empty:
            return {"error": f"Nessun dato per il ticker {ticker}"}

        fund = MarketDataService.get_ticker_fundamentals(ticker)
        is_usd = fund.get("currency", "USD").upper() == "USD"
        pred = PredictiveTradingEngine.generate_prediction_and_trade_plan(df, ticker, currency="USD" if is_usd else "EUR")

        price_eur = pred["current_price_eur"]
        tp1_eur = pred["take_profit_1_eur"]
        sl_eur = pred["stop_loss_eur"]

        if price_eur <= 0:
            return {"error": "Prezzo di mercato non valido"}

        # Quote acquistabili con il budget inserito
        shares = budget_eur / price_eur
        
        # Ordine limite consigliato: 0.2% sotto il prezzo ask corrente per evitare spread
        limit_order_price = round(price_eur * 0.998, 2)

        # Rischio monetario in Euro (€)
        risk_per_share = price_eur - sl_eur
        total_risk_eur = round(shares * risk_per_share, 2)
        risk_pct = round((risk_per_share / price_eur) * 100, 2)

        # Guadagno potenziale al Take Profit 1 in Euro (€)
        gain_per_share = tp1_eur - price_eur
        total_gain_eur = round(shares * gain_per_share, 2)
        gain_pct = round((gain_per_share / price_eur) * 100, 2)

        return {
            "ticker": ticker.upper(),
            "asset_name": fund.get("short_name", ticker),
            "budget_eur": budget_eur,
            "current_price_eur": price_eur,
            "shares_to_buy": round(shares, 4),
            "suggested_order_type": "Ordine Limite (Limit Order)",
            "limit_price_eur": limit_order_price,
            "tp1_eur": tp1_eur,
            "potential_gain_eur": total_gain_eur,
            "potential_gain_pct": gain_pct,
            "sl_eur": sl_eur,
            "monetary_risk_eur": total_risk_eur,
            "monetary_risk_pct": risk_pct,
            "risk_reward_ratio": pred["risk_reward_tp1"]
        }
