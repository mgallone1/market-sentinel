"""
Cycle Analyst & Smart Money Structure Service
Modulo per l'analisi avanzata di Price Action, Cicli di Wyckoff,
Divergenze RSI, Fair Value Gaps (FVG), Volume Climax e Ritracciamenti di Fibonacci.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional

class CycleAnalystService:
    @staticmethod
    def detect_rsi_divergence(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Rileva divergenze regolari o nascoste tra Prezzo e RSI (14) sugli ultimi 30 periodi.
        """
        if df.empty or len(df) < 30 or "RSI" not in df.columns:
            return {"divergence": "Nessuna", "details": ""}

        window = df.tail(30).copy()
        prices = window["Close"].values
        rsi = window["RSI"].values

        # Trova minimi locali recenti
        min_p_recent = np.min(prices[-10:])
        min_p_prev = np.min(prices[-30:-10])
        
        idx_p_recent = np.argmin(prices[-10:]) + 20
        idx_p_prev = np.argmin(prices[-30:-10])

        rsi_at_recent = rsi[idx_p_recent]
        rsi_at_prev = rsi[idx_p_prev]

        # Divergenza Rialzista (Bullish Divergence): Prezzo fa nuovo minimo, RSI fa minimo crescente
        if min_p_recent < min_p_prev and rsi_at_recent > rsi_at_prev:
            return {
                "divergence": "🟢 DIVERGENZA RIALZISTA REGOLARE (BULLISH DIVERGENCE)",
                "details": f"Il prezzo ha aggiornato i minimi ({min_p_recent:.2f} vs {min_p_prev:.2f}) ma l'RSI mostra forza relativa crescente ({rsi_at_recent:.1f} vs {rsi_at_prev:.1f}). Tipico segnale anticipatore di esaurimento vendite."
            }

        # Divergenza Ribassista (Bearish Divergence): Prezzo fa nuovo massimo, RSI fa massimo decrescente
        max_p_recent = np.max(prices[-10:])
        max_p_prev = np.max(prices[-30:-10])
        idx_max_recent = np.argmax(prices[-10:]) + 20
        idx_max_prev = np.argmax(prices[-30:-10])

        rsi_max_recent = rsi[idx_max_recent]
        rsi_max_prev = rsi[idx_max_prev]

        if max_p_recent > max_p_prev and rsi_max_recent < rsi_max_prev:
            return {
                "divergence": "🔴 DIVERGENZA RIBASSISTA (BEARISH DIVERGENCE)",
                "details": f"Nuovo massimo di prezzo non confermato dall'oscillatore RSI. Possibile formazione di top e perdita di momentum."
            }

        return {"divergence": "Nessuna divergenza marcata", "details": "Prezzo e oscillatore si muovono in accordo."}

    @staticmethod
    def detect_wyckoff_phase(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Determina la fase del ciclo secondo la metodologia Wyckoff:
        Accumulazione / Shakeout (Spring) / Markup / Distribuzione / Markdown.
        """
        if df.empty or len(df) < 40:
            return {"phase": "Non definibile", "description": ""}

        last = df.iloc[-1]
        price = float(last["Close"])
        sma20 = float(df["Close"].rolling(20).mean().iloc[-1])
        sma50 = float(df["Close"].rolling(50).mean().iloc[-1])
        sma200 = float(df["Close"].rolling(200).mean().iloc[-1]) if len(df) >= 200 else sma50
        vol_ratio = float(last.get("Volume_Ratio", 1.0))
        rsi = float(last.get("RSI", 50.0))

        # 1. Shakeout / Spring (Fase C di Accumulo di Wyckoff):
        # Forte spike di volume sui minimi con RSI < 30 e candela che recupera parte dell'intraday
        if rsi < 32 and vol_ratio >= 1.5:
            return {
                "phase": "⚡ SHAKEOUT ISTITUZIONALE / SPRING (Fase C di Wyckoff)",
                "description": "Fase di 'caccia alla liquidità' (Liquidity Sweep). Le mani forti spingono il prezzo sotto i minimi evidenti per innescare gli stop loss dei retail e accumulare a sconto. Spesso anticipa inversioni ad alta velocità."
            }
        
        # 2. Markdown / Capitulation (Fase di scarico attivo)
        if price < sma50 < sma200 and rsi < 40:
            return {
                "phase": "📉 MARKDOWN / SCARICO STRUTTURALE (Fase Ribassista)",
                "description": "Fase di liquidazione aperta. I volumi dominanti sono in vendita e i rimbalzi vengono sistematicamente venduti sui retest delle medie mobili."
            }

        # 3. Markup / Trend Espansivo (Fase Rialzista piena)
        if price > sma20 > sma50:
            return {
                "phase": "🚀 MARKUP / TREND FOLLOWING (Fase di Espansione)",
                "description": "Istituzionali in controllo rialzista. Massimi e minimi crescenti con pullback fisiologici a basso volume verso la SMA 20."
            }

        # 4. Re-Accumulo o Distribuzione
        if abs(price - sma50) / sma50 < 0.03:
            return {
                "phase": "📦 CONSOLIDAMENTO / RE-ACCUMULAZIONE",
                "description": "Compressione di volatilità in un range laterale. Le bande di Bollinger si stringono preparando il prossimo breakout direzionale."
            }

        return {
            "phase": "⚖️ FASE DI TRANSIZIONE",
            "description": "Mercato alla ricerca di nuovi equilibri di volume."
        }

    @staticmethod
    def calculate_fibonacci_and_fvg(df: pd.DataFrame, eur_rate: float = 1.0) -> Dict[str, Any]:
        """
        Calcola i livelli aurei di Fibonacci (0.50 e Golden Pocket 0.618)
        e cerca eventuali Fair Value Gaps (squilibri di prezzo) recenti.
        """
        if df.empty or len(df) < 20:
            return {}

        window = df.tail(60)
        high = float(window["High"].max())
        low = float(window["Low"].min())
        diff = high - low

        fib_50 = (high - diff * 0.50) / eur_rate
        fib_618 = (high - diff * 0.618) / eur_rate
        fib_382 = (high - diff * 0.382) / eur_rate

        # Controllo Fair Value Gap (FVG) nelle ultime 5 candele
        # FVG Bearish: Minimo candela 1 > Massimo candela 3 (buco di liquidità da ritestare)
        fvg_note = "Nessun FVG evidente nelle ultime sedute."
        if len(df) >= 3:
            c1 = df.iloc[-3]
            c3 = df.iloc[-1]
            if c1["Low"] > c3["High"]:
                gap_low = c3["High"] / eur_rate
                gap_high = c1["Low"] / eur_rate
                fvg_note = f"Identificato Fair Value Gap (imbalance) tra {gap_low:.2f} € e {gap_high:.2f} €. Il mercato tende statisticamente a risucchiare il prezzo verso quest'area per chiudere il vuoto di liquidità."

        return {
            "fib_382_eur": round(fib_382, 2),
            "fib_50_eur": round(fib_50, 2),
            "fib_618_golden_pocket_eur": round(fib_618, 2),
            "fvg_note": fvg_note
        }
