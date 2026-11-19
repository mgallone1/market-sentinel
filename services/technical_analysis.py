"""
Technical Analysis Service
Calcolo indicatori tecnici con NumPy e Pandas:
RSI, SMA, EMA, MACD, Bande di Bollinger e Volume Spikes.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

class TechnicalAnalysisService:
    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcola i principali indicatori tecnici su un DataFrame OHLCV.
        """
        if df.empty or len(df) < 20:
            return df
        
        data = df.copy()
        
        # 1. Medie Mobili Semplici (SMA) ed Esponenziali (EMA)
        data["SMA_20"] = data["Close"].rolling(window=20).mean()
        data["SMA_50"] = data["Close"].rolling(window=50).mean()
        data["SMA_200"] = data["Close"].rolling(window=200).mean()
        data["EMA_12"] = data["Close"].ewm(span=12, adjust=False).mean()
        data["EMA_26"] = data["Close"].ewm(span=26, adjust=False).mean()

        # 2. MACD & Signal Line
        data["MACD"] = data["EMA_12"] - data["EMA_26"]
        data["MACD_Signal"] = data["MACD"].ewm(span=9, adjust=False).mean()
        data["MACD_Hist"] = data["MACD"] - data["MACD_Signal"]

        # 3. RSI (Relative Strength Index - 14 periodi con Wilder's Smoothing)
        delta = data["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)

        # In Wilder's smoothing, alpha = 1 / period
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        data["RSI"] = 100 - (100 / (1 + rs))

        # 4. Bande di Bollinger (20 periodi, 2 deviazioni standard)
        rolling_std = data["Close"].rolling(window=20).std()
        data["BB_Upper"] = data["SMA_20"] + (rolling_std * 2)
        data["BB_Lower"] = data["SMA_20"] - (rolling_std * 2)
        data["BB_Width"] = (data["BB_Upper"] - data["BB_Lower"]) / data["SMA_20"].replace(0, np.nan)

        # 5. ATR (Average True Range - 14 periodi) & Keltner Channels per Squeeze
        high_low = data["High"] - data["Low"]
        high_close = (data["High"] - data["Close"].shift()).abs()
        low_close = (data["Low"] - data["Close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        data["ATR_14"] = true_range.rolling(window=14).mean()

        # Bollinger Band vs Keltner Channel Squeeze (John Carter Squeeze)
        # Squeeze On quando la Banda di Bollinger è interamente dentro il Canale di Keltner (1.5 * ATR)
        keltner_upper = data["SMA_20"] + (data["ATR_14"] * 1.5)
        keltner_lower = data["SMA_20"] - (data["ATR_14"] * 1.5)
        data["In_Squeeze"] = (data["BB_Upper"] < keltner_upper) & (data["BB_Lower"] > keltner_lower)

        # 6. Analisi Volumi (Volume SMA 20 e Spike Ratio)
        data["Volume_SMA20"] = data["Volume"].rolling(window=20).mean()
        data["Volume_Ratio"] = data["Volume"] / data["Volume_SMA20"].replace(0, np.nan)

        # 7. On-Balance Volume (OBV) per accumulo/distribuzione istituzionale
        obv = [0]
        for i in range(1, len(data)):
            if data["Close"].iloc[i] > data["Close"].iloc[i-1]:
                obv.append(obv[-1] + data["Volume"].iloc[i])
            elif data["Close"].iloc[i] < data["Close"].iloc[i-1]:
                obv.append(obv[-1] - data["Volume"].iloc[i])
            else:
                obv.append(obv[-1])
        data["OBV"] = obv
        data["OBV_EMA20"] = pd.Series(obv, index=data.index).ewm(span=20, adjust=False).mean()

        return data

        return data

    @staticmethod
    def get_latest_technical_summary(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Estrae un riepilogo sintetico dei valori attuali per lo screener e l'analisi.
        """
        if df.empty or len(df) < 2:
            return {}

        last = df.iloc[-1]
        prev = df.iloc[-2]

        current_price = float(last["Close"])
        prev_price = float(prev["Close"])
        change_pct = ((current_price - prev_price) / prev_price) * 100 if prev_price else 0.0

        rsi = float(last["RSI"]) if "RSI" in last and not np.isnan(last["RSI"]) else None
        sma_20 = float(last["SMA_20"]) if "SMA_20" in last and not np.isnan(last["SMA_20"]) else None
        sma_50 = float(last["SMA_50"]) if "SMA_50" in last and not np.isnan(last["SMA_50"]) else None
        sma_200 = float(last["SMA_200"]) if "SMA_200" in last and not np.isnan(last["SMA_200"]) else None
        vol_ratio = float(last["Volume_Ratio"]) if "Volume_Ratio" in last and not np.isnan(last["Volume_Ratio"]) else 1.0

        # Calcolo supporti e resistenze approssimati sugli ultimi 60 periodi
        window_60 = df.tail(min(60, len(df)))
        recent_high = float(window_60["High"].max())
        recent_low = float(window_60["Low"].min())

        # Squeeze detection & BB Width
        in_squeeze = bool(last.get("In_Squeeze", False))
        bb_width = float(last["BB_Width"]) if "BB_Width" in last and not np.isnan(last["BB_Width"]) else None
        atr_14 = float(last["ATR_14"]) if "ATR_14" in last and not np.isnan(last["ATR_14"]) else None

        # Divergenza Volumi / Smart Money Accumulation (OBV vs Price)
        obv_diff = (float(last["OBV"]) - float(last["OBV_EMA20"])) if ("OBV" in last and "OBV_EMA20" in last) else 0.0
        smart_money_bias = "ACCUMULO" if obv_diff > 0 else "DISTRIBUZIONE"

        return {
            "current_price": round(current_price, 2),
            "prev_price": round(prev_price, 2),
            "change_pct": round(change_pct, 2),
            "rsi": round(rsi, 2) if rsi is not None else None,
            "sma_20": round(sma_20, 2) if sma_20 is not None else None,
            "sma_50": round(sma_50, 2) if sma_50 is not None else None,
            "sma_200": round(sma_200, 2) if sma_200 is not None else None,
            "volume_ratio": round(vol_ratio, 2),
            "recent_high": round(recent_high, 2),
            "recent_low": round(recent_low, 2),
            "in_squeeze": in_squeeze,
            "bb_width": round(bb_width, 4) if bb_width is not None else None,
            "atr_14": round(atr_14, 2) if atr_14 is not None else None,
            "smart_money_bias": smart_money_bias
        }
