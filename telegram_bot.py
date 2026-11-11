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
import pypdf
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
from services.llm_reasoning import LLMReasoningService, clean_telegram_markdown, strip_markdown
from services.cycle_analyst import CycleAnalystService
from services.hurst_migliorino_cycles import HurstMigliorinoCycleService
from services.cycle_radar import CycleRadarService
from services.advanced_predictive_system import AdvancedPredictiveSystem
from services.video_downloader import VideoDownloaderService
from services.day_trader_service import DayTraderService
from services.ensemble_predictor import EnsemblePredictorEngine
from services.proactive_sentinel import ProactiveSentinelService

supabase_svc = SupabaseService()
llm_svc = LLMReasoningService()
day_trader_svc = DayTraderService()
sentinel_svc = ProactiveSentinelService()
ACTIVE_CHAT_IDS: Set[int] = set()

class AsyncReentrantLock:
    """Lock asincrono rientrante per garantire l'elaborazione ordinata per singolo utente senza deadlock."""
    def __init__(self):
        self._lock = asyncio.Lock()
        self._owner_task = None
        self._depth = 0

    async def acquire(self):
        curr = asyncio.current_task()
        if self._owner_task == curr:
            self._depth += 1
            return True
        await self._lock.acquire()
        self._owner_task = curr
        self._depth = 1
        return True

    def release(self):
        curr = asyncio.current_task()
        if self._owner_task != curr:
            raise RuntimeError("Cannot release lock owned by another task")
        self._depth -= 1
        if self._depth == 0:
            self._owner_task = None
            self._lock.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()

USER_LOCKS: Dict[int, AsyncReentrantLock] = {}

def get_user_lock(user_id: int) -> AsyncReentrantLock:
    """Restituisce il Lock asincrono per l'utente, garantendo che comandi e testi in rapida successione non collidano."""
    if user_id not in USER_LOCKS:
        USER_LOCKS[user_id] = AsyncReentrantLock()
    return USER_LOCKS[user_id]

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

