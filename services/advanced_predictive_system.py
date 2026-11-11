"""
Advanced Predictive System: Monte Carlo, VIX Term Structure, Macro Yields & Elliott Waves
Motore quantitativo di livello hedge fund che integra:
1. Simulazione Monte Carlo (10.000 iterazioni a 20 e 60 sedute)
2. Monitoraggio Volatilità Implicita (VIX)
3. Macro Tassi Decennali USA (^TNX) e Dollaro (DXY)
4. Modello Frattale delle Onde di Elliott (Onda 1-5 / Correzione A-B-C)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from typing import Dict, Any, Optional

from services.market_data import MarketDataService

class AdvancedPredictiveSystem:
    @staticmethod
    def run_monte_carlo_simulation(df: pd.DataFrame, days_ahead: int = 20, num_simulations: int = 10000, eur_rate: float = 1.0) -> Dict[str, Any]:
        """
        Esegue 10.000 scenari stocastici di Monte Carlo (Geometric Brownian Motion)
        per estrarre la distribuzione di probabilità dei prezzi futuri in Euro (€).
        """
        clean_df = df.dropna(subset=["Close"]).copy()
        if clean_df.empty or len(clean_df) < 30:
            return {}

        rate = eur_rate if (eur_rate and eur_rate > 0 and not np.isnan(eur_rate)) else 1.08
        prices = clean_df["Close"].values
        current_price = float(prices[-1])
        current_price_eur = current_price / rate

        # Rendimenti logaritmici giornalieri privi di nan
        log_returns = np.diff(np.log(prices))
        log_returns = log_returns[~np.isnan(log_returns)]
        if len(log_returns) < 10:
            return {}

        mu = float(np.mean(log_returns))
        sigma = float(np.std(log_returns))
        if sigma <= 0 or np.isnan(sigma):
            sigma = 0.01

        # Generazione matrice casuale normale (10.000 x days_ahead)
        random_shocks = np.random.normal(loc=0, scale=1, size=(num_simulations, days_ahead))
        
        # Drift giornaliero corretto per volatilità (Itô's Lemma)
        drift = mu - 0.5 * (sigma ** 2)
        daily_log_returns = drift + sigma * random_shocks
        cumulative_returns = np.exp(np.cumsum(daily_log_returns, axis=1))
        
        # Prezzi finali simulati al giorno 'days_ahead'
        final_prices_eur = (current_price * cumulative_returns[:, -1]) / rate

        # Percentili statistici
        p05 = float(np.percentile(final_prices_eur, 5))
        p16 = float(np.percentile(final_prices_eur, 16))   # -1 Sigma (68% CI)
        p50 = float(np.percentile(final_prices_eur, 50))   # Mediana attesa
        p84 = float(np.percentile(final_prices_eur, 84))   # +1 Sigma (68% CI)
        p95 = float(np.percentile(final_prices_eur, 95))   # +2 Sigma (95% CI)

        var_95_eur = max(0.0, current_price_eur - p05)
        prob_positive = float(np.mean(final_prices_eur > current_price_eur) * 100)

        return {
            "days_ahead": days_ahead,
            "median_price_eur": round(p50, 2),
            "ci_68_range_eur": f"{round(p16, 2)} € - {round(p84, 2)} €",
            "ci_95_range_eur": f"{round(p05, 2)} € - {round(p95, 2)} €",
            "var_95_eur": round(var_95_eur, 2),
            "probability_positive_trend": f"{prob_positive:.1f}%",
            "daily_sigma_pct": round(sigma * 100, 2),
            "annualized_vol_pct": round(sigma * np.sqrt(252) * 100, 2)
        }

    @staticmethod
    def get_macro_market_context() -> Dict[str, Any]:
        """
        Recupera in tempo reale il quadro macroeconomico globale:
        - Indice di Volatilità VIX (^VIX)
        - Rendimento Treasury USA a 10 Anni (^TNX)
        - Tasso EUR/USD
        """
        eur_rate = MarketDataService.get_eur_usd_rate()
        vix_val = 22.5
        tnx_val = 4.35

        try:
            macro_data = yf.download(["^VIX", "^TNX"], period="5d", interval="1d", group_by="ticker", threads=True, progress=False)
            if "^VIX" in macro_data and not macro_data["^VIX"].empty:
                vix_val = float(macro_data["^VIX"]["Close"].dropna().iloc[-1])
            if "^TNX" in macro_data and not macro_data["^TNX"].empty:
                tnx_val = float(macro_data["^TNX"]["Close"].dropna().iloc[-1])
        except Exception as e:
            print(f"[AdvancedPredictiveSystem] Errore macro data: {e}")

        # Regime di Volatilità VIX
        if vix_val >= 30.0:
            vix_regime = "Forte Panico / Stress Sistemico (VIX elevato)"
        elif vix_val >= 20.0:
            vix_regime = "Volatilità Sopra la Media / Avversione al Rischio"
        elif vix_val <= 14.0:
            vix_regime = "Compiacenza / Volatilità Minima"
        else:
            vix_regime = "Fase Fisiologica di Equilibrio"

        return {
            "vix_value": round(vix_val, 2),
            "vix_regime": vix_regime,
            "tnx_10y_yield": round(tnx_val, 2),
            "eur_usd_rate": round(eur_rate, 4)
        }

    @staticmethod
    def detect_elliott_wave_phase(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analisi euristica della struttura frattale delle Onde di Elliott:
        Verifica se siamo in Onda 3 (impulsiva), Onda 4 (correttiva/ritracciamento)
        oppure in una correzione maggiore a 3 onde A-B-C.
        """
        if df.empty or len(df) < 50:
            return {"wave_label": "Non definibile", "analysis": ""}

        prices = df["Close"].values
        high_60 = float(np.max(prices[-60:]))
        low_60 = float(np.min(prices[-60:]))
        curr = float(prices[-1])

        # Ampiezza del range
        total_range = high_60 - low_60
        retrace = (high_60 - curr) / total_range if total_range > 0 else 0.0

        # Regole di Elliott:
        # Se il ritracciamento dai massimi è tra il 23.6% e il 38.2%: tipica ONDA 4 correttiva all'interno di un trend rialzista
        if 0.20 <= retrace <= 0.40:
            return {
                "wave_label": "🌊 ONDA 4 CORRETTIVA DI ELLIOTT (Trend Primario Preservato)",
                "analysis": "Il ribasso attuale presenta le caratteristiche di un'Onda 4 correttiva complessa. La struttura impulsiva di fondo non è compromessa: al termine di questa fase correttiva è attesa l'Onda 5 verso nuovi massimi."
            }
        elif retrace > 0.45:
            return {
                "wave_label": "📉 STRUTTURA CORRETTIVA MAGGIORE A-B-C",
                "analysis": "L'ampiezza della discesa ha superato la soglia di un'onda 4 fisiologica. Il mercato sta completando un ciclo correttivo a tre onde (A-B-C). Il prossimo rimbalzo costituirà l'Onda B di ritracciamento prima del consolidamento definitivo."
            }
        else:
            return {
                "wave_label": "🚀 ONDA 3 O 5 IMPULSIVA ESPANSIVA",
                "analysis": "Prezzi vicini ai massimi storici con forte spinta direzionale."
            }
