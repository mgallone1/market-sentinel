"""
Market Data Service
Interfaccia verso Yahoo Finance per acquisire quotazioni in tempo reale,
dati storici OHLCV e fondamentali aziendali.
"""

import yfinance as yf
import pandas as pd
from typing import Dict, Any, Optional

class MarketDataService:
    @classmethod
    def get_eur_usd_rate(cls) -> float:
        """Restituisce il tasso di cambio EUR/USD in tempo reale."""
        try:
            t = yf.Ticker("EURUSD=X")
            rate = float(t.fast_info.last_price)
            return rate if rate > 0 else 1.08
        except Exception:
            return 1.08

    @staticmethod
    def get_realtime_quote(ticker: str) -> Dict[str, Any]:
        """
        Recupera il prezzo esatto in tempo reale tramite fast_info.
        """
        try:
            t = yf.Ticker(ticker.strip().upper())
            fi = t.fast_info
            last_price = float(fi.last_price) if fi.last_price is not None else 0.0
            prev_close = float(fi.previous_close) if fi.previous_close is not None else last_price
            change_pct = ((last_price - prev_close) / prev_close) * 100 if prev_close else 0.0
            
            return {
                "last_price": round(last_price, 2),
                "previous_close": round(prev_close, 2),
                "change_pct": round(change_pct, 2),
                "currency": fi.currency or "USD",
                "day_high": round(float(fi.day_high), 2) if fi.day_high else None,
                "day_low": round(float(fi.day_low), 2) if fi.day_low else None,
                "market_cap": fi.market_cap
            }
        except Exception as e:
            print(f"[MarketDataService] Errore realtime quote {ticker}: {e}")
            return {"last_price": 0.0, "change_pct": 0.0, "currency": "USD"}

    @staticmethod
    def get_ticker_history(ticker: str, period: str = "1d", interval: str = "5m") -> pd.DataFrame:
        """
        Recupera serie storica OHLCV per un ticker, sia intraday (1m, 5m, 15m) sia multiday.
        """
        try:
            t = yf.Ticker(ticker.strip().upper())
            df = t.history(period=period, interval=interval)
            if df.empty:
                return pd.DataFrame()
            df.index = pd.to_datetime(df.index)
            return df
        except Exception as e:
            print(f"[MarketDataService] Errore recupero storico per {ticker}: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_ticker_fundamentals(ticker: str) -> Dict[str, Any]:
        """
        Recupera le metriche fondamentali essenziali di un titolo.
        """
        try:
            t = yf.Ticker(ticker.strip().upper())
            info = t.info or {}
            
            # Helper per valori sicuri
            def safe_val(key, default=None):
                v = info.get(key, default)
                return v if v is not None else default

            return {
                "symbol": ticker.strip().upper(),
                "short_name": safe_val("shortName", ticker),
                "sector": safe_val("sector", "N/D"),
                "industry": safe_val("industry", "N/D"),
                "currency": safe_val("currency", "USD"),
                "market_cap": safe_val("marketCap"),
                "trailing_pe": safe_val("trailingPE"),
                "forward_pe": safe_val("forwardPE"),
                "peg_ratio": safe_val("pegRatio"),
                "dividend_yield": safe_val("dividendYield"),
                "fifty_two_week_high": safe_val("fiftyTwoWeekHigh"),
                "fifty_two_week_low": safe_val("fiftyTwoWeekLow"),
                "target_mean_price": safe_val("targetMeanPrice"),
                "recommendation_key": safe_val("recommendationKey", "none").upper(),
                "summary": safe_val("longBusinessSummary", "")
            }
        except Exception as e:
            print(f"[MarketDataService] Errore recupero fondamentali per {ticker}: {e}")
            return {
                "symbol": ticker.strip().upper(),
                "short_name": ticker,
                "sector": "N/D",
                "industry": "N/D",
                "currency": "USD"
            }

    @staticmethod
    def get_ticker_news(ticker: str, max_items: int = 5) -> list:
        """
        Recupera le ultime notizie ufficiali associate al ticker (supporta formato legacy e v1.8+).
        """
        try:
            t = yf.Ticker(ticker.strip().upper())
            news_items = t.news or []
            results = []
            for item in news_items[:max_items]:
                # Supporto formato yfinance 1.8+ (annidato in 'content')
                content = item.get("content") if isinstance(item.get("content"), dict) else item
                title = content.get("title", "")
                summary = content.get("summary", "")
                link = content.get("canonicalUrl") or content.get("previewUrl") or content.get("link", "")
                provider = content.get("provider", {})
                publisher = provider.get("displayName") if isinstance(provider, dict) else content.get("publisher", "Financial News")
                pub_time = content.get("pubDate") or content.get("providerPublishTime")

                if title:
                    results.append({
                        "title": title,
                        "summary": summary,
                        "link": link,
                        "publisher": publisher,
                        "time": pub_time
                    })
            return results
        except Exception as e:
            print(f"[MarketDataService] Errore recupero news per {ticker}: {e}")
            return []
