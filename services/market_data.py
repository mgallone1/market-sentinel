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
        "XDEM.DE": ("IE00BL25JP72", "etf"),
        "XDEM": ("IE00BL25JP72", "etf"),
        "XDWD.DE": ("IE00BJ0KDQ92", "etf"),
        "XDWD": ("IE00BJ0KDQ92", "etf"),
        "BY6.F": ("CNE100000296", "aktie"),
        "BY6": ("CNE100000296", "aktie"),
        "BYD": ("CNE100000296", "aktie"),
        "NVDA": ("US67066G1040", "aktie"),
        "NVD.DE": ("US67066G1040", "aktie"),
        "AAPL": ("US0378331005", "aktie"),
        "TSLA": ("US88160R1014", "aktie"),
        "MSFT": ("US5949181045", "aktie"),
        "AMZN": ("US0231351067", "aktie"),
        "GOOGL": ("US02079K3059", "aktie"),
        "META": ("US30303M1027", "aktie"),
        "TSM": ("US8740391004", "aktie"),
        "AMD": ("US0079031078", "aktie"),
        "PLTR": ("US69608A1088", "aktie"),
        "ASML": ("NL0010273215", "aktie"),
        "ASML.AS": ("NL0010273215", "aktie")
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
        Restituisce prezzo Bid, Ask, Mid e la variazione percentuale odierna calcolata sul listino L&S (7:30 - 23:00).
        """
        sym = ticker.strip().upper()
        mapping = cls.ISIN_MAP.get(sym)
        if not mapping:
            # Fallback controllo su ticker base
            base_sym = sym.split(".")[0]
            mapping = cls.ISIN_MAP.get(base_sym)
        if not mapping:
            return {}

        isin, category = mapping
        url = f"https://www.ls-x.de/de/{category}/{isin}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                if resp.getcode() != 200:
                    return {}
                html_text = resp.read().decode("utf-8", errors="ignore")
                if "Kein Wertpapier gefunden" in html_text or "Seite nicht gefunden" in html_text:
                    return {}

                pos_mid = html_text.find('field="mid"')
                if pos_mid == -1:
                    return {}

                chunk = html_text[pos_mid:pos_mid+500]
                data = {}

                # Prezzo Mid (riferimento centrale Trade Republic)
                m_mid = re.search(r'field="mid"[^>]*>([^<]+)', chunk)
                if m_mid:
                    data["mid"] = float(m_mid.group(1).replace(".", "").replace(",", "."))

                # Variazione percentuale Trade Republic / Lang & Schwarz odierna
                m_perf = re.search(r'field="midPerf1dRelWithPercentSign"[^>]*>(?:<span[^>]*>)?([^<&]+)', chunk)
                if m_perf:
                    perf_str = m_perf.group(1).replace(".", "").replace(",", ".").replace("+", "").strip()
                    try:
                        data["change_pct"] = float(perf_str)
                    except Exception:
                        pass

                # Bid e Ask
                m_bid = re.search(r'field="bid"[^>]*>([^<]+)', html_text)
                if m_bid:
                    data["bid"] = float(m_bid.group(1).replace(".", "").replace(",", "."))
                m_ask = re.search(r'field="ask"[^>]*>([^<]+)', html_text)
                if m_ask:
                    data["ask"] = float(m_ask.group(1).replace(".", "").replace(",", "."))

                return data
        except Exception as e:
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
        Recupera il prezzo esatto e la variazione percentuale allineati alle quotazioni
        di Trade Republic (Lang & Schwarz Exchange, orario 7:30 - 23:00) e comprensivi
        di Pre-Market e Post-Market (extended hours).
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

            # 1. Priorità Trade Republic / Lang & Schwarz (ETF e titoli su L&S operativi 7:30 - 23:00)
            ls_quote = cls.get_trade_republic_ls_quote(sym)
            if ls_quote and "mid" in ls_quote:
                mid_p = safe_float(ls_quote["mid"], 0.0)
                if mid_p > 0:
                    bid_p = safe_float(ls_quote.get("bid"), mid_p)
                    ask_p = safe_float(ls_quote.get("ask"), mid_p)
                    change_p = safe_float(ls_quote.get("change_pct"), 0.0)
                    prev_c = round(mid_p / (1.0 + (change_p / 100.0)), 2) if (1.0 + (change_p / 100.0)) > 0 else mid_p
                    return {
                        "last_price": round(mid_p, 2),
                        "previous_close": prev_c,
                        "change_pct": round(change_p, 2),
                        "currency": "EUR",
                        "day_high": None,
                        "day_low": None,
                        "market_cap": None,
                        "tr_bid": round(bid_p, 2),
                        "tr_ask": round(ask_p, 2),
                        "tr_mid": round(mid_p, 2),
                        "source": "trade_republic_ls"
                    }

            # 2. Quotazione standard o titoli esteri / crypto via Yahoo Finance con Pre/Post Market
            t = yf.Ticker(sym)
            fi = t.fast_info
            
            raw_last = getattr(fi, "last_price", None)
            raw_prev = getattr(fi, "previous_close", None)
            last_price = safe_float(raw_last, 0.0)
            prev_close = safe_float(raw_prev, last_price)

            # Includi le quotazioni Pre-Market e After-Hours (prepost=True)
            # per non mostrare scostamenti sfasati quando la borsa regolare è chiusa
            try:
                df_intra = t.history(period="2d", interval="5m", prepost=True)
                if not df_intra.empty and "Close" in df_intra:
                    valid_intra = df_intra["Close"].dropna()
                    if not valid_intra.empty:
                        extended_last = safe_float(valid_intra.iloc[-1], 0.0)
                        if extended_last > 0:
                            last_price = extended_last
            except Exception:
                pass

            # Fallback se last_price è ancora non valido
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

            return {
                "last_price": round(last_price, 2),
                "previous_close": round(prev_close, 2),
                "change_pct": round(change_pct, 2),
                "currency": getattr(fi, "currency", "USD") or "USD",
                "day_high": round(safe_float(getattr(fi, "day_high", None)), 2) if getattr(fi, "day_high", None) is not None else None,
                "day_low": round(safe_float(getattr(fi, "day_low", None)), 2) if getattr(fi, "day_low", None) is not None else None,
                "market_cap": getattr(fi, "market_cap", None),
                "source": "extended_market"
            }
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
