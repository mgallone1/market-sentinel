"""
News Sentiment Service
Aggregazione notizie finanziarie e calcolo del sentiment basato su un lessico
finanziario specialistico (Earnings, Guidance, Upgrades, Downgrades, etc.).
"""

import feedparser
import re
import time
import calendar
import html
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import List, Dict, Any

# Lessico finanziario ponderato
BULLISH_KEYWORDS = {
    "beat": 2.0, "surge": 2.0, "soar": 2.0, "record": 1.5, "upgrade": 2.5,
    "buy": 1.5, "outperform": 2.0, "growth": 1.2, "rally": 1.8, "profit": 1.5,
    "bullish": 2.0, "dividend hike": 2.0, "expansion": 1.2, "partnership": 1.5,
    "breakout": 1.5, "strong guidance": 2.5, "acquisition": 1.0, "top estimates": 2.0
}

BEARISH_KEYWORDS = {
    "miss": -2.0, "plunge": -2.5, "tumble": -2.0, "drop": -1.5, "downgrade": -2.5,
    "sell": -1.5, "underperform": -2.0, "loss": -1.8, "bearish": -2.0, "cut": -1.5,
    "warning": -2.0, "investigation": -2.5, "lawsuit": -2.0, "slump": -2.0,
    "weak guidance": -2.5, "layoffs": -1.0, "bankruptcy": -3.0, "inflation pressure": -1.5
}

