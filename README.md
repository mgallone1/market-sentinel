# 📈 Market Sentinel AI

Piattaforma di Financial Intelligence e Market Screening in tempo reale con assistenza conversazionale sulle opportunità d'acquisto in borsa.

## 🚀 Architettura Modulare

- `config.py`: Watchlist di riferimento (Big Tech USA, Semiconduttori & AI, Borse Europee, ETF Macro) e parametri di analisi.
- `services/market_data.py`: Interfaccia verso feed di mercato (prezzi real-time, storico OHLCV, multipli di bilancio, target analisti).
- `services/technical_analysis.py`: Motore quantitativo vettoriale (RSI Wilder, Medie Mobili 20/50/200, MACD, Bande di Bollinger, Volume Spike Ratio).
- `services/news_sentiment.py`: Aggregatore di notizie finanziarie e calcolo del sentiment NLP orientato a catalyst di borsa (Earnings beat/miss, upgrade/downgrade, guidance).
- `services/signal_generator.py`: Generatore di schede strategiche e setup operativi (Bull Factors, Bear Factors, Target Price, Stop Loss e Rapporto Rischio/Rendimento).
- `app.py`: Interfaccia Web interattiva Streamlit con grafici candlestick Plotly, screener automatico e chat quantitativa.

## 💻 Come Avviare l'Applicazione

Nel terminale, basta eseguire:

```bash
cd /home/michele/.gemini/antigravity/scratch/market-sentinel
./run.sh
```

Oppure direttamente con Streamlit:
```bash
./venv/bin/streamlit run app.py
```

L'applicazione si aprirà all'indirizzo locale: `http://localhost:8501`.
