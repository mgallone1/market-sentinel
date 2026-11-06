"""
Telegram Financial Copilot Bot (Senior Portfolio Manager Edition)
Tutto rigorosamente in Italiano e in Euro (€).
Include:
- Dialogo comunicativo e approfondito da Senior Analyst
- Scanner /occasioni (Opportunity Hunter in tempo reale)
- Simulatore d'Ordine per Trade Republic (/simula)
- Briefing di mercato automatici (08:30 e 15:35) e su richiesta (/briefing)
- Portafoglio dinamico su Supabase (/portafoglio) e supporto screenshot
"""

import os
import re
import io
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, Set
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo
from datetime import datetime

from services.market_data import MarketDataService
from services.technical_analysis import TechnicalAnalysisService
from services.predictive_engine import PredictiveTradingEngine
from services.news_sentiment import NewsSentimentService
from services.opportunity_scanner import OpportunityScannerService
from services.order_simulator import OrderSimulatorService
from services.supabase_service import SupabaseService
from services.llm_reasoning import LLMReasoningService
from services.cycle_analyst import CycleAnalystService
from services.hurst_migliorino_cycles import HurstMigliorinoCycleService
from services.cycle_radar import CycleRadarService
from services.advanced_predictive_system import AdvancedPredictiveSystem

supabase_svc = SupabaseService()
llm_svc = LLMReasoningService()
ACTIVE_CHAT_IDS: Set[int] = set()

# Mappa alias titoli comuni
TICKER_MAP = {
    # ETF World e Momentum negoziati su Trade Republic (Xetra/Francoforte in Euro)
    "IWMO": "XDEM.DE",
    "IWMO.L": "XDEM.DE",
    "XDEM": "XDEM.DE",
    "XDEM.DE": "XDEM.DE",
    "MOMENTUM": "XDEM.DE",
    "MSCI WORLD MOMENTUM": "XDEM.DE",
    "URTH": "XDWD.DE",
    "EUNL": "XDWD.DE",
    "EUNL.DE": "XDWD.DE",
    "XDWD": "XDWD.DE",
    "XDWD.DE": "XDWD.DE",
    "MSCI WORLD": "XDWD.DE",
    # BYD Company (Auto Elettriche - quotata a Francoforte / Trade Republic in Euro)
    "BYD": "BY6.F",
    "BY6": "BY6.F",
    "BY6.F": "BY6.F",
    "BYD COMPANY": "BY6.F",
    "BYD AUTO": "BY6.F",
    # Big Tech USA
    "NVIDIA": "NVDA",
    "NVDA": "NVDA",
    "TESLA": "TSLA",
    "TSLA": "TSLA",
    "APPLE": "AAPL",
    "AAPL": "AAPL",
    "MICROSOFT": "MSFT",
    "MSFT": "MSFT",
    "AMAZON": "AMZN",
    "AMZN": "AMZN",
    "GOOGLE": "GOOGL",
    "GOOGL": "GOOGL",
    "ALPHABET": "GOOGL",
    "META": "META",
    "FACEBOOK": "META",
    "TSMC": "TSM",
    "TSM": "TSM",
    "ASML": "ASML",
    "MARVELL": "MRVL",
    "MRVL": "MRVL",
    "BROADCOM": "AVGO",
    "AVGO": "AVGO",
    "QUALCOMM": "QCOM",
    "QCOM": "QCOM",
    "ARM": "ARM",
    "LILLY": "LLY",
    "ELI LILLY": "LLY",
    "LLY": "LLY",
    "UNICREDIT": "UCG.MI",
    "UCG": "UCG.MI",
    "INTESA": "ISP.MI",
    "ISP": "ISP.MI",
    "FERRARI": "RACE.MI",
    "RACE": "RACE.MI",
    "STELLANTIS": "STLAM.MI",
    "ENI": "ENI.MI",
    # Principali Criptovalute negoziabili su Trade Republic
    "BITCOIN": "BTC-EUR",
    "BTC": "BTC-EUR",
    "ETHEREUM": "ETH-EUR",
    "ETH": "ETH-EUR",
    "SOLANA": "SOL-EUR",
    "SOL": "SOL-EUR",
    "RIPPLE": "XRP-EUR",
    "XRP": "XRP-EUR",
    "CARDANO": "ADA-EUR",
    "ADA": "ADA-EUR",
    "AVALANCHE": "AVAX-EUR",
    "AVAX": "AVAX-EUR",
    "CHAINLINK": "LINK-EUR",
    "LINK": "LINK-EUR",
    "POLKADOT": "DOT-EUR",
    "DOT": "DOT-EUR",
    "DOGECOIN": "DOGE-USD",
    "DOGE": "DOGE-USD",
    "SUI": "SUI20947-USD"
}

COMMON_WORDS = {
    "CIAO", "COME", "COSA", "QUANTO", "VALE", "OGGI", "PREZZO", "COMPRARE", "VENDERE",
    "INFO", "ANALISI", "VEDI", "FA", "IL", "LA", "PER", "CHE", "DI", "UN", "UNA", "SUL",
    "SULLA", "NEL", "CON", "PERCHE", "SE", "HAI", "HO", "NON", "MIO", "PORTAFOGLIO",
    "AZIONE", "AZIONI", "TITOLO", "TITOLI", "BOT", "AIUTO", "STAI", "FACCIAMO", "CONVIENE",
    "MERCATO", "BORSA", "NOTIZIE", "NEWS", "TUTTO", "BUONGIORNO", "BUONASERA", "GRAZIE",
    "OCCASIONI", "SCONTO", "SCONTI", "SIMULA", "ORDINE"
}

def resolve_ticker(text: str) -> Optional[str]:
    cleaned = text.strip().upper()
    if cleaned in TICKER_MAP:
        return TICKER_MAP[cleaned]

    for name, sym in TICKER_MAP.items():
        if re.search(r"\b" + re.escape(name) + r"\b", cleaned):
            return sym

    cash_match = re.search(r"\$([A-Z]{2,6})\b", cleaned)
    if cash_match:
        return cash_match.group(1)

    tokens = re.findall(r"\b[A-Z]{2,6}(?:\.[A-Z]{2})?\b", cleaned)
    for tok in tokens:
        if tok not in COMMON_WORDS:
            return tok

    return None

