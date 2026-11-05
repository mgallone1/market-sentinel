"""
Signal & Strategy Generator
Motore di sintesi che combina Analisi Tecnica, Fondamentale e News Sentiment
per generare tesi d'investimento strutturate con livelli di Rischio/Rendimento.
"""

from typing import Dict, Any, Optional

class SignalGeneratorService:
    @staticmethod
    def generate_trade_setup(
        ticker: str,
        technical: Dict[str, Any],
        fundamentals: Dict[str, Any],
        news_sentiment_score: float = 0.0
    ) -> Dict[str, Any]:
        """
        Produce una scheda operativa completa con tesi rialzista, tesi ribassista,
        prezzi chiave e ratio rischio/rendimento.
        """
        price = technical.get("current_price", 0.0)
        rsi = technical.get("rsi")
        sma_20 = technical.get("sma_20")
        sma_50 = technical.get("sma_50")
        sma_200 = technical.get("sma_200")
        vol_ratio = technical.get("volume_ratio", 1.0)
        recent_high = technical.get("recent_high", price * 1.1)
        recent_low = technical.get("recent_low", price * 0.9)

        if price <= 0:
            return {
                "ticker": ticker,
                "status": "DATI_INSUFFICIENTI",
                "verdict": "Dati di mercato non disponibili",
                "score": 0
            }

        # Calcolo punteggio multi-fattoriale (-10 a +10)
        score = 0
        bull_factors = []
        bear_factors = []

        # 1. Fattore Trend (Medie Mobili)
        if sma_50 and sma_200:
            if price > sma_50 > sma_200:
                score += 3
                bull_factors.append("Trend rialzista primario (Prezzo > SMA50 > SMA200 - Golden Setup)")
            elif price < sma_50 < sma_200:
                score -= 3
                bear_factors.append("Trend ribassista strutturale (Prezzo < SMA50 < SMA200 - Death Cross)")
            elif price > sma_50:
                score += 1
                bull_factors.append("Prezzo sopra la media mobile a 50 giorni")
            else:
                score -= 1
                bear_factors.append("Prezzo sotto la media mobile a 50 giorni")

        # 2. Fattore Momentum (RSI)
        if rsi is not None:
            if rsi < 32:
                score += 2
                bull_factors.append(f"RSI in forte ipervenduto ({rsi}), potenziale rimbalzo tecnico")
            elif rsi > 70:
                score -= 2
                bear_factors.append(f"RSI in forte ipercomprato ({rsi}), rischio ritracciamento/prese di profitto")
            elif 45 <= rsi <= 60:
                score += 1
                bull_factors.append(f"RSI in zona di consolidamento costruttivo ({rsi})")

        # 3. Fattore Volumi
        if vol_ratio >= 1.5:
            if technical.get("change_pct", 0) > 0:
                score += 2
                bull_factors.append(f"Volume anomalo in acquisto ({vol_ratio}x rispetto alla media)")
            else:
                score -= 2
                bear_factors.append(f"Volume anomalo in vendita ({vol_ratio}x rispetto alla media)")

        # 4. Fattore News Sentiment
        if news_sentiment_score > 1.0:
            score += 2
            bull_factors.append("Sentiment delle ultime notizie positivo/catalyst favorevole")
        elif news_sentiment_score < -1.0:
            score -= 2
            bear_factors.append("Sentiment delle ultime notizie negativo/pressione mediatica")

        # 5. Determinazione Livelli Operativi
        # Supporto dinamico (invalidazione) e Target
        support_level = sma_50 if sma_50 and sma_50 < price else (price * 0.94)
        # Se c'è un minimo recente vicino, usiamo quello
        if recent_low < price and (price - recent_low) / price < 0.10:
            support_level = recent_low * 0.98

        resistance_level = recent_high if recent_high > price else (price * 1.12)
        # Se il target di consenso degli analisti è disponibile e coerente, consideriamolo
        analyst_target = fundamentals.get("target_mean_price")
        if analyst_target and analyst_target > price:
            target_price = round(float(analyst_target), 2)
        else:
            target_price = round(resistance_level, 2)

        stop_loss = round(support_level, 2)
        risk = max(price - stop_loss, price * 0.02)
        reward = max(target_price - price, price * 0.04)
        rr_ratio = round(reward / risk, 2) if risk > 0 else 1.0

        # Verdetto Finale
        if score >= 4:
            verdict = "ACCUMULO RIALZISTA (BULLISH)"
            verdict_badge = "🟢 FORTE BUY SETUP"
            action_advice = "Impostare acquisto sulla forza o su lieve ritracciamento verso supporto."
        elif score >= 2:
            verdict = "MODERATAMENTE POSITIVO (MILD BUY)"
            verdict_badge = "🟡 BUY SELETTIVO"
            action_advice = "Monitorare la tenuta del supporto per ingressi frazionati."
        elif score <= -4:
            verdict = "RIBASSISTA (BEARISH / SHORT)"
            verdict_badge = "🔴 RISCHIO ELEVATO / EVITARE"
            action_advice = "Evitare acquisti; attendere stabilizzazione o considerare prese di profitto."
        elif score <= -2:
            verdict = "MODERATAMENTE DEBOLE"
            verdict_badge = "🟠 CAUTELA / NEUTRALE"
            action_advice = "Consolidamento fragile o prese di beneficio in atto."
        else:
            verdict = "NEUTRALE / ATTESA SETUP"
            verdict_badge = "⚪ FASE LATERALE"
            action_advice = "Attendere la rottura di resistenze chiave o scarico dei volumi."

        return {
            "ticker": ticker,
            "company_name": fundamentals.get("short_name", ticker),
            "sector": fundamentals.get("sector", "N/D"),
            "current_price": price,
            "currency": fundamentals.get("currency", "USD"),
            "score": score,
            "verdict": verdict,
            "verdict_badge": verdict_badge,
            "action_advice": action_advice,
            "entry_zone": f"{round(price * 0.99, 2)} - {round(price * 1.01, 2)}",
            "target_price": target_price,
            "stop_loss": stop_loss,
            "risk_reward_ratio": f"1 : {rr_ratio}",
            "bull_factors": bull_factors if bull_factors else ["Nessun catalizzatore rialzista predominante"],
            "bear_factors": bear_factors if bear_factors else ["Nessuna criticità tecnica imminente rilevata"]
        }
