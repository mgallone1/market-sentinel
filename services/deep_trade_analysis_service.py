"""
Deep Trade Analysis Service
Calcola la diagnostica quantitativa avanzata su singoli asset / trade aperti:
- Timeframe di Analisi Esplicito (Timeframe Daily 1D per Onde e Hurst, 4H per Trend)
- Ciclica di Hurst (con curva FLD sovrapposta nel grafico)
- Battleplan a 4 Tempi di Giuseppe Migliorino (con curva teorica sinusoidale sovrapposta)
- Onde di Elliott con identificazione visiva dei punti cardine (Pivot High/Low, ritracciamenti Fibonacci)
- Simulazione Stocastica Monte Carlo (5.000 iterazioni geometric brownian motion)
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
_CACHE_TTL = 90.0 # 90s di cache in memoria per asset

def get_deep_trade_forecast(symbol: str, tf: str = "1d") -> Dict[str, Any]:
    """Genera l'analisi ciclica, ondulatoria e stocastica per un simbolo (es. XRPUSDT, BTCUSDT) sul timeframe richiesto (1d, 4h, 1h)."""
    now = time.time()
    clean_sym = symbol.upper().replace("/", "").replace("-", "")
    tf_clean = tf.lower().strip()
    cache_key = f"{clean_sym}_{tf_clean}"

    if cache_key in _ANALYSIS_CACHE and (now - _ANALYSIS_CACHE[cache_key]["time"]) < _CACHE_TTL:
        return _ANALYSIS_CACHE[cache_key]["data"]

    # Mappatura ticker yfinance
    yf_ticker = clean_sym
    if clean_sym.endswith("USDT"):
        base = clean_sym.replace("USDT", "")
        yf_ticker = f"{base}-USD"
    elif clean_sym.endswith("USD"):
        base = clean_sym.replace("USD", "")
        yf_ticker = f"{base}-USD"

    try:
        # Configurazione timeframe dinamica: (period, interval, label)
        if tf_clean == "1h":
            period_str = "1mo"
            interval_str = "1h"
            timeframe_label = "1H (Orario - 1 Mese / Intraday)"
        elif tf_clean == "4h":
            period_str = "3mo"
            interval_str = "1h" # yfinance aggrega orario a 4h o usa 1h con ricampionamento
            timeframe_label = "4H (4 Ore - 3 Mesi / Swing)"
        else:
            tf_clean = "1d"
            period_str = "6mo"
            interval_str = "1d"
            timeframe_label = "1D (Giornaliero - 6 Mesi / Macro)"

        df = yf.download(yf_ticker, period=period_str, interval=interval_str, progress=False)
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)

        clean_df = df.dropna(subset=["Close"]).copy()
        if tf_clean == "4h" and len(clean_df) >= 8:
            # Ricampiona a 4H se richiesto 4h
            clean_df = clean_df.resample('4h').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()

        if clean_df.empty or len(clean_df) < 20:
            # Fallback sicuro a 1D
            clean_df = yf.download(yf_ticker, period="6mo", interval="1d", progress=False).dropna()
            if hasattr(clean_df.columns, 'levels') and len(clean_df.columns.levels) > 1:
                clean_df.columns = clean_df.columns.get_level_values(0)
            timeframe_label = "1D (Giornaliero - Fallback)"

        # 1. Ciclica di Hurst & Giuseppe Migliorino
        cycle_metrics = HurstMigliorinoCycleService.calculate_cycle_metrics(clean_df)

        # 2. Onde di Elliott
        elliott = AdvancedPredictiveSystem.detect_elliott_wave_phase(clean_df)

        # 3. Wyckoff e FVG/Fibonacci
        wyckoff = CycleAnalystService.detect_wyckoff_phase(clean_df)
        fib = CycleAnalystService.calculate_fibonacci_and_fvg(clean_df)

        # 4. Simulazione Stocastica Monte Carlo (15 barre proiettate)
        days_ahead = 15
        mc_summary = AdvancedPredictiveSystem.run_monte_carlo_simulation(clean_df, days_ahead=days_ahead, num_simulations=5000)

        # 5. Generazione serie numeriche per il Grafico Multilivello (ultimi 25 giorni + 15 giorni previsionali)
        prices = clean_df["Close"].values
        recent_window = 25
        recent_hist = [round(float(p), 4) for p in prices[-recent_window:]]
        last_price = float(recent_hist[-1])

        # A. Hurst FLD (Future Line of Demarcation a 20 periodi: trasla indietro di 10 periodi)
        half_fld = 10
        fld_curve = []
        for i in range(len(prices) - recent_window, len(prices)):
            idx_fld = max(0, i - half_fld)
            fld_curve.append(round(float(prices[idx_fld]), 4))

        # B. Battleplan di Migliorino (Onda composita a 4 tempi sinusoidale modulata sul prezzo)
        bars_since_min = int(cycle_metrics.get("bars_since_mensile_min", 2) or 2)
        # Costruiamo la sinusoide teorica del ciclo T+2 (32 barre) composto da 4 sottocicli T da 8 barre
        t_indices = np.arange(recent_window)
        # Ampiezza stimata dal range recente
        amp = (max(recent_hist) - min(recent_hist)) * 0.35 if (max(recent_hist) - min(recent_hist)) > 0 else (last_price * 0.05)
        # Allineiamo la fase al minimo ciclico rilevato
        phase_offset = bars_since_min
        sine_t2 = np.sin(2 * np.pi * (t_indices - phase_offset) / 32)
        sine_t = 0.45 * np.sin(2 * np.pi * (t_indices - phase_offset) / 8)
        base_line = np.mean(recent_hist)
        battleplan_curve = [round(float(base_line + amp * (sine_t2[k] + sine_t[k])), 4) for k in range(recent_window)]

        # C. Simulazione Monte Carlo
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

        # Genera label temporali leggibili
        hist_labels = [f"-{recent_window-i}g" for i in range(recent_window)]
        forecast_labels = [f"+{i}g" for i in range(days_ahead + 1)]

        
        # Calcolo Segnale Azionabile Matematico (Zero Ambiguità)
        # Combinazione: FLD Cross + Quarto Battleplan + Onda Elliott + P(Up) Monte Carlo
        is_fld_bullish = last_price >= fld_curve[-1]
        bars_into_cycle = int(cycle_metrics.get("bars_since_mensile_min", 2) or 2)
        p_up_num = float(mc_summary.get("probability_positive_trend", "50%").replace("%", "").strip() or 50)
        
        # Livelli Chiave Operativi
        entry_ref = last_price
        fld_target = fld_curve[-1]
        fib_golden = float(fib.get("fib_618_golden_pocket_eur", last_price * 1.08))
        fib_support = float(fib.get("fib_382_eur", last_price * 0.96))
        
        # Verdetto Tattico
        if is_fld_bullish and bars_into_cycle <= 12 and p_up_num >= 52:
            action_verdict = "COMPRA / ACCUMULO RIALZISTA"
            action_color = "green"
            action_badge = "LONG"
            action_reason = f"Prezzo sopra FLD (${fld_target:.2f}), ciclo al {bars_into_cycle}° tempo (spinta rialzista) e Monte Carlo favorevole ({p_up_num}%)."
            action_strategy = f"Entrata LONG consigliata. Target primario a ${fib_golden:.2f} (+{((fib_golden/entry_ref)-1)*100:.1f}%), Stop Loss protettivo sotto ${fld_target*0.985:.2f}."
        elif not is_fld_bullish and bars_into_cycle >= 20:
            action_verdict = "SHORT / HEDGE PROTETTIVO"
            action_color = "red"
            action_badge = "SHORT"
            action_reason = f"Prezzo sotto FLD (${fld_target:.2f}), ciclo nella seconda metà discendente (barra {bars_into_cycle}/32) verso il pavimento ciclico."
            action_strategy = f"Fase discendente attiva. Se hai posizioni long riduci l'esposizione. Target ribasso verso ${fib_support:.2f} (-{abs(((fib_support/entry_ref)-1)*100):.1f}%)."
        elif bars_into_cycle >= 28:
            action_verdict = "PREPARAZIONE ACCUMULO (MINIMO IMMINENTE)"
            action_color = "amber"
            action_badge = "ATTENDI INVERSIONE"
            action_reason = f"Mancano ~{max(1, 32 - bars_into_cycle)} barre alla morte del ciclo: preparare la liquidità per l'inversione sui minimi."
            action_strategy = f"Non vendere sui minimi: attendi la rottura al rialzo della FLD (${fld_target:.2f}) per aprire posizioni long a basso rischio."
        else:
            action_verdict = "NEUTRALE / MONITORAGGIO ATTIVO"
            action_color = "amber"
            action_badge = "NEUTRALE"
            action_reason = "Fase di transizione tra onde cicliche in attesa di breakout direzionale confermato dalla FLD."
            action_strategy = f"Attendere un superamento deciso di ${fld_target:.2f} prima di aprire posizioni aggressive."

        actionable_plan = {
            "verdict": action_verdict,
            "badge": action_badge,
            "color": action_color,
            "reason": action_reason,
            "strategy": action_strategy,
            "target_tp": round(fib_golden if action_badge == "LONG" else fib_support, 4),
            "target_sl": round(fld_target * 0.985 if action_badge == "LONG" else fld_target * 1.015, 4),
            "bars_to_reversal": max(1, 32 - bars_into_cycle) if bars_into_cycle >= 16 else max(1, 16 - bars_into_cycle)
        }

        result = {
            "symbol": clean_sym,
            "current_price": last_price,
            "timeframe": timeframe_label,
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
                "analysis": elliott.get("analysis", "Struttura frattale in evoluzione."),
                "fib_levels": {
                    "fib_382": fib.get("fib_382_eur", round(last_price * 1.05, 2)),
                    "fib_500": fib.get("fib_50_eur", round(last_price * 1.08, 2)),
                    "fib_618": fib.get("fib_618_golden_pocket_eur", round(last_price * 1.12, 2)),
                    "fvg_note": fib.get("fvg_note", "Nessun Fair Value Gap aperto.")
                }
            },
            "wyckoff": {
                "phase": wyckoff.get("phase", "Neutro"),
                "bias": wyckoff.get("bias", "Neutro")
            },
            "actionable": actionable_plan,
            "monte_carlo": {
                "probability_positive": mc_summary.get("probability_positive_trend", "50%"),
                "median_forecast": mc_summary.get("median_price_eur", last_price),
                "ci_95_range": mc_summary.get("ci_95_range_eur", f"${p05_curve[-1]} - ${p95_curve[-1]}"),
                "annualized_vol": mc_summary.get("annualized_vol_pct", 45.0)
            },
            "chart_data": {
                "historical": recent_hist,
                "historical_labels": hist_labels,
                "hurst_fld": fld_curve,
                "battleplan_migliorino": battleplan_curve,
                "forecast_p50": p50_curve,
                "forecast_p05": p05_curve,
                "forecast_p95": p95_curve,
                "forecast_labels": forecast_labels
            }
        }

        _ANALYSIS_CACHE[cache_key] = {
            "time": now,
            "data": result
        }
        return result
    except Exception as e:
        return {"error": f"Errore calcolo analisi avanzata: {str(e)}", "symbol": clean_sym}