class NewsSentimentService:
    @staticmethod
    def analyze_text(text: str) -> Dict[str, Any]:
        """
        Analizza una stringa o titolo di news e calcola il punteggio di sentiment.
        """
        if not text:
            return {"score": 0.0, "label": "NEUTRALE", "color": "gray"}
        
        words = re.findall(r"\b[a-zA-Z\s]+\b", text.lower())
        joined_lower = " ".join(words)
        
        score = 0.0
        matches_bull = []
        matches_bear = []

        for kw, weight in BULLISH_KEYWORDS.items():
            if kw in joined_lower:
                score += weight
                matches_bull.append(kw)

        for kw, weight in BEARISH_KEYWORDS.items():
            if kw in joined_lower:
                score += weight
                matches_bear.append(kw)

        # Normalizzazione
        if score > 1.0:
            label = "RIALZISTA (BULLISH)"
            color = "#10b981"  # verde smeraldo
        elif score < -1.0:
            label = "RIBASSISTA (BEARISH)"
            color = "#ef4444"  # rosso corallo
        else:
            label = "NEUTRALE"
            color = "#6b7280"  # grigio

        return {
            "score": round(score, 2),
            "label": label,
            "color": color,
            "bull_signals": matches_bull,
            "bear_signals": matches_bear
        }

    @classmethod
    def analyze_news_list(cls, news_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Arricchisce una lista di news con l'analisi di sentiment.
        """
        enriched = []
        for item in news_list:
            title = item.get("title", "")
            sentiment = cls.analyze_text(title)
            enriched.append({
                **item,
                "sentiment": sentiment
            })
        return enriched

    @classmethod
    def fetch_global_rss_news(cls, feeds: List[str], max_per_feed: int = 5) -> List[Dict[str, Any]]:
        """
        Scarica breaking news finanziarie e geopolitiche da feed RSS globali verificati.
        Include filtro temporale rigido (scarta notizie con più di 48 ore di anzianità o nel passato).
        """
        all_news = []
        now_ts = time.time()

        for url in feeds:
            try:
                parsed = feedparser.parse(url)
                source_name = parsed.feed.get("title", "Global Market Feed")
                for entry in parsed.entries[:max_per_feed]:
                    title = entry.get("title", "").strip()
                    summary = entry.get("summary", "") or entry.get("description", "")
                    # Pulizia da tag HTML grezzi nel sommario
                    clean_summary = re.sub(r"<[^>]+>", "", summary).strip()
                    link = entry.get("link", "#")

                    # Validazione temporale rigorosa (anti-allucinazione da feed obsoleti)
                    parsed_time = entry.get("published_parsed")
                    pub_str = ""
                    if parsed_time:
                        pub_ts = calendar.timegm(parsed_time)
                        age_hours = (now_ts - pub_ts) / 3600.0
                        if age_hours > 48.0 or age_hours < -5.0:
                            # Notizia obsoleta (vecchia di giorni/anni): scarta assolutamente
                            continue
                        dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
                        pub_str = dt.strftime("%d/%m/%Y %H:%M")
                    else:
                        pub_str = entry.get("published", "")[:25]

                    sentiment = cls.analyze_text(title)
                    if title:
                        all_news.append({
                            "title": title,
                            "summary": clean_summary[:300],
                            "link": link,
                            "published": pub_str,
                            "source": source_name,
                            "sentiment": sentiment
                        })
            except Exception as e:
                print(f"[NewsSentimentService] Errore RSS {url}: {e}")
        return all_news

    @classmethod
    def fetch_telegram_squawk_news(cls, channels: List[str] = None, max_items_per_channel: int = 6) -> List[Dict[str, Any]]:
        """
        Scarica breaking news sub-minuto dai canali pubblici di Financial Squawk (FinancialJuice, etc.).
        Estrae le ultime headline flash dei terminali senza ritardo e con sentiment score.
        """
        if not channels:
            channels = ["financialjuice"]

        squawk_items = []
        now_ts = time.time()

        for ch in channels:
            url = f"https://t.me/s/{ch}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            try:
                with urllib.request.urlopen(req, timeout=6) as resp:
                    content = resp.read().decode("utf-8", errors="ignore")
                    raw_blocks = re.findall(
                        r'<div class="tgme_widget_message_wrap[^>]*>.*?<time datetime="([^"]+)".*?<div class="tgme_widget_message_text[^>]*>(.*?)</div>',
                        content,
                        re.DOTALL
                    )
                    for dt_str, text_html in raw_blocks[-max_items_per_channel:]:
                        clean_text = re.sub(r"<[^>]+>", "", text_html)
                        clean_text = html.unescape(clean_text).replace("|FJ", "").strip()
                        if not clean_text:
                            continue

                        # Parsing timestamp ISO (es. 2026-11-06T19:41:41+00:00)
                        try:
                            # Filtro: controlla se recente (meno di 24h)
                            dt_obj = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                            dt_rome = dt_obj.astimezone(ZoneInfo("Europe/Rome"))
                            pub_formatted = dt_rome.strftime("%d/%m/%Y %H:%M")
                            age_hours = (now_ts - dt_obj.timestamp()) / 3600.0
                            if age_hours > 24.0:
                                continue
                        except Exception:
                            pub_formatted = dt_str[:16]

                        sentiment = cls.analyze_text(clean_text)
                        squawk_items.append({
                            "title": clean_text[:140],
                            "summary": clean_text,
                            "link": f"https://t.me/{ch}",
                            "published": pub_formatted,
                            "source": f"Squawk Wire (@{ch})",
                            "sentiment": sentiment
                        })
            except Exception as e:
                print(f"[NewsSentimentService] Errore lettura Squawk Telegram @{ch}: {e}")

        return squawk_items

    @classmethod
    def fetch_google_realtime_news(cls, query: str = "stock market breaking news when:4h", max_items: int = 8) -> List[Dict[str, Any]]:
        """
        Interroga Google News in tempo reale per catturare articoli usciti nelle ultimissime ore.
        """
        encoded_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
        items = []
        now_ts = time.time()

        try:
            d = feedparser.parse(url)
            for e in d.entries[:max_items]:
                title = e.get("title", "").strip()
                p = e.get("published_parsed")
                pub_str = ""
                if p:
                    pub_ts = calendar.timegm(p)
                    age_hours = (now_ts - pub_ts) / 3600.0
                    if age_hours > 48.0 or age_hours < -5.0:
                        continue
                    dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
                    pub_str = dt.strftime("%d/%m/%Y %H:%M")
                else:
                    pub_str = e.get("published", "")[:25]

                summary = e.get("summary", "")
                clean_summary = re.sub(r"<[^>]+>", "", summary).strip()
                source = e.get("source", {}).get("title", "Google Real-Time News")
                sentiment = cls.analyze_text(title)

                if title:
                    items.append({
                        "title": title,
                        "summary": clean_summary[:250],
                        "link": e.get("link", "#"),
                        "published": pub_str,
                        "source": source,
                        "sentiment": sentiment
                    })
        except Exception as e:
            print(f"[NewsSentimentService] Errore Google Realtime News: {e}")

        return items

    @classmethod
    def fetch_ticker_breaking_news(cls, ticker: str, max_items: int = 5) -> List[Dict[str, Any]]:
        """
        Raccoglie breaking news mirate sul singolo ticker intercettando notizie delle ultime 24-48 ore.
        """
        query = f"{ticker} stock news when:2d"
        return cls.fetch_google_realtime_news(query=query, max_items=max_items)
