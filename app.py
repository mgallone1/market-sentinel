"""
Market Sentinel AI - Real-Time Financial Intelligence Platform
Applicazione interattiva per l'analisi di mercato, screening e discussione operativa.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import html
import re
from datetime import datetime

from config import DEFAULT_WATCHLISTS, RSS_NEWS_FEEDS, AppConfig
from services.market_data import MarketDataService
from services.technical_analysis import TechnicalAnalysisService
from services.news_sentiment import NewsSentimentService
from services.signal_generator import SignalGeneratorService

# Configurazione pagina Streamlit
st.set_page_config(
    page_title="Market Sentinel AI | Real-Time Financial Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS per rifinitura grafica e leggibilità
st.markdown("""
<style>
    .main-header {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1e293b;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748b;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #f8fafc;
        border-radius: 8px;
        padding: 14px;
        border: 1px solid #e2e8f0;
    }
    .card-badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.82rem;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Helper di validazione ticker
def sanitize_ticker(ticker_str: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\.\-\^]", "", ticker_str.strip().upper())
    return cleaned[:12]

# Sidebar di navigazione e parametri
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/combo-chart.png", width=64)
    st.title("Market Sentinel")
    st.caption("AI Quantitative Financial Copilot")
    st.divider()

    watchlist_choice = st.selectbox(
        "Seleziona Watchlist di Mercato",
        options=list(DEFAULT_WATCHLISTS.keys()),
        index=0
    )

    custom_ticker_input = st.text_input(
        "Aggiungi o Cerca Ticker Singolo (es. NVDA, AAPL, UCG.MI)",
        value="NVDA"
    )
    cleaned_ticker = sanitize_ticker(custom_ticker_input)

    TIMEFRAME_MAP = {
        "Oggi in tempo reale (Candele 1m)": ("1d", "1m"),
        "Oggi in tempo reale (Candele 5m)": ("1d", "5m"),
        "Ultimi 5 Giorni (Candele 15m)": ("5d", "15m"),
        "1 Mese (Candele Giornaliere)": ("1mo", "1d"),
        "6 Mesi (Candele Giornaliere)": ("6mo", "1d"),
        "1 Anno (Trend di Lungo)": ("1y", "1d")
    }

    time_choice = st.selectbox(
        "Intervallo Temporale Grafici",
        options=list(TIMEFRAME_MAP.keys()),
        index=1  # Default su Oggi 5m
    )
    time_period, time_interval = TIMEFRAME_MAP[time_choice]

    st.divider()
    st.markdown("### ⚠️ Avviso di Rischio")
    st.caption(
        "Questo strumento ha finalità esclusivamente analitiche e quantitative. "
        "Le valutazioni fornite non costituiscono consulenza finanziaria personalizzata o sollecitazione al pubblico risparmio."
    )

# Header Principale
col_title, col_time = st.columns([3, 1])
with col_title:
    st.markdown("<div class='main-header'>📈 Market Sentinel AI</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub-header'>Monitoraggio di mercato in tempo reale, news sentiment e idee operative su cosa comprare in borsa.</div>", unsafe_allow_html=True)
with col_time:
    now_str = datetime.now().strftime("%d/%m/%Y - %H:%M:%S")
    st.metric(label="Ora di Sistema", value=now_str)

# Schede / Tabs Principali
tab_screener, tab_deepdive, tab_news, tab_dialogue = st.tabs([
    "📊 Screener & Setup Operativi",
    "🔍 Analisi Dettagliata Titolo",
    "📰 Breaking News & Sentiment",
    "💬 Assistente & Discussione"
])

