"""
Test di verifica a ciclo chiuso per Market Sentinel AI.
"""

import sys
from pathlib import Path

# Aggiungi cartella di progetto al sys.path
sys.path.insert(0, str(Path(__file__).parent))

from services.market_data import MarketDataService
from services.technical_analysis import TechnicalAnalysisService
from services.news_sentiment import NewsSentimentService
from services.signal_generator import SignalGeneratorService

def test_pipeline():
    ticker = "AAPL"
    print(f"[TEST 1] Acquisizione storico per {ticker}...")
    df = MarketDataService.get_ticker_history(ticker, period="3mo", interval="1d")
    assert not df.empty, "DataFrame storico non deve essere vuoto"
    print(f" -> Recuperate {len(df)} righe di dati OHLCV.")

    print(f"[TEST 2] Calcolo indicatori tecnici...")
    df_tech = TechnicalAnalysisService.calculate_indicators(df)
    assert "RSI" in df_tech.columns, "Colonna RSI mancante"
    assert "SMA_20" in df_tech.columns, "Colonna SMA_20 mancante"
    summary = TechnicalAnalysisService.get_latest_technical_summary(df_tech)
    assert summary["current_price"] > 0, "Prezzo attuale non valido"
    print(f" -> Prezzo: {summary['current_price']}, RSI: {summary['rsi']}, VolRatio: {summary['volume_ratio']}")

    print(f"[TEST 3] Test Sentiment Analysis...")
    sample_text_bull = "Apple reports record profit and beats revenue estimates"
    res_bull = NewsSentimentService.analyze_text(sample_text_bull)
    assert res_bull["score"] > 0, "Il sentiment positivo deve avere score > 0"
    print(f" -> Bullish text score: {res_bull['score']} ({res_bull['label']})")

    sample_text_bear = "Company cuts guidance amid severe drop in demand and downgrade"
    res_bear = NewsSentimentService.analyze_text(sample_text_bear)
    assert res_bear["score"] < 0, "Il sentiment negativo deve avere score < 0"
    print(f" -> Bearish text score: {res_bear['score']} ({res_bear['label']})")

    print(f"[TEST 4] Generazione Setup Operativo...")
    fund = MarketDataService.get_ticker_fundamentals(ticker)
    setup = SignalGeneratorService.generate_trade_setup(ticker, summary, fund, news_sentiment_score=res_bull["score"])
    assert "verdict_badge" in setup, "Verdetto mancante"
    assert "target_price" in setup, "Target price mancante"
    assert "stop_loss" in setup, "Stop loss mancante"
    print(f" -> Setup: {setup['verdict_badge']} | Target: {setup['target_price']} | Stop: {setup['stop_loss']}")

    print("\n✅ TUTTI I TEST HANNO AVUTO SUCCESSO! Il sistema funziona correttamente.")

if __name__ == "__main__":
    test_pipeline()