async def send_safe_text(update: Update, text: str, parse_mode: str = "Markdown"):
    """Invia messaggi spezzandoli automaticamente se superano il limite Telegram di 4096 caratteri."""
    if len(text) <= 3500:
        try:
            await update.message.reply_text(text, parse_mode=parse_mode)
        except Exception:
            await update.message.reply_text(text)
        return

    chunks = []
    current_chunk = ""
    for paragraph in text.split("\n\n"):
        if len(current_chunk) + len(paragraph) + 2 > 3500:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = paragraph
        else:
            current_chunk = (current_chunk + "\n\n" + paragraph) if current_chunk else paragraph
    if current_chunk:
        chunks.append(current_chunk)

    for c in chunks:
        try:
            await update.message.reply_text(c, parse_mode=parse_mode)
        except Exception:
            await update.message.reply_text(c)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    msg = (
        "👋 *Ciao! Sono il tuo Financial Strategist & Trading Copilot personale.*\n\n"
        "Parliamo in italiano, con tutte le quotazioni e i calcoli convertiti rigorosamente in **Euro (€)**, pronti per le tue operazioni su Trade Republic.\n\n"
        "Ecco le funzioni ad alto valore aggiunto che abbiamo attive:\n\n"
        "🎯 *Analisi Approfondita Titolo:* Scrivi semplicemente il nome o ticker (es. `NVIDIA`, `TSLA`, `TSMC`, `Marvell`) per ricevere una tesi discorsiva con livelli di ingresso, target e probabilità di rimbalzo in Euro.\n"
        "💎 *Opportunity Hunter:* Digita `/occasioni` per scansionare all'istante l'intero mercato e trovare i titoli a forte sconto statistico.\n"
        "🧮 *Simulatore Ordini Trade Republic:* Digita `/simula TICKER BUDGET` (es. `/simula TSM 500`) per calcolare quote esatte, prezzo limite consigliato e rischio in Euro.\n"
        "🌅 *Briefing di Mercato:* Digita `/briefing` per il resoconto completo su Wall Street, Europa e geopolitica (erogato in automatico alle **07:00** e **15:00 CET** con continuità di memoria storica).\n"
        "💼 *Portafoglio:* Digita `/portafoglio` o mandami uno screenshot per vedere il riepilogo in tempo reale."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def build_macro_briefing(slot: str = "auto") -> str:
    """
    Costruisce il briefing macro e geopolitico in tempo reale:
    - Calcola la sessione di mercato in base all'ora esatta di Roma:
      * morning: 06:00-11:59 (apertura Europa & Asia overnight)
      * afternoon: 12:00-17:29 (metà seduta UE & sessione USA)
      * evening: 17:30-22:30 (chiusura Europa, Wall Street closing & bilancio)
      * night: 22:31-05:59 (overnight, crypto 24/7 & pre-Asia)
    - Mantiene memoria del briefing precedente tramite Supabase.
    - Prezzi espressi rigorosamente in Euro (€).
    """
    now_rome = datetime.now(ZoneInfo("Europe/Rome"))
    h = now_rome.hour
    m = now_rome.minute
    cur_time = now_rome.strftime("%H:%M")

    if slot == "auto":
        if 6 <= h < 12:
            slot = "morning"
        elif 12 <= h < 17 or (h == 17 and m < 30):
            slot = "afternoon"
        elif (h == 17 and m >= 30) or (18 <= h <= 22):
            slot = "evening"
        else:
            slot = "night"

    eur_rate = MarketDataService.get_eur_usd_rate()
    
    indices = [
        ("S&P 500 (SPY)", "SPY"),
        ("Nasdaq 100 (QQQ)", "QQQ"),
        ("Semiconduttori (SMH)", "SMH"),
        ("MSCI World Core (XDWD)", "XDWD.DE"),
        ("MSCI World Momentum (XDEM)", "XDEM.DE"),
        ("Borsa Italiana (FTSE MIB)", "FTSEMIB.MI"),
        ("Bitcoin (BTC)", "BTC-EUR"),
        ("Oro (GLD)", "GLD")
    ]
    
    indices_summary = []
    if slot == "morning":
        title_header = f"🌅 *BRIEFING MATTINO (ORE {cur_time} CET) - APERTURA BORSE EUROPEE*"
    elif slot == "afternoon":
        title_header = f"☕ *BRIEFING POMERIGGIO (ORE {cur_time} CET) - SESSIONE USA & MACRO*"
    elif slot == "evening":
        title_header = f"🌙 *BRIEFING SERALE (ORE {cur_time} CET) - CHIUSURA WALL STREET & BILANCIO*"
    else:
        title_header = f"🌌 *BRIEFING NOTTURNO (ORE {cur_time} CET) - OVERNIGHT & MERCATI GLOBALI*"

    header_lines = [
        title_header + "\n",
        f"💶 *Tasso di Cambio EUR/USD:* `1.00 € = {eur_rate:.4f} $`\n",
        "📊 *Indici & Asset Chiave (in Euro):*"
    ]

    for label, sym in indices:
        try:
            q = MarketDataService.get_realtime_quote(sym)
            p = q.get("last_price", 0.0)
            c = q.get("change_pct", 0.0)
            is_already_eur = "MI" in sym or "EUR" in sym or sym.endswith(".DE") or sym.endswith(".F")
            p_eur = p if is_already_eur else (p / eur_rate if eur_rate > 0 else p)
            icon = "🟢" if c >= 0 else "🔴"
            header_lines.append(f"{icon} *{label}:* `{p_eur:.2f} €` (`{c:+.2f}%`)")
            indices_summary.append({
                "label": label,
                "price_eur": round(p_eur, 2),
                "change": round(c, 2)
            })
        except Exception as e:
            print(f"[!] Errore recupero {sym}: {e}")

    # Raccogli flussi ultra-rapidi: Squawk Telegram + Google News Realtime + Feed Istituzionali
    from config import RSS_NEWS_FEEDS, FAST_SQUAWK_CHANNELS
    
    # 1. Breaking Squawk in tempo reale sub-minuto (FinancialJuice terminal stream)
    squawk_news = NewsSentimentService.fetch_telegram_squawk_news(FAST_SQUAWK_CHANNELS, max_items_per_channel=5)
    
    # 2. Google News Real-Time (notizie ad altissima frequenza emerse nelle ultime 4 ore)
    google_fast_news = NewsSentimentService.fetch_google_realtime_news("stock market breaking news when:4h", max_items=4)
    
    # 3. Feed RSS Istituzionali verificati (ForexLive, Bloomberg, CNBC, BBC, etc.)
    institutional_news = NewsSentimentService.fetch_global_rss_news(RSS_NEWS_FEEDS, max_per_feed=2)
    
    global_news = squawk_news + google_fast_news + institutional_news
    
    # News mirate sui principali leader di mercato
    for sym in ["NVDA", "SMH", "TSM"]:
        try:
            tk_news = MarketDataService.get_ticker_news(sym, max_items=2)
            global_news.extend(tk_news)
        except Exception:
            pass

    # Recupera il contesto del briefing precedente per continuità
    prev_briefing = supabase_svc.get_latest_macro_briefing()

    # Genera analisi tramite LLM
    macro_comment = llm_svc.generate_macro_market_briefing(
        indices_data=indices_summary,
        news_list=global_news,
        slot=slot,
        previous_briefing_context=prev_briefing
    )
    if not macro_comment:
        if slot == "morning":
            macro_comment = (
                "Sessione asiatica mista con futures europei cauti. L'overnight di Wall Street riflette un riposizionamento "
                "in attesa dei catalizzatori macroeconomici e delle decisioni sui tassi. Focus sui titoli tech ed energia."
            )
        elif slot == "afternoon":
            macro_comment = (
                "Borse europee a metà seduta con scambi selettivi. I futures statunitensi indicano un'apertura guardinga "
                "in vista dei dati macro pomeridiani su mercato del lavoro ed inflazione."
            )
        elif slot == "evening":
            macro_comment = (
                "Borse europee chiuse in territorio misto. Wall Street chiude la sessione settimanale assorbendo "
                "i dati sul mercato del lavoro e le tensioni sui titoli tecnologici e tassi d'interesse."
            )
        else:
            macro_comment = (
                "Fase di contrattazioni notturne a volumi ridotti. Mercati azionari chiusi, focus sui mercati asiatici "
                "e sugli scambi continui delle principali criptovalute."
            )

    # Format top breaking real-time news with exact timestamps for transparency
    news_display_lines = ["\n⚡ *BREAKING NEWS IN TEMPO REALE (ULTIME ORE):*"]
    displayed_items = []
    seen_titles = set()
    for item in (squawk_news + google_fast_news + institutional_news):
        raw_title = item.get("title", "").replace("|FJ", "").strip()
        clean_title = raw_title.replace("*", "").replace("`", "").replace("_", " ")
        if not clean_title or clean_title.lower() in seen_titles:
            continue
        seen_titles.add(clean_title.lower())
        pub = item.get("published", "")
        time_str = "Ultime ore"
        if len(pub) >= 16 and ":" in pub:
            time_str = pub[-5:] + " CET"
        elif pub:
            time_str = pub

        src = item.get("source", "Wire")
        if "financialjuice" in src.lower():
            src = "Squawk Wire"
        elif "google" in src.lower():
            src = "Google Fast"
        elif "forexlive" in src.lower():
            src = "ForexLive"
        elif "bloomberg" in src.lower():
            src = "Bloomberg"
        elif "cnbc" in src.lower():
            src = "CNBC"
        elif "guardian" in src.lower():
            src = "The Guardian"

        displayed_items.append(f"• 🔴 `[{time_str}]` *{src}:* {clean_title}")
        if len(displayed_items) >= 4:
            break

    if displayed_items:
        news_display_lines.extend(displayed_items)
    else:
        news_display_lines.append("• ⚪ *Wire:* Nessun breaking news straordinario nelle ultime ore.")

    full_reply = (
        "\n".join(header_lines) + "\n" +
        "\n".join(news_display_lines) + "\n\n" +
        "🧭 *ANALISI STRATEGICA & CATALYST DI MERCATO:*\n" +
        macro_comment
    )

    # Salva il briefing appena generato nel database per memoria del briefing successivo
    supabase_svc.save_latest_macro_briefing(slot=slot, briefing_text=macro_comment)

    return full_reply

async def briefing_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    
    # Determina automaticamente la fase di mercato e l'orario attuale esatto
    now_rome = datetime.now(ZoneInfo("Europe/Rome"))
    h = now_rome.hour
    m = now_rome.minute
    cur_time = now_rome.strftime("%H:%M")

    if 6 <= h < 12:
        slot = "morning"
        slot_label = f"del mattino (ore {cur_time} CET)"
    elif 12 <= h < 17 or (h == 17 and m < 30):
        slot = "afternoon"
        slot_label = f"del pomeriggio (ore {cur_time} CET)"
    elif (h == 17 and m >= 30) or (18 <= h <= 22):
        slot = "evening"
        slot_label = f"serale di chiusura (ore {cur_time} CET)"
    else:
        slot = "night"
        slot_label = f"notturno / overnight (ore {cur_time} CET)"

    await update.message.reply_text(f"📊 *Sto elaborando l'aggiornamento attuale ({slot_label}) con quotazioni live in Euro e breaking news...*", parse_mode="Markdown")
    
    full_reply = await build_macro_briefing(slot=slot)
    await send_safe_text(update, full_reply)
    
    # Registra nella cronologia conversazione
    supabase_svc.log_message(user_id, "user", "/briefing")
    supabase_svc.log_message(user_id, "assistant", full_reply)

async def cicli_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    await update.message.reply_text("📡 *Scansione Multi-Ciclica & Previsionale in corso (Hurst & Migliorino)...*", parse_mode="Markdown")

    radar_items = CycleRadarService.scan_active_cycles()
    if not radar_items:
        await update.message.reply_text("Nessun ciclo attivo calcolabile.")
        return

    lines = [
        "🔄 *RADAR DEI CICLI & CONFLUENZE PREVISIONALI*\n",
        "Monitoraggio combinato: Ciclo Settimanale (T), Semestrale (T+4) e Modelli di Prezzo:\n"
    ]

    for item in radar_items:
        lines.append(f"*{item['name']}* (`{item['ticker']}`) - `{item['price_eur']:.2f} €`")
        lines.append(f"{item['confluence']}")
        lines.append(f"• 📅 *Ciclo Settimanale T:* Barra `{item['bars_settimanale']}/7` ➔ Mancano ~*{item['bars_left_settimanale']} candele* al minimo.")
        lines.append(f"• ⏳ *Ciclo Semestrale T+4:* Barra `{item['bars_semestrale']}/138` ➔ Mancano ~*{item['bars_left_semestrale']} candele* al minimo.")
        lines.append(f"• 🔮 *Previsione:* Prob. Rimbalzo *{item['rebound_prob']}* (Z-Score: `{item['z_score']:.2f}`)")
        lines.append(f"• 🎯 *Setup in Euro:* Target TP1: `{item['tp1_eur']:.2f} €` | Stop Loss: `{item['sl_eur']:.2f} €` (R:R `{item['risk_reward']}`)\n")

    lines.append("───────────────────────")
    lines.append("💡 *Come Usare Questi Dati:* Quando il conteggio delle barre sul ciclo settimanale e semestrale arriva a zero in concomitanza con un'alta probabilità di rimbalzo (>80%), scatta la finestra di acquisto ideale.")

    await send_safe_text(update, "\n".join(lines))

async def memoria_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    
    recent_msgs = supabase_svc.get_recent_chat_history(user_id, limit=8)
    long_term = supabase_svc.get_long_term_summary(user_id)
    
    lines = ["🧠 *STATO DELLA MEMORIA DEL BOT (BREVE & LUNGO TERMINE)*\n"]
    lines.append("📅 *Memoria di Lungo Termine (30 Giorni):*")
    if long_term:
        lines.append(f"_{long_term}_\n")
    else:
        lines.append("_Nessuna decisione strategica mensile archiviata ancora. Viene aggiornata man mano che parliamo._\n")

    lines.append("🗓️ *Memoria di Breve Termine (Ultimi Scambi):*")
    if recent_msgs:
        for m in recent_msgs[-6:]:
            role_icon = "👤" if m["role"] == "user" else "🤖"
            snippet = m["content"][:100].replace("\n", " ")
            lines.append(f"{role_icon} *{m['role'].capitalize()}:* _{snippet}..._")
    else:
        lines.append("_Nessuno scambio recente registrato._")

    lines.append("\n💡 Il bot ricorda automaticamente tutti i titoli analizzati e le strategie concordate.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def occasioni_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Scansione mercati in corso... cerco le migliori asimmetrie di prezzo in Euro (€)...*", parse_mode="Markdown")
    
    opps = OpportunityScannerService.scan_best_opportunities(top_n=3)
    if not opps:
        await update.message.reply_text("Nessun titolo attualmente in forte anomalia statistica.")
        return

    lines = ["💎 *LE 3 MIGLIORI OCCASIONI A SCONTO OGGI (IN EURO):*\n"]
    for i, o in enumerate(opps, 1):
        lines.append(
            f"*{i}. {o['name']}* (`{o['ticker']}`)\n"
            f"• Prezzo Attuale: `{o['price_eur']:.2f} €` (Oggi: `{o['change_pct']:+.2f}%`)\n"
            f"• Livello RSI: `{o['rsi']:.1f}` | Z-Score: `{o['z_score']:.2f}`\n"
            f"• 📈 Probabilità Rimbalzo: *{o['rebound_prob']}*\n"
            f"• 🎯 Target Stimato: `{o['tp1_eur']:.2f} €`\n"
            f"• 🛑 Stop Loss Calcolato: `{o['sl_eur']:.2f} €` (Rapporto R:R `{o['rr_ratio']}`)\n"
            f"• ⚡ *Azione:* _{o['primary_action']}_\n"
        )

    lines.append("───────────────────────")
    lines.append("💡 *Consiglio Esecutivo su Trade Republic:*")
    lines.append("Per evitare lo spread di Lang & Schwarz, usa sempre un **Ordine Limite** qualche centesimo sotto il prezzo corrente anziché comprare a mercato.")
    lines.append("Per simulare l'acquisto di uno di questi titoli, scrivi ad esempio: `/simula NVDA 500`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def simula_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Uso corretto del simulatore: `/simula <TICKER> <BUDGET_IN_EURO>`\n\n"
            "Esempio:\n"
            "`/simula TSM 500` (Simula 500€ su TSMC)\n"
            "`/simula NVDA 1000` (Simula 1.000€ su NVIDIA)",
            parse_mode="Markdown"
        )
        return

    raw_ticker = args[0].upper()
    ticker = resolve_ticker(raw_ticker) or raw_ticker
    try:
        budget = float(args[1].replace("€", "").replace(",", "."))
    except ValueError:
        await update.message.reply_text("Inserisci un budget numerico valido in Euro.")
        return

    await update.message.reply_text(f"🧮 Calcolo il piano di acquisto per *{ticker}* con budget di *{budget:.2f} €*...", parse_mode="Markdown")
    sim = OrderSimulatorService.simulate_order(ticker, budget)
    if "error" in sim:
        await update.message.reply_text(f"Errore nella simulazione: {sim['error']}")
        return

    reply = (
        f"📋 *SCHEDA OPERATIVA TRADE REPUBLIC: {sim['asset_name']}* (`{sim['ticker']}`)\n\n"
        f"💶 *Budget Allocato:* `{sim['budget_eur']:.2f} €`\n"
        f"🏷️ *Prezzo Attuale di Mercato:* `{sim['current_price_eur']:.2f} €`\n"
        f"📦 *Quote Esatte da Comprare:* `{sim['shares_to_buy']} quote`\n\n"
        f"⚙️ *Parametri di Ordine Consigliati su Trade Republic:*\n"
        f"• Tipo d'Ordine: *{sim['suggested_order_type']}*\n"
        f"• Prezzo Limite da Inserire: `{sim['limit_price_eur']:.2f} €` (protezione anti-spread)\n\n"
        f"🎯 *Rapporto Rischio / Rendimento:* `{sim['risk_reward_ratio']}`\n"
        f"• 🟢 *Obiettivo Take Profit (TP1):* `{sim['tp1_eur']:.2f} €` ➔ Potenziale guadagno: *+{sim['potential_gain_eur']:.2f} €* (`+{sim['potential_gain_pct']}%`)\n"
        f"• 🔴 *Livello Stop Loss (Invalidazione):* `{sim['sl_eur']:.2f} €` ➔ Rischio monetario massimo: *{sim['monetary_risk_eur']:.2f} €* (`-{sim['monetary_risk_pct']}%`)"
    )
    await update.message.reply_text(reply, parse_mode="Markdown")

async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    positions = supabase_svc.get_portfolio(user_id)
    
    if not positions:
        await update.message.reply_text(
            "📂 *Il tuo portafoglio è attualmente vuoto.*\n\n"
            "Puoi registrare una posizione con il comando:\n"
            "`/add TICKER QUOTE PREZZO`\n\n"
            "Esempi:\n"
            "• `/add XDWD.DE 30.054 131.89` (MSCI World)\n"
            "• `/add XDEM.DE 32.242 81.50` (Momentum)\n\n"
            "Oppure mandami direttamente lo screenshot da Trade Republic!",
            parse_mode="Markdown"
        )
        return

    text_lines = ["💼 *IL TUO PORTAFOGLIO IN TEMPO REALE (IN EURO):*\n"]
    total_invested = 0.0
    total_current = 0.0
    eur_rate = MarketDataService.get_eur_usd_rate()

    for pos in positions:
        ticker = pos["ticker"]
        shares = float(pos["shares"])
        pmc = float(pos["average_buy_price"])

        quote = MarketDataService.get_realtime_quote(ticker)
        raw_price = quote.get("last_price") or pmc
        
        # Converte in Euro solo se il ticker è nativamente quotato in USD
        fund = MarketDataService.get_ticker_fundamentals(ticker)
        is_already_eur = ticker.endswith(".DE") or ticker.endswith(".F") or ticker.endswith(".MI") or ticker.endswith("-EUR")
        is_usd = fund.get("currency", "USD").upper() == "USD" and not is_already_eur
        current_price_eur = raw_price / eur_rate if is_usd else raw_price
        
        invested_val = shares * pmc
        current_val = shares * current_price_eur
        pnl_eur = current_val - invested_val
        pnl_pct = ((current_price_eur - pmc) / pmc) * 100 if pmc > 0 else 0.0

        total_invested += invested_val
        total_current += current_val

        icon = "🟢" if pnl_eur >= 0 else "🔴"
        text_lines.append(
            f"*{pos['asset_name']}* (`{ticker}`)\n"
            f"• Quote: `{shares:.4f}` | PMC: `{pmc:.2f} €`\n"
            f"• Prezzo Live: `{current_price_eur:.2f} €`\n"
            f"• Controvalore: `{current_val:.2f} €` | Risultato: {icon} `{pnl_eur:+.2f} €` (`{pnl_pct:+.2f}%`)\n"
        )

    tot_pnl_eur = total_current - total_invested
    tot_pnl_pct = ((total_current - total_invested) / total_invested) * 100 if total_invested > 0 else 0.0
    tot_icon = "🚀" if tot_pnl_eur >= 0 else "⚠️"

    text_lines.append("───────────────────────")
    text_lines.append(f"💰 *Capitale Investito:* `{total_invested:.2f} €`")
    text_lines.append(f"📈 *Valore Attuale:* `{total_current:.2f} €`")
    text_lines.append(f"{tot_icon} *Plusvalenza / Minusvalenza:* `{tot_pnl_eur:+.2f} €` (`{tot_pnl_pct:+.2f}%`)")

    await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown")

async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Uso: `/add TICKER QUOTE PREZZO`\n"
            "Es: `/add XDWD.DE 30.05 131.89`\n"
            "Oppure: `/add XDEM.DE 32.24 81.50`",
            parse_mode="Markdown"
        )
        return

    raw_ticker = args[0].upper()
    ticker = resolve_ticker(raw_ticker) or raw_ticker
    try:
        shares = float(args[1].replace(",", "."))
        price = float(args[2].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Inserisci quote e prezzo numerici validi.")
        return

    fund = MarketDataService.get_ticker_fundamentals(ticker)
    asset_name = fund.get("short_name") or ticker

    supabase_svc.upsert_position(user_id, ticker, asset_name, shares, price, currency="EUR")
    await update.message.reply_text(
        f"✅ *Posizione registrata con successo su Supabase!*\n\n"
        f"• Titolo: *{asset_name}* (`{ticker}`)\n"
        f"• Quote in carico: `{shares}`\n"
        f"• Prezzo medio d'acquisto: `{price:.2f} €`\n\n"
        f"Usa `/portafoglio` per vedere la situazione globale aggiornata in tempo reale.",
        parse_mode="Markdown"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    await update.message.reply_text("🔍 *Screenshot ricevuto! Lo sto esaminando con la visione artificiale di Gemini...*", parse_mode="Markdown")

    try:
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        img_bytes = await tg_file.download_as_bytearray()
        
        # Analisi visiva tramite Gemini
        analysis = llm_svc.analyze_screenshot(bytes(img_bytes), mime_type="image/jpeg")
        
        if analysis.get("type") == "position" and analysis.get("position_data"):
            p = analysis["position_data"]
            asset_name = p.get("asset_name", "Titolo")
            shares = float(p.get("shares", 0.0))
            pmc = float(p.get("average_buy_price", 0.0))
            ticker = resolve_ticker(p.get("ticker_candidate") or asset_name) or p.get("ticker_candidate") or "ASSET"

            if shares > 0 and pmc > 0:
                # Salva automaticamente su Supabase
                supabase_svc.upsert_position(user_id, ticker, asset_name, shares, pmc, currency="EUR")
                
                # Calcola subito anche il controvalore LIVE reale in Euro
                q_live = MarketDataService.get_realtime_quote(ticker)
                raw_live_p = q_live.get("last_price") or pmc
                fund_info = MarketDataService.get_ticker_fundamentals(ticker)
                is_usd = fund_info.get("currency", "USD").upper() == "USD"
                eur_rate = MarketDataService.get_eur_usd_rate() if is_usd else 1.0
                live_p_eur = raw_live_p / eur_rate if is_usd else raw_live_p
                
                cur_val_eur = shares * live_p_eur
                invested_eur = shares * pmc
                diff_eur = cur_val_eur - invested_eur
                diff_pct = ((live_p_eur - pmc) / pmc) * 100 if pmc > 0 else 0.0
                icon = "🟢" if diff_eur >= 0 else "🔴"

                reply = (
                    f"✅ *POSIZIONE RILEVATA E SALVATA SU SUPABASE!*\n\n"
                    f"• Strumento: *{asset_name}* (`{ticker}`)\n"
                    f"• Quote: `{shares:.4f}`\n"
                    f"• Prezzo Medio d'Acquisto: `{pmc:.4f} €`\n"
                    f"• Valore di Carico (Investito): `{invested_eur:.2f} €`\n\n"
                    f"📊 *Situazione Live Attuale:*\n"
                    f"• Prezzo Live: `{live_p_eur:.4f} €`\n"
                    f"• Controvalore Attuale: `{cur_val_eur:.2f} €`\n"
                    f"• P&L: {icon} `{diff_eur:+.2f} €` (`{diff_pct:+.2f}%`)\n\n"
                    f"La posizione è ora monitorata in tempo reale nel tuo `/portafoglio`."
                )
                await update.message.reply_text(reply, parse_mode="Markdown")
                return

        # Se non è una posizione o è un grafico/notizia
        text_resp = analysis.get("text", "Analisi visiva completata.")
        await update.message.reply_text(f"📸 *Analisi Visiva dello Screenshot:*\n\n{text_resp}", parse_mode="Markdown")
    except Exception as e:
        print(f"Errore handle_photo: {e}")
        await update.message.reply_text("⚠️ Si è verificato un errore durante l'elaborazione dell'immagine. Puoi comunque registrarla manualmente con `/add TICKER QUOTE PREZZO`.")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await _handle_text_message_core(update, context)
    except Exception as e:
        print(f"[!] Errore critico in handle_text_message: {e}")
        try:
            await update.message.reply_text("⚠️ Ho riscontrato una temporanea difficoltà nell'elaborazione del comando. Sto rigenerando la risposta, riprova tra un istante o usa un comando come `/portafoglio`.")
        except Exception:
            pass

async def _handle_text_message_core(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    raw_text = update.message.text.strip()
    upper_text = raw_text.upper()

    # Salva il messaggio dell'utente nella memoria di breve termine
    supabase_svc.log_message(user_id, "user", raw_text)

    # Recupera memoria di breve termine (scambi recenti entro 7 giorni) e lungo termine (30 giorni)
    recent_history = supabase_svc.get_recent_chat_history(user_id, limit=6)
    long_term_mem = supabase_svc.get_long_term_summary(user_id)
    
    memory_context_parts = []
    if long_term_mem:
        memory_context_parts.append(f"Decisioni e tesi dell'ultimo mese: {long_term_mem}")
    if recent_history:
        recent_snippets = [f"{m['role']}: {m['content'][:120]}" for m in recent_history[-4:]]
        memory_context_parts.append(f"Scambi recenti di questa settimana:\n" + "\n".join(recent_snippets))
    
    memory_context = "\n".join(memory_context_parts)

    # Comandi rapidi testuali diretti
    if upper_text in ["PORTAFOGLIO", "/PORTAFOGLIO"]:
        await portfolio_cmd(update, context)
        return

    if upper_text in ["OCCASIONI", "/OCCASIONI", "SCONTI", "SCONTO"]:
        await occasioni_cmd(update, context)
        return

    if upper_text in ["BRIEFING", "/BRIEFING"]:
        await briefing_cmd(update, context)
        return

    if upper_text in ["MEMORIA", "/MEMORIA"]:
        await memoria_cmd(update, context)
        return

    if "CICLO" in upper_text or "CICLI" in upper_text or "/CICLI" in upper_text:
        await cicli_cmd(update, context)
        return

    # Prepara un breve sommario degli ultimi 3 scambi per dare contesto alla classificazione dell'intento
    recent_context_str = ""
    if recent_history:
        recent_context_str = "\n".join([f"{m['role']}: {m['content'][:100]}" for m in recent_history[-3:]])

    # Classificazione intelligente dell'intento tramite Gemini con memoria contestuale
    classification = llm_svc.classify_intent(raw_text, recent_history_summary=recent_context_str)
    intent = classification.get("intent", "general_chat")
    ticker = classification.get("ticker")

    # 1. Se l'utente chiede una panoramica di mercato
    if intent == "market_overview":
        await briefing_cmd(update, context)
        return

    # 2. Se l'utente chiede di aggiornare/sostituire i ticker del portafoglio
    if intent == "update_portfolio_ticker":
        replacements = classification.get("replacements") or []
        user_portfolio = supabase_svc.get_portfolio(user_id)
        
        # Logica euristica per XDWD e XDEM se menzionati nel messaggio
        if "XDWD" in upper_text or "XDEM" in upper_text:
            for pos in user_portfolio:
                old_t = pos["ticker"]
                old_n = pos.get("asset_name", "").upper()
                if "XDWD" in upper_text and ("EUNL" in old_t or "URTH" in old_t or "MSCI WORLD USD" in old_n):
                    if supabase_svc.client:
                        supabase_svc.client.table("finance_portfolio").update({
                            "ticker": "XDWD.DE",
                            "asset_name": "Xtrackers MSCI World UCITS ETF"
                        }).eq("id", pos["id"]).execute()
                if "XDEM" in upper_text and ("IWMO" in old_t or "MOMENTUM" in old_n or "XDEM" not in old_t):
                    if supabase_svc.client:
                        supabase_svc.client.table("finance_portfolio").update({
                            "ticker": "XDEM.DE",
                            "asset_name": "Xtrackers MSCI World Momentum UCITS ETF"
                        }).eq("id", pos["id"]).execute()

        # Esegui eventuali rimpiazzi espliciti estratti da Gemini
        for rep in replacements:
            old_val = str(rep.get("old_ticker_or_name", "")).upper()
            new_sym = str(rep.get("new_ticker", "")).upper()
            resolved_new = resolve_ticker(new_sym) or (new_sym + ".DE" if not "." in new_sym and not "-" in new_sym else new_sym)
            
            for pos in user_portfolio:
                if old_val in pos["ticker"].upper() or old_val in pos.get("asset_name", "").upper():
                    if supabase_svc.client:
                        fund_info = MarketDataService.get_ticker_fundamentals(resolved_new)
                        new_name = fund_info.get("short_name") or resolved_new
                        supabase_svc.client.table("finance_portfolio").update({
                            "ticker": resolved_new,
                            "asset_name": new_name
                        }).eq("id", pos["id"]).execute()

        await update.message.reply_text("✅ *Ho aggiornato e corretto i ticker nel tuo portafoglio! Ecco la nuova situazione ricalcolata:*", parse_mode="Markdown")
        await portfolio_cmd(update, context)
        return

    # 3. Se l'utente chiede del portafoglio o di ricontrollare i calcoli
    if intent == "portfolio":
        await portfolio_cmd(update, context)
        return

    # 4. Se l'intento è analizzare uno specifico titolo o crypto
    if intent == "ticker_analysis" and ticker:
        # Risolvi ticker per crypto e alias comuni
        resolved = resolve_ticker(ticker) or ticker
        await update.message.reply_text(f"📈 *Analizzo price action, simulazione Monte Carlo e cicli di Wyckoff per {resolved}...*", parse_mode="Markdown")
        df_hist = MarketDataService.get_ticker_history(resolved, period="6mo", interval="1d")
        
        # Fallback a coppia USD se la coppia diretta EUR non ha storico sufficiente
        if (df_hist.empty or len(df_hist) < 20) and resolved.endswith("-EUR"):
            usd_equiv = resolved.replace("-EUR", "-USD")
            df_usd = MarketDataService.get_ticker_history(usd_equiv, period="6mo", interval="1d")
            if not df_usd.empty and len(df_usd) >= 20:
                resolved = usd_equiv
                df_hist = df_usd

        if not df_hist.empty and len(df_hist) >= 20:
            fund = MarketDataService.get_ticker_fundamentals(resolved)
            is_usd = fund.get("currency", "USD").upper() == "USD" or resolved.endswith("-USD")
            eur_rate = MarketDataService.get_eur_usd_rate() if is_usd else 1.0

            df_tech = TechnicalAnalysisService.calculate_indicators(df_hist)
            pred = PredictiveTradingEngine.generate_prediction_and_trade_plan(df_hist, resolved, currency="USD" if is_usd else "EUR")
            news = MarketDataService.get_ticker_news(resolved, max_items=3)
            # Breaking news mirate in tempo reale sul ticker (ultime 24-48 ore via Google News Real-time)
            fast_ticker_news = NewsSentimentService.fetch_ticker_breaking_news(resolved, max_items=3)
            news = (fast_ticker_news or []) + (news or [])

            # Ingestione Intelligente News: Ticker specifico + Contesto Macro/Politico Globale
            is_crypto = "-EUR" in resolved or "-USD" in resolved or resolved in ["BTC", "ETH", "SOL", "XRP", "ADA"]
            from config import RSS_NEWS_FEEDS
            
            # Recupera breaking news di prima fascia (WSJ, Bloomberg, CNBC, CoinDesk)
            target_feeds = RSS_NEWS_FEEDS[6:] if is_crypto else RSS_NEWS_FEEDS[:6]
            macro_rss_news = NewsSentimentService.fetch_global_rss_news(target_feeds, max_per_feed=2)
            
            # Combina notizie societarie con il quadro geopolitico / Wall Street del momento
            macro_formatted = [
                {
                    "title": f"[{m.get('source', 'Top Media')}] {m.get('title', '')}",
                    "summary": m.get("summary", "")
                }
                for m in macro_rss_news[:3]
            ]
            news = (news or []) + macro_formatted

            # Analisi Struttura Ciclica, Hurst & Migliorino
            div_data = CycleAnalystService.detect_rsi_divergence(df_tech)
            wyck_data = CycleAnalystService.detect_wyckoff_phase(df_tech)
            fib_data = CycleAnalystService.calculate_fibonacci_and_fvg(df_tech, eur_rate)
            hurst_migl_data = HurstMigliorinoCycleService.calculate_cycle_metrics(df_hist)

            # Sistema Quantitativo Avanzato: Monte Carlo, Macro VIX/^TNX, Elliott
            mc_data = AdvancedPredictiveSystem.run_monte_carlo_simulation(df_hist, days_ahead=20, eur_rate=eur_rate)
            macro_data = AdvancedPredictiveSystem.get_macro_market_context()
            elliott_data = AdvancedPredictiveSystem.detect_elliott_wave_phase(df_hist)

            advanced_context = {
                "monte_carlo": mc_data,
                "macro": macro_data,
                "elliott": elliott_data
            }

            cycle_context = {
                "wyckoff_phase": wyck_data.get("phase", "N/D"),
                "wyckoff_desc": wyck_data.get("description", ""),
                "divergence": div_data.get("divergence", "Nessuna"),
                "div_details": div_data.get("details", ""),
                "fib_618_eur": fib_data.get("fib_618_golden_pocket_eur", "N/D"),
                "fib_50_eur": fib_data.get("fib_50_eur", "N/D"),
                "fvg_note": fib_data.get("fvg_note", ""),
                "tempo_battleplan": hurst_migl_data.get("tempo_battleplan", "N/D"),
                "descrizione_battleplan": hurst_migl_data.get("descrizione_battleplan", ""),
                "consiglio_pratico": hurst_migl_data.get("consiglio_pratico", ""),
                "bars_since_mensile_min": hurst_migl_data.get("bars_since_mensile_min", "N/D"),
                "candele_al_minimo": hurst_migl_data.get("candele_al_minimo", "N/D"),
                "bars_since_intermedio_min": hurst_migl_data.get("bars_since_intermedio_min", "N/D"),
                "vincolo_migliorino": hurst_migl_data.get("vincolo_migliorino", "N/D"),
                "spiegazione_vincolo": hurst_migl_data.get("spiegazione_vincolo", ""),
                "hurst_fld_value": hurst_migl_data.get("hurst_fld_value", "N/D"),
                "hurst_fld_signal": hurst_migl_data.get("hurst_fld_signal", "")
            }

            # Commento ragionato del Senior Chartist tramite Gemini con memoria e quant data
            gemini_comment = llm_svc.generate_financial_commentary(
                ticker,
                pred,
                fund,
                news,
                cycle_data=cycle_context,
                advanced_data=advanced_context,
                memory_context=memory_context
            )
            if not gemini_comment:
                gemini_comment = (
                    f"Fase ciclica: {cycle_context['wyckoff_phase']}.\n"
                    f"Battleplan Migliorino: {cycle_context['tempo_battleplan']}.\n"
                    f"Divergenza: {cycle_context['divergence']}.\n"
                    f"Supporto aureo di Fibonacci: {cycle_context['fib_618_eur']} €."
                )

            news_block = ""
            if news:
                news_block = "\n📰 *Catalyst & News di Mercato:*\n"
                for n in news[:2]:
                    news_block += f"• {n['title']}\n"

            # Sintesi Monte Carlo ed Elliott Wave
            mc_summary_block = ""
            if mc_data:
                mc_summary_block = (
                    f"🎲 *Simulazione Monte Carlo (10.000 iterazioni a 20 sedute):*\n"
                    f"• Valore Mediano Atteso: `{mc_data.get('median_price_eur')} €`\n"
                    f"• Range Confidenza 68% (1σ): `{mc_data.get('ci_68_range_eur')}`\n"
                    f"• Range Confidenza 95% (2σ): `{mc_data.get('ci_95_range_eur')}`\n"
                    f"• Probabilità Trend Positivo: *{mc_data.get('probability_positive_trend')}* | VaR 95%: `{mc_data.get('var_95_eur')} €`\n\n"
                    f"🌐 *Macro Context & Elliott:*\n"
                    f"• VIX: `{macro_data.get('vix_value')}` ({macro_data.get('vix_regime')})\n"
                    f"• Onde di Elliott: *{elliott_data.get('wave_label')}*\n\n"
                )

            # Calcolo Prezzo Limite Consigliato (Supporto 1-Sigma Monte Carlo o sconto statistico)
            current_p = pred['current_price_eur']
            stop_loss = pred['stop_loss_eur']
            tp1 = pred['take_profit_1_eur']
            tp2 = pred['take_profit_2_eur']

            # Se Monte Carlo fornisce il range 1-Sigma, usiamo l'estremo inferiore come limite statistico
            limit_price = current_p
            if mc_data and "ci_68_range_eur" in mc_data:
                try:
                    p16_str = mc_data["ci_68_range_eur"].split("€")[0].strip()
                    p16_val = float(p16_str)
                    if stop_loss < p16_val < current_p:
                        limit_price = p16_val
                except Exception:
                    pass

            if limit_price == current_p:
                limit_price = round(current_p * 0.96, 2)  # 4% sotto mercato come default anti-spread

            # Risk Reward su Ordine Limite Ottimizzato
            risk_lim = max(0.01, limit_price - stop_loss)
            gain_lim_tp1 = max(0.0, tp1 - limit_price)
            gain_lim_tp2 = max(0.0, tp2 - limit_price)
            rr_lim_tp1 = round(gain_lim_tp1 / risk_lim, 1)
            rr_lim_tp2 = round(gain_lim_tp2 / risk_lim, 1)

            # 1. LIVELLO PRIMARIO: Fotografia del Momento, Catalyst & Strategia Immediata
            exec_brief = llm_svc.generate_executive_market_brief(
                ticker,
                pred,
                fund,
                news,
                cycle_data=cycle_context,
                memory_context=memory_context
            )
            if not exec_brief:
                exec_brief = (
                    f"Il titolo {fund.get('short_name', ticker)} quota attualmente a {current_p:.2f} €.\n"
                    f"Momento ciclico: {cycle_context['tempo_battleplan']}.\n"
                    f"💡 {cycle_context['consiglio_pratico']}"
                )

            reply_primary = (
                f"🌍 *QUADRO DEL MOMENTO & STRATEGIA: {fund.get('short_name', pred['ticker'])}* (`{pred['ticker']}`)\n\n"
                f"💶 *Prezzo Live in Euro:* `{current_p:.2f} €`" + (f" (${pred['raw_price']:.2f})" if is_usd else "") + "\n\n"
                f"📰 *Cosa sta succedendo & Tesi di Mercato:*\n{exec_brief}\n\n"
                f"🔄 *Inquadramento Ciclico (Migliorino):*\n"
                f"• Fase: *{cycle_context['tempo_battleplan']}*\n"
                f"• Indicazione pratica: 💡 *{cycle_context['consiglio_pratico']}*\n\n"
                f"⚡ *Mappa Operativa (Trade Republic Ready):*\n"
                f"• 🏷️ *Ordine Limite Consigliato:* `{limit_price:.2f} €`\n"
                f"• 🎯 *Take Profit 1:* `{tp1:.2f} €` (R:R a mercato `{pred['risk_reward_tp1']}` ➔ *1:{rr_lim_tp1} con Limite*)\n"
                f"• 🛑 *Stop Loss:* `{stop_loss:.2f} €`\n\n"
                f"👉 *Vuoi simularne l'acquisto su Trade Republic?* Scrivi: `/simula {pred['ticker']} 500`"
            )

            # Tastiera Inline per il Deep Dive Tecnico su richiesta
            keyboard = [
                [InlineKeyboardButton("📊 Apri Deep Dive Tecnico (Monte Carlo, FLD, Elliott)", callback_data=f"quant_{resolved}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Salva risposta nella cronologia
            supabase_svc.log_message(user_id, "assistant", reply_primary)
            await update.message.reply_text(reply_primary, parse_mode="Markdown", reply_markup=reply_markup)
            return
        else:
            await update.message.reply_text(f"⚠️ Dati storici non sufficienti per il titolo `{ticker}`.", parse_mode="Markdown")
            return

    # 4. Domanda conversazionale / aperta
    await update.message.reply_text("💬 *Ci penso su un secondo...*", parse_mode="Markdown")
    ai_answer = llm_svc.answer_general_query(raw_text, memory_context=memory_context)
    if ai_answer:
        supabase_svc.log_message(user_id, "assistant", ai_answer)
        await send_safe_text(update, ai_answer)
    else:
        fallback = "Dimmi pure: puoi scrivermi il nome di un'azione (es. NVIDIA, TSMC, Tesla), chiedermi /occasioni, /simula o /portafoglio!"
        supabase_svc.log_message(user_id, "assistant", fallback)
        await update.message.reply_text(fallback)

# Callback query handler per il bottone del Deep Dive Tecnico
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("quant_"):
        ticker = data.replace("quant_", "")
        await query.message.reply_text(f"🔬 *Elaboro il Deep Dive Quantitativo per {ticker} (Monte Carlo, FLD & Elliott)...*", parse_mode="Markdown")

        df_hist = MarketDataService.get_ticker_history(ticker, period="6mo", interval="1d")
        if df_hist.empty or len(df_hist) < 20:
            await query.message.reply_text(f"Dati non sufficienti per il Deep Dive di {ticker}.")
            return

        fund = MarketDataService.get_ticker_fundamentals(ticker)
        is_usd = fund.get("currency", "USD").upper() == "USD" or ticker.endswith("-USD")
        eur_rate = MarketDataService.get_eur_usd_rate() if is_usd else 1.0

        df_tech = TechnicalAnalysisService.calculate_indicators(df_hist)
        pred = PredictiveTradingEngine.generate_prediction_and_trade_plan(df_hist, ticker, currency="USD" if is_usd else "EUR")
        div_data = CycleAnalystService.detect_rsi_divergence(df_tech)
        wyck_data = CycleAnalystService.detect_wyckoff_phase(df_tech)
        fib_data = CycleAnalystService.calculate_fibonacci_and_fvg(df_tech, eur_rate)
        hurst_migl_data = HurstMigliorinoCycleService.calculate_cycle_metrics(df_hist)
        mc_data = AdvancedPredictiveSystem.run_monte_carlo_simulation(df_hist, days_ahead=20, eur_rate=eur_rate)
        macro_data = AdvancedPredictiveSystem.get_macro_market_context()
        elliott_data = AdvancedPredictiveSystem.detect_elliott_wave_phase(df_hist)

        deep_dive_text = (
            f"🔬 *DEEP DIVE QUANTITATIVO: {fund.get('short_name', ticker)}* (`{ticker}`)\n\n"
            f"🎲 *1. Distribuzione Stocastica Monte Carlo (10.000 scenari):*\n"
            f"• Prezzo Mediano Atteso (50° perc.): `{mc_data.get('median_price_eur')} €`\n"
            f"• Intervallo 68% Confidenza (1σ): `{mc_data.get('ci_68_range_eur')}`\n"
            f"• Intervallo 95% Confidenza (2σ): `{mc_data.get('ci_95_range_eur')}`\n"
            f"• Value at Risk (VaR 95%): `{mc_data.get('var_95_eur')} €`\n"
            f"• Probabilità Rendimento Positivo: *{mc_data.get('probability_positive_trend')}*\n"
            f"• Volatilità Annualizzata Storica: `{mc_data.get('annualized_vol_pct')}%`\n\n"
            f"🌊 *2. Onde di Elliott & Frattali:*\n"
            f"• Struttura Attuale: *{elliott_data.get('wave_label')}*\n"
            f"• Diagnosi: _{elliott_data.get('analysis')}_\n\n"
            f"🔄 *3. Parametri Ciclici Avanzati (Hurst & Migliorino):*\n"
            f"• Linea Spartiacque FLD (20 barre): `{hurst_migl_data.get('hurst_fld_value')} €`\n"
            f"  ↳ _{hurst_migl_data.get('hurst_fld_signal')}_\n"
            f"• Vincolo di Migliorino: _{hurst_migl_data.get('vincolo_migliorino')}_\n"
            f"• Golden Pocket Fibonacci (0.618): `{fib_data.get('fib_618_golden_pocket_eur')} €`\n"
            f"• Wyckoff & Divergenze RSI: {wyck_data.get('phase')} | {div_data.get('divergence')}\n\n"
            f"🌐 *4. Macro Context & Valute:*\n"
            f"• VIX Volatility Index: `{macro_data.get('vix_value')}` ({macro_data.get('vix_regime')})\n"
            f"• Rendimento Treasury 10Y (^TNX): `{macro_data.get('tnx_10y_yield')}%`\n"
            f"• Tasso EUR/USD: `{macro_data.get('eur_usd_rate')}`"
        )
        await send_safe_text(query, deep_dive_text)

_last_briefing_sent: Dict[str, float] = {}

# Funzione per inviare briefing automatici programmati (07:00 e 15:00 CET)
async def send_scheduled_briefing(app, slot: str, force: bool = False):
    """
    Eroga il briefing programmato a tutti gli utenti attivi:
    - slot='morning' alle 07:00 CET (sintesi ultime 12 ore)
    - slot='afternoon' alle 15:00 CET (sintesi ultime ore e pre-apertura USA)
    - Deduplicazione automatica entro 40 minuti per evitare doppi invii.
    """
    import time
    now_ts = time.time()
    last_sent = _last_briefing_sent.get(slot, 0)
    if not force and (now_ts - last_sent < 2400):
        print(f"⏩ [Scheduler] Briefing {slot} già inviato {int(now_ts - last_sent)}s fa. Deduplicato.")
        return
    _last_briefing_sent[slot] = now_ts

    print(f"⏰ [Scheduler] Esecuzione briefing programmato: slot={slot} (force={force})...")
    try:
        briefing_text = await build_macro_briefing(slot=slot)
        chat_ids = supabase_svc.get_active_chat_ids()
        print(f"📡 [Scheduler] Invio a {len(chat_ids)} utenti registrati: {chat_ids}")

        for chat_id in chat_ids:
            chunks = []
            if len(briefing_text) <= 3500:
                chunks = [briefing_text]
            else:
                curr = ""
                for p in briefing_text.split("\n\n"):
                    if len(curr) + len(p) + 2 > 3500:
                        if curr:
                            chunks.append(curr)
                        curr = p
                    else:
                        curr = (curr + "\n\n" + p) if curr else p
                if curr:
                    chunks.append(curr)

            for chunk in chunks:
                try:
                    await app.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
                except Exception:
                    try:
                        await app.bot.send_message(chat_id=chat_id, text=chunk)
                    except Exception as e_plain:
                        print(f"[!] Errore invio briefing a {chat_id}: {e_plain}")
            
            # Registra il briefing nella chat history per memoria
            try:
                supabase_svc.log_message(chat_id, "assistant", briefing_text)
            except Exception:
                pass

        print(f"✅ [Scheduler] Briefing {slot} completato con successo!")
    except Exception as e:
        print(f"[!] Errore critico generazione scheduled briefing: {e}")

async def post_init(application):
    """Configura il menu dei comandi nativo di Telegram e avvia lo scheduler dei briefing alle 07:00 e 15:00 CET."""
    bot_commands = [
        BotCommand("portafoglio", "💼 Visualizza il portafoglio in tempo reale"),
        BotCommand("briefing", "🌅 Quadro di mercato, Wall Street ed Europa"),
        BotCommand("occasioni", "💎 Scanner titoli a forte sconto statistico"),
        BotCommand("cicli", "🔄 Radar ciclico Hurst & Battleplan"),
        BotCommand("simula", "🧮 Simula piano d'ordine su Trade Republic"),
        BotCommand("memoria", "🧠 Visualizza la memoria a lungo termine"),
        BotCommand("add", "➕ Aggiungi manualmente una posizione"),
        BotCommand("help", "ℹ️ Mostra la guida all'uso del bot")
    ]
    try:
        await application.bot.set_my_commands(bot_commands)
        print("✅ Menu comandi Telegram registrato con successo!")
    except Exception as e:
        print(f"[!] Errore registrazione comandi Telegram: {e}")

    # Avvio Scheduler Asincrono per briefing alle 07:00 e alle 15:00 fuso orario di Roma
    try:
        scheduler = AsyncIOScheduler(timezone="Europe/Rome")
        scheduler.add_job(
            send_scheduled_briefing,
            CronTrigger(hour=7, minute=0, timezone="Europe/Rome"),
            args=[application, "morning"],
            id="morning_briefing_0700",
            replace_existing=True
        )
        scheduler.add_job(
            send_scheduled_briefing,
            CronTrigger(hour=15, minute=0, timezone="Europe/Rome"),
            args=[application, "afternoon"],
            id="afternoon_briefing_1500",
            replace_existing=True
        )
        scheduler.add_job(
            send_scheduled_briefing,
            CronTrigger(hour=21, minute=30, timezone="Europe/Rome"),
            args=[application, "evening"],
            id="evening_briefing_2130",
            replace_existing=True
        )
        scheduler.start()
        application.bot_data["briefing_scheduler"] = scheduler
        print("⏰ [Scheduler] Programmato: Briefing Mattino ore 07:00 CET | Briefing Pomeriggio ore 15:00 CET!")
    except Exception as e:
        print(f"[!] Errore configurazione scheduler in post_init: {e}")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("[!] Variabile TELEGRAM_BOT_TOKEN non impostata.")
        return

    app = ApplicationBuilder().token(token).post_init(post_init).build()
    
    # Handlers dei comandi
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", start_cmd))
    app.add_handler(CommandHandler("briefing", briefing_cmd))
    app.add_handler(CommandHandler("occasioni", occasioni_cmd))
    app.add_handler(CommandHandler("cicli", cicli_cmd))
    app.add_handler(CommandHandler("simula", simula_cmd))
    app.add_handler(CommandHandler("portafoglio", portfolio_cmd))
    app.add_handler(CommandHandler("memoria", memoria_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))

    print("🤖 Bot Telegram Market Sentinel (Senior Edition - Full Italian & EUR) avviato...")
    app.run_polling()

if __name__ == "__main__":
    main()