# -------------------------------------------------------------
# TAB 1: SCREENER & SETUP OPERATIVI
# -------------------------------------------------------------
with tab_screener:
    st.subheader(f"Screening Watchlist: {watchlist_choice}")
    symbols = DEFAULT_WATCHLISTS.get(watchlist_choice, [])
    
    if st.button("🔄 Aggiorna Dati di Mercato"):
        st.cache_data.clear()

    progress_bar = st.progress(0)
    screen_results = []

    for idx, sym in enumerate(symbols):
        progress_bar.progress((idx + 1) / len(symbols))
        df_hist = MarketDataService.get_ticker_history(sym, period="6mo", interval="1d")
        if df_hist.empty:
            continue
        
        df_tech = TechnicalAnalysisService.calculate_indicators(df_hist)
        tech_summary = TechnicalAnalysisService.get_latest_technical_summary(df_tech)
        fundamentals = MarketDataService.get_ticker_fundamentals(sym)
        news = MarketDataService.get_ticker_news(sym, max_items=2)
        news_sentiment = NewsSentimentService.analyze_news_list(news)
        avg_news_score = sum(n["sentiment"]["score"] for n in news_sentiment) if news_sentiment else 0.0

        setup = SignalGeneratorService.generate_trade_setup(
            ticker=sym,
            technical=tech_summary,
            fundamentals=fundamentals,
            news_sentiment_score=avg_news_score
        )

        screen_results.append({
            "setup": setup,
            "tech": tech_summary,
            "fundamentals": fundamentals
        })

    progress_bar.empty()

    if screen_results:
        # Ordina per score decrescente
        screen_results.sort(key=lambda x: x["setup"]["score"], reverse=True)

        # Tabella riassuntiva
        summary_rows = []
        for item in screen_results:
            s = item["setup"]
            t = item["tech"]
            f = item["fundamentals"]
            summary_rows.append({
                "Ticker": s["ticker"],
                "Nome Azienda": s["company_name"],
                "Prezzo Attuale": f"{t.get('current_price', 0.0)} {s['currency']}",
                "Var. %": f"{t.get('change_pct', 0.0):+.2f}%",
                "RSI (14)": t.get("rsi", "N/D"),
                "Score": s["score"],
                "Setup Operativo": s["verdict_badge"],
                "Target Stimato": f"{s['target_price']} {s['currency']}",
                "Stop Loss": f"{s['stop_loss']} {s['currency']}",
                "R:R": s["risk_reward_ratio"]
            })
        
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        st.markdown("### 🎯 Schede dei Titoli con Miglior Potenziale")
        cols = st.columns(min(3, len(screen_results)))
        for i, item in enumerate(screen_results[:3]):
            s = item["setup"]
            t = item["tech"]
            with cols[i % len(cols)]:
                with st.container(border=True):
                    st.markdown(f"#### **{s['ticker']}** - {s['company_name']}")
                    st.caption(f"Settore: {s['sector']}")
                    st.markdown(f"### {s['verdict_badge']}")
                    st.write(f"**Azione consigliata:** {s['action_advice']}")
                    st.divider()
                    st.write(f"**Zona d'ingresso:** {s['entry_zone']} {s['currency']}")
                    st.write(f"**Target:** {s['target_price']} {s['currency']}")
                    st.write(f"**Stop Loss:** {s['stop_loss']} {s['currency']}")
                    st.write(f"**Rapporto R:R:** {s['risk_reward_ratio']}")
                    st.markdown("**Driver Rialzisti:**")
                    for bf in s["bull_factors"]:
                        st.markdown(f"- 🟢 {html.escape(bf)}")
                    if s["score"] < 4:
                        st.markdown("**Elementi di Rischio:**")
                        for br in s["bear_factors"]:
                            st.markdown(f"- 🔴 {html.escape(br)}")

