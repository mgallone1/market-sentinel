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

# Feed RSS per breaking news finanziarie
RSS_NEWS_FEEDS: List[str] = [
    "https://finance.yahoo.com/news/rssindex",
    "https://feeds.content.dowjones.io/public/rss/mw_topstories"
]
