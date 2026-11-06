"""
Market Sentinel Configuration
Impostazioni generali, watchlist predefinite e parametri di analisi.
"""

from dataclasses import dataclass
from typing import List, Dict

@dataclass(frozen=True)
class AppConfig:
    APP_NAME: str = "Market Sentinel AI"
    VERSION: str = "1.0.0"
    DEFAULT_INTERVAL: str = "1d"
    DEFAULT_PERIOD: str = "6mo"
    RSI_PERIOD: int = 14
    RSI_OVERSOLD: float = 30.0
    RSI_OVERBOUGHT: float = 70.0
    VOLUME_SPIKE_THRESHOLD: float = 1.5  # 1.5x rispetto alla media mobile 20 periodi

# Watchlist di riferimento raggruppate per settore/categoria
DEFAULT_WATCHLISTS: Dict[str, List[str]] = {
    "Big Tech USA": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "LLY"],
    "Semiconduttori & AI": ["NVDA", "TSM", "AMD", "ASML", "AVGO", "QCOM", "ARM", "MRVL"],
    "Borse Europee & Trade Republic": ["BY6.F", "RACE.MI", "UCG.MI", "ISP.MI", "ENI.MI", "SAP.DE"],
    "ETF Core & Momentum (Trade Republic)": ["XDWD.DE", "XDEM.DE", "SPY", "QQQ", "SMH", "GLD"]
}

# Feed RSS Istituzionali Premium Verificati Live (Solo feed attivi in tempo reale)
RSS_NEWS_FEEDS: List[str] = [
    "https://www.forexlive.com/feed/news",                          # ForexLive: Fast Macro, Central Banks & Geopolitics
    "https://feeds.bloomberg.com/markets/news.rss",                 # Bloomberg Markets
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",      # MarketWatch: Top Stories & Earnings
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",          # CNBC: Finance & Central Banks
    "https://www.cnbc.com/id/20910258/device/rss/rss.html",          # CNBC: Economy, Macro & Rates
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",         # CNBC: US Politics & World Events
    "https://feeds.bbci.co.uk/news/world/rss.xml",                  # BBC: Geopolitics & Global Trade
    "https://www.investing.com/rss/news_25.rss",                    # Investing.com: Stock Market News Live
    "https://cointelegraph.com/rss",                                 # Cointelegraph: Crypto & ETF Flows
    "https://www.coindesk.com/arc/outboundfeeds/rss/"                # CoinDesk: Global Digital Assets & Regulation
]

# Canali Social & Squawk ad altissima frequenza (aggiornamenti in secondi/minuti)
FAST_SQUAWK_CHANNELS: List[str] = [
    "financialjuice"                                                # Terminal Squawk Wire (Bloomberg/Reuters mirror)
]