# -------------------------------------------------------------
# TAB 2: ANALISI DETTAGLIATA TITOLO (DEEP DIVE)
# -------------------------------------------------------------
with tab_deepdive:
    st.subheader(f"Analisi Tecnica e Fondamentale: {cleaned_ticker}")
    
    # Recupera quote istantanea live e storico all'intervallo scelto
    live_quote = MarketDataService.get_realtime_quote(cleaned_ticker)
    df_raw = MarketDataService.get_ticker_history(cleaned_ticker, period=time_period, interval=time_interval)
    if df_raw.empty:
        st.warning(f"Nessun dato trovato per il ticker `{cleaned_ticker}`. Verifica la sigla.")
    else:
        df_analyzed = TechnicalAnalysisService.calculate_indicators(df_raw)
        tech_last = TechnicalAnalysisService.get_latest_technical_summary(df_analyzed)
        fund = MarketDataService.get_ticker_fundamentals(cleaned_ticker)
        ticker_news = MarketDataService.get_ticker_news(cleaned_ticker, max_items=4)
        enriched_news = NewsSentimentService.analyze_news_list(ticker_news)
        avg_sentiment = sum(n["sentiment"]["score"] for n in enriched_news) if enriched_news else 0.0

        setup_single = SignalGeneratorService.generate_trade_setup(
            ticker=cleaned_ticker,
            technical=tech_last,
            fundamentals=fund,
            news_sentiment_score=avg_sentiment
        )

        # Metriche in evidenza con prezzo real-time
        current_display_price = live_quote.get("last_price") or tech_last.get("current_price", 0.0)
        current_display_change = live_quote.get("change_pct") or tech_last.get("change_pct", 0.0)
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Prezzo Live Tick", f"{current_display_price} {fund.get('currency', 'USD')}", f"{current_display_change:+.2f}%")
        m2.metric("RSI (14)", f"{tech_last.get('rsi', 'N/D')}")
        m3.metric("P/E Trailing / Forward", f"{fund.get('trailing_pe', 'N/D')} / {fund.get('forward_pe', 'N/D')}")
        m4.metric("Setup Sintetico", setup_single["verdict_badge"])

        # Grafico Candlestick Interattivo Plotly
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.75, 0.25],
            subplot_titles=[f"Candlestick & Medie Mobili ({cleaned_ticker})", "RSI (14)"]
        )

        # Candele di prezzo
        fig.add_trace(go.Candlestick(
            x=df_analyzed.index,
            open=df_analyzed["Open"],
            high=df_analyzed["High"],
            low=df_analyzed["Low"],
            close=df_analyzed["Close"],
            name="Prezzo"
        ), row=1, col=1)

        # Medie mobili
        if "SMA_20" in df_analyzed:
            fig.add_trace(go.Scatter(x=df_analyzed.index, y=df_analyzed["SMA_20"], name="SMA 20", line=dict(color="#f59e0b", width=1.5)), row=1, col=1)
        if "SMA_50" in df_analyzed:
            fig.add_trace(go.Scatter(x=df_analyzed.index, y=df_analyzed["SMA_50"], name="SMA 50", line=dict(color="#3b82f6", width=1.5)), row=1, col=1)
        if "SMA_200" in df_analyzed:
            fig.add_trace(go.Scatter(x=df_analyzed.index, y=df_analyzed["SMA_200"], name="SMA 200", line=dict(color="#a855f7", width=1.8)), row=1, col=1)

        # Sottografico RSI
        if "RSI" in df_analyzed:
            fig.add_trace(go.Scatter(x=df_analyzed.index, y=df_analyzed["RSI"], name="RSI", line=dict(color="#ec4899", width=1.5)), row=2, col=1)
            # Linee 70 (Ipercomprato) e 30 (Ipervenduto)
            fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", row=2, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="#10b981", row=2, col=1)

        fig.update_layout(
            xaxis_rangeslider_visible=False,
            height=580,
            margin=dict(l=20, r=20, t=40, b=20),
            template="plotly_white"
        )
        st.plotly_chart(fig, use_container_width=True)

        # Dettaglio Piano Operativo (Trade Thesis)
        col_setup, col_news = st.columns([1.2, 1])
        with col_setup:
            with st.container(border=True):
                st.markdown(f"### 📋 Scheda Strategica: {cleaned_ticker}")
                st.markdown(f"**Verdetto:** {setup_single['verdict_badge']}")
                st.write(f"**Spiegazione:** {setup_single['action_advice']}")
                st.divider()
                st.write(f"🎯 **Prezzo Target Stimato:** {setup_single['target_price']} {fund.get('currency', 'USD')}")
                st.write(f"🛑 **Livello Stop Loss (Invalidazione):** {setup_single['stop_loss']} {fund.get('currency', 'USD')}")
                st.write(f"⚖️ **Rapporto Rischio/Rendimento:** {setup_single['risk_reward_ratio']}")
                st.markdown("**Perché Comprare (Bull Factors):**")
                for bf in setup_single["bull_factors"]:
                    st.markdown(f"- 🟢 {html.escape(bf)}")
                st.markdown("**Fattori di Cautela (Bear Factors):**")
                for br in setup_single["bear_factors"]:
                    st.markdown(f"- 🔴 {html.escape(br)}")

        with col_news:
            with st.container(border=True):
                st.markdown(f"### 📰 Notizie Recenti su {cleaned_ticker}")
                if enriched_news:
                    for n in enriched_news:
                        sent = n["sentiment"]
                        st.markdown(f"**[{html.escape(n['title'])}]({n['link']})**")
                        st.caption(f"Fonte: {html.escape(n.get('publisher', 'News'))} | Sentiment: {sent['label']}")
                        st.divider()
                else:
                    st.info("Nessuna notizia rilevante trovata per questo ticker nelle ultime ore.")