async def send_safe_text(update: Any, text: str, parse_mode: str = "Markdown", reply_markup: Optional[InlineKeyboardMarkup] = None):
    """
    Invia messaggi spezzandoli automaticamente se superano il limite Telegram (3500 caratteri)
    e sanificando preventivamente il Markdown per eliminare caratteri grezzi (*, #).
    In caso di qualsiasi eccezione dell'entity parser di Telegram, esegue un fallback a strip_markdown
    senza parse_mode per garantire che l'utente non veda MAI asterischi o cancelletti a schermo.
    """
    target = getattr(update, "message", None) or update
    cleaned = clean_telegram_markdown(text) if parse_mode == "Markdown" else text

    if len(cleaned) <= 3500:
        try:
            await target.reply_text(cleaned, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception as e:
            print(f"[!] Warning parsing Markdown Telegram ({e}): fallback a strip_markdown pulito")
            await target.reply_text(strip_markdown(text), reply_markup=reply_markup)
        return

    chunks = []
    current_chunk = ""
    for paragraph in cleaned.split("\n\n"):
        if len(current_chunk) + len(paragraph) + 2 > 3500:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = paragraph
        else:
            current_chunk = (current_chunk + "\n\n" + paragraph) if current_chunk else paragraph
    if current_chunk:
        chunks.append(current_chunk)

    for i, c in enumerate(chunks):
        c_clean = clean_telegram_markdown(c) if parse_mode == "Markdown" else c
        markup = reply_markup if i == len(chunks) - 1 else None
        try:
            await target.reply_text(c_clean, parse_mode=parse_mode, reply_markup=markup)
        except Exception as e_chunk:
            print(f"[!] Warning parsing chunk Markdown ({e_chunk}): fallback a strip_markdown pulito")
            await target.reply_text(strip_markdown(c), reply_markup=markup)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    msg = (
        "👋 *Ciao! Sono il tuo Financial Strategist & Chief Investment Officer (CIO) personale.*\n\n"
        "Parliamo in italiano, con tutte le quotazioni e i calcoli convertiti rigorosamente in *Euro (€)*, pronti per le tue operazioni su Trade Republic.\n\n"
        "Ecco le funzioni di consulenza patrimoniale attive:\n\n"
        "🧭 *Consulenza Titolo con Tesi del CIO:* Scrivi semplicemente il nome o ticker (es. `XDEM`, `XDWD`, `NVIDIA`, `TSMC`, `BYD`) per ricevere una vera consulenza strategica, con giudizio chiaro e piano d'azione in Euro.\n"
        "💼 *Diagnosi Globale di Portafoglio:* Digita `/portafoglio` o inviami uno screenshot per visualizzare la diagnosi patrimoniale, i pesi di allocazione e il consiglio di ribilanciamento.\n"
        "👤 *Profilo Investitore & PAC:* Digita `/profilo` per vedere o aggiornare i tuoi obiettivi, il budget mensile e l'orizzonte temporale.\n"
        "💎 *Opportunity Hunter:* Digita `/occasioni` per scansionare all'istante l'intero mercato e trovare i titoli a forte sconto statistico con approfondimento discorsivo del CIO.\n"
        "🔮 *Previsioni Quantitative d'Insieme:* Digita `/previsione TICKER` (es. `/previsione NVDA`, `/previsione BTC`) per il modello predittivo a 10.000 iterazioni Monte Carlo, Cicli Hurst ed Elliott.\n"
        "🛡️ *Sentinella Proattiva & Radar:* Digita `/sentinel` (o `/radar`) per verificare la sorveglianza autonoma 24/7 su anomalie, breakout e disclosure.\n"
        "⚡ *Day Trader Chart Scanner:* Digita `/scanner` (o `/daytrade`) per individuare breakout a 20 giorni, bull flags e rimbalzi tecnici da ipervenduto.\n"
        "🏛️ *Capitol Hill & Pelosi Tracker:* Digita `/pelosi` (o `/congresso`) per consultare gli ultimi disclosure ufficiali (PTR) depositati al Congresso USA.\n"
        "🧮 *Simulatore Ordini Trade Republic:* Digita `/simula TICKER BUDGET` (es. `/simula XDEM 500`) per calcolare quote esatte e prezzo limite anti-spread.\n"
        "🌅 *Briefing di Mercato:* Digita `/briefing` per il resoconto completo su Wall Street, Europa e geopolitica (erogato in automatico alle *07:00* e *15:00 CET*).\n"
        "🎬 *Visione Video & Social:* Mandami un video o incolla un link da YouTube Shorts, TikTok, Instagram Reel o X per una decodifica approfondita di parlato e grafici con fact-checking del CIO."
    )
    await send_safe_text(update, msg)

async def fetch_macro_market_context():
    """
    Raccoglie in tempo reale le quotazioni degli indici chiave (convertiti in Euro)
    e le ultime breaking news (FinancialJuice, Google Realtime, RSS verificati).
    """
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
    import math
    def is_valid_num(v) -> bool:
        if v is None:
            return False
        try:
            f = float(v)
            return not (math.isnan(f) or math.isinf(f)) and f > 0
        except Exception:
            return False

    indices_summary = []
    for label, sym in indices:
        try:
            q = MarketDataService.get_realtime_quote(sym)
            p = q.get("last_price", 0.0)
            if not is_valid_num(p):
                p = q.get("previous_close", 0.0)
            c = q.get("change_pct", 0.0)
            if c is None or (isinstance(c, float) and math.isnan(c)):
                c = 0.0

            is_already_eur = MarketDataService.is_euro_asset(sym)
            p_eur = p if is_already_eur else (p / eur_rate if eur_rate > 0 else p)
            indices_summary.append({
                "label": label,
                "price_eur": round(float(p_eur), 2),
                "change": round(float(c), 2)
            })
        except Exception as e:
            print(f"[!] Errore recupero {sym}: {e}")

    from config import RSS_NEWS_FEEDS, FAST_SQUAWK_CHANNELS
    squawk_news = NewsSentimentService.fetch_telegram_squawk_news(FAST_SQUAWK_CHANNELS, max_items_per_channel=5)
    google_fast_news = NewsSentimentService.fetch_google_realtime_news("stock market breaking news when:4h", max_items=4)
    institutional_news = NewsSentimentService.fetch_global_rss_news(RSS_NEWS_FEEDS, max_per_feed=2)
    global_news = squawk_news + google_fast_news + institutional_news

    for sym in ["NVDA", "SMH", "TSM"]:
        try:
            tk_news = MarketDataService.get_ticker_news(sym, max_items=2)
            global_news.extend(tk_news)
        except Exception:
            pass

    return indices_summary, global_news, eur_rate

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

    if slot == "morning":
        title_header = f"🌅 *BRIEFING MATTINO (ORE {cur_time} CET) - APERTURA BORSE EUROPEE*"
    elif slot == "afternoon":
        title_header = f"☕ *BRIEFING POMERIGGIO (ORE {cur_time} CET) - SESSIONE USA & MACRO*"
    elif slot == "evening":
        title_header = f"🌙 *BRIEFING SERALE (ORE {cur_time} CET) - CHIUSURA WALL STREET & BILANCIO*"
    else:
        title_header = f"🌌 *BRIEFING NOTTURNO (ORE {cur_time} CET) - OVERNIGHT & MERCATI GLOBALI*"

    indices_summary, global_news, eur_rate = await fetch_macro_market_context()

    header_lines = [
        title_header + "\n",
        f"💶 *Tasso di Cambio EUR/USD:* `1.00 € = {eur_rate:.4f} $`\n",
        "📊 *Indici & Asset Chiave (in Euro):*"
    ]
    for item in indices_summary:
        icon = "🟢" if item["change"] >= 0 else "🔴"
        header_lines.append(f"{icon} *{item['label']}:* `{item['price_eur']:.2f} €` (`{item['change']:+.2f}%`)")

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
    for item in global_news:
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

    async with get_user_lock(user_id):
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

        msg_target = update.effective_message or update.message
        status_msg = None
        if msg_target:
            try:
                status_msg = await msg_target.reply_text(f"📊 *Sto elaborando l'aggiornamento attuale ({slot_label}) con quotazioni live in Euro e breaking news...*", parse_mode="Markdown")
            except Exception:
                pass
        
        try:
            full_reply = await build_macro_briefing(slot=slot)
        except Exception as e:
            print(f"[!] Errore critico generazione briefing: {e}")
            full_reply = "⚠️ Si è verificato un errore temporaneo nel recupero dei dati macro. Riprova tra pochi istanti."

        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

        await send_safe_text(update, full_reply)
        
        # Registra nella cronologia conversazione e nello stato della sessione
        context.user_data["last_interaction"] = {
            "command": "/briefing",
            "topic": "Macro Briefing Mercati",
            "active_ticker": None,
            "summary": full_reply[:800],
            "timestamp": time.time()
        }
        supabase_svc.log_message(user_id, "user", "/briefing")
        supabase_svc.log_message(user_id, "assistant", full_reply)

async def cicli_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)

    async with get_user_lock(user_id):
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

        keyboard = [
            [
                InlineKeyboardButton("📖 Spiegazione 4 Tempi & Onde", callback_data="explain_cycles"),
                InlineKeyboardButton("💎 Top Occasioni", callback_data="cmd_occasioni")
            ],
            [
                InlineKeyboardButton("💼 Il Mio Portafoglio", callback_data="cmd_portfolio"),
                InlineKeyboardButton("🛡️ Radar Sentinella", callback_data="cmd_sentinel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        full_text = "\n".join(lines)
        await send_safe_text(update, full_text, reply_markup=reply_markup)

        context.user_data["last_interaction"] = {
            "command": "/cicli",
            "topic": "Radar Ciclico Hurst",
            "active_ticker": None,
            "summary": full_text[:800],
            "timestamp": time.time()
        }
        supabase_svc.log_message(user_id, "user", "/cicli")
        supabase_svc.log_message(user_id, "assistant", full_text)

async def memoria_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)

    async with get_user_lock(user_id):
        recent_msgs = supabase_svc.get_recent_chat_history(user_id, limit=8)
        long_term = supabase_svc.get_long_term_summary(user_id)
        last_inter = context.user_data.get("last_interaction") or {}
        
        lines = ["🧠 *STATO DELLA MEMORIA DEL BOT (BREVE & LUNGO TERMINE)*\n"]
        if last_inter:
            lines.append(f"🔄 *Ultima Azione di Contesto:* `{last_inter.get('command')}` ({last_inter.get('topic')})\n")

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

        lines.append("\n💡 Il bot ricorda automaticamente tutti i comandi eseguiti, i titoli analizzati e le preferenze personali.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def occasioni_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)

    async with get_user_lock(user_id):
        await update.message.reply_text("🔍 *Scansione quantitativa in corso sui mercati... elaboro le 10 migliori occasioni con approfondimento discorsivo in Euro (€)...*", parse_mode="Markdown")
        
        opps = OpportunityScannerService.scan_best_opportunities(top_n=10)
        if not opps:
            await update.message.reply_text("Nessun titolo attualmente in forte anomalia statistica.")
            return

        # Genera il report approfondito e discorsivo del CIO tramite Gemini
        detailed_report = llm_svc.generate_detailed_opportunities_report(opps)
        
        if not detailed_report:
            lines = ["💎 *TOP 10 MIGLIORI OCCASIONI A SCONTO OGGI (IN EURO):*\n"]
            for i, o in enumerate(opps, 1):
                tr_info = ""
                if o.get("tr_bid") and o.get("tr_ask"):
                    tr_info = f"  └─ 📱 *Trade Republic (L&S Live):* Vendita `{o['tr_bid']:.2f} €` | Acquisto `{o['tr_ask']:.2f} €`\n"

                lines.append(
                    f"*{i}. {o['name']}* (`{o['ticker']}`)\n"
                    f"• Prezzo di Riferimento: `{o['price_eur']:.2f} €` (Oggi: `{o['change_pct']:+.2f}%`)\n"
                    f"{tr_info}"
                    f"• Livello RSI: `{o['rsi']:.1f}` | Z-Score: `{o['z_score']:.2f}`\n"
                    f"• 📈 Probabilità Rimbalzo: *{o['rebound_prob']}*\n"
                    f"• 🎯 Target Stimato: `{o['tp1_eur']:.2f} €`\n"
                    f"• 🛑 Stop Loss Calcolato: `{o['sl_eur']:.2f} €` (Rapporto R:R `{o['rr_ratio']}`)\n"
                    f"• ⚡ *Azione:* _{o['primary_action']}_\n"
                    f"📝 *Perché è un'occasione:* Il titolo presenta una deviazione statistica di {o['z_score']:.2f}σ rispetto alla media a 20 periodi con RSI a {o['rsi']:.1f}, configurando un netto ipervenduto con elevata asimmetria statistica favorevole all'accumulo strategico.\n"
                )

            lines.append("───────────────────────")
            lines.append("💡 *Consiglio Esecutivo su Trade Republic:*")
            lines.append("Per evitare lo spread di Lang & Schwarz, usa sempre un *Ordine Limite* qualche centesimo sotto il prezzo corrente anziché comprare a mercato.")
            lines.append("Per simulare l'acquisto di uno di questi titoli, scrivi ad esempio: `/simula XDEM 500`")
            detailed_report = "\n".join(lines)

        await send_safe_text(update, detailed_report)

        context.user_data["last_interaction"] = {
            "command": "/occasioni",
            "topic": "Top 10 Occasioni a Sconto",
            "active_ticker": None,
            "summary": detailed_report[:800],
            "timestamp": time.time()
        }
        supabase_svc.log_message(user_id, "user", "/occasioni")
        supabase_svc.log_message(user_id, "assistant", detailed_report)

async def pelosi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)

    async with get_user_lock(user_id):
        status_msg = await update.message.reply_text("🏛️ *Consulto i registri del Congresso USA e i report PTR ufficiali (Day Trader Suite)...*", parse_mode="Markdown")

        try:
            user_profile = supabase_svc.get_user_profile(user_id)
            current_long_term = supabase_svc.get_long_term_summary(user_id)

            filings = day_trader_svc.get_congress_trades(member="pelosi", max_reports=3)

            if not filings:
                await send_safe_text(update, "Non sono riuscito a reperire i disclosure recenti del Congresso in questo momento. Riprova più tardi.")
                return

            user_query = "Quali sono gli ultimi disclosure e trade ufficiali depositati da Nancy Pelosi e membri del Congresso USA?"
            explanation = llm_svc.explain_congress_trades(
                user_query=user_query,
                filings=filings,
                user_profile=user_profile,
                memory_context=current_long_term
            )

            keyboard = [
                [
                    InlineKeyboardButton("🔄 Aggiorna Congress Trades", callback_data="cmd_pelosi"),
                    InlineKeyboardButton("⚡ Day Trader Scanner", callback_data="cmd_scanner")
                ],
                [
                    InlineKeyboardButton("💼 Il Mio Portafoglio", callback_data="cmd_portfolio"),
                    InlineKeyboardButton("🌅 Briefing Mercati", callback_data="cmd_briefing")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

            context.user_data["last_interaction"] = {
                "command": "/pelosi",
                "topic": "Capitol Hill Pelosi Disclosures",
                "active_ticker": None,
                "summary": explanation[:800],
                "timestamp": time.time()
            }
            supabase_svc.log_message(user_id, "user", "/pelosi")
            supabase_svc.log_message(user_id, "assistant", explanation)
            await send_safe_text(update, explanation, reply_markup=reply_markup)

        except Exception as e:
            print(f"[!] Errore in pelosi_cmd: {e}")
            await send_safe_text(update, f"Si è verificato un errore durante l'interrogazione dei registri congressuali: {e}")
        finally:
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

async def scanner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)

    async with get_user_lock(user_id):
        status_msg = await update.message.reply_text("⚡ *Scansione dei grafici in corso: cerco breakout a 20 giorni, bull flags e titoli in ipervenduto...*", parse_mode="Markdown")

        try:
            user_profile = supabase_svc.get_user_profile(user_id)
            current_long_term = supabase_svc.get_long_term_summary(user_id)

            target_symbols = [
                "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "AMZN", "META", "GOOGL",
                "PLTR", "COIN", "MSTR", "SMCI", "AVGO", "INTC", "ASML", "ARM"
            ]
            scan_results = day_trader_svc.scan_market_setups(symbols=target_symbols)

            user_query = "Quali setup tecnici e pattern di day trading (breakout 20d, bull flag, ipervenduto) emergono dallo scanner di oggi?"
            explanation = llm_svc.explain_market_scan(
                user_query=user_query,
                scan_results=scan_results,
                user_profile=user_profile,
                memory_context=current_long_term
            )

            keyboard = [
                [
                    InlineKeyboardButton("🔄 Ripeti Scanner", callback_data="cmd_scanner"),
                    InlineKeyboardButton("🏛️ Pelosi Tracker", callback_data="cmd_pelosi")
                ],
                [
                    InlineKeyboardButton("💎 Top Occasioni", callback_data="cmd_occasioni"),
                    InlineKeyboardButton("💼 Portafoglio", callback_data="cmd_portfolio")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

            context.user_data["last_interaction"] = {
                "command": "/scanner",
                "topic": "Day Trader Scanner",
                "active_ticker": None,
                "summary": explanation[:800],
                "timestamp": time.time()
            }
            supabase_svc.log_message(user_id, "user", "/scanner")
            supabase_svc.log_message(user_id, "assistant", explanation)
            await send_safe_text(update, explanation, reply_markup=reply_markup)

        except Exception as e:
            print(f"[!] Errore in scanner_cmd: {e}")
            await send_safe_text(update, f"Si è verificato un errore durante la scansione di mercato: {e}")
        finally:
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

    try:
        user_profile = supabase_svc.get_user_profile(user_id)
        current_long_term = supabase_svc.get_long_term_summary(user_id)

        target_symbols = [
            "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "AMZN", "META", "GOOGL",
            "PLTR", "COIN", "MSTR", "SMCI", "AVGO", "INTC", "ASML", "ARM"
        ]
        scan_results = day_trader_svc.scan_market_setups(symbols=target_symbols)

        user_query = "Quali setup tecnici e pattern di day trading (breakout 20d, bull flag, ipervenduto) emergono dallo scanner di oggi?"
        explanation = llm_svc.explain_market_scan(
            user_query=user_query,
            scan_results=scan_results,
            user_profile=user_profile,
            memory_context=current_long_term
        )

        keyboard = [
            [
                InlineKeyboardButton("🔄 Ripeti Scanner", callback_data="cmd_scanner"),
                InlineKeyboardButton("🏛️ Pelosi Tracker", callback_data="cmd_pelosi")
            ],
            [
                InlineKeyboardButton("💎 Top Occasioni", callback_data="cmd_occasioni"),
                InlineKeyboardButton("💼 Portafoglio", callback_data="cmd_portfolio")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

        supabase_svc.log_message(user_id, "assistant", explanation)
        await send_safe_text(update, explanation, reply_markup=reply_markup)

    except Exception as e:
        print(f"[!] Errore in scanner_cmd: {e}")
        await send_safe_text(update, f"Si è verificato un errore durante la scansione di mercato: {e}")
    finally:
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

async def previsione_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, user_query: Optional[str] = None):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)

    async with get_user_lock(user_id):
        args = context.args or []
        raw_ticker = args[0].upper() if args else ""
        extra_notes = " ".join(args[1:]) if len(args) > 1 else ""
        if user_query and not extra_notes:
            extra_notes = user_query

        if not raw_ticker:
            last_inter = supabase_svc.get_last_user_interaction(user_id)
            raw_ticker = (last_inter.get("active_ticker") if last_inter else None) or "BTC"

        ticker = resolve_ticker(raw_ticker) or raw_ticker
        status_msg = await update.message.reply_text(f"🔮 *Elaboro la Previsione Quantitativa d'Insieme per {ticker} (Monte Carlo, Hurst & Z-Score)...*", parse_mode="Markdown")

        try:
            user_portfolio = supabase_svc.get_portfolio(user_id)
            user_profile = supabase_svc.get_user_profile(user_id)
            current_long_term = supabase_svc.get_long_term_summary(user_id)

            forecast = EnsemblePredictorEngine.generate_ensemble_forecast(ticker)
            if forecast.get("error"):
                await send_safe_text(update, f"⚠️ Impossibile calcolare la previsione per `{ticker}`: {forecast['error']}")
                return

            full_query = f"Qual è la previsione quantitativa dettagliata e la traiettoria più probabile per {ticker}?"
            if extra_notes:
                full_query += f" Note e vincoli espressi dall'investitore: {extra_notes}"

            explanation = llm_svc.explain_ensemble_prediction(
                user_query=full_query,
                forecast_data=forecast,
                user_portfolio=user_portfolio,
                user_profile=user_profile,
                memory_context=current_long_term
            )

            keyboard = [
                [
                    InlineKeyboardButton(f"🧮 Simula Ordine {ticker}", callback_data=f"sim_{ticker}"),
                    InlineKeyboardButton(f"🔬 Deep Dive Cicli", callback_data=f"quant_{ticker}")
                ],
                [
                    InlineKeyboardButton("🛡️ Radar Sentinella", callback_data="cmd_sentinel"),
                    InlineKeyboardButton("💼 Portafoglio", callback_data="cmd_portfolio")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

            context.user_data["last_interaction"] = {
                "command": "/previsione",
                "topic": f"Previsione {ticker}",
                "active_ticker": ticker,
                "summary": explanation[:800],
                "timestamp": time.time()
            }
            context.user_data["current_topic"] = {"ticker": ticker, "asset_name": forecast.get("asset_name", ticker)}

            user_cmd_log = f"/previsione {ticker} {extra_notes}".strip() if extra_notes else f"/previsione {ticker}"
            supabase_svc.log_message(user_id, "user", user_cmd_log)
            supabase_svc.log_message(user_id, "assistant", explanation)
            await send_safe_text(update, explanation, reply_markup=reply_markup)

        except Exception as e:
            print(f"[!] Errore in previsione_cmd: {e}")
            await send_safe_text(update, f"Si è verificato un errore durante l'elaborazione della previsione: {e}")
        finally:
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

async def sentinel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)

    async with get_user_lock(user_id):
        dash = sentinel_svc.get_sentinel_dashboard()
        pillars_lines = []
        for p in dash.get("detection_pillars", []):
            pillars_lines.append(f"• *{p['name']}*\n  `{p['rule']}`")
        pillars_str = "\n".join(pillars_lines)

        msg = (
            "🛡️ *SENTINELLA PROATTIVA & RADAR DI MERCATO*\n"
            "───────────────────────\n"
            f"• *Stato Sorveglianza:* {dash['status']}\n"
            f"• *Finestra Operativa:* {dash['active_hours']}\n"
            f"• *Orario Attuale (CET):* `{dash['current_time_cet']}`\n"
            f"• *Alert Inviati Oggi:* `{dash['alerts_sent_today']}`\n"
            f"• *Cooldown Intelligente:* `{dash.get('cooldown_period', '4h per asset')}`\n\n"
            "📡 *I 5 Pilastri di Sorveglianza Attiva:*\n"
            f"{pillars_str}\n"
            "───────────────────────\n"
            "💡 *Come funziona la Sentinella:* Le soglie sono tarate per cogliere i movimenti in anticipo (es. ETF all'1.2%, Mega-Cap al 2.8%, VIX a +8.0% e breaking geopolitiche da squawk wire). Quando si verifica un'anomalia, ricevi subito un alert strategico del CIO con impatto e condotta operativa su Trade Republic!"
        )

        keyboard = [
            [
                InlineKeyboardButton("⚡ Day Trader Scanner", callback_data="cmd_scanner"),
                InlineKeyboardButton("🏛️ Pelosi Tracker", callback_data="cmd_pelosi")
            ],
            [
                InlineKeyboardButton("💼 Il Mio Portafoglio", callback_data="cmd_portfolio"),
                InlineKeyboardButton("🌅 Briefing Mercati", callback_data="cmd_briefing")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_safe_text(update, msg, reply_markup=reply_markup)

        context.user_data["last_interaction"] = {
            "command": "/sentinel",
            "topic": "Radar Sentinella Proattiva",
            "active_ticker": None,
            "summary": msg[:800],
            "timestamp": time.time()
        }
        supabase_svc.log_message(user_id, "user", "/sentinel")
        supabase_svc.log_message(user_id, "assistant", msg)

async def simula_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)

    async with get_user_lock(user_id):
        args = context.args or []
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

        context.user_data["last_interaction"] = {
            "command": "/simula",
            "topic": f"Simulazione Ordine {ticker}",
            "active_ticker": ticker,
            "summary": reply[:800],
            "timestamp": time.time()
        }
        context.user_data["current_topic"] = {"ticker": ticker, "asset_name": sim.get("asset_name", ticker)}
        supabase_svc.log_message(user_id, "user", f"/simula {ticker} {budget:.2f}€")
        supabase_svc.log_message(user_id, "assistant", reply)

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Visualizza o aggiorna la scheda investitore e gli obiettivi patrimoniali."""
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    args = context.args

    if args:
        full_arg = " ".join(args).lower()
        profile = supabase_svc.get_user_profile(user_id)
        
        if "pac" in full_arg:
            import re
            nums = re.findall(r"\d+(?:[.,]\d+)?", full_arg)
            if nums:
                val = float(nums[0].replace(",", "."))
                profile["monthly_pac_eur"] = val
                supabase_svc.save_user_profile(user_id, profile)
                await update.message.reply_text(
                    f"✅ *Budget PAC aggiornato!*\n"
                    f"Ora il tuo piano di accumulo mensile è impostato su `{val:.2f} €/mese`.\n"
                    f"Tutti i consigli di acquisto, simulazione e ribilanciamento terranno conto di questo importo.",
                    parse_mode="Markdown"
                )
                return

        if "orizzonte" in full_arg or "anni" in full_arg:
            profile["horizon"] = " ".join(args)
            supabase_svc.save_user_profile(user_id, profile)
            await update.message.reply_text(
                f"✅ *Orizzonte temporale aggiornato a:*\n`{profile['horizon']}`",
                parse_mode="Markdown"
            )
            return

        if "rischio" in full_arg:
            profile["risk_profile"] = " ".join(args)
            supabase_svc.save_user_profile(user_id, profile)
            await update.message.reply_text(
                f"✅ *Profilo di rischio aggiornato a:*\n`{profile['risk_profile']}`",
                parse_mode="Markdown"
            )
            return

    profile = supabase_svc.get_user_profile(user_id)
    long_mem = supabase_svc.get_long_term_summary(user_id)
    pac_val = profile.get("monthly_pac_eur")
    pac_str = f"`{pac_val:.2f} €/mese`" if pac_val else "_Non impostato fisso / Gestione manuale liquidità_"
    if profile.get("pac_details"):
        pac_str += f" ({profile.get('pac_details')})"

    mem_block = f"\n🧠 *Regole e Memoria Permanente Registrata:*\n_{long_mem}_\n" if long_mem else ""

    msg = (
        "👤 *SCHEDA INVESTITORE & OBIETTIVI PATRIMONIALI*\n\n"
        f"• *Investitore:* {profile.get('investor_name', 'Michele')}\n"
        f"• *Orizzonte Temporale:* {profile.get('horizon', 'Lungo termine')}\n"
        f"• *Strategia:* {profile.get('strategy', 'Personalizzata')}\n"
        f"• *Budget PAC Mensile:* {pac_str}\n"
        f"• *Profilo di Rischio:* {profile.get('risk_profile', 'Dinamico')}\n"
        f"• *Broker Operativo:* {profile.get('broker', 'Trade Republic')}\n"
        f"{mem_block}\n"
        "───────────────────────\n"
        "💡 *Come modificare la memoria e il profilo:*\n"
        "Scrivimi direttamente in chat ciò che vuoi cambiare con parole tue! Ad esempio:\n"
        "• *'Non ho un PAC da 500€ su Momentum, il mio PAC è di 300€ su MSCI World'*\n"
        "• *'Ricordati che ho cambiato orizzonte temporale a 3 anni'*\n"
        "• *'Memorizza che la mia liquidità disponibile è di 4.000€'*"
    )
    await send_safe_text(update, msg)

def compute_portfolio_metrics(positions: list) -> tuple:
    """Calcola in modo deterministico controvalori, P&L e pesi percentuali del portafoglio in Euro, immunizzato da NaN."""
    import math
    calc_items = []
    total_invested = 0.0
    total_current = 0.0
    eur_rate = MarketDataService.get_eur_usd_rate()
    if not eur_rate or math.isnan(eur_rate) or eur_rate <= 0:
        eur_rate = 1.08

    def is_valid_float(v) -> bool:
        if v is None:
            return False
        try:
            f = float(v)
            return not (math.isnan(f) or math.isinf(f)) and f > 0
        except Exception:
            return False

    for pos in positions:
        ticker = pos["ticker"]
        shares = float(pos["shares"]) if is_valid_float(pos.get("shares")) else 0.0
        pmc = float(pos["average_buy_price"]) if is_valid_float(pos.get("average_buy_price")) else 0.0

        quote = MarketDataService.get_realtime_quote(ticker)
        raw_price = quote.get("last_price")
        if not is_valid_float(raw_price):
            raw_price = quote.get("tr_mid") or quote.get("tr_bid")
        if not is_valid_float(raw_price):
            raw_price = quote.get("previous_close")
        if not is_valid_float(raw_price):
            raw_price = pmc if pmc > 0 else 100.0

        fund = MarketDataService.get_ticker_fundamentals(ticker)
        is_already_eur = MarketDataService.is_euro_asset(ticker, fund)
        is_usd = not is_already_eur
        current_price_eur = raw_price / eur_rate if is_usd else raw_price

        invested_val = shares * pmc
        current_val = shares * current_price_eur
        pnl_eur = current_val - invested_val
        pnl_pct = ((current_price_eur - pmc) / pmc) * 100 if pmc > 0 else 0.0

        total_invested += invested_val
        total_current += current_val

        calc_items.append({
            "ticker": ticker,
            "asset_name": pos.get("asset_name") or ticker,
            "shares": shares,
            "pmc": pmc,
            "current_price_eur": current_price_eur,
            "current_val": current_val,
            "invested_val": invested_val,
            "pnl_eur": pnl_eur,
            "pnl_pct": pnl_pct
        })

    for item in calc_items:
        item["weight_pct"] = (item["current_val"] / total_current) * 100 if total_current > 0 else 0.0

    calc_items.sort(key=lambda x: x["weight_pct"], reverse=True)
    return calc_items, total_invested, total_current

async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, user_query: Optional[str] = None):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)

    async with get_user_lock(user_id):
        # Se user_query non è specificato ma context.args contiene testo aggiuntivo (es. /portafoglio cosa pensi di BYD?)
        if user_query is None and context.args:
            user_query = " ".join(context.args)

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

        calc_items, total_invested, total_current = compute_portfolio_metrics(positions)

        text_lines = ["💼 *IL TUO PORTAFOGLIO IN TEMPO REALE (IN EURO):*\n"]
        for item in calc_items:
            tr_info = ""
            tr_quote = MarketDataService.get_trade_republic_ls_quote(item["ticker"])
            if tr_quote and "bid" in tr_quote:
                tr_info = f" *(TR: {tr_quote['bid']:.2f} €)*"

            icon = "🟢" if item["pnl_eur"] >= 0 else "🔴"
            text_lines.append(
                f"*{item['asset_name']}* (`{item['ticker']}`) — *Peso: {item['weight_pct']:.1f}%*\n"
                f"• Quote: `{item['shares']:.4f}` | PMC: `{item['pmc']:.2f} €`\n"
                f"• Prezzo Live: `{item['current_price_eur']:.2f} €`{tr_info}\n"
                f"• Controvalore: `{item['current_val']:.2f} €` | Risultato: {icon} `{item['pnl_eur']:+.2f} €` (`{item['pnl_pct']:+.2f}%`)\n"
            )

        tot_pnl_eur = total_current - total_invested
        tot_pnl_pct = ((total_current - total_invested) / total_invested) * 100 if total_invested > 0 else 0.0
        tot_icon = "🚀" if tot_pnl_eur >= 0 else "⚠️"

        text_lines.append("───────────────────────")
        text_lines.append(f"💰 *Capitale Investito:* `{total_invested:.2f} €`")
        text_lines.append(f"📈 *Valore Attuale:* `{total_current:.2f} €`")
        text_lines.append(f"{tot_icon} *Plusvalenza / Minusvalenza Totale:* `{tot_pnl_eur:+.2f} €` (`{tot_pnl_pct:+.2f}%`)")

        await send_safe_text(update, "\n".join(text_lines))

        # Diagnosi Strategica Esecutiva del Chief Investment Officer (CIO)
        status_msg = await update.message.reply_text(
            "🧠 *Elaboro la diagnosi patrimoniale di Asset Allocation e la strategia di ribilanciamento del CIO...*",
            parse_mode="Markdown"
        )
        user_profile = supabase_svc.get_user_profile(user_id)
        long_term_mem = supabase_svc.get_long_term_summary(user_id)
        diagnosis = llm_svc.generate_portfolio_strategic_diagnosis(
            portfolio_items=calc_items,
            total_invested=total_invested,
            total_current=total_current,
            user_profile=user_profile,
            user_query_or_notes=user_query or "",
            memory_context=long_term_mem
        )
        if diagnosis:
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            await send_safe_text(update, diagnosis)

            # Salva stato sessione per dare piena continuità a qualunque messaggio o domanda successiva
            context.user_data["last_interaction"] = {
                "command": "/portafoglio",
                "topic": "Diagnosi Portafoglio",
                "active_ticker": None,
                "summary": diagnosis[:800],
                "calc_items": calc_items,
                "total_invested": total_invested,
                "total_current": total_current,
                "timestamp": time.time()
            }

            user_cmd_log = f"/portafoglio {user_query}".strip() if user_query else "/portafoglio"
            supabase_svc.log_message(user_id, "user", user_cmd_log)
            supabase_svc.log_message(user_id, "assistant", diagnosis)
        else:
            await status_msg.edit_text("💡 Ricorda di ribilanciare periodicamente gli asset più volatili verso il Core World.")

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
                is_eur = MarketDataService.is_euro_asset(ticker, fund_info)
                eur_rate = 1.0 if is_eur else MarketDataService.get_eur_usd_rate()
                live_p_eur = raw_live_p / eur_rate if not is_eur else raw_live_p
                
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
                await send_safe_text(update, reply)
                return

        # Se non è una posizione o è un grafico/notizia
        text_resp = analysis.get("text", "Analisi visiva completata.")
        await send_safe_text(update, f"📸 *Analisi Visiva dello Screenshot:*\n\n{text_resp}")
    except Exception as e:
        print(f"Errore handle_photo: {e}")
        await update.message.reply_text("⚠️ Si è verificato un errore durante l'elaborazione dell'immagine. Puoi comunque registrarla manualmente con `/add TICKER QUOTE PREZZO`.")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Riceve ed esamina video inviati direttamente su Telegram (video, video note, animazioni/gif).
    Supporta:
    - Registrazioni schermo di Trade Republic / Degiro per auto-importazione del portafoglio.
    - Video di approfondimento finanziario con trascrizione audio e OCR dei fotogrammi.
    """
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    msg = update.message
    video_obj = msg.video or msg.video_note or msg.animation
    if not video_obj:
        return

    caption = msg.caption or ""
    file_size_mb = (video_obj.file_size or 0) / (1024 * 1024)
    if file_size_mb > 20:
        await msg.reply_text(
            f"⚠️ *Video troppo pesante per il download diretto di Telegram* (limite Bot API: 20MB, questo file è `{file_size_mb:.1f} MB`).\n"
            "Se è un video social, inviami direttamente il link (YouTube Shorts, TikTok, Instagram Reel o X)!",
            parse_mode="Markdown"
        )
        return

    status_msg = await msg.reply_text(
        "🎬 *Video ricevuto! Scarico ed esamino il contenuto (audio, parlato e fotogrammi) con la visione multimodale di Gemini...*",
        parse_mode="Markdown"
    )

    local_file_path = None
    try:
        tg_file = await context.bot.get_file(video_obj.file_id)
        os.makedirs(VideoDownloaderService.DOWNLOAD_DIR, exist_ok=True)
        ext = "mp4"
        if hasattr(video_obj, "mime_type") and video_obj.mime_type and "webm" in video_obj.mime_type:
            ext = "webm"
        local_file_path = os.path.join(VideoDownloaderService.DOWNLOAD_DIR, f"{video_obj.file_unique_id}.{ext}")

        await tg_file.download_to_drive(custom_path=local_file_path)

        analysis = llm_svc.analyze_video(local_file_path, user_prompt=caption)
        if analysis.get("type") == "error":
            err_msg = analysis.get("text") or "Errore durante l'analisi del video."
            await status_msg.edit_text(f"⚠️ {err_msg}")
            return

        # Posizioni di portafoglio da registrazione schermo
        if analysis.get("is_portfolio") and analysis.get("positions"):
            positions = analysis["positions"]
            saved_lines = []
            for p in positions:
                asset_name = p.get("asset_name", "Strumento")
                shares = float(p.get("shares", 0.0))
                pmc = float(p.get("average_buy_price", 0.0))
                cand_ticker = p.get("ticker_candidate", "")
                resolved_ticker = resolve_ticker(cand_ticker or asset_name) or cand_ticker or "ASSET"
                if shares > 0 and pmc > 0:
                    supabase_svc.upsert_position(user_id, resolved_ticker, asset_name, shares, pmc, currency="EUR")
                    saved_lines.append(f"• *{asset_name}* (`{resolved_ticker}`): `{shares}` quote a `{pmc:.2f} €`")

            header = "✅ *POSIZIONI ESTRATTE DAL VIDEO E REGISTRATE SU SUPABASE!*\n\n"
            pos_summary = "\n".join(saved_lines)
            reply = f"{header}{pos_summary}\n\nUsa `/portafoglio` per vedere la situazione aggiornata in tempo reale."
            await send_safe_text(update, reply)
            return

        report_text = analysis.get("text", "Analisi video completata.")
        await status_msg.edit_text("🎬 *Analisi Multimodale del Video:*", parse_mode="Markdown")
        await send_safe_text(update, report_text)

        supabase_svc.log_message(user_id, "user", f"[Video inviato] {caption}")
        supabase_svc.log_message(user_id, "assistant", report_text)

    except Exception as e:
        print(f"Errore handle_video: {e}")
        await msg.reply_text(f"⚠️ Si è verificato un errore durante l'elaborazione del video: {str(e)}")
    finally:
        VideoDownloaderService.cleanup(local_file_path)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Riceve ed elabora documenti PDF inviati dall'utente (estratti conto broker come Trade Republic, 
    schede portafoglio, trimestrali, bilanci, report di ricerca).
    """
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    doc = update.message.document
    if not doc:
        return

    async with get_user_lock(user_id):
        file_name = doc.file_name or "documento.pdf"
        caption = update.message.caption or ""

        # Controllo dimensione (limite download Bot API standard 20MB)
        file_size_mb = (doc.file_size or 0) / (1024 * 1024)
        if file_size_mb > 20:
            await update.message.reply_text(
                f"⚠️ *Documento troppo grande per il download diretto di Telegram* (limite: 20MB, questo file è `{file_size_mb:.1f} MB`).",
                parse_mode="Markdown"
            )
            return

        status_msg = await update.message.reply_text(
            f"📄 *Documento PDF ricevuto:* `{file_name}`\n"
            "Scarico ed esamino il contenuto (tabelle di portafoglio, rendiconti e report) con Gemini...",
            parse_mode="Markdown"
        )

        try:
            tg_file = await context.bot.get_file(doc.file_id)
            pdf_bytes = await tg_file.download_as_bytearray()
            raw_pdf_bytes = bytes(pdf_bytes)

            extracted_text = ""
            try:
                reader = pypdf.PdfReader(io.BytesIO(raw_pdf_bytes))
                pages_text = []
                for i, page in enumerate(reader.pages[:30]):
                    t = page.extract_text()
                    if t:
                        pages_text.append(f"--- Pagina {i+1} ---\n{t.strip()}")
                extracted_text = "\n\n".join(pages_text)
            except Exception as pe:
                print(f"[!] Errore estrazione testo pypdf: {pe}")

            user_portfolio = supabase_svc.get_portfolio(user_id)
            user_profile = supabase_svc.get_user_profile(user_id)
            long_term_mem = supabase_svc.get_long_term_summary(user_id)

            analysis = llm_svc.analyze_pdf_document(
                pdf_bytes=raw_pdf_bytes,
                raw_text=extracted_text,
                filename=file_name,
                user_notes=caption,
                user_portfolio=user_portfolio,
                user_profile=user_profile,
                memory_context=long_term_mem
            )

            if analysis.get("type") == "error":
                err_text = analysis.get("text") or "Errore durante l'analisi del documento."
                await status_msg.edit_text(f"⚠️ {err_text}")
                return

            # Se il PDF contiene posizioni di portafoglio (estratto conto Trade Republic, posizioni broker)
            if analysis.get("is_portfolio") and analysis.get("positions"):
                positions = analysis["positions"]
                saved_lines = []
                for p in positions:
                    asset_name = p.get("asset_name", "Strumento")
                    shares = float(p.get("shares", 0.0))
                    pmc = float(p.get("average_buy_price", 0.0))
                    cand_ticker = p.get("ticker_candidate", "")
                    resolved_ticker = resolve_ticker(cand_ticker or asset_name) or cand_ticker or "ASSET"
                    if shares > 0 and pmc > 0:
                        supabase_svc.upsert_position(user_id, resolved_ticker, asset_name, shares, pmc, currency="EUR")
                        saved_lines.append(f"• *{asset_name}* (`{resolved_ticker}`): `{shares:.4f}` quote a `{pmc:.2f} €`")

                header = "✅ *POSIZIONI ESTRATTE DAL DOCUMENTO E SALVATE SU SUPABASE!*\n\n"
                pos_summary = "\n".join(saved_lines) if saved_lines else "Nessuna nuova posizione con parametri validi individuata."
                reply = f"{header}{pos_summary}\n\nUsa `/portafoglio` per visualizzare la situazione ricalcolata in tempo reale con i prezzi live!"

                if status_msg:
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass

                await send_safe_text(update, reply)
                context.user_data["last_interaction"] = {
                    "command": "/document",
                    "topic": f"Import Portafoglio da PDF: {file_name}",
                    "active_ticker": None,
                    "summary": reply[:800],
                    "timestamp": time.time()
                }
                supabase_svc.log_message(user_id, "user", f"[Documento PDF inviato: {file_name}] {caption}".strip())
                supabase_svc.log_message(user_id, "assistant", reply)
                return

            # Caso report / bilancio / analisi finanziaria
            report_text = analysis.get("text", "Analisi del documento completata.")
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

            await send_safe_text(update, report_text)
            context.user_data["last_interaction"] = {
                "command": "/document",
                "topic": f"Analisi Documento PDF: {file_name}",
                "active_ticker": None,
                "summary": report_text[:800],
                "timestamp": time.time()
            }
            supabase_svc.log_message(user_id, "user", f"[Documento PDF inviato: {file_name}] {caption}".strip())
            supabase_svc.log_message(user_id, "assistant", report_text)

        except Exception as e:
            print(f"[!] Errore critico handle_document: {e}")
            if status_msg:
                try:
                    await status_msg.edit_text(f"⚠️ Si è verificato un errore durante l'elaborazione del file PDF: {e}")
                except Exception:
                    pass

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else 0
    try:
        async with get_user_lock(user_id):
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

    # 0. Controllo presenza link video social (YouTube, Shorts, TikTok, Instagram Reels, X/Twitter, direct video)
    video_url = VideoDownloaderService.extract_video_url(raw_text)
    if video_url:
        status_msg = await update.message.reply_text(
            "🎬 *Link video social rilevato!*\nScarico ed esamino il contenuto (audio, fotogrammi e parlato) con la visione multimodale di Gemini...",
            parse_mode="Markdown"
        )
        local_path = VideoDownloaderService.download_video(video_url)
        if not local_path:
            await status_msg.edit_text(
                "⚠️ Non è stato possibile scaricare il video dal link indicato. Il video potrebbe essere privato, rimosso o superare la dimensione massima consentita (40MB)."
            )
            return

        try:
            user_comment = raw_text.replace(video_url, "").strip()
            analysis = llm_svc.analyze_video(local_path, user_prompt=user_comment or "Analizza questo video finanziario")
            if analysis.get("type") == "error":
                err_msg = analysis.get("text") or "Errore durante l'analisi del video."
                await status_msg.edit_text(f"⚠️ {err_msg}")
                return

            if analysis.get("is_portfolio") and analysis.get("positions"):
                positions = analysis["positions"]
                saved_lines = []
                for p in positions:
                    asset_name = p.get("asset_name", "Strumento")
                    shares = float(p.get("shares", 0.0))
                    pmc = float(p.get("average_buy_price", 0.0))
                    cand_ticker = p.get("ticker_candidate", "")
                    resolved_ticker = resolve_ticker(cand_ticker or asset_name) or cand_ticker or "ASSET"
                    if shares > 0 and pmc > 0:
                        supabase_svc.upsert_position(user_id, resolved_ticker, asset_name, shares, pmc, currency="EUR")
                        saved_lines.append(f"• *{asset_name}* (`{resolved_ticker}`): `{shares}` quote a `{pmc:.2f} €`")

                header = "✅ *POSIZIONI ESTRATTE DAL VIDEO E SALVATE SU SUPABASE!*\n\n"
                pos_summary = "\n".join(saved_lines)
                reply = f"{header}{pos_summary}\n\nUsa `/portafoglio` per la situazione aggiornata in tempo reale."
                await send_safe_text(update, reply)
                return

            report_text = analysis.get("text", "Analisi video completata.")
            await status_msg.edit_text("🎬 *Analisi Multimodale del Video Social:*", parse_mode="Markdown")
            await send_safe_text(update, report_text)

            supabase_svc.log_message(user_id, "user", raw_text)
            supabase_svc.log_message(user_id, "assistant", report_text)
            return
        except Exception as ve:
            print(f"Errore analisi link video: {ve}")
            await status_msg.edit_text(f"⚠️ Si è verificato un errore durante l'analisi del video: {str(ve)}")
            return
        finally:
            VideoDownloaderService.cleanup(local_path)

    # Salva il messaggio dell'utente nella memoria di breve termine
    supabase_svc.log_message(user_id, "user", raw_text)

    # Recupera memoria di breve termine (ultimi 8 scambi completi) e lungo termine (30 giorni)
    recent_history = supabase_svc.get_recent_chat_history(user_id, limit=8)
    long_term_mem = supabase_svc.get_long_term_summary(user_id)
    
    memory_context_parts = []
    if long_term_mem:
        memory_context_parts.append(f"Decisioni e tesi dell'ultimo mese: {long_term_mem}")
    if recent_history:
        recent_snippets = [f"{'Michele' if m['role'] == 'user' else 'Consulente'}: {m['content'][:800]}" for m in recent_history[-6:]]
        memory_context_parts.append(f"Scambi recenti della conversazione:\n" + "\n".join(recent_snippets))
    
    memory_context = "\n".join(memory_context_parts)

    # Recupera il topic/ticker attivo nella sessione dell'utente
    active_topic = context.user_data.get("current_topic") or {}
    active_ticker = active_topic.get("ticker", "")

    # Recupera l'ultimo comando / interazione recente dell'utente (entro 30 minuti)
    last_interaction = context.user_data.get("last_interaction") or {}
    last_cmd = last_interaction.get("command", "")
    last_topic = last_interaction.get("topic", "")
    last_summary = last_interaction.get("summary", "")
    last_time = last_interaction.get("timestamp", 0)
    now_ts = time.time()

    last_cmd_ctx = ""
    if last_cmd and (now_ts - last_time < 1800):
        last_cmd_ctx = f"Ultimo comando eseguito: {last_cmd} ({last_topic}). Sintesi risposta precedente: {last_summary[:400]}"

    # Fast-path per comandi composti (es. /portafoglio cosa pensi di BYD?, /previsione NVDA con budget 2000€)
    lower_raw = raw_text.lower()

    if lower_raw.startswith(("/portafoglio ", "portafoglio ")):
        extra = raw_text.split(None, 1)[1].strip() if " " in raw_text else ""
        if extra:
            await portfolio_cmd(update, context, user_query=extra)
            return

    if lower_raw.startswith(("/previsione ", "previsione ", "/previsioni ", "previsioni ", "/forecast ", "forecast ")):
        rem = raw_text.split(None, 1)[1].strip() if " " in raw_text else ""
        if rem:
            parts = rem.split()
            context.args = parts
            await previsione_cmd(update, context, user_query=rem)
            return

    if lower_raw.startswith(("/simula ", "simula ")):
        rem = raw_text.split(None, 1)[1].strip() if " " in raw_text else ""
        if rem:
            context.args = rem.split()
            await simula_cmd(update, context)
            return

    # Comandi rapidi testuali diretti
    if upper_text in ["PORTAFOGLIO", "/PORTAFOGLIO"]:
        await portfolio_cmd(update, context)
        return

    if any(w in upper_text for w in ["OCCASIONI", "/OCCASIONI", "OCCASIONE", "SCONTI", "SCONTO", "OPPORTUNITY", "OPPORTUNITÀ", "MIGLIORI TITOLI", "COSA COMPRARE"]):
        await occasioni_cmd(update, context)
        return

    if any(w in upper_text for w in ["PELOSI", "/PELOSI", "CONGRESSO", "/CONGRESSO", "CAPITOL HILL"]):
        await pelosi_cmd(update, context)
        return

    if any(w in upper_text for w in ["SCANNER", "/SCANNER", "DAYTRADE", "/DAYTRADE", "DAY TRADING"]):
        await scanner_cmd(update, context)
        return

    if any(w in upper_text for w in ["SENTINEL", "/SENTINEL", "RADAR", "/RADAR"]):
        await sentinel_cmd(update, context)
        return

    if any(w in upper_text for w in ["PREVISIONE", "/PREVISIONE", "PREVISIONI", "/PREVISIONI", "FORECAST", "/FORECAST"]):
        context.args = raw_text.split()[1:] if " " in raw_text else []
        await previsione_cmd(update, context)
        return

    if upper_text in ["BRIEFING", "/BRIEFING"]:
        await briefing_cmd(update, context)
        return

    if upper_text in ["MEMORIA", "/MEMORIA"]:
        await memoria_cmd(update, context)
        return

    if upper_text in ["PROFILO", "/PROFILO"]:
        await profile_cmd(update, context)
        return

    if "CICLO" in upper_text or "CICLI" in upper_text or "/CICLI" in upper_text:
        await cicli_cmd(update, context)
        return

    # Prepara il contesto completo degli ultimi scambi per dare continuità logica alla classificazione dell'intento
    recent_context_str = ""
    if recent_history:
        recent_context_str = "\n".join([f"{'Michele' if m['role'] == 'user' else 'Consulente'}: {m['content'][:400]}" for m in recent_history[-4:]])

    # Classificazione intelligente dell'intento tramite Gemini con memoria contestuale e topic attivo
    classification = llm_svc.classify_intent(
        raw_text,
        recent_history_summary=recent_context_str,
        active_topic_ticker=active_ticker,
        last_command_context=last_cmd_ctx
    )
    intent = classification.get("intent", "general_chat")
    ticker = classification.get("ticker") or active_ticker

    # Controllo euristico per richieste di modifica memoria / PAC / preferenze personali
    lower_raw = raw_text.lower()
    is_memory_update_keyword = any(k in lower_raw for k in [
        "ricordati", "memorizza", "piano di accumulo", "il mio pac", "modifica il pac",
        "modifica il piano", "non ho un pac", "non è così", "fartelo ricordare",
        "cambia il profilo", "aggiorna la memoria", "aggiorna il profilo", "ho cambiato strategia",
        "non investo", "non considero"
    ])

    # 1. Se l'utente chiede di modificare il PAC, correggere la memoria o aggiornare il profilo da testo
    if intent == "update_memory_or_profile" or is_memory_update_keyword:
        status_msg = await update.message.reply_text("🧠 *Aggiorno la mia memoria permanente e la tua scheda investitore...*", parse_mode="Markdown")
        user_profile = supabase_svc.get_user_profile(user_id)
        current_long_term = supabase_svc.get_long_term_summary(user_id)

        parsed_update = llm_svc.parse_and_update_memory_request(
            user_text=raw_text,
            current_profile=user_profile,
            current_memory_summary=current_long_term
        )

        profile_mods = parsed_update.get("profile_updates") or {}
        if profile_mods:
            supabase_svc.save_user_profile(user_id, profile_mods)

        mem_fact = parsed_update.get("memory_fact") or ""
        if mem_fact:
            supabase_svc.append_to_long_term_memory(user_id, mem_fact)

        resp_text = parsed_update.get("response_text") or "Ho registrato e memorizzato le tue nuove preferenze operative."

        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

        keyboard = [
            [
                InlineKeyboardButton("👤 Visualizza Scheda Profilo", callback_data="cmd_profile"),
                InlineKeyboardButton("💼 Il Mio Portafoglio", callback_data="cmd_portfolio")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        supabase_svc.log_message(user_id, "assistant", resp_text)
        await send_safe_text(update, resp_text, reply_markup=reply_markup)
        return

    # 1. Se l'utente chiede le migliori occasioni o idee di trading
    if intent == "opportunities":
        await occasioni_cmd(update, context)
        return

    # Se l'utente chiede i trade del congresso o di Nancy Pelosi
    if intent == "congress_trades":
        await pelosi_cmd(update, context)
        return

    # Se l'utente chiede lo scanner dei grafici o setup di day trading
    if intent == "market_scanner":
        await scanner_cmd(update, context)
        return

    # Se l'utente chiede lo stato della sentinella o del radar
    if intent == "sentinel_status":
        await sentinel_cmd(update, context)
        return

    # Se l'utente chiede esplicitamente previsioni o target su un titolo
    if intent == "forecast_prediction":
        target_ticker = ticker or active_ticker or (last_interaction.get("active_ticker") if last_interaction else None)
        context.args = [target_ticker] if target_ticker else []
        await previsione_cmd(update, context, user_query=raw_text)
        return

    # 2. Se l'utente chiede espressamente il bollettino / briefing programmato
    if intent in ["market_briefing", "market_overview"]:
        lower_raw = raw_text.lower()
        if any(w in lower_raw for w in ["perché", "perche", "come mai", "cosa succede", "cosa sta succedendo", "scendendo", "scende", "crolla", "rosso", "calo", "ribasso", "panico"]):
            intent = "market_explanation"
        else:
            await briefing_cmd(update, context)
            return

    # 3. Se l'utente chiede SPIEGAZIONI su cosa muove il mercato o perché scende tutto (Vera Consulenza CIO, Zero Reporter)
    if intent == "market_explanation":
        status_msg = await update.message.reply_text("🧭 *Analizzo i driver macroeconomici, i flussi istituzionali e il tuo portafoglio...*", parse_mode="Markdown")
        indices_summary, global_news, eur_rate = await fetch_macro_market_context()
        user_portfolio = supabase_svc.get_portfolio(user_id)
        user_profile = supabase_svc.get_user_profile(user_id)

        explanation = llm_svc.explain_market_movement(
            user_query=raw_text,
            indices_data=indices_summary,
            news_list=global_news,
            user_portfolio=user_portfolio,
            user_profile=user_profile,
            memory_context=memory_context
        )
        if not explanation:
            explanation = "I mercati registrano una fase di riposizionamento tattico dovuta a flussi di liquidità e tassi d'interesse. Mantieni la calma e la disciplina del piano d'accumulo."

        try:
            await status_msg.delete()
        except Exception:
            pass

        keyboard = [
            [
                InlineKeyboardButton("💼 Diagnosi Portafoglio", callback_data="cmd_portfolio"),
                InlineKeyboardButton("💎 Top Occasioni a Sconto", callback_data="cmd_occasioni")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        supabase_svc.log_message(user_id, "user", raw_text)
        supabase_svc.log_message(user_id, "assistant", explanation)
        await send_safe_text(update, explanation, reply_markup=reply_markup)
        return

    # 3. Se l'utente chiede di aggiornare/sostituire i ticker del portafoglio
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

    # 3. Se l'utente chiede del portafoglio o di riflettere/agire sulle posizioni
    if intent == "portfolio":
        # Controlliamo se è una semplice richiesta di visualizzazione o una domanda/riflessione specifica
        is_simple_view = any(lower_raw.strip() == p for p in [
            "portafoglio", "/portafoglio", "mio portafoglio", "il mio portafoglio",
            "mostrami il portafoglio", "posizioni", "mie posizioni", "visualizza portafoglio",
            "situazione portafoglio", "stato portafoglio", "saldo", "patrimonio"
        ])

        if is_simple_view:
            await portfolio_cmd(update, context)
            return

        # È una domanda/riflessione di approfondimento (es. "cosa pensi se vendo BYD?", "come ribilanciare?")
        status_msg = await update.message.reply_text(
            "💼 *Analizzo la tua riflessione strategica rispetto all'asset allocation e al portafoglio in Euro...*",
            parse_mode="Markdown"
        )
        positions = supabase_svc.get_portfolio(user_id)
        if not positions:
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            await update.message.reply_text("Non hai ancora registrato posizioni in portafoglio. Usa `/add TICKER QUOTE PREZZO` o inviami uno screenshot da Trade Republic.")
            return

        calc_items, total_invested, total_current = compute_portfolio_metrics(positions)
        user_profile = supabase_svc.get_user_profile(user_id)
        last_diagnosis_summary = last_interaction.get("summary", "")

        consultation = llm_svc.generate_portfolio_followup_consultation(
            user_query=raw_text,
            portfolio_items=calc_items,
            total_invested=total_invested,
            total_current=total_current,
            user_profile=user_profile,
            last_diagnosis_summary=last_diagnosis_summary,
            memory_context=memory_context
        )

        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

        if not consultation:
            await portfolio_cmd(update, context, user_query=raw_text)
            return

        keyboard = [
            [
                InlineKeyboardButton("💼 Mostra Tabella Portafoglio", callback_data="cmd_portfolio"),
                InlineKeyboardButton("💎 Top Occasioni", callback_data="cmd_occasioni")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        context.user_data["last_interaction"] = {
            "command": "/portafoglio",
            "topic": "Consulenza Portfolio Follow-up",
            "active_ticker": None,
            "summary": consultation[:800],
            "calc_items": calc_items,
            "total_invested": total_invested,
            "total_current": total_current,
            "timestamp": time.time()
        }
        supabase_svc.log_message(user_id, "user", raw_text)
        supabase_svc.log_message(user_id, "assistant", consultation)
        await send_safe_text(update, consultation, reply_markup=reply_markup)
        return

    # 4. Se l'utente chiede spiegazioni tecniche approfondite su probabilità, indicatori, Z-Score, cicli o onde
    if intent == "technical_explanation":
        active_topic = context.user_data.get("current_topic") or {}
        if not active_topic and ticker:
            resolved_t = resolve_ticker(ticker) or ticker
            active_topic = {"ticker": resolved_t, "asset_name": resolved_t}
        if not active_topic:
            active_topic = {"ticker": "XDEM.DE", "asset_name": "MSCI World Momentum UCITS ETF"}

        target_sym = active_topic.get("ticker", "XDEM.DE")
        df_hist = MarketDataService.get_ticker_history(target_sym, period="6mo", interval="1d")
        if not df_hist.empty and len(df_hist) >= 20:
            hurst_metrics = HurstMigliorinoCycleService.calculate_cycle_metrics(df_hist)
            elliott_metrics = AdvancedPredictiveSystem.detect_elliott_wave_phase(df_hist)
            quote = MarketDataService.get_realtime_quote(target_sym)
            active_topic["quant_data"] = {
                "hurst_migliorino": hurst_metrics,
                "elliott_wave": elliott_metrics,
                "quote": quote
            }
            active_topic["price_eur"] = quote.get("last_price", 0.0)

        status_msg = await update.message.reply_text("🔬 *Elaboro l'approfondimento tecnico e quantitativo sul modello...*", parse_mode="Markdown")
        user_portfolio = supabase_svc.get_portfolio(user_id)
        user_profile = supabase_svc.get_user_profile(user_id)

        tech_explanation = llm_svc.explain_technical_metrics(
            user_query=raw_text,
            topic_info=active_topic,
            user_portfolio=user_portfolio,
            user_profile=user_profile,
            memory_context=memory_context
        )
        if not tech_explanation:
            tech_explanation = "Il nostro modello calcola la probabilità di rimbalzo combinando la deviazione standard (Z-Score) dalla media mobile a 20 sedute, l'oscillatore RSI e il timing ciclico per stimare l'asimmetria statistica favorevole."

        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

        current_t = active_topic.get("ticker", "XDWD.DE")
        keyboard = [
            [
                InlineKeyboardButton(f"🧮 Simula Ordine per {current_t}", callback_data=f"sim_{current_t}"),
                InlineKeyboardButton("💼 Il Mio Portafoglio", callback_data="cmd_portfolio")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        supabase_svc.log_message(user_id, "user", raw_text)
        supabase_svc.log_message(user_id, "assistant", tech_explanation)
        await send_safe_text(update, tech_explanation, reply_markup=reply_markup)
        return

    # 5. Se l'intento è analizzare uno specifico titolo o crypto
    if intent == "ticker_analysis" and ticker:
        # Risolvi ticker per crypto e alias comuni
        resolved = resolve_ticker(ticker) or ticker
        status_msg = await update.message.reply_text(f"🧭 *Valuto la situazione e il contesto di mercato per {resolved}...*", parse_mode="Markdown")
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
            is_already_eur = MarketDataService.is_euro_asset(resolved, fund)
            is_usd = not is_already_eur
            eur_rate = 1.0 if is_already_eur else MarketDataService.get_eur_usd_rate()

            df_tech = TechnicalAnalysisService.calculate_indicators(df_hist)
            pred = PredictiveTradingEngine.generate_prediction_and_trade_plan(df_hist, resolved, currency="EUR" if is_already_eur else "USD")
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

            # Posizione esistente nel portafoglio di Michele
            user_portfolio = supabase_svc.get_portfolio(user_id)
            existing_pos = None
            for p in user_portfolio:
                if p["ticker"].upper() == resolved.upper() or p["ticker"].upper().startswith(resolved.upper().split(".")[0]):
                    sh = float(p["shares"])
                    pmc = float(p["average_buy_price"])
                    c_val = sh * current_p
                    pnl_e = c_val - (sh * pmc)
                    pnl_p = ((current_p - pmc) / pmc) * 100 if pmc > 0 else 0.0
                    existing_pos = {
                        "shares": sh,
                        "pmc": pmc,
                        "current_val": c_val,
                        "pnl_eur": pnl_e,
                        "pnl_pct": pnl_p
                    }
                    break

            user_profile = supabase_svc.get_user_profile(user_id)
            tr_quote = MarketDataService.get_trade_republic_ls_quote(pred['ticker'])
            pred["limit_price_eur"] = limit_price

            # Consulenza Strategica Senior Wealth Advisor / CIO
            advisor_note = llm_svc.generate_advisor_consultation(
                ticker=resolved,
                pred_data=pred,
                fund_data=fund,
                news_list=news,
                cycle_data=cycle_context,
                advanced_data=advanced_context,
                existing_position=existing_pos,
                user_profile=user_profile,
                tr_quote=tr_quote,
                memory_context=memory_context,
                user_query=raw_text
            )

            if not advisor_note:
                advisor_note = (
                    f"🧭 *CONSULENZA STRATEGICA: {fund.get('short_name', ticker)}* (`{pred['ticker']}`)\n\n"
                    f"💶 Prezzo Live: `{current_p:.2f} €`\n\n"
                    f"Consiglio di operare con Ordine Limite a `{limit_price:.2f} €` per proteggersi dallo spread di Lang & Schwarz, con primo target di rimbalzo a `{tp1:.2f} €` e stop di allerta a `{stop_loss:.2f} €`."
                )

            # Tastiera Inline per Deep Dive Quantitativo, Simulazione rapida o Portafoglio
            keyboard = [
                [
                    InlineKeyboardButton("📊 Indicatori di Supporto", callback_data=f"quant_{resolved}"),
                    InlineKeyboardButton("🧮 Simula Ordine su TR", callback_data=f"sim_{resolved}")
                ],
                [
                    InlineKeyboardButton("💼 Verifica nel Mio Portafoglio", callback_data="cmd_portfolio"),
                    InlineKeyboardButton("💎 Altre Occasioni", callback_data="cmd_occasioni")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

            context.user_data["current_topic"] = {
                "ticker": resolved,
                "asset_name": fund.get("short_name", resolved),
                "price_eur": current_p,
                "quant_data": {
                    "rebound_probability": pred.get("mean_reversion_probability", "75%"),
                    "z_score": pred.get("z_score"),
                    "rsi": pred.get("rsi"),
                    "limit_price_eur": limit_price,
                    "tp1_eur": tp1,
                    "stop_loss_eur": stop_loss,
                    "monte_carlo_median": mc_data.get("median_price_eur"),
                    "monte_carlo_ci_68": mc_data.get("ci_68_range_eur"),
                    "monte_carlo_var_95": mc_data.get("var_95_eur"),
                    "hurst_tempo_battleplan": hurst_migl_data.get("tempo_battleplan"),
                    "bars_to_minimum": hurst_migl_data.get("candele_al_minimo"),
                    "wyckoff_phase": wyck_data.get("phase")
                }
            }

            supabase_svc.log_message(user_id, "assistant", advisor_note)
            await send_safe_text(update, advisor_note, reply_markup=reply_markup)
            return
        else:
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

            await update.message.reply_text(f"⚠️ Dati storici non sufficienti per il titolo `{ticker}`.", parse_mode="Markdown")
            return

    # 4. Domanda conversazionale / aperta
    status_msg = await update.message.reply_text("💬 *Ci penso su un secondo...*", parse_mode="Markdown")
    ai_answer = llm_svc.answer_general_query(raw_text, memory_context=memory_context)
    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass

    if ai_answer:
        keyboard = [
            [
                InlineKeyboardButton("💼 Diagnosi Portafoglio", callback_data="cmd_portfolio"),
                InlineKeyboardButton("💎 Top Occasioni a Sconto", callback_data="cmd_occasioni")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        supabase_svc.log_message(user_id, "assistant", ai_answer)
        await send_safe_text(update, ai_answer, reply_markup=reply_markup)
    else:
        fallback = "Dimmi pure: puoi scrivermi il nome di un'azione (es. NVIDIA, TSMC, Tesla), chiedermi /occasioni, /simula o /portafoglio!"
        supabase_svc.log_message(user_id, "assistant", fallback)
        await update.message.reply_text(fallback)

# Callback query handler per il bottone del Deep Dive Tecnico
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "briefing" or data.startswith("briefing"):
        await briefing_cmd(update, context)
        return

    if data == "cmd_portfolio":
        await portfolio_cmd(update, context)
        return

    if data == "cmd_profile":
        await profile_cmd(update, context)
        return

    if data == "cmd_occasioni":
        await occasioni_cmd(update, context)
        return

    if data == "cmd_pelosi":
        await pelosi_cmd(update, context)
        return

    if data == "cmd_scanner":
        await scanner_cmd(update, context)
        return

    if data == "cmd_sentinel":
        await sentinel_cmd(update, context)
        return

    if data == "explain_cycles":
        user_id = update.effective_user.id
        msg_target = query.message
        status_msg = await msg_target.reply_text("🔬 *Elaboro la Guida Completa all'Analisi Ciclica di Migliorino e alle Onde di Elliott...*", parse_mode="Markdown")
        user_portfolio = supabase_svc.get_portfolio(user_id)
        user_profile = supabase_svc.get_user_profile(user_id)
        long_term_mem = supabase_svc.get_long_term_summary(user_id)
        active_topic = context.user_data.get("current_topic") or {"ticker": "XDEM.DE", "asset_name": "MSCI World Momentum UCITS ETF"}

        target_sym = active_topic.get("ticker", "XDEM.DE")
        df_hist = MarketDataService.get_ticker_history(target_sym, period="6mo", interval="1d")
        if not df_hist.empty and len(df_hist) >= 20:
            hurst_metrics = HurstMigliorinoCycleService.calculate_cycle_metrics(df_hist)
            elliott_metrics = AdvancedPredictiveSystem.detect_elliott_wave_phase(df_hist)
            quote = MarketDataService.get_realtime_quote(target_sym)
            active_topic["quant_data"] = {
                "hurst_migliorino": hurst_metrics,
                "elliott_wave": elliott_metrics,
                "quote": quote
            }
            active_topic["price_eur"] = quote.get("last_price", 0.0)

        explanation = llm_svc.explain_technical_metrics(
            user_query="Spiegami in modo dettagliato e senza dare nulla per scontato l'analisi ciclica di Giuseppe Migliorino (i 4 tempi del Battleplan e i vincoli ciclici), la FLD di Hurst e le Onde di Elliott, spiegando il significato pratico per la mia operatività su Trade Republic.",
            topic_info=active_topic,
            user_portfolio=user_portfolio,
            user_profile=user_profile,
            memory_context=long_term_mem
        )
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass
        await send_safe_text(update, explanation)
        return

    if data.startswith("quant_"):
        ticker = data.replace("quant_", "")
        await query.message.reply_text(f"🔬 *Elaboro il Deep Dive Quantitativo per {ticker} (Monte Carlo, FLD & Elliott)...*", parse_mode="Markdown")

        df_hist = MarketDataService.get_ticker_history(ticker, period="6mo", interval="1d")
        if df_hist.empty or len(df_hist) < 20:
            await query.message.reply_text(f"Dati non sufficienti per il Deep Dive di {ticker}.")
            return

        fund = MarketDataService.get_ticker_fundamentals(ticker)
        is_already_eur = MarketDataService.is_euro_asset(ticker, fund)
        is_usd = not is_already_eur
        eur_rate = 1.0 if is_already_eur else MarketDataService.get_eur_usd_rate()

        df_tech = TechnicalAnalysisService.calculate_indicators(df_hist)
        pred = PredictiveTradingEngine.generate_prediction_and_trade_plan(df_hist, ticker, currency="EUR" if is_already_eur else "USD")
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

    elif data.startswith("sim_"):
        ticker = data.replace("sim_", "")
        profile = supabase_svc.get_user_profile(query.from_user.id)
        budget = profile.get("monthly_pac_eur", 500.0)
        sim = OrderSimulatorService.simulate_trade_republic_order(ticker, budget)
        if sim.get("status") == "error":
            await query.message.reply_text(f"⚠️ Impossibile calcolare la simulazione per {ticker}.")
            return
        sim_text = (
            f"📋 *SCHEDA OPERATIVA TRADE REPUBLIC: {sim['asset_name']}* (`{sim['ticker']}`)\n\n"
            f"💶 *Budget Allocato:* `{sim['budget_eur']:.2f} €` (calibrato sul tuo PAC)\n"
            f"🏷️ *Prezzo Attuale:* `{sim['current_price_eur']:.2f} €`\n"
            f"📦 *Quote Esatte da Comprare:* `{sim['shares_to_buy']} quote`\n\n"
            f"⚙️ *Parametri d'Ordine su Trade Republic:*\n"
            f"• Tipo d'Ordine: *{sim['suggested_order_type']}*\n"
            f"• Prezzo Limite Consigliato: `{sim['limit_price_eur']:.2f} €` (protezione anti-spread L&S)\n\n"
            f"🎯 *Rapporto Rischio / Rendimento:*\n"
            f"• Take Profit (TP1): `{sim['tp1_eur']:.2f} €` (R:R `{sim['risk_reward_tp1']}`)\n"
            f"• Stop Loss Consigliato: `{sim['stop_loss_eur']:.2f} €`\n\n"
            f"💡 *Come inserire l'ordine su Trade Republic:*\n"
            f"Apri l'app > Cerca `{sim['ticker']}` > Clicca su *Acquista* > In alto a destra seleziona *Ordine Limite* > Inserisci `{sim['limit_price_eur']:.2f} €` e `{sim['shares_to_buy']}` quote."
        )
        await send_safe_text(query, sim_text)

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

        cleaned_briefing = clean_telegram_markdown(briefing_text)
        for chat_id in chat_ids:
            chunks = []
            if len(cleaned_briefing) <= 3500:
                chunks = [cleaned_briefing]
            else:
                curr = ""
                for p in cleaned_briefing.split("\n\n"):
                    if len(curr) + len(p) + 2 > 3500:
                        if curr:
                            chunks.append(curr)
                        curr = p
                    else:
                        curr = (curr + "\n\n" + p) if curr else p
                if curr:
                    chunks.append(curr)

            for chunk in chunks:
                chunk_clean = clean_telegram_markdown(chunk)
                try:
                    await app.bot.send_message(chat_id=chat_id, text=chunk_clean, parse_mode="Markdown")
                except Exception as e_parse:
                    print(f"[!] Warning parsing Markdown briefing Telegram ({e_parse}): fallback a strip_markdown pulito")
                    try:
                        await app.bot.send_message(chat_id=chat_id, text=strip_markdown(chunk))
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

async def sentinel_watchdog_job(application):
    """Esegue il controllo proattivo periodico della sentinella."""
    try:
        res = await sentinel_svc.run_sentinel_watchdog(application)
        if res and res != "no_triggers":
            print(f"🛡️ [Sentinel] Risultato watchdog: {res}")
    except Exception as e:
        print(f"[!] Errore sentinel_watchdog_job: {e}")

async def post_init(application):
    """Configura il menu dei comandi nativo di Telegram e avvia lo scheduler dei briefing e della sentinella proattiva."""
    bot_commands = [
        BotCommand("portafoglio", "💼 Diagnosi del portafoglio e asset allocation"),
        BotCommand("previsione", "🔮 Previsione ensemble (Monte Carlo, Hurst & Z-Score)"),
        BotCommand("sentinel", "🛡️ Stato radar sentinella proattiva 24/7"),
        BotCommand("scanner", "⚡ Day trader chart scanner (breakout & ipervenduto)"),
        BotCommand("pelosi", "🏛️ Congressional trades & Pelosi tracker"),
        BotCommand("profilo", "👤 Profilo investitore, PAC e orizzonte temporale"),
        BotCommand("briefing", "🌅 Quadro di mercato, Wall Street ed Europa"),
        BotCommand("occasioni", "💎 Top 10 occasioni a sconto con tesi del CIO"),
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

    # Avvio Scheduler Asincrono per briefing e sentinella proattiva
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
        # Watchdog proattivo ogni 20 minuti
        scheduler.add_job(
            sentinel_watchdog_job,
            CronTrigger(minute="*/20", timezone="Europe/Rome"),
            args=[application],
            id="sentinel_watchdog_20min",
            replace_existing=True
        )
        scheduler.start()
        application.bot_data["briefing_scheduler"] = scheduler
        print("⏰ [Scheduler] Programmato: Briefing 07:00 / 15:00 CET | Watchdog Sentinella ogni 20 minuti!")
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
    app.add_handler(CommandHandler("aiuto", start_cmd))
    app.add_handler(CommandHandler("briefing", briefing_cmd))
    app.add_handler(CommandHandler("occasioni", occasioni_cmd))
    app.add_handler(CommandHandler("pelosi", pelosi_cmd))
    app.add_handler(CommandHandler("congresso", pelosi_cmd))
    app.add_handler(CommandHandler("scanner", scanner_cmd))
    app.add_handler(CommandHandler("daytrade", scanner_cmd))
    app.add_handler(CommandHandler("previsione", previsione_cmd))
    app.add_handler(CommandHandler("forecast", previsione_cmd))
    app.add_handler(CommandHandler("sentinel", sentinel_cmd))
    app.add_handler(CommandHandler("radar", sentinel_cmd))
    app.add_handler(CommandHandler("cicli", cicli_cmd))
    app.add_handler(CommandHandler("simula", simula_cmd))
    app.add_handler(CommandHandler("portafoglio", portfolio_cmd))
    app.add_handler(CommandHandler("profilo", profile_cmd))
    app.add_handler(CommandHandler("memoria", memoria_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE | filters.ANIMATION, handle_video))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))

    print("🤖 Bot Telegram Market Sentinel (Senior Edition - Full Italian & EUR) avviato...")
    app.run_polling()

if __name__ == "__main__":
    main()
