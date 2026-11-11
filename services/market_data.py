"""
Market Data Service
Interfaccia verso Yahoo Finance per acquisire quotazioni in tempo reale,
dati storici OHLCV e fondamentali aziendali.
"""

import yfinance as yf
import pandas as pd
import urllib.request
import re
from typing import Dict, Any, Optional

class MarketDataService:
    ISIN_MAP = {
        "XDEM.DE": "IE00BL25JP72",
        "XDEM": "IE00BL25JP72",
        "XDWD.DE": "IE00BJ0KDQ92",
        "XDWD": "IE00BJ0KDQ92",
        "BY6.F": "CNE100000296",
        "BYD": "CNE100000296"
    }

    @classmethod
    def is_euro_asset(cls, ticker: str, fund: Optional[Dict[str, Any]] = None) -> bool:
        """
        Determina in modo deterministico se un asset è già denominato in Euro (€).
        Evita categoricamente la doppia conversione (divisione per EUR/USD che causava 75.66 € -> 67.89 €).
        """
        sym = ticker.strip().upper()
        
        # 1. Ticker con estensioni di borsa europee
        euro_suffixes = (
            ".DE", ".F", ".MI", ".PA", ".AS", ".BR", ".MC", ".LS", ".VI", ".IR", ".BE", ".DU", ".HM", ".MU", ".SG"
        )
        if any(sym.endswith(suf) for suf in euro_suffixes):
            return True

        # 2. Coppie crypto esplicite in Euro
        if sym.endswith("-EUR") or sym.endswith("EUR"):
            return True

        # 3. Noti strumenti Trade Republic / indici europei
        base_sym = sym.split(".")[0]
        if base_sym in ["XDEM", "XDWD", "BY6", "FTSEMIB", "DAX", "SX5E", "EUNL", "IWDA"]:
            return True

        # 4. Controllo esplicito sui fondamentali se disponibili
        if fund:
            curr = str(fund.get("currency", "")).upper()
            if curr == "EUR":
                return True

        return False

    @classmethod
    def get_trade_republic_ls_quote(cls, ticker: str) -> Dict[str, float]:
        """
        Recupera le quotazioni in tempo reale da Lang & Schwarz Exchange (il market maker ufficiale di Trade Republic).
        Restituisce prezzo di vendita (Bid), prezzo di acquisto (Ask) e Mid price in Euro (€).
        """
        sym = ticker.strip().upper()
        isin = cls.ISIN_MAP.get(sym)
        if not isin:
            return {}

        url = f"https://www.ls-x.de/de/etf/{isin}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                html_text = resp.read().decode("utf-8", errors="ignore")
                data = {}
                for m in re.finditer(r'field=\"(bid|ask|mid|last)\"[^>]*>([^<]+)', html_text):
                    val_str = m.group(2).strip().replace(".", "").replace(",", ".")
                    try:
                        data[m.group(1)] = float(val_str)
                    except Exception:
                        pass
                return data
        except Exception:
            return {}

    @classmethod
    def get_eur_usd_rate(cls) -> float:
        """Restituisce il tasso di cambio EUR/USD in tempo reale."""
        try:
            t = yf.Ticker("EURUSD=X")
            rate = float(t.fast_info.last_price)
            return rate if rate > 0 else 1.08
        except Exception:
            return 1.08

    @classmethod
    def get_realtime_quote(cls, ticker: str) -> Dict[str, Any]:
        """
        Recupera il prezzo esatto in tempo reale tramite fast_info e arricchisce con dati Trade Republic (L&S).
        Garantisce numeri finiti e validi, senza alcun NaN o None.
        """
        import math
        def safe_float(val, fallback=0.0):
            if val is None:
                return fallback
            try:
                f = float(val)
                if math.isnan(f) or math.isinf(f):
                    return fallback
                return f
            except Exception:
                return fallback

        try:
            sym = ticker.strip().upper()
            t = yf.Ticker(sym)
            fi = t.fast_info
            
            raw_last = getattr(fi, "last_price", None)
            raw_prev = getattr(fi, "previous_close", None)
            last_price = safe_float(raw_last, 0.0)
            prev_close = safe_float(raw_prev, last_price)

            # Se last_price o prev_close sono <= 0 (pre-market o prime ore del mattino),
            # recupera l'ultimo prezzo valido dallo storico recente
            if last_price <= 0:
                try:
                    df_fallback = t.history(period="5d", interval="1d")
                    if not df_fallback.empty and "Close" in df_fallback:
                        valid_closes = df_fallback["Close"].dropna()
                        if not valid_closes.empty:
                            last_price = safe_float(valid_closes.iloc[-1], 0.0)
                            if len(valid_closes) > 1:
                                prev_close = safe_float(valid_closes.iloc[-2], last_price)
                            else:
                                prev_close = last_price
                except Exception:
                    pass

            change_pct = ((last_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0

            res = {
                "last_price": round(last_price, 2),
                "previous_close": round(prev_close, 2),
                "change_pct": round(change_pct, 2),
                "currency": getattr(fi, "currency", "USD") or "USD",
                "day_high": round(safe_float(getattr(fi, "day_high", None)), 2) if getattr(fi, "day_high", None) is not None else None,
                "day_low": round(safe_float(getattr(fi, "day_low", None)), 2) if getattr(fi, "day_low", None) is not None else None,
                "market_cap": getattr(fi, "market_cap", None)
            }

            # Se disponibile quotazione Lang & Schwarz (Trade Republic), arricchisce con bid/ask reali
            ls_quote = cls.get_trade_republic_ls_quote(sym)
            if ls_quote and "bid" in ls_quote and "ask" in ls_quote:
                bid_f = safe_float(ls_quote["bid"], 0.0)
                ask_f = safe_float(ls_quote["ask"], 0.0)
                if bid_f > 0:
                    res["tr_bid"] = round(bid_f, 2)
                    res["tr_ask"] = round(ask_f if ask_f > 0 else bid_f, 2)
                    res["tr_mid"] = round((bid_f + (ask_f if ask_f > 0 else bid_f)) / 2, 2)
                    # Se last_price era 0, usiamo il prezzo L&S reale di Trade Republic
                    if last_price <= 0:
                        res["last_price"] = res["tr_mid"]

            return res
        except Exception as e:
            print(f"[MarketDataService] Errore realtime quote {ticker}: {e}")
            return {"last_price": 0.0, "previous_close": 0.0, "change_pct": 0.0, "currency": "USD"}

    @staticmethod
    def get_ticker_history(ticker: str, period: str = "1d", interval: str = "5m") -> pd.DataFrame:
        """
        Recupera serie storica OHLCV per un ticker, sia intraday (1m, 5m, 15m) sia multiday.
        Rimuove righe con Close nullo o NaN per evitare propagazione di errori numerici.
        """
        try:
            t = yf.Ticker(ticker.strip().upper())
            df = t.history(period=period, interval=interval)
            if df.empty:
                return pd.DataFrame()
            df.index = pd.to_datetime(df.index)
            df = df.dropna(subset=["Close"])
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
