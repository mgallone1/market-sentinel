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
    "Big Tech USA": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"],
    "Semiconduttori & AI": ["NVDA", "TSM", "AMD", "ASML", "AVGO", "QCOM", "ARM"],
    "Borse Europee / Italia": ["RACE.MI", "UCG.MI", "ISP.MI", "ENI.MI", "STLAM.MI", "SAP.DE", "MC.PA"],
    "Indici & Macro ETF": ["SPY", "QQQ", "IWM", "EEM", "GLD", "TLT"]
}

# Feed RSS Istituzionali Premium per Breaking News Finanziarie, Macro, Politica USA ed Europa
RSS_NEWS_FEEDS: List[str] = [
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",               # Wall Street Journal: Markets
    "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",              # Wall Street Journal: US Business & Economy
    "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                  # Wall Street Journal: World News & Geopolitics
    "https://feeds.bloomberg.com/markets/news.rss",                 # Bloomberg Markets
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",      # MarketWatch: Top Stories & Earnings
    "https://feeds.marketwatch.com/marketwatch/marketpulse/",       # MarketWatch: MarketPulse
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",          # CNBC: Finance & Central Banks
    "https://www.cnbc.com/id/20910258/device/rss/rss.html",          # CNBC: Economy, Macro & Rates
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",         # CNBC: US Politics & World Events
    "https://feeds.bbci.co.uk/news/world/rss.xml",                  # BBC: Geopolitics & Global Trade
    "https://cointelegraph.com/rss",                                 # Cointelegraph: Crypto & ETF Flows
    "https://www.coindesk.com/arc/outboundfeeds/rss/"                # CoinDesk: Global Digital Assets & Regulation
]