# -------------------------------------------------------------
# TAB 3: BREAKING NEWS & SENTIMENT GLOBALE
# -------------------------------------------------------------
with tab_news:
    st.subheader("Rassegna Stampa Finanziaria Globale in Tempo Reale")
    if st.button("Aggiorna Rassegna Stampa"):
        st.cache_data.clear()
        
    global_news = NewsSentimentService.fetch_global_rss_news(RSS_NEWS_FEEDS, max_per_feed=6)
    
    if global_news:
        bull_count = sum(1 for n in global_news if n["sentiment"]["score"] > 1.0)
        bear_count = sum(1 for n in global_news if n["sentiment"]["score"] < -1.0)
        neutral_count = len(global_news) - bull_count - bear_count

        col_s1, col_s2, col_s3 = st.columns(3)
        col_s1.metric("News con Sentiment Positivo", bull_count)
        col_s2.metric("News con Sentiment Negativo", bear_count)
        col_s3.metric("News Neutrali", neutral_count)

        st.divider()
        for gn in global_news:
            sent = gn["sentiment"]
            with st.container(border=True):
                col_n1, col_n2 = st.columns([4, 1])
                with col_n1:
                    st.markdown(f"#### [{html.escape(gn['title'])}]({gn['link']})")
                    st.caption(f"Fonte: {html.escape(gn['source'])} | Pubblicato: {html.escape(gn.get('published', 'N/D'))}")
                with col_n2:
                    st.markdown(f"<span style='color:{sent['color']}; font-weight:bold;'>{sent['label']}</span>", unsafe_allow_html=True)
    else:
        st.info("Caricamento feed notizie in corso...")

# -------------------------------------------------------------
# TAB 4: ASSISTENTE & DISCUSSIONE
# -------------------------------------------------------------
with tab_dialogue:
    st.subheader("💬 Discussione & Consultazione Interattiva")
    st.caption("Fai domande sul mercato o su titoli specifici per ottenere tesi operative e considerazioni su rischi e rendimenti.")

    user_query = st.text_input(
        "Fai una domanda (es. 'Ha senso comprare adesso?', 'Qual è il rischio su questo titolo?', 'Come sono i volumi?')",
        value=f"Qual è la situazione attuale su {cleaned_ticker} e come conviene impostare un'eventuale posizione?"
    )

    if st.button("Genera Risposta Analitica"):
        with st.spinner("Analisi quantitativa e sintesi in corso..."):
            df_hist_q = MarketDataService.get_ticker_history(cleaned_ticker, period="6mo", interval="1d")
            if not df_hist_q.empty:
                df_q_analyzed = TechnicalAnalysisService.calculate_indicators(df_hist_q)
                tech_q = TechnicalAnalysisService.get_latest_technical_summary(df_q_analyzed)
                fund_q = MarketDataService.get_ticker_fundamentals(cleaned_ticker)
                setup_q = SignalGeneratorService.generate_trade_setup(cleaned_ticker, tech_q, fund_q)

                st.markdown(f"""
### 📑 Resoconto Operativo per **{cleaned_ticker}** ({fund_q.get('short_name', cleaned_ticker)})

**1. Quadro di Mercato Attuale:**
- **Prezzo di Riferimento:** {tech_q.get('current_price')} {fund_q.get('currency', 'USD')} (Variazione: {tech_q.get('change_pct'):+.2f}%)
- **Momentum (RSI):** {tech_q.get('rsi')} {'(In ipervenduto - possibile rimbalzo)' if tech_q.get('rsi', 50) < 30 else '(In ipercomprato)' if tech_q.get('rsi', 50) > 70 else '(Fase equilibrata)'}
- **Rapporto Volumi:** {tech_q.get('volume_ratio')}x rispetto alla media a 20 giorni.

**2. Tesi d'Investimento Sintetica:**
- **Verdetto:** {setup_q['verdict_badge']}
- **Linee Guida:** {setup_q['action_advice']}

**3. Livelli Operativi di Gestione del Rischio:**
- **Area di Ingresso Suggerita:** `{setup_q['entry_zone']} {fund_q.get('currency', 'USD')}`
- **Target Price (Scenario Base):** `{setup_q['target_price']} {fund_q.get('currency', 'USD')}`
- **Invalidazione / Stop Loss Rigido:** `{setup_q['stop_loss']} {fund_q.get('currency', 'USD')}`
- **Rapporto Rischio/Rendimento:** `{setup_q['risk_reward_ratio']}`

**4. Check dei Rischi:**
Non sovraesporsi mai oltre il 2-3% del portafoglio sul singolo titolo. Se il titolo viola il supporto di `{setup_q['stop_loss']}`, la tesi rialzista decade e la posizione va chiusa o ridotta.
""")
            else:
                st.error("Impossibile reperire i dati di mercato per il titolo indicato.")
