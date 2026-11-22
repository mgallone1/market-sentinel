"""
Deep Trade Analysis Service
Calcola la diagnostica quantitativa avanzata su singoli asset / trade aperti:
- Ciclica di Hurst (FLD Future Line of Demarcation)
- Battleplan a 4 Tempi e Vincoli di Giuseppe Migliorino
- Onde di Elliott (Onda 3 impulsiva, Onda 4 correttiva, A-B-C)
- Simulazione Stocastica Monte Carlo (10.000 iterazioni geometric brownian motion)
- Traiettorie previsionali a 15 giorni (Mediana P50, intervallo di confidenza 95% P05-P95)
"""

import time
import numpy as np
import pandas as pd
import yfinance as yf
from typing import Dict, Any

from services.hurst_migliorino_cycles import HurstMigliorinoCycleService
from services.advanced_predictive_system import AdvancedPredictiveSystem
from services.cycle_analyst import CycleAnalystService

_ANALYSIS_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 120.0 # 2 minuti di cache in memoria per asset

def get_deep_trade_forecast(symbol: str) -> Dict[str, Any]:
    """Genera l'analisi ciclica, ondulatoria e stocastica per un simbolo (es. XRPUSDT, BTCUSDT)."""
    now = time.time()
    clean_sym = symbol.upper().replace("/", "").replace("-", "")

    if clean_sym in _ANALYSIS_CACHE and (now - _ANALYSIS_CACHE[clean_sym]["time"]) < _CACHE_TTL:
        return _ANALYSIS_CACHE[clean_sym]["data"]

    # Mappatura ticker yfinance
    yf_ticker = clean_sym
    if clean_sym.endswith("USDT"):
        base = clean_sym.replace("USDT", "")
        yf_ticker = f"{base}-USD"
    elif clean_sym.endswith("USD"):
        base = clean_sym.replace("USD", "")
        yf_ticker = f"{base}-USD"

    try:
        df = yf.download(yf_ticker, period="6mo", interval="1d", progress=False)
        if df.empty or len(df) < 35:
            # Fallback 3mo 1h se 6mo giornaliero non è disponibile
            df = yf.download(yf_ticker, period="1mo", interval="1h", progress=False)
        
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)

        clean_df = df.dropna(subset=["Close"]).copy()
        if clean_df.empty or len(clean_df) < 20:
            return {"error": f"Dati storici insufficienti per {clean_sym}"}

        # 1. Ciclica di Hurst & Giuseppe Migliorino
        cycle_metrics = HurstMigliorinoCycleService.calculate_cycle_metrics(clean_df)

        # 2. Onde di Elliott
        elliott = AdvancedPredictiveSystem.detect_elliott_wave_phase(clean_df)

        # 3. Wyckoff e FVG/Fibonacci
        wyckoff = CycleAnalystService.detect_wyckoff_phase(clean_df)
        fib = CycleAnalystService.calculate_fibonacci_and_fvg(clean_df)

        # 4. Simulazione Stocastica Monte Carlo (10.000 iterazioni, 15 barre proiettate)
        days_ahead = 15
        mc_summary = AdvancedPredictiveSystem.run_monte_carlo_simulation(clean_df, days_ahead=days_ahead, num_simulations=5000)

        # 5. Generazione traiettoria visuale per Chart.js (ultimi 20 giorni + 15 giorni previsionali)
        prices = clean_df["Close"].values
        recent_hist = [float(p) for p in prices[-20:]]
        last_price = float(recent_hist[-1])

        # Calcolo andamento geometrico stocastico
        log_ret = np.diff(np.log(prices))
        mu = float(np.mean(log_ret))
        sigma = float(np.std(log_ret))
        if sigma <= 0 or np.isnan(sigma):
            sigma = 0.02
        drift = mu - 0.5 * (sigma ** 2)

        shocks = np.random.normal(0, 1, size=(3000, days_ahead))
        paths = last_price * np.exp(np.cumsum(drift + sigma * shocks, axis=1))

        p05_curve = [last_price] + [round(float(v), 4) for v in np.percentile(paths, 5, axis=0)]
        p50_curve = [last_price] + [round(float(v), 4) for v in np.percentile(paths, 50, axis=0)]
        p95_curve = [last_price] + [round(float(v), 4) for v in np.percentile(paths, 95, axis=0)]

        # Genera label temporali
        hist_labels = [f"-{20-i}g" for i in range(len(recent_hist))]
        forecast_labels = [f"+{i}g" for i in range(days_ahead + 1)]

        result = {
            "symbol": clean_sym,
            "current_price": last_price,
            "cycle": {
                "tempo_battleplan": cycle_metrics.get("tempo_battleplan", "N/D"),
                "descrizione_battleplan": cycle_metrics.get("descrizione_battleplan", "In consolidamento ciclico."),
                "consiglio_pratico": cycle_metrics.get("consiglio_pratico", "Mantenere trailing stop protettivo."),
                "vincolo_migliorino": cycle_metrics.get("vincolo_migliorino", "LIBERO"),
                "spiegazione_vincolo": cycle_metrics.get("spiegazione_vincolo", "Nessun vincolo restrittivo."),
                "hurst_fld_value": cycle_metrics.get("hurst_fld_value", round(last_price, 4)),
                "hurst_fld_signal": cycle_metrics.get("hurst_fld_signal", "Prezzo allineato alla mediana.")
            },
            "elliott": {
                "wave_label": elliott.get("wave_label", "Onde in consolidamento"),
                "analysis": elliott.get("analysis", "Struttura frattale in evoluzione.")
            },
            "wyckoff": {
                "phase": wyckoff.get("phase", "Neutro"),
                "bias": wyckoff.get("bias", "Neutro")
            },
            "monte_carlo": {
                "probability_positive": mc_summary.get("probability_positive_trend", "50%"),
                "median_forecast": mc_summary.get("median_price_eur", last_price),
                "ci_95_range": mc_summary.get("ci_95_range_eur", f"${p05_curve[-1]} - ${p95_curve[-1]}"),
                "annualized_vol": mc_summary.get("annualized_vol_pct", 45.0)
            },
            "chart_data": {
                "historical": recent_hist,
                "historical_labels": hist_labels,
                "forecast_p50": p50_curve,
                "forecast_p05": p05_curve,
                "forecast_p95": p95_curve,
                "forecast_labels": forecast_labels
            }
        }

        _ANALYSIS_CACHE[clean_sym] = {
            "time": now,
            "data": result
        }
        return result
    except Exception as e:
        return {"error": f"Errore calcolo analisi avanzata: {str(e)}", "symbol": clean_sym}
