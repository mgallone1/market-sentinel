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
import html
import time
import asyncio
import pypdf
from pathlib import Path
from typing import Dict, Any, Optional, Set, Tuple, List
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
from apscheduler.triggers.interval import IntervalTrigger
from zoneinfo import ZoneInfo
from datetime import datetime

from services.market_data import MarketDataService
from services import market_calendar
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
from services.alpaca_execution_service import AlpacaExecutionService
from services.bybit_execution_service import BybitExecutionService, make_order_link_id, classify_btc_bias, hysteresis_bias
from services.risk_budget_manager import RiskBudgetManager
from services import risk_limits
from services.dashboard_web_service import create_web_app
from aiohttp import web

try:
    alpaca_service = AlpacaExecutionService()
except Exception as _e_alp:
    alpaca_service = None
    print(f"[!] Alpaca disabilitato: {_e_alp}")
bybit_service = BybitExecutionService()
risk_manager = RiskBudgetManager(max_risk_usd=100.0, min_rr=2.0)
from services.video_downloader import VideoDownloaderService
from services.day_trader_service import DayTraderService
from services.ensemble_predictor import EnsemblePredictorEngine
from services.proactive_sentinel import ProactiveSentinelService
from services.trade_journal_service import TradeJournalService
from services import learning_engine_service
from services.learning_engine_service import (
    learning_engine,
    normalize_context_key,
    compute_atr_ratchet_levels,
    optimize_exit_frontier,
)
from services import telemetry_features as tele_v2
from services.strategy_engines_service import (
    ENGINE_TREND_PULLBACK,
    ENGINE_LIQUIDITY_SWEEP,
    ENGINE_INTRADAY_MOMENTUM,
    ENGINE_ORB_BREAKOUT,
    prepare_closed_bars,
    compute_adx,
    compute_spread_bps,
    extract_normalized_features,
    regime_router,
    engine_trend_pullback_4h1d,
    engine_liquidity_sweep_mr,
    engine_intraday_momentum,
    engine_orb_breakout_15m,
    evaluate_timemachine_gate,
    evaluate_fokker_planck,
    replay_signal_history,
    late_session_entry_check,
    STRATEGY_RULESET_VERSION,
    select_best_signal,
)

supabase_svc = SupabaseService()
llm_svc = LLMReasoningService()
day_trader_svc = DayTraderService()
sentinel_svc = ProactiveSentinelService()
trade_journal_svc = TradeJournalService()
ACTIVE_CHAT_IDS: Set[int] = set()
ALLOWED_CHAT_ID: Optional[str] = os.getenv("ALLOWED_CHAT_ID", "").strip() or None

def get_target_chat_ids() -> Set[int]:
    """Restituisce l'insieme di tutti i chat_id registrati su Supabase e attivi nella sessione."""
    target_ids = set(ACTIVE_CHAT_IDS)
    try:
        db_ids = supabase_svc.get_active_chat_ids()
        if db_ids:
            target_ids.update(db_ids)
    except Exception:
        pass
    if not target_ids:
        target_ids.add(424093845)
    return target_ids


def _resolve_learning_chat_ids() -> List[int]:
    """Risolve i chat_id destinatari degli audit automatici privilegiando ALLOWED_CHAT_ID se configurato."""
    raw = str(ALLOWED_CHAT_ID or os.getenv("ALLOWED_CHAT_ID", "")).strip()
    if raw and raw.lower() != "none":
        try:
            return [int(raw)]
        except Exception:
            pass
    return sorted(get_target_chat_ids())


def _is_chat_authorized(update: Any) -> bool:
    """Verifica autorizzazione chat rispetto ad ALLOWED_CHAT_ID (se configurato)."""
    raw = str(ALLOWED_CHAT_ID or os.getenv("ALLOWED_CHAT_ID", "")).strip()
    if not raw or raw.lower() == "none":
        return True
    chat_obj = getattr(update, "effective_chat", None)
    user_obj = getattr(update, "effective_user", None)
    cid = getattr(chat_obj, "id", None) if chat_obj is not None else None
    uid = getattr(user_obj, "id", None) if user_obj is not None else None
    return str(cid) == raw or str(uid) == raw

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
    # Commodities: Metalli Preziosi e Petrolio (Negoziabili su Alpaca & Trade Republic)
    "ORO": "GLD",
    "GOLD": "GLD",
    "GLD": "GLD",
    "ARGENTO": "SLV",
    "SILVER": "SLV",
    "SLV": "SLV",
    "PETROLIO": "USO",
    "OIL": "USO",
    "CRUDE OIL": "USO",
    "USO": "USO",
    "BRENT": "BNO",
    "BNO": "BNO",
    "GAS": "UNG",
    "GAS NATURALE": "UNG",
    "NATURAL GAS": "UNG",
    "UNG": "UNG",
    "RAME": "CPER",
    "COPPER": "CPER",
    "CPER": "CPER",
    "PLATINO": "PPLT",
    "PLATINUM": "PPLT",
    "PPLT": "PPLT",
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

def get_target_msg(update: Any):
    """Restituisce l'oggetto messaggio valido per .reply_text sia per comandi che per callback query."""
    if hasattr(update, "callback_query") and update.callback_query and getattr(update.callback_query, "message", None):
        return update.callback_query.message
    if hasattr(update, "message") and getattr(update, "message", None):
        return update.message
    if getattr(update, "effective_message", None):
        return update.effective_message
    return update

async def send_safe_text(update: Any, text: str, parse_mode: str = "Markdown", reply_markup: Optional[InlineKeyboardMarkup] = None):
    """
    Invia messaggi spezzandoli automaticamente se superano il limite Telegram (3500 caratteri)
    e sanificando preventivamente il Markdown per eliminare caratteri grezzi (*, #).
    In caso di qualsiasi eccezione dell'entity parser di Telegram, esegue un fallback a strip_markdown
    senza parse_mode per garantire che l'utente non veda MAI asterischi o cancelletti a schermo.
    """
    target = get_target_msg(update)
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
        "👋 *Ciao! Sono il tuo Market Sentinel & Financial Copilot personale.*\n\n"
        "Comandi rapidi disponibili:\n\n"
        "⚡ `/alpaca` — Pannello trading live: saldo, posizioni aperte, movimenti odierni e chiusure\n"
        "🪙 `/crypto` — Trading Crypto 24/7 (Bitcoin, Ethereum, Solana con quotazioni in EUR e ordini 1-click)\n"
        "💼 `/portafoglio` — Diagnosi del portafoglio titoli Trade Republic e pesi di allocazione\n"
        "🌅 `/briefing` — Quadro di mercato macro, indici Wall Street ed Europa e breaking news\n"
        "⚡ `/scanner` — Day trader chart scanner per breakout a 20 giorni, bull flags e rimbalzi\n"
        "🏛️ `/pelosi` — Tracker dei disclosure ufficiali (PTR) del Congresso USA e di Capitol Hill\n"
        "💎 `/occasioni` — Top opportunità e titoli a forte sconto statistico\n"
        "🛡️ `/sentinel` — Stato del radar di sorveglianza proattiva continua\n\n"
        "💡 *Interazione Libera:* Puoi sempre scrivermi in chat naturale (es. _\"Come va su Alpaca?\"_, _\"Shorta Nvidia\"_, _\"Compra 2500$ di Solana\"_ o mandarmi uno screenshot di Trade Republic)."
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
    - Riconosce weekend (Sabato/Domenica): borse tradizionali CHIUSE, focus su bilancio, macro & crypto 24/7.
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
    is_weekend = now_rome.weekday() >= 5
    day_name = "Sabato" if now_rome.weekday() == 5 else ("Domenica" if now_rome.weekday() == 6 else "")

    if is_weekend:
        slot = "weekend"
        title_header = f"☕ *BRIEFING WEEKEND ({day_name.upper()} ORE {cur_time} CET) - MERCATI CHIUSI & SINTESI*"
    else:
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

    status_tag = " (Mercati Chiusi nel Weekend)" if is_weekend else ""
    header_lines = [
        title_header + "\n",
        f"💶 *Tasso di Cambio EUR/USD:* `1.00 € = {eur_rate:.4f} $`\n",
        f"📊 *Indici & Asset Chiave (in Euro){status_tag}:*"
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
        if is_weekend:
            macro_comment = (
                f"I mercati azionari tradizionali sono chiusi per il fine settimana ({day_name}). "
                "La settimana si è chiusa con un bilancio guidato dai dati sull'inflazione e dai rendimenti obbligazionari. "
                "Il mercato Crypto prosegue gli scambi 24/7 mentre gli investitori monitorano le tensioni geopolitiche in vista della riapertura di lunedì."
            )
        elif slot == "morning":
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
        is_weekend = now_rome.weekday() >= 5
        day_name = "Sabato" if now_rome.weekday() == 5 else ("Domenica" if now_rome.weekday() == 6 else "")

        if is_weekend:
            slot = "weekend"
            slot_label = f"del weekend ({day_name} ore {cur_time} CET - Borse chiuse)"
        elif 6 <= h < 12:
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
    msg_target = get_target_msg(update)

    async with get_user_lock(user_id):
        await msg_target.reply_text("📡 *Scansione Multi-Ciclica & Previsionale in corso (Hurst & Migliorino)...*", parse_mode="Markdown")

        radar_items = CycleRadarService.scan_active_cycles()
        if not radar_items:
            await msg_target.reply_text("Nessun ciclo attivo calcolabile.")
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
        msg_target = get_target_msg(update)
        await msg_target.reply_text("\n".join(lines), parse_mode="Markdown")

async def occasioni_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ACTIVE_CHAT_IDS.add(user_id)
    msg_target = get_target_msg(update)

    async with get_user_lock(user_id):
        await msg_target.reply_text("🔍 *Scansione quantitativa in corso sui mercati... elaboro le 10 migliori occasioni con approfondimento discorsivo in Euro (€)...*", parse_mode="Markdown")
        
        opps = OpportunityScannerService.scan_best_opportunities(top_n=10)
        if not opps:
            await msg_target.reply_text("Nessun titolo attualmente in forte anomalia statistica.")
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
    msg_target = get_target_msg(update)

    async with get_user_lock(user_id):
        status_msg = await msg_target.reply_text("🏛️ *Consulto i registri del Congresso USA e i report PTR ufficiali (Day Trader Suite)...*", parse_mode="Markdown")

        try:
            user_profile = supabase_svc.get_user_profile(user_id)
            current_long_term = supabase_svc.get_long_term_summary(user_id)

            filings = day_trader_svc.get_congress_trades(member="pelosi", max_reports=3)
            trump_filings = day_trader_svc.get_trump_disclosures(max_reports=3)

            # Combina i disclosure di Capitol Hill con i Form 4 SEC di Trump & Family
            all_political_filings = filings + trump_filings

            if not all_political_filings:
                await send_safe_text(update, "Non sono riuscito a reperire i disclosure recenti in questo momento. Riprova più tardi.")
                return

            user_query = "Quali sono gli ultimi disclosure e trade ufficiali depositati da Nancy Pelosi, Donald Trump & famiglia e membri chiave del Congresso USA?"
            explanation = llm_svc.explain_congress_trades(
                user_query=user_query,
                filings=all_political_filings,
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
    msg_target = get_target_msg(update)

    async with get_user_lock(user_id):
        status_msg = await msg_target.reply_text("⚡ *Scansione dei grafici in corso: cerco breakout a 20 giorni, bull flags e titoli in ipervenduto...*", parse_mode="Markdown")

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
        msg_target = get_target_msg(update)
        status_msg = await msg_target.reply_text(f"🔮 *Elaboro la Previsione Quantitativa d'Insieme per {ticker} (Monte Carlo, Hurst & Z-Score)...*", parse_mode="Markdown")

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
    msg_target = get_target_msg(update)

    async with get_user_lock(user_id):
        args = context.args or []
        if len(args) < 1:
            await msg_target.reply_text(
                "Uso corretto del simulatore: `/simula <TICKER> [BUDGET_IN_EURO]`\n\n"
                "Esempi:\n"
                "• `/simula NVDA` (Calcola automaticamente su base 1 quota o PAC)\n"
                "• `/simula TSM 500` (Simula 500€ su TSMC)\n"
                "• `/simula NVDA 1000` (Simula 1.000€ su NVIDIA)",
                parse_mode="Markdown"
            )
            return

        raw_ticker = args[0].upper()
        ticker = resolve_ticker(raw_ticker) or raw_ticker
        
        budget = 0.0
        if len(args) >= 2:
            try:
                budget = float(args[1].replace("€", "").replace(",", "."))
            except ValueError:
                await msg_target.reply_text("Inserisci un budget numerico valido in Euro.")
                return
        else:
            # Nessun budget passato da riga di comando: controlla il profilo utente
            profile = supabase_svc.get_user_profile(user_id) or {}
            budget = float(profile.get("monthly_pac_eur", 0.0) or 0.0)

        calc_note = f" con budget di *{budget:.2f} €*" if budget > 0 else " con dimensionamento automatico"
        await msg_target.reply_text(f"🧮 Calcolo il piano di acquisto per *{ticker}*{calc_note}...", parse_mode="Markdown")
        sim = OrderSimulatorService.simulate_order(ticker, budget)
        if "error" in sim:
            await msg_target.reply_text(f"Errore nella simulazione: {sim['error']}")
            return

        budget_note = " (calibrato sul tuo PAC)" if (not sim.get("budget_is_fallback") and budget > 0) else " _(simulazione standard / quota intera base)_"
        reply = (
            f"📋 *SCHEDA OPERATIVA TRADE REPUBLIC: {sim['asset_name']}* (`{sim['ticker']}`)\n\n"
            f"💶 *Budget Allocato:* `{sim['budget_eur']:.2f} €`{budget_note}\n"
            f"🏷️ *Prezzo Attuale di Mercato:* `{sim['current_price_eur']:.2f} €`\n"
            f"📦 *Quote Esatte da Comprare:* `{sim['shares_to_buy']} quote`\n\n"
            f"⚙️ *Parametri di Ordine Consigliati su Trade Republic:*\n"
            f"• Tipo d'Ordine: *{sim['suggested_order_type']}*\n"
            f"• Prezzo Limite da Inserire: `{sim['limit_price_eur']:.2f} €` (protezione anti-spread)\n\n"
            f"🎯 *Rapporto Rischio / Rendimento:* `{sim['risk_reward_ratio']}`\n"
            f"• 🟢 *Obiettivo Take Profit (TP1):* `{sim['tp1_eur']:.2f} €` ➔ Potenziale guadagno: *+{sim['potential_gain_eur']:.2f} €* (`+{sim['potential_gain_pct']}%`)\n"
            f"• 🔴 *Livello Stop Loss (Invalidazione):* `{sim['sl_eur']:.2f} €` ➔ Rischio monetario massimo: *{sim['monetary_risk_eur']:.2f} €* (`-{sim['monetary_risk_pct']}%`)\n\n"
            f"💡 *Nota:* Per personalizzare il budget digita `/simula {sim['ticker']} <IMPORTO>` (es. `/simula {sim['ticker']} 500`)."
        )
        await msg_target.reply_text(reply, parse_mode="Markdown")

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
    msg_target = get_target_msg(update)
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
                await msg_target.reply_text(
                    f"✅ *Budget PAC aggiornato!*\n"
                    f"Ora il tuo piano di accumulo mensile è impostato su `{val:.2f} €/mese`.\n"
                    f"Tutti i consigli di acquisto, simulazione e ribilanciamento terranno conto di questo importo.",
                    parse_mode="Markdown"
                )
                return

        if "orizzonte" in full_arg or "anni" in full_arg:
            profile["horizon"] = " ".join(args)
            supabase_svc.save_user_profile(user_id, profile)
            await msg_target.reply_text(
                f"✅ *Orizzonte temporale aggiornato a:*\n`{profile['horizon']}`",
                parse_mode="Markdown"
            )
            return

        if "rischio" in full_arg:
            profile["risk_profile"] = " ".join(args)
            supabase_svc.save_user_profile(user_id, profile)
            await msg_target.reply_text(
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
    msg_target = get_target_msg(update)

    async with get_user_lock(user_id):
        # Se user_query non è specificato ma context.args contiene testo aggiuntivo (es. /portafoglio cosa pensi di BYD?)
        if user_query is None and context.args:
            user_query = " ".join(context.args)

        positions = supabase_svc.get_portfolio(user_id)
        if not positions:
            await msg_target.reply_text(
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
        status_msg = await msg_target.reply_text(
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

    # --- 0.0 INTERCETTAZIONE RAPIDA COMANDI CHAT SENZA SLASH ---
    lower_raw = raw_text.strip().lower()
    if lower_raw in ["alpaca", "trade", "trading", "saldo", "conto"] or (
        "alpaca" in lower_raw and any(k in lower_raw for k in ["come sta andando", "come va", "andando con", "andando su", "perso", "guadagnato", "stato", "saldo", "posizioni", "portafoglio alpaca"])
    ):
        await alpaca_cmd(update, context)
        return

    # --- 0.1 INTERCETTAZIONE ORDINI IN TEMPO REALE SU ALPACA ---
    # Riconosce ordini vocali/testuali tipo: "compra 5 azioni di NVDA", "vai short su Nvidia con 50 quote", "vendi TSLA", "fai un trade su AAPL", "compra 100$ di NVDA"
    order_pattern = re.search(r'\b(?:vai\s+)?(compra|acquista|long|short|vendi)\s+(\d+(?:\.\d+)?)\s*(azioni|pezzi|quote|\$|euro|usd)?\s*(?:di|su)?\s*([A-Za-z0-9\.\-\/]+)', raw_text, re.IGNORECASE)
    if not order_pattern:
        # Es. "vai short su Nvidia con 50 quote"
        order_pattern_alt = re.search(r'\b(?:vai\s+)?(compra|acquista|long|short|vendi)\s+(?:su\s+|di\s+)?([A-Za-z0-9\.\-\/]+)\s+(?:con\s+|per\s+)?(\d+(?:\.\d+)?)\s*(azioni|pezzi|quote|\$|euro|usd)?', raw_text, re.IGNORECASE)
        if order_pattern_alt:
            g = order_pattern_alt.groups()
            action = g[0].lower()
            side = "sell" if action in ["short", "vendi"] else "buy"
            sym = g[1].upper()
            val_num = float(g[2]) if g[2] else 1.0
            unit = (g[3] or "azioni").lower()
            order_pattern = True
        else:
            order_pattern = re.search(r'\b(?:vai\s+)?(compra|acquista|long|short|vendi)\s+([A-Za-z0-9\.\-\/]+)\s*(?:per\s+)?(\d+(?:\.\d+)?)\s*(\$|euro|usd|azioni|quote)?', raw_text, re.IGNORECASE)

    if order_pattern and order_pattern is not True:
        groups = order_pattern.groups()
        # Normalizza i campi
        action = groups[0].lower()
        side = "sell" if action in ["short", "vendi"] else "buy"
        
        # Estrai ticker e quantità/ammontare
        if groups[1].replace('.', '', 1).isdigit():
            val_num = float(groups[1])
            unit = (groups[2] or "azioni").lower()
            sym = groups[3].upper()
        else:
            sym = groups[1].upper()
            val_num = float(groups[2]) if groups[2] else 1.0
            unit = (groups[3] or "azioni").lower()

        # Risolvi ticker (es. NVIDIA -> NVDA, TESLA -> TSLA)
        resolved_sym = resolve_ticker(sym) or sym
        resolved_sym = resolved_sym.replace(".MI", "") # Alpaca tratta ticker USA o crypto

        status_order_msg = await update.message.reply_text(
            f"⚡ *ELABORAZIONE ORDINE ALPACA IN TEMPO REALE...*\n"
            f"• *Operazione:* `{side.upper()}`\n"
            f"• *Strumento:* `{resolved_sym}`\n"
            f"• *Parametro:* `{val_num} {unit}`\n"
            f"Calcolo parametri prima dell'invio a mercato...",
            parse_mode="Markdown"
        )

        # Riconoscimento speciale per Crypto (BTC, ETH, SOL, LINK, AVAX...) -> 100% SU BYBIT FUTURES DEMO
        is_crypto_target = any(c in resolved_sym for c in ["BTC", "ETH", "SOL", "LINK", "AVAX", "XRP", "DOGE", "BITCOIN", "ETHEREUM", "SOLANA"]) or "/" in resolved_sym
        if is_crypto_target:
            bybit_sym = "BTCUSDT" if "BTC" in resolved_sym or "BITCOIN" in resolved_sym else (
                "ETHUSDT" if "ETH" in resolved_sym or "ETHEREUM" in resolved_sym else (
                    "SOLUSDT" if "SOL" in resolved_sym or "SOLANA" in resolved_sym else (
                        "LINKUSDT" if "LINK" in resolved_sym else (
                            "AVAXUSDT" if "AVAX" in resolved_sym else (
                                "XRPUSDT" if "XRP" in resolved_sym else (
                                    "DOGEUSDT" if "DOGE" in resolved_sym else f"{resolved_sym.replace('/', '')}USDT"
                                )
                            )
                        )
                    )
                )
            )
            # Se l'utente specifica un importo in valuta lo usa, altrimenti assegna default aggressivo di $15.000
            if unit in ["$", "usd", "euro", "dollari"]:
                notional_amt = val_num
            elif unit in ["azioni", "quote", "crypto", "pezzi"] and val_num <= 10:
                notional_amt = val_num * 15000.0
            else:
                notional_amt = 15000.0

            side_bybit = "Buy" if side.lower() in ["buy", "long", "compra"] else "Sell"
            action_label = "LONG (Rialzista)" if side_bybit == "Buy" else "SHORT (Ribassista)"
            action_icon = "🟢" if side_bybit == "Buy" else "🔻"

            res_order = bybit_service.place_order(symbol=bybit_sym, side=side_bybit, notional_usd=notional_amt, take_profit_pct=0.8, stop_loss_pct=0.6)
            if "error" in res_order:
                await status_order_msg.edit_text(
                    f"⚠️ *Errore ordine Crypto su Bybit:*\n`{res_order['error']}`",
                    parse_mode="Markdown"
                )
            else:
                await status_order_msg.edit_text(
                    f"{action_icon} *ORDINE CRYPTO ESEGUITO SU BYBIT (24/7)!* 🚀\n"
                    f"────────────────────────\n"
                    f"• *Contratto:* `{bybit_sym}`\n"
                    f"• *Operazione:* `{action_label}`\n"
                    f"• *Importo Notionale:* `${notional_amt:,.2f} USDT`\n"
                    f"• *Prezzo Esecuzione:* `${res_order.get('price'):.2f}`\n"
                    f"• *Take Profit:* `${res_order.get('take_profit')}` (+0.80% ~+$120 USDT)\n"
                    f"• *Stop Loss:* `${res_order.get('stop_loss')}` (-0.60%)\n"
                    f"• *Protezione Break-Even:* Attiva al +0.30%\n"
                    f"• *Status:* `APERTO SUL CONTO DEMO BYBIT` 🎯\n\n"
                    f"💡 _Visualizza il saldo e le posizioni con `/crypto`._",
                    parse_mode="Markdown"
                )
            return

        try:
            # Recupera ultimo prezzo
            quote = MarketDataService.get_realtime_quote(resolved_sym)
            last_p = quote.get("price") if quote else None
            if not last_p or last_p <= 0:
                last_p = 100.0 # fallback

            # Calcolo quote se importo in $
            if unit in ["$", "usd", "euro"]:
                shares = max(1, int(val_num / last_p))
            else:
                shares = max(1, int(val_num))

            # Calcola Bracket automatico (Stop 1.5%, Target 3.0% = 2R)
            if side == "buy":
                stop_loss = round(last_p * 0.985, 2)
                take_profit = round(last_p * 1.03, 2)
            else:
                stop_loss = round(last_p * 1.015, 2)
                take_profit = round(last_p * 0.97, 2)

            if alpaca_service is None:
                await send_safe_text(update, "Alpaca non configurato.")
                return
            # Invia ordine bracket su Alpaca
            order_res = alpaca_service.place_bracket_order(
                symbol=resolved_sym,
                qty=shares,
                side=side,
                take_profit_price=take_profit,
                stop_loss_price=stop_loss
            )

            if "error" in order_res:
                await status_order_msg.edit_text(
                    f"⚠️ *Errore rifiuto ordine da Alpaca:*\n`{order_res['error']}`\n\n"
                    f"_Verifica che la borsa sia aperta (ore 15:30) o che l'asset sia negoziabile._",
                    parse_mode="Markdown"
                )
            else:
                order_id = order_res.get('id', 'N/D')
                await status_order_msg.edit_text(
                    f"✅ *ORDINE ESEGUITO SU ALPACA!* 🚀\n"
                    f"────────────────────────\n"
                    f"• *ID Ordine:* `{order_id[:8]}...`\n"
                    f"• *Operazione:* `{side.upper()} x{shares} {resolved_sym}`\n"
                    f"• *Prezzo Stimato:* `${last_p:.2f}`\n"
                    f"• *Stop Loss Protettivo:* `${stop_loss:.2f}` (-1.5%)\n"
                    f"• *Take Profit Automatico (2R):* `${take_profit:.2f}` (+3.0%)\n"
                    f"• *Tipo Ordine:* `Bracket Day Order`\n\n"
                    f"L'operazione è ora registrata e visibile sul tuo conto Alpaca Paper.",
                    parse_mode="Markdown"
                )
            return
        except Exception as oe:
            await status_order_msg.edit_text(f"⚠️ Errore esecuzione ordine: {oe}")
            return

    # Recupera memoria di breve termine (ultimi 8 scambi completi) e lungo termine (30 giorni)
    recent_history = supabase_svc.get_recent_chat_history(user_id, limit=8)
    long_term_mem = supabase_svc.get_long_term_summary(user_id)
    
    memory_context_parts = []
    if long_term_mem:
        memory_context_parts.append(f"Decisioni e tesi dell'ultimo mese: {long_term_mem}")
    if recent_history:
        # Sanifica gli estratti della memoria recente: elimina vecchie domande retoriche o paternalismi
        cleaned_history = []
        for m in recent_history[-6:]:
            speaker = 'Michele' if m['role'] == 'user' else 'Consulente'
            txt = clean_telegram_markdown(m['content'])[:500]
            cleaned_history.append(f"{speaker}: {txt}")
        memory_context_parts.append("Scambi recenti della conversazione:\n" + "\n".join(cleaned_history))
    
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

    # Se l'utente chiede lo stato di Alpaca o del trading paper
    if intent == "alpaca_status":
        await alpaca_cmd(update, context)
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

            # Se non ci sono dati di borsa (es. società non quotata come Anthropic o OpenAI, oppure query discorsiva)
            # passa la palla ad answer_general_query per non bloccare la risposta
            status_msg = await update.message.reply_text("💬 *Analizzo il contesto societario e macroeconomico...*", parse_mode="Markdown")
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
                supabase_svc.log_message(user_id, "user", raw_text)
                supabase_svc.log_message(user_id, "assistant", ai_answer)
                await send_safe_text(update, ai_answer, reply_markup=reply_markup)
            else:
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

    if data == "briefing" or data.startswith("briefing") or data == "cmd_briefing":
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

    if data in ("alpaca_refresh", "alpaca_close_all", "buy_gld", "buy_uso", "buy_slv", "buy_crypto_btc", "buy_crypto_eth", "buy_crypto_sol") and alpaca_service is None:
        await query.message.reply_text("Alpaca non configurato.")
        return

    if data == "alpaca_refresh":
        summary = alpaca_service.get_account_summary()
        acc = summary.get("account", {})
        if "error" in acc:
            await query.message.edit_text(f"⚠️ Errore connessione Alpaca: {acc['error']}")
            return

        msg, markup = build_alpaca_dashboard_text(summary)
        try:
            await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            if "Message is not modified" not in str(e):
                print(f"[!] Warning edit alpaca_refresh: {e}")
        return

    if data == "cmd_crypto":
        # Inoltra al pannello unificato Bybit Crypto 24/7
        await crypto_cmd(update, context)
        return

    if data == "alpaca_close_all":
        res = alpaca_service.close_all_positions()
        await query.message.reply_text("🚨 *Tutte le posizioni Alpaca sono state liquidate a mercato.*", parse_mode="Markdown")
        return

    if data == "alpaca_run_scanner":
        await scanner_cmd(update, context)
        return

    if data in ["buy_gld", "buy_uso", "buy_slv"]:
        sym_map = {"buy_gld": "GLD", "buy_uso": "USO", "buy_slv": "SLV"}
        chosen_sym = sym_map[data]
        quote = MarketDataService.get_realtime_quote(chosen_sym)
        curr_p = (quote.get("price") if quote else None) or 100.0
        shares = max(1, int(1000.0 / curr_p)) # ~1,000$ di ordine
        stop_p = round(curr_p * 0.985, 2)
        target_p = round(curr_p * 1.03, 2)
        res = alpaca_service.place_bracket_order(chosen_sym, shares, "buy", target_p, stop_p)
        if "error" not in res:
            await query.message.reply_text(
                f"✅ *ORDINE COMMODITY INVIATO SU ALPACA!* 🚀\n"
                f"• *Strumento:* `{chosen_sym}`\n"
                f"• *Quantità:* `x{shares} quote` (~$1,000)\n"
                f"• *Stop Loss:* `${stop_p:.2f}` (-1.5%)\n"
                f"• *Take Profit:* `${target_p:.2f}` (+3.0%)",
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text(f"⚠️ Errore esecuzione: {res.get('error')}")
        return

    if data in ["buy_crypto_btc", "buy_crypto_eth", "buy_crypto_sol"]:
        sym_map = {
            "buy_crypto_btc": "BTC/USD",
            "buy_crypto_eth": "ETH/USD",
            "buy_crypto_sol": "SOL/USD"
        }
        chosen_sym = sym_map[data]
        res = alpaca_service.place_crypto_order(symbol=chosen_sym, notional=2500.0, side="buy")
        if "error" not in res:
            await query.message.reply_text(
                f"✅ *ORDINE LONG CRYPTO ESEGUITO (24/7)!* 🚀\n"
                f"• *Coppia:* `{chosen_sym}`\n"
                f"• *Importo Notionale:* `$2,500.00`\n"
                f"• *Tipo Ordine:* Market GTC (Crypto 24/7)\n"
                f"• *Status:* `{res.get('status', 'inviato').upper()}`\n\n"
                "💡 _Verifica la posizione aggiornata digitando `/crypto` o `/alpaca`._",
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text(f"⚠️ Errore esecuzione crypto: {res.get('error')}")
        return

    if data in ["short_crypto_btc", "short_crypto_eth", "short_crypto_sol"]:
        sym_map = {
            "short_crypto_btc": "BTCUSDT",
            "short_crypto_eth": "ETHUSDT",
            "short_crypto_sol": "SOLUSDT"
        }
        chosen_sym = sym_map[data]
        res = bybit_service.place_order(symbol=chosen_sym, side="Sell", notional_usd=2500.0, take_profit_pct=2.5, stop_loss_pct=1.5)
        if "error" not in res:
            await query.message.reply_text(
                f"🔻 *ORDINE SHORT CRYPTO ESEGUITO SU BYBIT (24/7)!* 📉\n"
                f"────────────────────────\n"
                f"• *Contratto:* `{chosen_sym}`\n"
                f"• *Operazione:* `SHORT (Vendita allo Scoperto)`\n"
                f"• *Controvalore:* `$2,500.00 USDT`\n"
                f"• *Prezzo Esecuzione:* `${res.get('price'):.2f}`\n"
                f"• *Take Profit:* `${res.get('take_profit')}` (+2.5%)\n"
                f"• *Stop Loss:* `${res.get('stop_loss')}` (-1.5%)\n"
                f"• *Status:* `APERTO SUL CONTO DEMO BYBIT` 🎯\n\n"
                "💡 _Digita `/crypto` per vedere il P&L live della posizione short._",
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text(f"⚠️ Errore esecuzione Short Bybit: {res.get('error')}")
        return

    if data == "cmd_crypto":
        await crypto_cmd(update, context)
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
        profile = supabase_svc.get_user_profile(query.from_user.id) or {}
        raw_pac = profile.get("monthly_pac_eur", 0.0)
        budget = float(raw_pac) if raw_pac and float(raw_pac) > 0 else 0.0
        sim = OrderSimulatorService.simulate_trade_republic_order(ticker, budget)
        if sim.get("status") == "error":
            await query.message.reply_text(f"⚠️ Impossibile calcolare la simulazione per {ticker}.")
            return

        budget_label = "(calibrato sul tuo PAC)" if (not sim.get("budget_is_fallback") and budget > 0) else "(simulazione standard / quota base)"
        sim_text = (
            f"📋 *SCHEDA OPERATIVA TRADE REPUBLIC: {sim['asset_name']}* (`{sim['ticker']}`)\n\n"
            f"💶 *Budget Allocato:* `{sim['budget_eur']:.2f} €` {budget_label}\n"
            f"🏷️ *Prezzo Attuale:* `{sim['current_price_eur']:.2f} €`\n"
            f"📦 *Quote Esatte da Comprare:* `{sim['shares_to_buy']} quote`\n\n"
            f"⚙️ *Parametri d'Ordine su Trade Republic:*\n"
            f"• Tipo d'Ordine: *{sim['suggested_order_type']}*\n"
            f"• Prezzo Limite Consigliato: `{sim['limit_price_eur']:.2f} €` (protezione anti-spread L&S)\n\n"
            f"🎯 *Rapporto Rischio / Rendimento:*\n"
            f"• Take Profit (TP1): `{sim['tp1_eur']:.2f} €` (R:R `{sim['risk_reward_tp1']}`)\n"
            f"• Stop Loss Consigliato: `{sim['stop_loss_eur']:.2f} €`\n\n"
            f"💡 *Come inserire l'ordine su Trade Republic:*\n"
            f"Apri l'app > Cerca `{sim['ticker']}` > Clicca su *Acquista* > In alto a destra seleziona *Ordine Limite* > Inserisci `{sim['limit_price_eur']:.2f} €` e `{sim['shares_to_buy']}` quote.\n\n"
            f"ℹ️ _Per simulare con un budget specifico scrivi es:_ `/simula {sim['ticker']} 500`"
        )
        await send_safe_text(query, sim_text)

_last_briefing_sent: Dict[str, float] = {}

# Funzione per inviare briefing automatici programmati (07:00 e 15:00 CET nei feriali, 09:30 nei weekend)
async def send_scheduled_briefing(app, slot: str, force: bool = False):
    """
    Eroga il briefing programmato a tutti gli utenti attivi:
    - Nei giorni feriali (lun-ven):
      * slot='morning' alle 07:00 CET (sintesi ultime 12 ore e pre-Europa)
      * slot='afternoon' alle 15:00 CET (sintesi pre-apertura USA)
      * slot='evening' alle 21:30 CET (chiusura Wall Street & bilancio)
    - Nel weekend (sabato e domenica):
      * Supprime i briefing infrasettimanali 'afternoon' (15:00) e 'evening' (21:30) per evitare messaggi inutili a mercati chiusi.
      * Eroga una singola edizione Weekend Macro & Crypto alle 09:30 CET con bilancio e catalyst.
    - Deduplicazione automatica entro 40 minuti per evitare doppi invii.
    """
    now_rome = datetime.now(ZoneInfo("Europe/Rome"))
    is_weekend = now_rome.weekday() >= 5

    # Nel weekend non mandiamo gli aggiornamenti 'afternoon' (15:00) o 'evening' (21:30) delle borse aperte
    if is_weekend and slot in ["afternoon", "evening"] and not force:
        print(f"⏸️ [Scheduler] Weekend attivo ({now_rome.strftime('%A')}): briefing '{slot}' soppresso poiché i mercati azionari sono chiusi.")
        return

    import time
    now_ts = time.time()
    last_sent = _last_briefing_sent.get(slot, 0)
    if not force and (now_ts - last_sent < 2400):
        print(f"⏩ [Scheduler] Briefing {slot} già inviato {int(now_ts - last_sent)}s fa. Deduplicato.")
        return
    _last_briefing_sent[slot] = now_ts

    print(f"⏰ [Scheduler] Esecuzione briefing programmato: slot={slot} (weekend={is_weekend}, force={force})...")
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

async def daily_evening_recap_job(application):
    """Report Giornaliero Silenzioso delle 22:00 CET: bilancio di fine giornata, trade chiusi, posizioni e Health Score."""
    try:
        from services.trading_compass_service import trading_compass
        wallet = bybit_service.get_wallet_summary()
        b_pos = bybit_service.get_open_positions()
        res_closed = bybit_service.session.get_closed_pnl(category="linear", limit=20)
        closed_list = res_closed.get("result", {}).get("list", []) if res_closed.get("retCode") == 0 else []

        tot_eq = float(wallet.get("total_equity", 0.0) or 0.0)
        unreal_pnl = sum(p.get("unrealized_pnl", 0.0) for p in b_pos)

        # Filtra i trade chiusi nelle ultime 24 ore (o oggi)
        today_start_ms = int(datetime.now(ZoneInfo("Europe/Rome")).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        today_closed = [c for c in closed_list if int(c.get("updatedTime", 0)) >= today_start_ms]
        today_realized = sum(float(c.get("closedPnl", 0.0)) for c in today_closed)
        wins = sum(1 for c in today_closed if float(c.get("closedPnl", 0.0)) > 0)
        total_closed = len(today_closed)
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0

        compass_data = trading_compass.compute_edge_metrics(closed_list, b_pos, tot_eq)
        health_score = compass_data.get("health_score", 50)
        verdict = compass_data.get("verdict", "ALLINEATO")

        sign_real = "+" if today_realized >= 0 else ""
        sign_unreal = "+" if unreal_pnl >= 0 else ""
        icon_res = "🟢" if (today_realized + unreal_pnl) >= 0 else "🔻"

        msg = (
            f"🌙 *BILANCIO QUANTITATIVO GIORNALIERO (22:00 CET)*\n"
            f"────────────────────────\n"
            f"• *PnL Realizzato Oggi:* `{sign_real}${today_realized:.2f}` ({wins}/{total_closed} vincenti - `{win_rate:.0f}%`)\n"
            f"• *PnL Fluttuante Aperto:* `{sign_unreal}${unreal_pnl:.2f}`\n"
            f"• *Risultato Netto Operativo:* {icon_res} `{(today_realized + unreal_pnl):+.2f} USDT`\n"
            f"• *Health & Alignment Score:* `{health_score}/100` [{verdict}]\n\n"
        )

        if b_pos:
            msg += f"📊 *POSIZIONI NOTTURNE IN GESTIONE ({len(b_pos)}):*\n"
            for bp in b_pos:
                bsign = "+" if bp['unrealized_pnl'] >= 0 else ""
                stage = _POSITION_RISK_STAGE.get(bp['symbol'], 'INITIAL')
                stage_badge = "🛡️ BE PROTECTED" if stage == "BE_SAFE" else ("🔒 LOCK PROFIT" if stage == "LOCK_PROFIT" else "PARACADUTE SL")
                msg += f"• `{bp['symbol']}` [{bp['side']}]: `{bsign}${bp['unrealized_pnl']:.2f}` ({bp['pnl_pct']:+.2f}%) &rarr; _{stage_badge}_\n"
        else:
            msg += "💤 *Nessuna posizione aperta sui futures.* Monitoraggio radar attivo 24/7."

        target_ids = get_target_chat_ids()
        clean_recap = clean_telegram_markdown(msg)
        for uid in target_ids:
            try:
                await application.bot.send_message(chat_id=uid, text=clean_recap, parse_mode="Markdown")
            except Exception:
                try:
                    await application.bot.send_message(chat_id=uid, text=strip_markdown(msg))
                except Exception:
                    pass
    except Exception as e_recap:
        print(f"[!] Errore recap giornaliero: {e_recap}")

AUTO_FLATTEN_LEAD_MINUTES = 8.0


async def auto_flatten_overnight_job(application, now: Any = None, clock: Optional[Dict[str, Any]] = None):
    """
    Regola tassativa Day-Trading per azioni tradizionali: flat negli ultimi
    `AUTO_FLATTEN_LEAD_MINUTES` minuti della sessione regolare NYSE, sull'orologio di New York.

    Il job gira ogni minuto 12:50-12:59 e 15:50-15:59 ET (giorni feriali) e agisce solo se la
    chiusura di OGGI e' entro il margine: copre quindi sia la chiusura regolare (16:00 ET) sia le
    chiusure anticipate (13:00 ET, es. 27/11/2026 e 24/12/2026), indipendentemente dallo
    sfasamento dell'ora legale USA/UE. La chiusura del broker (clock Alpaca `next_close`) prevale
    sul calendario statico. Idempotente: senza posizioni azionarie non fa nulla.
    LE CRYPTO SONO ESCLUSE: il mercato crypto scambia 24/7 ed è gestito dal bot dedicato.
    """
    if alpaca_service is None:
        return
    try:
        if clock is None:
            try:
                clock = alpaca_service._api_request("clock")
            except Exception:
                clock = None
        mkt = market_calendar.session_status(now, clock if isinstance(clock, dict) else None)
        mtc = mkt.get("minutes_to_close")
        if mtc is None or mtc > AUTO_FLATTEN_LEAD_MINUTES:
            return
        summary = alpaca_service.get_account_summary()
        positions = summary.get("positions", [])
        stock_positions = []
        for p in positions:
            sym = p.get("symbol", "")
            # Se non è una crypto (non contiene USD/EUR e non appartiene alla classe crypto)
            is_crypto = (
                p.get("asset_class") == "crypto"
                or "/" in sym
                or (sym.endswith("USD") and any(sym.startswith(c) for c in ["BTC", "ETH", "SOL", "ADA", "XRP", "DOGE"]))
            )
            if not is_crypto:
                stock_positions.append(sym)

        if stock_positions:
            close_lbl = str(mkt.get("close_ny") or "")[11:16] or "16:00"
            print(f"🛑 [Auto-Flatten {close_lbl} ET -{mtc:.0f}m] Rilevate {len(stock_positions)} posizioni azionarie. Liquidazione forzata anti-overnight in corso...")
            for s in stock_positions:
                alpaca_service.close_position(s)
            # Invia notifica di sicurezza
            for user_id in get_target_chat_ids():
                try:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"🛑 *PROTEZIONE ANTI-OVERNIGHT AZIONARIA ATTIVATA ({mtc:.0f} min alla chiusura NY {close_lbl} ET)*\n"
                            "────────────────────────\n"
                            f"Liquidate automaticamente *{len(stock_positions)} posizioni su azioni* aperte prima della chiusura di Wall Street.\n"
                            + (f"• Seduta a chiusura anticipata: {mkt.get('early_close')}.\n" if mkt.get("early_close") else "")
                            + "• Zero commissioni di prestito overnight a margine.\n"
                            "• Zero rischio di gap down all'apertura successiva.\n"
                            "💡 *Nota:* Le posizioni *Crypto 24/7* restano attive e gestite dal risk manager continuo."
                        ),
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
    except Exception as e:
        print(f"[!] Errore auto_flatten_overnight_job: {e}")

def _get_btc_macro_bias():
    """
    Determina il bias direzionale macro (BULLISH, BEARISH o NEUTRAL) combinando:
    1. Trend Strutturale 4 Ore (EMA 20 e 50 di BTCUSDT)
    2. Trend Tattico Intraday 1 Ora (EMA 20 e 50 di BTCUSDT)
    3. Fase Ciclica Hurst & Battleplan di Migliorino sul ciclo a 1H
    
    ISTERESI (stateless, restart-safe): il bias e' calcolato sull'ultima 1H chiusa E sulla 1H chiusa
    precedente; viene restituito solo se le due valutazioni concordano, altrimenti NEUTRAL. Questo evita
    chiusure Macro-Shield causate dal flip di una singola candela.

    Se c'è discordanza tra 4H e 1H (es. 4H ancora sotto EMA50 ma 1H in solido recupero con rottura FLD),
    il mercato entra in stato NEUTRAL (Transizione). In stato NEUTRAL il bot sblocca l'operatività
    selettiva verificando la singola ciclica dell'asset.
    """
    try:
        # Candele 4 Ore (Strutturale) con open-time, solo barre chiuse
        res_4h = bybit_service.session.get_kline(category="linear", symbol="BTCUSDT", interval="240", limit=200)
        c_4h = res_4h.get("result", {}).get("list", [])
        if not c_4h or len(c_4h) < 30:
            return "NEUTRAL"
        # Scarta la candela in formazione (Bybit restituisce per prima la piu' recente, ancora aperta)
        c_4h = list(reversed(c_4h[1:]))
        t_4h = [int(c[0]) for c in c_4h]
        closes_4h = [float(c[4]) for c in c_4h]

        # Candele 1 Ora (Tattico Intraday)
        res_1h = bybit_service.session.get_kline(category="linear", symbol="BTCUSDT", interval="60", limit=200)
        c_1h = res_1h.get("result", {}).get("list", [])
        c_1h = list(reversed(c_1h[1:])) if c_1h else c_1h
        if not c_1h or len(c_1h) < 3:
            return "NEUTRAL"
        t_1h = [int(c[0]) for c in c_1h]
        closes_1h = [float(c[4]) for c in c_1h]

        current = classify_btc_bias(closes_4h, closes_1h)
        # Valutazione precedente: senza l'ultima 1h chiusa; 4h solo se chiusa (open+4h) entro la chiusura della 1h precedente
        prev_close_ms = t_1h[-1]
        n4 = len([t for t in t_4h if t + 4 * 3600 * 1000 <= prev_close_ms])
        if n4 < 30:
            return "NEUTRAL"
        previous = classify_btc_bias(closes_4h[:n4], closes_1h[:-1])
        return hysteresis_bias(current, previous)

    except Exception as e_bias:
        print(f"[!] Errore calcolo bias BTC macro: {e_bias}")
        return "NEUTRAL"

# Stato storico tracciato in memoria per notifiche push tempestive (Zero Spam)
_LAST_NOTIFIED_MACRO_BIAS: Optional[str] = None
_LAST_NOTIFIED_EQUITIES_BIAS: Optional[str] = None
_POSITION_RISK_STAGE: Dict[str, str] = {}  # {symbol: "INITIAL" | "TIGHT_RISK" | "BE_SAFE" | "LOCK_MID" | "LOCK_PROFIT"}
_ALPACA_RISK_STAGE: Dict[str, str] = {}    # {symbol: "INITIAL" | "TIGHT_RISK" | "BE_SAFE" | "LOCK_MID" | "LOCK_PROFIT"}
_LAST_JOURNAL_DEDUP_TS: float = 0.0
_JOURNAL_DEDUP_COOLDOWN_SEC: float = 1800.0


def _maybe_deduplicate_journal() -> None:
    """Esegue deduplicazione idempotente dei record untracked legacy con cooldown periodico."""
    global _LAST_JOURNAL_DEDUP_TS
    now_ts = time.time()
    if (now_ts - _LAST_JOURNAL_DEDUP_TS) < _JOURNAL_DEDUP_COOLDOWN_SEC:
        return
    _LAST_JOURNAL_DEDUP_TS = now_ts
    try:
        removed = trade_journal_svc.deduplicate_legacy_untracked()
        if removed:
            print(f"🧹 [Trade Journal] Rimossi {removed} record legacy untracked duplicati.")
    except Exception as e_dedup:
        print(f"[!] Warning deduplicate_legacy_untracked: {e_dedup}")


def _reconcile_broker_closed_trades(broker: str, closed_trades: List[Dict[str, Any]]) -> None:
    """Riconcilia le chiusure lato exchange con le righe OPEN nel SQLite journal aggiornando RiskState."""
    if not closed_trades:
        return
    try:
        transitioned = trade_journal_svc.reconcile_closed_trades_with_open_journal(broker, closed_trades)
        for tr in transitioned:
            _risk_closed(broker, tr.get("pnl_usd", 0.0))
    except Exception as e_rec:
        print(f"[!] Warning reconcile_closed_trades ({broker}): {e_rec}")


def _get_approved_exit_params() -> Optional[Dict[str, Any]]:
    """Restituisce i parametri adattivi di uscita approvati dall'ultimo EXIT_FRONTIER audit."""
    try:
        audit = trade_journal_svc.get_latest_audit("EXIT_FRONTIER")
        if isinstance(audit, dict):
            metrics = audit.get("metrics")
            if isinstance(metrics, dict) and metrics.get("approved") is True:
                return metrics
    except Exception:
        pass
    return None


def _estimate_exit_fees_and_bars(
    broker: str,
    symbol: str,
    notional_usd: float,
    bar_minutes: int = 15,
) -> Tuple[float, Optional[int]]:
    """Stima commissioni round-trip realistiche e barre detenute dall'apertura OPEN nel journal."""
    broker_u = str(broker or "").upper()
    fee_pct = 0.0013 if broker_u == "BYBIT" else 0.0
    fees_usd = round(max(0.0, float(notional_usd or 0.0)) * fee_pct, 4)
    bars_held: Optional[int] = None
    try:
        open_rows = trade_journal_svc.get_open_trade_ids()
        match = next(
            (r for r in open_rows if str(r.get("broker", "")).upper() == broker_u and str(r.get("symbol", "")).upper() == symbol.upper()),
            None,
        )
        if match and match.get("opened_at"):
            raw_open = str(match["opened_at"]).strip()
            if raw_open.endswith("Z"):
                raw_open = raw_open[:-1] + "+00:00"
            open_dt = datetime.fromisoformat(raw_open)
            if open_dt.tzinfo is None:
                open_dt = open_dt.replace(tzinfo=ZoneInfo("Europe/Rome"))
            now_dt = datetime.now(ZoneInfo("Europe/Rome"))
            elapsed_min = max(0.0, (now_dt - open_dt).total_seconds() / 60.0)
            bars_held = max(1, int(elapsed_min // max(1, bar_minutes)))
    except Exception:
        bars_held = None
    return fees_usd, bars_held


def _compute_closed_df_atr_pct(df: Any, fallback: float = 1.0) -> float:
    """Calcola ATR% Wilder da un DataFrame OHLCV chiuso con fallback deterministico."""
    try:
        import pandas as pd
        from services.indicators_safe import atr_wilder
        if df is None or not isinstance(df, pd.DataFrame) or len(df) < 16:
            return fallback
        close = df["Close"].iloc[:, 0] if isinstance(df["Close"], pd.DataFrame) else df["Close"]
        high = df["High"].iloc[:, 0] if isinstance(df["High"], pd.DataFrame) else df["High"]
        low = df["Low"].iloc[:, 0] if isinstance(df["Low"], pd.DataFrame) else df["Low"]
        last_c = float(close.iloc[-1] or 0.0)
        if last_c <= 0.0:
            return fallback
        atr_val = float(atr_wilder(high, low, close, 14).iloc[-1] or 0.0)
        if atr_val <= 0.0:
            return fallback
        return max(0.20, round((atr_val / last_c) * 100.0, 4))
    except Exception:
        return fallback


def _extract_symbol_df_from_bulk(bulk_df: Any, sym: str):
    """Estrae OHLCV pulito per singolo ticker da DataFrame yfinance multi-ticker o singolo."""
    import pandas as pd
    if bulk_df is None or not isinstance(bulk_df, pd.DataFrame) or bulk_df.empty:
        return None
    try:
        cols = bulk_df.columns
        if isinstance(cols, pd.MultiIndex):
            lvl0 = cols.get_level_values(0)
            if "Close" in lvl0 and sym in bulk_df["Close"]:
                data = {}
                for field in ("Open", "High", "Low", "Close", "Volume"):
                    if field in lvl0 and sym in bulk_df[field]:
                        data[field] = bulk_df[field][sym]
                if "Close" in data:
                    out = pd.DataFrame(data).dropna(subset=["Close"])
                    for f in ("Open", "High", "Low"):
                        if f not in out:
                            out[f] = out["Close"]
                    if "Volume" not in out:
                        out["Volume"] = 1.0
                    return out if not out.empty else None
            if sym in lvl0:
                sub = bulk_df[sym].dropna(subset=["Close"])
                return sub if not sub.empty else None
        elif "Close" in bulk_df.columns and not isinstance(bulk_df["Close"], pd.DataFrame):
            out = bulk_df.dropna(subset=["Close"]).copy()
            return out if not out.empty else None
    except Exception:
        return None
    return None


def _resample_ohlcv(df: Any, rule: str):
    """Ricampiona un DataFrame OHLCV chiuso in un timeframe superiore (es. 1h o 4h)."""
    import pandas as pd
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    if not isinstance(df.index, pd.DatetimeIndex):
        return None
    try:
        agg_map = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
        if "Volume" in df.columns:
            agg_map["Volume"] = "sum"
        out = df.resample(rule).agg(agg_map).dropna(subset=["Close"])
        return out if not out.empty else None
    except Exception:
        return None


def _fetch_bybit_closed_ohlcv(
    b_sym: str,
    b_yf: Optional[str],
    interval_str: str,
    interval_min: int,
    limit: int = 120,
):
    """Scarica candele chiuse da Bybit linear (o yfinance fallback) garantendo drop della barra in formazione."""
    import pandas as pd
    df = None
    try:
        kl = bybit_service.session.get_kline(category="linear", symbol=b_sym, interval=interval_str, limit=limit)
        kl_list = kl.get("result", {}).get("list", []) if isinstance(kl, dict) else []
        if kl_list and len(kl_list) >= 20:
            raw_df = pd.DataFrame(
                list(reversed(kl_list)),
                columns=["start", "Open", "High", "Low", "Close", "Volume", "turnover"],
            )
            for _col in ("Open", "High", "Low", "Close", "Volume"):
                raw_df[_col] = raw_df[_col].astype(float)
            raw_df.index = pd.to_datetime(raw_df["start"].astype("int64"), unit="ms", utc=True)
            df = prepare_closed_bars(raw_df, interval_minutes=interval_min)
    except Exception:
        df = None

    if (df is None or df.empty) and b_yf:
        try:
            import yfinance as yf
            yf_period = "3d" if interval_min == 15 else ("1mo" if interval_min == 60 else "3mo")
            yf_int = "15m" if interval_min == 15 else "1h"
            raw_yf = yf.download(b_yf, period=yf_period, interval=yf_int, progress=False)
            if raw_yf is not None and not raw_yf.empty:
                if hasattr(raw_yf.columns, "levels") and len(raw_yf.columns.levels) > 1:
                    raw_yf.columns = raw_yf.columns.get_level_values(0)
                df = prepare_closed_bars(raw_yf, interval_minutes=interval_min)
        except Exception:
            df = None
    return df


# ---------------------------------------------------------------------------
# Telemetry v2 (solo registrazione): variabili di stato ortogonali per (broker, simbolo).
# Nessuna regola di ingresso/uscita, filtro, risk manager o allocatore legge questi valori.
# ---------------------------------------------------------------------------
_TELEMETRY_CTX: Dict[Tuple[str, str], Dict[str, Any]] = {}
_BYBIT_PUBLIC_STATE: Optional[Any] = None


def _bybit_public_state():
    """Fetcher pubblico Bybit (funding/OI) non bloccante, creato alla prima richiesta."""
    global _BYBIT_PUBLIC_STATE
    if _BYBIT_PUBLIC_STATE is None:
        _BYBIT_PUBLIC_STATE = tele_v2.BybitPublicState(base_url=os.getenv("BYBIT_PUBLIC_BASE") or None)
    return _BYBIT_PUBLIC_STATE


def _set_telemetry_ctx(broker: str, symbol: str, data: Optional[Dict[str, Any]]) -> None:
    try:
        _TELEMETRY_CTX[(str(broker).upper(), str(symbol))] = {
            k: v for k, v in dict(data or {}).items() if v is not None
        }
    except Exception:
        pass


def _telemetry_ctx(broker: str, symbol: str) -> Dict[str, Any]:
    try:
        return dict(_TELEMETRY_CTX.get((str(broker).upper(), str(symbol)), {}))
    except Exception:
        return {}


def _log_shadow_rejection(
    broker: str,
    symbol: str,
    side: Optional[str],
    engine: str,
    macro_bias: str,
    atr_pct: float,
    rome_hour: int,
    reject_reason: str,
    signal_price: float,
    sl_pct: float,
    tp_pct: float,
    features: Optional[Dict[str, Any]],
    context_key_override: Optional[str] = None,
) -> None:
    """Registra candidati bloccati/scartati in `signal_shadows` filtrando rumore NO_SIGNAL/INSUFFICIENT_DATA."""
    reason_u = str(reject_reason or "").strip().upper()
    if not reason_u or reason_u in ("NO_SIGNAL", "INSUFFICIENT_DATA"):
        return
    eff_side = str(side or "").strip().upper()
    if eff_side not in ("LONG", "SHORT"):
        bias_u = str(macro_bias or "NEUTRAL").upper()
        if bias_u == "BULLISH":
            eff_side = "LONG"
        elif bias_u == "BEARISH":
            eff_side = "SHORT"
        else:
            rsi_val = float((features or {}).get("rsi", 50.0) or 50.0)
            eff_side = "LONG" if rsi_val >= 50.0 else "SHORT"
    if float(signal_price or 0.0) <= 0.0:
        return
    try:
        ctx_key = context_key_override or normalize_context_key(
            broker,
            eff_side,
            macro_bias,
            float(atr_pct or 1.0),
            int(rome_hour),
            engine,
        )
        trade_journal_svc.record_shadow_signal(
            broker=broker,
            symbol=symbol,
            side=eff_side,
            engine=engine,
            context_key=ctx_key,
            reject_reason=reason_u,
            signal_price=float(signal_price),
            sl_pct=max(0.25, float(sl_pct or 1.2)),
            tp_pct=max(0.50, float(tp_pct or 3.0)),
            features={
                **_telemetry_ctx(broker, symbol),
                **dict(features or {}),
                "ruleset_version": STRATEGY_RULESET_VERSION,
            },
        )
    except Exception as e_sh:
        print(f"[!] Warning record_shadow_signal ({broker} {symbol}): {e_sh}")


def _apply_context_allocation(
    context_key: str,
    base_notional: float,
    available_budget: float,
    min_notional: float,
    gate_scale: float = 1.0,
) -> Tuple[bool, float, Dict[str, Any]]:
    """Applica il moltiplicatore Bayesiano contestuale rispettando cap esposizione 70% e Shadow Mode."""
    try:
        alloc = learning_engine.compute_context_allocation(
            context_key=context_key,
            db_path=trade_journal_svc.db_path,
        )
    except Exception as e_al:
        print(f"[!] Warning compute_context_allocation ({context_key}): {e_al}")
        alloc = {"context_key": context_key, "mode": "STANDARD", "scale": 1.0}

    scale = float(alloc.get("scale", 1.0) or 0.0)
    mode_u = str(alloc.get("mode", "STANDARD") or "STANDARD").upper()
    if scale <= 0.0 or mode_u in ("SHADOW", "SHADOW_BLOCKED"):
        return False, 0.0, alloc

    scaled_notional = round(min(float(available_budget), float(base_notional) * scale * float(gate_scale)), 2)
    if scaled_notional < float(min_notional):
        return False, 0.0, alloc
    return True, scaled_notional, alloc


def _apply_dynamic_ratchet_and_exits(
    *,
    broker: str,
    symbol: str,
    side_norm: str,
    entry_price: float,
    current_price: float,
    current_sl: float,
    pnl_pct: float,
    unrealized_usd: float,
    notional_usd: float,
    atr_pct: float,
    macro_bias: str,
    stage_map: Dict[str, str],
    update_sl_fn: Any,
    close_fn: Any,
    bar_minutes: int,
    adaptive_params: Optional[Dict[str, Any]],
    notification_events: List[str],
    macro_close_thresh: float = -0.10,
) -> bool:
    """Gestisce Macro Shield, Ratchet Stop dinamico ATR-adattivo (BE >= 0.25%) e chiusure TP/SL con check rigoroso degli errori."""
    stage_rank = {"INITIAL": 0, "TIGHT_RISK": 1, "BE_SAFE": 2, "LOCK_MID": 3, "LOCK_PROFIT": 4}
    curr_stage = stage_map.setdefault(symbol, "INITIAL")
    side_u = "LONG" if str(side_norm).upper() in ("LONG", "BUY") else "SHORT"
    bias_u = str(macro_bias or "NEUTRAL").upper()

    macro_conflict = (bias_u == "BEARISH" and side_u == "LONG") or (bias_u == "BULLISH" and side_u == "SHORT")
    if macro_conflict and pnl_pct < macro_close_thresh:
        c_res = close_fn(symbol)
        if not isinstance(c_res, dict) or "error" in c_res:
            err_msg = c_res.get("error") if isinstance(c_res, dict) else "invalid_response"
            print(f"[!] Macro Shield ({broker}): chiusura {symbol} non eseguita ({err_msg}), nessun journal/notifica.")
            return True
        stage_map.pop(symbol, None)
        try:
            _risk_closed(broker, unrealized_usd)
            fees_usd, bars_held = _estimate_exit_fees_and_bars(broker, symbol, notional_usd, bar_minutes=bar_minutes)
            trade_journal_svc.record_exit(
                broker=broker,
                symbol=symbol,
                exit_price=current_price or entry_price,
                pnl_usd=unrealized_usd,
                pnl_pct=pnl_pct,
                close_reason="MACRO_SHIELD",
                fees_usd=fees_usd,
                bars_held=bars_held,
            )
        except Exception as e_j:
            print(f"[!] Warning journal exit ({broker} {symbol}): {e_j}")
        notification_events.append((
            f"🛑 *MACRO SHIELD ({broker}): CHIUSURA PREVENTIVA CONTRO-TREND*\n"
            f"────────────────────────\n"
            f"• *Asset:* `{symbol}` [{side_u}]\n"
            f"• *PnL Chiusura:* `${unrealized_usd:+.2f}` ({pnl_pct:+.2f}%)\n"
            f"• *Motivazione:* Inversione Macro a `{bias_u}`.\n"
            f"💡 _Capitale preservato: evitato accumulo di drawdown contro-trend._"
        ))
        return True

    levels = compute_atr_ratchet_levels(atr_pct, side_u, entry_price, adaptive_params=adaptive_params)
    tiers = (
        ("LOCK_PROFIT", levels["max_trigger_pct"], levels["max_lock_pct"], levels["max_sl"], "🚀 *TRAILING PROFIT LOCK ATTIVATO*"),
        ("LOCK_MID", levels["mid_trigger_pct"], levels["mid_lock_pct"], levels["mid_sl"], "💰 *PROFITTO INTERMEDIO GARANTITO*"),
        ("BE_SAFE", levels["be_trigger_pct"], levels["be_lock_pct"], levels["be_sl"], "🛡️ *BREAK-EVEN SAFE ATTIVATO (COPRE FEE)*"),
        ("TIGHT_RISK", levels["tight_trigger_pct"], levels["tight_lock_pct"], levels["tight_sl"], "🛡️ *RATCHET STOP: RISCHIO RIDOTTO*"),
    )
    for target_stage, trig_pct, lock_pct, raw_sl, title in tiers:
        if pnl_pct >= trig_pct:
            if stage_rank.get(curr_stage, 0) < stage_rank[target_stage]:
                target_sl = round(float(raw_sl), 2) if (broker == "ALPACA" and float(raw_sl) >= 1.0) else float(raw_sl)
                sl_improved = (current_sl <= 0.0) or (side_u == "LONG" and current_sl < target_sl) or (side_u == "SHORT" and current_sl > target_sl)
                if target_sl > 0.0 and sl_improved:
                    sl_res = update_sl_fn(symbol, target_sl)
                    if isinstance(sl_res, dict) and "error" not in sl_res:
                        stage_map[symbol] = target_stage
                        notification_events.append((
                            f"{title}\n"
                            f"────────────────────────\n"
                            f"• *Asset ({broker}):* `{symbol}` [{side_u}]\n"
                            f"• *Nuovo Stop:* `${target_sl:.4f}` (`{lock_pct:+.2f}%` vs entry, trigger `{trig_pct:+.2f}%`)\n"
                            f"• *PnL Fluttuante:* `${unrealized_usd:+.2f}` ({pnl_pct:+.2f}%)\n"
                            f"• *Target Dinamico:* TP `+{levels['tp_pct']:.2f}%` | ATR `{atr_pct:.2f}%`"
                        ))
            break

    if pnl_pct >= levels["tp_pct"] or pnl_pct <= -levels["sl_pct"]:
        c_res = close_fn(symbol)
        if not isinstance(c_res, dict) or "error" in c_res:
            err_msg = c_res.get("error") if isinstance(c_res, dict) else "invalid_response"
            print(f"[!] TP/SL ({broker}): chiusura {symbol} non eseguita ({err_msg}), nessun journal/notifica.")
            return True
        stage_map.pop(symbol, None)
        is_tp = pnl_pct >= levels["tp_pct"]
        c_reason = "TAKE_PROFIT" if is_tp else "STOP_LOSS"
        try:
            _risk_closed(broker, unrealized_usd)
            fees_usd, bars_held = _estimate_exit_fees_and_bars(broker, symbol, notional_usd, bar_minutes=bar_minutes)
            trade_journal_svc.record_exit(
                broker=broker,
                symbol=symbol,
                exit_price=current_price or entry_price,
                pnl_usd=unrealized_usd,
                pnl_pct=pnl_pct,
                close_reason=c_reason,
                fees_usd=fees_usd,
                bars_held=bars_held,
            )
        except Exception as e_j:
            print(f"[!] Warning journal exit ({broker} {symbol}): {e_j}")
        event_title = f"🎯 *TAKE PROFIT RAGGIUNTO (+{levels['tp_pct']:.2f}%)*" if is_tp else f"🛑 *STOP LOSS ESEGUITO (-{levels['sl_pct']:.2f}%)*"
        notification_events.append((
            f"{event_title}\n"
            f"────────────────────────\n"
            f"• *Asset ({broker}):* `{symbol}` [{side_u}]\n"
            f"• *Risultato Incassato:* `${unrealized_usd:+.2f}` ({pnl_pct:+.2f}%)\n"
            f"• *Disciplina Quantitativa:* Uscita ATR-adattiva eseguita su {broker}."
        ))
        return True
    return False

def _get_equities_macro_bias():
    """
    Determina il bias direzionale macro (BULLISH, BEARISH o NEUTRAL) per Wall Street:
    1. Trend Strutturale Daily (SPY ETF - EMA 20 e 50 Daily)
    2. Trend Tattico Intraday 1 Ora (SPY ETF - EMA 20 e 50 1H)
    3. Motore Dinamico VIX (^VIX): Delta di variazione (cooling vs spike) e livello assoluto.
    """
    try:
        import yfinance as yf
        import pandas as pd

        # Scarica SPY Daily e 1H
        df_spy_1d = yf.download("SPY", period="6mo", interval="1d", progress=False)
        if df_spy_1d.empty or len(df_spy_1d) < 30:
            return "NEUTRAL", 20.0, 0.0
        
        c_1d = df_spy_1d["Close"].iloc[:, 0] if isinstance(df_spy_1d["Close"], pd.DataFrame) else df_spy_1d["Close"]
        ema20_1d = float(c_1d.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50_1d = float(c_1d.ewm(span=50, adjust=False).mean().iloc[-1])
        last_1d = float(c_1d.iloc[-1])

        df_spy_1h = yf.download("SPY", period="1mo", interval="1h", progress=False)
        c_1h = df_spy_1h["Close"].iloc[:, 0] if isinstance(df_spy_1h["Close"], pd.DataFrame) else df_spy_1h["Close"]
        ema20_1h = float(c_1h.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50_1h = float(c_1h.ewm(span=50, adjust=False).mean().iloc[-1])
        last_1h = float(c_1h.iloc[-1])

        # VIX e Delta Volatilità
        vix_df = yf.download("^VIX", period="10d", interval="1d", progress=False)
        vix_val = 20.0
        vix_delta_pct = 0.0
        if not vix_df.empty:
            v_close = vix_df["Close"].iloc[:, 0] if isinstance(vix_df["Close"], pd.DataFrame) else vix_df["Close"]
            vix_val = float(v_close.iloc[-1])
            prev_vix = float(v_close.iloc[-2]) if len(v_close) >= 2 else vix_val
            vix_delta_pct = ((vix_val - prev_vix) / prev_vix) * 100.0 if prev_vix > 0 else 0.0

        # Regole di Volatilità VIX Istituzionali:
        # 1. VIX in Aumento / Turbolenza Avversa: se il VIX sale (+3.0% o oltre) o quota sopra 24.0 con variazione positiva,
        #    la volatilità implicita cresce comprimendo i multipli azionari: VIETATO qualsiasi bias BULLISH o LONG.
        is_vix_rising = (vix_delta_pct >= 3.0) or (vix_val >= 24.0 and vix_delta_pct > 0.0)
        # 2. VIX Shock / Panico Confermato: VIX sopra 26 con delta positivo o picco assoluto > 35
        is_vix_shock = (vix_val >= 26.0 and vix_delta_pct > 0.0) or (vix_delta_pct >= 8.0) or (vix_val > 35.0)
        # 3. Cooling VIX: distensione effettiva della volatilità (VIX in calo deciso < -3% oppure livello tranquillo < 20)
        is_vix_cooling = (vix_delta_pct <= -3.0 and vix_val < 26.0) or (vix_val < 19.0)

        # SE IL VIX È IN FORTE RIALZO O IN STATO DI SHOCK:
        # Il regime passa categoricamente a BEARISH (se sotto medie o rottura 1H) o al massimo NEUTRAL DIFENSIVO senza Long.
        if is_vix_shock or (is_vix_rising and (last_1h < ema20_1h or last_1d < ema50_1d)):
            return "BEARISH", vix_val, vix_delta_pct

        # 1. BULLISH PURO: Trend strutturale Daily e 1H positivo, ma TASSATIVAMENTE con VIX disteso o in calo (mai in ascesa)
        if last_1d > ema50_1d and ema20_1d >= ema50_1d and last_1h > ema20_1h and not is_vix_rising and not is_vix_shock:
            return "BULLISH", vix_val, vix_delta_pct

        # 2. NEUTRAL (REBOUND / ACCUMULO SELETTIVO): Prezzo 1H sopra EMA20 ma ESCLUSIVAMENTE se la volatilità è in ritracciamento (cooling)
        elif last_1h > ema20_1h and is_vix_cooling and not is_vix_rising:
            return "NEUTRAL", vix_val, vix_delta_pct

        # 3. BEARISH: Prezzo sotto le medie o VIX in salita
        elif last_1d < ema50_1d or last_1h < ema20_1h or is_vix_rising:
            return "BEARISH", vix_val, vix_delta_pct

        else:
            return "NEUTRAL", vix_val, vix_delta_pct

    except Exception as e_eq:
        print(f"[!] Errore calcolo bias equities macro: {e_eq}")
        return "NEUTRAL", 20.0, 0.0

def _timemachine_precheck_or_reject(
    *,
    broker: str,
    symbol: str,
    df_bars: Any,
    side: str,
    engine: str,
    macro_bias: str,
    atr_pct: float,
    rome_hour: int,
    signal_price: float,
    sl_pct: float,
    tp_pct: float,
    features: Optional[Dict[str, Any]],
    context_key: str,
    fee_rt_pct: float,
    interval_minutes: Optional[int],
    horizon_bars: int = 24,
    max_horizon_bars: Optional[int] = None,
    replay_df: Any = None,
    replay_interval_minutes: Optional[int] = None,
    replay_max_bars: int = 24,
    session_bound: bool = False,
) -> Tuple[bool, Dict[str, Any]]:
    """Pre-entry Monte Carlo Time Machine gate with shadow rejection telemetry.

    Also replays the same entry rule on the symbol's past bars (`replay_df`, real paths) and
    attaches the result as `tm_res["history"]`: telemetry only, it never blocks an order.
    """
    tm_res = evaluate_timemachine_gate(
        df_bars,
        side=side,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        n_replays=1200,
        horizon_bars=horizon_bars,
        fee_rt_pct=fee_rt_pct,
        interval_minutes=interval_minutes,
        max_horizon_bars=max_horizon_bars,
    )
    try:
        tm_res["history"] = replay_signal_history(
            replay_df if replay_df is not None else df_bars,
            engine=engine, side=side, sl_pct=sl_pct, tp_pct=tp_pct, fee_rt_pct=fee_rt_pct,
            max_bars=replay_max_bars,
            interval_minutes=(replay_interval_minutes if replay_df is not None else interval_minutes),
            session_bound=session_bound, flatten_lead_minutes=AUTO_FLATTEN_LEAD_MINUTES,
        )
    except Exception as e_hist:
        tm_res["history"] = {"n": 0, "error": str(e_hist)[:120]}
    try:
        # Fokker-Planck in forma chiusa e numero di Peclet: solo telemetria, non blocca nulla
        tm_res["fp"] = evaluate_fokker_planck(
            df_bars, side=side, sl_pct=sl_pct, tp_pct=tp_pct, horizon_bars=horizon_bars,
            fee_rt_pct=fee_rt_pct, interval_minutes=interval_minutes, max_horizon_bars=max_horizon_bars,
            asset_class=("equity" if str(broker).upper() == "ALPACA" else "crypto"),
        )
    except Exception as e_fp:
        tm_res["fp"] = {"fp_ok": False, "error": str(e_fp)[:120]}
    if not tm_res.get("passed", True):
        rej = str(tm_res.get("reason") or "TIMEMACHINE_MC")
        _log_shadow_rejection(
            broker, symbol, side, engine, macro_bias, atr_pct, rome_hour,
            rej, signal_price, sl_pct, tp_pct, _with_tm_features(features, tm_res),
            context_key_override=context_key,
        )
        print(
            f"[TimeMachine BLOCK] {broker} {symbol} {side} ({engine}): {rej} "
            f"E[R] lordo={float(tm_res.get('expected_r_gross', 0.0)):+.2f} "
            f"netto={float(tm_res.get('expected_r', 0.0)):+.2f} "
            f"drift z={float(tm_res.get('drift_z', 0.0)):+.2f}"
        )
        return False, tm_res
    return True, tm_res


def _tm_journal_fields(tm_res: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Compact Time Machine / same-rule replay fields for the trade journal and shadow features."""
    tm = tm_res or {}
    hist = tm.get("history") or {}
    return {
        "ruleset_version": STRATEGY_RULESET_VERSION,
        "tm_expected_r": tm.get("expected_r"),
        "tm_expected_r_gross": tm.get("expected_r_gross"),
        "tm_p_tp": tm.get("p_tp_first"),
        "tm_p_sl": tm.get("p_sl_first"),
        "tm_drift_z": tm.get("drift_z"),
        "tm_horizon_bars": tm.get("horizon_bars"),
        "hist_n": hist.get("n"),
        "hist_mean_r": hist.get("mean_r"),
        "hist_win_rate": hist.get("win_rate"),
        "hist_t_stat": hist.get("t_stat"),
        **{k: v for k, v in (tm.get("fp") or {}).items() if k.startswith(("fp_", "pe"))},
    }


def _tm_notification_text(tm_res: Optional[Dict[str, Any]], minutes_to_close: Optional[float]) -> str:
    tm = tm_res or {}
    if int(tm.get("replays", 0) or 0) <= 0:
        return ""
    txt = (
        f"\n• *Time Machine MC ({tm.get('replays', 0)}, {tm.get('horizon_bars', '?')} barre):* "
        f"`E[R]={float(tm.get('expected_r', 0.0)):+.2f}` | `P(TP)={float(tm.get('p_tp_first', 0.0)) * 100:.0f}%` "
        f"| `P(SL)={float(tm.get('p_sl_first', 0.0)) * 100:.0f}%`"
    )
    fpd = tm.get("fp") or {}
    if fpd.get("fp_ok"):
        extra = ""
        if fpd.get("fp_p_tp_bayes") is not None:
            extra += f" · `{float(fpd.get('fp_p_tp_bayes') or 0.0) * 100:.0f}%` bayes"
        if fpd.get("fp_p_tp_rs") is not None:
            extra += f" · `{float(fpd.get('fp_p_tp_rs') or 0.0) * 100:.0f}%` RS"
        txt += (
            f"\n• *Fokker-Planck:* `P(TP)={float(fpd.get('fp_p_tp', 0.0)) * 100:.0f}%` "
            f"(`{float(fpd.get('fp_p_tp0', 0.0)) * 100:.0f}%` senza drift{extra}) | "
            f"`Pe={float(fpd.get('pe', 0.0)):+.1f}±{float(fpd.get('pe_se', 0.0)):.1f}` _(solo telemetria)_"
        )
    hist = tm.get("history") or {}
    if int(hist.get("n", 0) or 0) > 0:
        txt += (
            f"\n• *Storico stessa regola:* `{hist.get('n')} segnali` | `R medio {float(hist.get('mean_r') or 0.0):+.2f}` "
            f"| `vincenti {float(hist.get('win_rate') or 0.0) * 100:.0f}%` _(solo telemetria)_"
        )
    if minutes_to_close is not None:
        txt += f"\n• *Chiusura NY tra:* `{float(minutes_to_close):.0f} min`"
    return txt


def _with_tm_features(features: Optional[Dict[str, Any]], tm_res: Optional[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    merged = dict(features or {})
    merged.update(_tm_journal_fields(tm_res))
    merged.update(extra)
    return merged


def _evaluate_and_trade_alpaca_candidate(
    *,
    sym: str,
    df_sym_1h: Any,
    eq_bias: str,
    vix_val: float,
    vix_delta_pct: float,
    spy_24h_ch: float,
    equity_alpaca: float,
    base_notional: float,
    available_budget: float,
    positions: List[Dict[str, Any]],
    adaptive_params: Optional[Dict[str, Any]],
    notification_events: List[str],
    df_sym_5m: Any = None,
    minutes_to_close: Optional[float] = None,
    telemetry_cycle: Optional[Dict[str, Any]] = None,
) -> float:
    """Valuta un titolo USA con regime router multi-engine, allocator Bayesiano e RiskGate.

    `minutes_to_close` (orologio NYSE): sotto i 30 minuti nessun ingresso; tra 30 e 90 minuti
    solo setup forti con TP raggiungibile prima della chiusura forzata (late-session gate).
    """
    import pandas as pd
    from services.hurst_migliorino_cycles import HurstMigliorinoCycleService

    if df_sym_1h is None or len(df_sym_1h) < 35:
        return 0.0
    try:  # Telemetry v2 (solo registrazione, mai bloccante)
        tc = telemetry_cycle or {}
        _set_telemetry_ctx("ALPACA", sym, {
            **dict((tc.get("idio") or {}).get(sym) or {}),
            "vrp_spread": tc.get("vrp_spread"),
            **tele_v2.safe_telemetry(
                tele_v2.ofi_bvc, df_sym_5m if (df_sym_5m is not None and len(df_sym_5m) >= 30) else df_sym_1h,
            ),
        })
    except Exception:
        pass
    sc = df_sym_1h["Close"]
    high_s = df_sym_1h["High"]
    low_s = df_sym_1h["Low"]
    vol_s = df_sym_1h["Volume"]
    last_c = float(sc.iloc[-1])
    if last_c <= 0.0:
        return 0.0

    s_ch = ((sc.iloc[-1] - sc.iloc[-7]) / sc.iloc[-7]) * 100.0 if len(sc) >= 8 else 0.0
    alpha = s_ch - spy_24h_ch
    atr_pct = _compute_closed_df_atr_pct(df_sym_1h, fallback=1.2)
    adx_1h = float(compute_adx(high_s, low_s, sc, 14).iloc[-1] or 20.0)
    avg_vol = float(vol_s.rolling(20).mean().iloc[-1] or 1.0)
    vol_ratio = float(vol_s.iloc[-1] or 0.0) / (avg_vol + 1e-5)

    cycle = HurstMigliorinoCycleService.calculate_cycle_metrics(pd.DataFrame({"Close": sc}))
    tempo_battleplan = cycle.get("tempo_battleplan", "")
    is_vix_unfavorable = (vix_delta_pct > 2.0) or (vix_val >= 24.0 and vix_delta_pct >= 0.0) or (vix_val >= 28.0)
    now_cet = datetime.now(ZoneInfo("Europe/Rome"))

    route = regime_router(eq_bias, adx_1h, atr_pct, funding_rate=0.0, vix_val=vix_val, spread_bps=0.0, is_equities=True)
    allowed_engines = set(route.get("allowed_engines") or [])
    prefer_limit = bool(route.get("prefer_limit", False))

    candidates: List[Dict[str, Any]] = []
    df_sym_4h = _resample_ohlcv(df_sym_1h, "4h")
    if ENGINE_TREND_PULLBACK in allowed_engines and df_sym_4h is not None and len(df_sym_4h) >= 20:
        sig_tp = engine_trend_pullback_4h1d(
            df_sym_4h, df_sym_1h, eq_bias, cycle_data=cycle, funding_rate=0.0,
            interval_minutes_4h=240, interval_minutes_1h=60,
        )
        if sig_tp:
            candidates.append(sig_tp)

    if ENGINE_INTRADAY_MOMENTUM in allowed_engines:
        sig_mom = engine_intraday_momentum(
            df_sym_1h, eq_bias, cycle, None, None, 0.0, vol_ratio,
            is_overnight=False, is_equities=True, vix_unfavorable=is_vix_unfavorable,
            adx_min=16.0, interval_minutes=60,
        )
        if sig_mom.get("triggered"):
            candidates.append(sig_mom)
        elif sig_mom.get("reject_reason"):
            _log_shadow_rejection(
                "ALPACA", sym, sig_mom.get("side"), ENGINE_INTRADAY_MOMENTUM, eq_bias, atr_pct,
                now_cet.hour, str(sig_mom.get("reject_reason")), last_c,
                float(sig_mom.get("sl_pct") or 1.2), float(sig_mom.get("tp_pct") or 3.6), sig_mom.get("features"),
            )

    if ENGINE_ORB_BREAKOUT in allowed_engines and df_sym_5m is not None and len(df_sym_5m) >= 6:
        sig_orb = engine_orb_breakout_15m(
            df_sym_5m, eq_bias, cycle_data=cycle, vix_unfavorable=is_vix_unfavorable, interval_minutes=5,
        )
        if sig_orb.get("triggered"):
            candidates.append(sig_orb)
        elif sig_orb.get("reject_reason") in ("VIX_SHIELD", "LOW_VOLUME", "CYCLE_CONFLICT"):
            _log_shadow_rejection(
                "ALPACA", sym, sig_orb.get("side"), ENGINE_ORB_BREAKOUT, eq_bias, atr_pct,
                now_cet.hour, str(sig_orb.get("reject_reason")), last_c,
                float(sig_orb.get("sl_pct") or 1.2), float(sig_orb.get("tp_pct") or 3.0), sig_orb.get("features"),
            )

    best_sig = select_best_signal(candidates)
    if not best_sig:
        return 0.0

    sig_side = str(best_sig["side"]).upper()
    chosen_engine = str(best_sig.get("engine") or ENGINE_INTRADAY_MOMENTUM).upper()
    ratchet_entry = compute_atr_ratchet_levels(atr_pct, sig_side, last_c, adaptive_params=adaptive_params)
    sl_pct = float(ratchet_entry["sl_pct"] if adaptive_params else best_sig.get("sl_pct", ratchet_entry["sl_pct"]))
    tp_pct = float(ratchet_entry["tp_pct"] if adaptive_params else best_sig.get("tp_pct", ratchet_entry["tp_pct"]))
    context_key = normalize_context_key("ALPACA", sig_side, eq_bias, atr_pct, now_cet.hour, chosen_engine)

    sentinel_data = sentinel_svc.get_asset_fundamental_sentiment(sym)
    if (sig_side == "LONG" and sentinel_data.get("sentiment") == "BEARISH") or (
        sig_side == "SHORT" and sentinel_data.get("sentiment") == "BULLISH" and sentinel_data.get("has_political_interest")
    ):
        _log_shadow_rejection(
            "ALPACA", sym, sig_side, chosen_engine, eq_bias, atr_pct, now_cet.hour,
            "SENTINEL_SHIELD", last_c, sl_pct, tp_pct, best_sig.get("features"), context_key_override=context_key,
        )
        return 0.0

    alloc_ok, alloc_notional, alloc_info = _apply_context_allocation(
        context_key, base_notional, available_budget, min_notional=500.0,
    )
    if not alloc_ok:
        _log_shadow_rejection(
            "ALPACA", sym, sig_side, chosen_engine, eq_bias, atr_pct, now_cet.hour,
            "SHADOW_ALLOCATOR", last_c, sl_pct, tp_pct, best_sig.get("features"), context_key_override=context_key,
        )
        return 0.0

    raw_otype = str(best_sig.get("order_type") or ("limit" if prefer_limit else "market")).strip().lower()
    order_type = "limit" if raw_otype == "limit" else "market"
    limit_price = best_sig.get("limit_price")
    if order_type == "limit" and (limit_price is None or float(limit_price) <= 0.0):
        limit_price = round(last_c * (0.999 if sig_side == "LONG" else 1.001), 2)
    elif limit_price is not None:
        limit_price = round(float(limit_price), 2)

    ref_p = float(limit_price) if (order_type == "limit" and limit_price) else last_c
    shares = max(1, int(alloc_notional / ref_p))
    target_p = round(ref_p * (1 + tp_pct / 100.0), 2) if sig_side == "LONG" else round(ref_p * (1 - tp_pct / 100.0), 2)
    stop_p = round(ref_p * (1 - sl_pct / 100.0), 2) if sig_side == "LONG" else round(ref_p * (1 + sl_pct / 100.0), 2)

    tm_use_5m = df_sym_5m is not None and len(df_sym_5m) >= 22
    tm_interval = 5 if tm_use_5m else 60
    # Orizzonte della simulazione tagliato alla chiusura forzata di oggi (orologio NY)
    tm_max_h: Optional[int] = None
    if minutes_to_close is not None:
        tm_max_h = max(1, int((float(minutes_to_close) - AUTO_FLATTEN_LEAD_MINUTES) // tm_interval))
    replay_is_orb = chosen_engine == ENGINE_ORB_BREAKOUT and df_sym_5m is not None
    tm_ok, tm_res = _timemachine_precheck_or_reject(
        broker="ALPACA", symbol=sym, df_bars=(df_sym_5m if tm_use_5m else df_sym_1h),
        side=sig_side, engine=chosen_engine, macro_bias=eq_bias, atr_pct=atr_pct,
        rome_hour=now_cet.hour, signal_price=ref_p, sl_pct=sl_pct, tp_pct=tp_pct,
        features=best_sig.get("features"), context_key=context_key,
        fee_rt_pct=0.05, interval_minutes=tm_interval,
        horizon_bars=(36 if tm_use_5m else 18), max_horizon_bars=tm_max_h,
        replay_df=(df_sym_5m if replay_is_orb else df_sym_1h),
        replay_interval_minutes=(5 if replay_is_orb else 60),
        replay_max_bars=(78 if replay_is_orb else 7),
        session_bound=True,
    )
    if not tm_ok:
        return 0.0

    late_chk = late_session_entry_check(minutes_to_close, float(best_sig.get("score") or 0.0), tm_res)
    if not late_chk.get("allowed", True):
        _log_shadow_rejection(
            "ALPACA", sym, sig_side, chosen_engine, eq_bias, atr_pct, now_cet.hour,
            str(late_chk.get("reason")), ref_p, sl_pct, tp_pct,
            _with_tm_features(best_sig.get("features"), tm_res, minutes_to_close=minutes_to_close,
                              score=best_sig.get("score")),
            context_key_override=context_key,
        )
        print(
            f"[LateSession BLOCK] ALPACA {sym} {sig_side} ({chosen_engine}): {late_chk.get('reason')} "
            f"a {float(minutes_to_close or 0.0):.0f} min dalla chiusura | score={float(best_sig.get('score') or 0.0):.0f} "
            f"P(TP)={float(tm_res.get('p_tp_first', 0.0)) * 100.0:.0f}% E[R]={float(tm_res.get('expected_r', 0.0)):+.2f}"
        )
        return 0.0

    if not _risk_gate(
        "ALPACA", sym, equity_alpaca,
        [{"entry_price": float(pp.get("avg_entry_price", 0) or 0), "size": float(pp.get("qty", 0) or 0)} for pp in positions],
        ref_p, stop_p, target_p, shares, notification_events,
    ):
        _log_shadow_rejection(
            "ALPACA", sym, sig_side, chosen_engine, eq_bias, atr_pct, now_cet.hour,
            "RISK_GATE", ref_p, sl_pct, tp_pct, best_sig.get("features"), context_key_override=context_key,
        )
        return 0.0

    order_res = alpaca_service.place_bracket_order(
        sym, shares, ("buy" if sig_side == "LONG" else "sell"), target_p, stop_p,
        order_type=order_type, limit_price=(limit_price if order_type == "limit" else None),
    )
    if not isinstance(order_res, dict) or "error" in order_res:
        return 0.0

    _risk_opened("ALPACA", equity_alpaca)
    client_oid = str(order_res.get("client_order_id") or order_res.get("id") or make_order_link_id(sym, sig_side[0], df_sym_1h.index[-1]))
    try:
        trade_journal_svc.record_entry(
            broker="ALPACA", symbol=sym, side=sig_side, entry_price=ref_p, notional_usd=shares * ref_p,
            context={
                "macro_bias": eq_bias, "cycle_tempo": tempo_battleplan, "alpha_spy": round(alpha, 2),
                "rsi": best_sig.get("features", {}).get("rsi"), "vix": round(vix_val, 1),
                "sl_pct": sl_pct, "tp_pct": tp_pct, "atr_pct": round(atr_pct, 3),
                "engine": chosen_engine, "context_key": context_key, "order_type": order_type,
                "alloc_mode": alloc_info.get("mode"), "alloc_scale": alloc_info.get("scale"),
                "sentinel_sentiment": sentinel_data.get("sentiment"), "sentinel_reasons": sentinel_data.get("reasons", []),
                **_telemetry_ctx("ALPACA", sym),
                **_tm_journal_fields(tm_res),
                "minutes_to_close": minutes_to_close, "late_zone": late_chk.get("zone"),
                "signal_score": best_sig.get("score"),
            },
            client_order_id=client_oid, engine=chosen_engine, context_key=context_key,
        )
    except Exception as e_j:
        print(f"[!] Warning trade journal entry: {e_j}")

    boost_txt = f"\n• *Fondamentali Sentinella:* `{sentinel_data.get('sentiment')}` ({', '.join(sentinel_data.get('reasons', ['Allineato']))})" if sentinel_data.get("reasons") else ""
    tm_txt = _tm_notification_text(tm_res, minutes_to_close)
    notification_events.append((
        f"{'🟢' if sig_side == 'LONG' else '🔻'} *NUOVO ORDINE WALL STREET ({chosen_engine})*\n"
        f"────────────────────────\n"
        f"• *Titolo:* `{sym}` [{sig_side}] x{shares} (`{order_type.upper()}`)\n"
        f"• *Controvalore Dinamico (Cap 70%):* `${shares * ref_p:,.0f}` (Alloc `{alloc_info.get('mode', 'STANDARD')}` {float(alloc_info.get('scale', 1.0)):.2f}x)\n"
        f"• *Macro SPY:* `{eq_bias}` | *Alpha:* `{alpha:+.2f}%` | *VIX:* `{vix_val:.1f}` ({vix_delta_pct:+.1f}%)\n"
        f"• *Target ATR:* TP `${target_p:.2f}` (`+{tp_pct:.2f}%`) | SL `${stop_p:.2f}` (`-{sl_pct:.2f}%`){tm_txt}{boost_txt}"
    ))
    return float(shares * ref_p)


def _sync_alpaca_risk_and_screening():
    """
    Motore quantitativo istituzionale per Wall Street (Alpaca Equities):
    1. Allineamento Macro SPY (Daily + 1H) & VIX Volatility Shield
    2. Dynamic Position Sizing (Fixed Fractional Compounding su equity Alpaca)
    3. Protezione Trailing Lock / Break-Even Safe sulle posizioni aperte
    4. Ranking Alpha vs SPY e Filtro Ciclico di Hurst & Migliorino per ingressi selettivi A+
    """
    if alpaca_service is None:
        return []
    global _LAST_NOTIFIED_EQUITIES_BIAS
    notification_events = []
    try:
        _maybe_deduplicate_journal()
        try:
            recent_alpaca_closed = alpaca_service.get_recent_closed_trades(limit_days=7) or []
            _reconcile_broker_closed_trades("ALPACA", recent_alpaca_closed)
        except Exception as e_rec_a:
            print(f"[!] Warning riconciliazione Alpaca: {e_rec_a}")

        # 1. Verifica se il mercato azionario USA è aperto
        clock = alpaca_service._api_request("clock")
        is_open = clock.get("is_open", False) if isinstance(clock, dict) else False
        if not is_open:
            return []
        mkt_session = market_calendar.session_status(None, clock if isinstance(clock, dict) else None)
        session_minutes_to_close = mkt_session.get("minutes_to_close")
        session_minutes_since_open = mkt_session.get("minutes_since_open")

        # 2. Leggi Trend Macro SPY e VIX (con Delta Volatilità)
        eq_bias, vix_val, vix_delta_pct = _get_equities_macro_bias()
        vix_status_desc = f"{vix_val:.1f} ({vix_delta_pct:+.1f}%)"
        print(f"🏛️ [Macro Bias Equities SPY] Direzione Wall Street: {eq_bias} (VIX: {vix_status_desc})")

        if _LAST_NOTIFIED_EQUITIES_BIAS is None:
            _LAST_NOTIFIED_EQUITIES_BIAS = eq_bias
        elif eq_bias in ["BULLISH", "BEARISH", "NEUTRAL"] and _LAST_NOTIFIED_EQUITIES_BIAS != eq_bias:
            bias_icon = "🟢" if eq_bias == "BULLISH" else ("🔻" if eq_bias == "BEARISH" else "⚖️")
            bias_title = "RIALZISTA (BULLISH)" if eq_bias == "BULLISH" else ("RIBASSISTA (BEARISH)" if eq_bias == "BEARISH" else "NEUTRO / TRANSIZIONE (NEUTRAL)")
            bias_rule = "Apertura esclusiva di posizioni LONG su breakout di forza" if eq_bias == "BULLISH" else ("Apertura posizioni SHORT/Hedge su debolezza" if eq_bias == "BEARISH" else "Flessibilità selettiva guidata da Alpha vs SPY e Ciclica 1H")
            notification_events.append((
                f"{bias_icon} *WALL STREET MACRO SHIELD: {bias_title}*\n"
                f"────────────────────────\n"
                f"• *Nuova Direzionalità:* `{eq_bias}` | *VIX:* `{vix_val:.1f}` ({vix_delta_pct:+.1f}%)\n"
                f"• *Regola Portafoglio:* {bias_rule}.\n"
                f"• *Benchmark Scudo:* S&P 500 ETF (SPY Daily + 1H).\n"
                f"💡 _Protezione attiva: dinamica di volatilità VIX e rotazione Alpha._"
            ))
            _LAST_NOTIFIED_EQUITIES_BIAS = eq_bias

        # 3. Gestione posizioni aperte Alpaca (Ratchet Stop Dinamico ATR-Adattivo & Exit Frontier)
        positions = alpaca_service._api_request("positions")
        if not isinstance(positions, list):
            positions = []

        current_syms = {p["symbol"] for p in positions}
        for s in [s for s in _ALPACA_RISK_STAGE if s not in current_syms]:
            del _ALPACA_RISK_STAGE[s]

        adaptive_params = _get_approved_exit_params()
        open_atr_map: Dict[str, float] = {}
        if current_syms:
            try:
                import yfinance as yf
                open_bulk = yf.download(list(current_syms), period="1mo", interval="1h", progress=False)
                for osym in current_syms:
                    odf = prepare_closed_bars(_extract_symbol_df_from_bulk(open_bulk, osym), interval_minutes=60)
                    open_atr_map[osym] = _compute_closed_df_atr_pct(odf, fallback=1.0)
            except Exception:
                pass

        closed_in_cycle: Set[str] = set()
        for p in positions:
            sym = p["symbol"]
            plpc = float(p.get("unrealized_plpc", 0.0) or 0.0) * 100.0
            unrealized = float(p.get("unrealized_pl", 0.0) or 0.0)
            side = p.get("side", "long").lower()
            entry_p = float(p.get("avg_entry_price", 0.0) or 0.0)
            curr_p = float(p.get("current_price", 0.0) or entry_p)
            notional_p = abs(float(p.get("market_value", 0.0) or 0.0))
            if _apply_dynamic_ratchet_and_exits(
                broker="ALPACA",
                symbol=sym,
                side_norm=("LONG" if side == "long" else "SHORT"),
                entry_price=entry_p,
                current_price=curr_p,
                current_sl=0.0,
                pnl_pct=plpc,
                unrealized_usd=unrealized,
                notional_usd=notional_p,
                atr_pct=open_atr_map.get(sym, 1.0),
                macro_bias=eq_bias,
                stage_map=_ALPACA_RISK_STAGE,
                update_sl_fn=alpaca_service.update_stop_loss,
                close_fn=alpaca_service.close_position,
                bar_minutes=60,
                adaptive_params=adaptive_params,
                notification_events=notification_events,
                macro_close_thresh=-0.15,
            ):
                if sym not in _ALPACA_RISK_STAGE:
                    closed_in_cycle.add(sym)

        open_positions_active = [p for p in positions if p["symbol"] not in closed_in_cycle]

        # 4. Dynamic Capital Exposure & Flexible Position Sizing (Fino al 70% del Capitale)
        acc_info = alpaca_service._api_request("account")
        equity_alpaca = float(acc_info.get("equity", 100000.0) or 100000.0) if isinstance(acc_info, dict) else 100000.0

        _risk_observe("ALPACA", equity_alpaca)
        current_invested_alpaca = sum(abs(float(p.get("market_value", 0.0) or 0.0)) for p in open_positions_active)
        max_allowed_exposure_alpaca = equity_alpaca * 0.70  # Fino al 70% del capitale
        available_risk_budget_alpaca = max(0.0, max_allowed_exposure_alpaca - current_invested_alpaca)
        base_notional_alpaca = round(min(max(1000.0, equity_alpaca * 0.10), available_risk_budget_alpaca), 0)
        max_conc = _get_max_concurrent_trades()

        # 5. Screening Ingressi Multi-Engine Wall Street (Fino al cap 70% e RiskConfig.max_concurrent_trades)
        if available_risk_budget_alpaca >= 1000.0 and eq_bias in ["BULLISH", "BEARISH", "NEUTRAL"]:
            import yfinance as yf
            # Open Bell Filter sull'orologio di New York (immune allo sfasamento DST USA/UE)
            if session_minutes_since_open is not None and float(session_minutes_since_open) < 15.0:
                print(f"⏱️ [Open Bell Filter] Primi 15 minuti di Wall Street ({mkt_session.get('now_ny', '')[11:16]} ET). Attesa stabilizzazione spread.")
                return notification_events

            active_syms = {p["symbol"] for p in open_positions_active}
            universe_equities = ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "META", "GOOGL", "AMD"]
            try:
                bulk_df = yf.download(universe_equities + ["SPY"], period="1mo", interval="1h", progress=False)
                spy_df = prepare_closed_bars(_extract_symbol_df_from_bulk(bulk_df, "SPY"), interval_minutes=60)
                spy_24h_ch = 0.0
                if spy_df is not None and len(spy_df) >= 8:
                    spy_c = spy_df["Close"]
                    spy_24h_ch = ((float(spy_c.iloc[-1]) - float(spy_c.iloc[-7])) / float(spy_c.iloc[-7])) * 100.0

                stock_dfs: Dict[str, Any] = {}
                for sym in universe_equities:
                    sdf = prepare_closed_bars(_extract_symbol_df_from_bulk(bulk_df, sym), interval_minutes=60)
                    if sdf is not None and len(sdf) >= 35:
                        stock_dfs[sym] = sdf

                stock_5m_dfs: Dict[str, Any] = {}
                try:
                    bulk_5m = yf.download(universe_equities, period="5d", interval="5m", progress=False)
                    for sym in universe_equities:
                        sdf5 = prepare_closed_bars(_extract_symbol_df_from_bulk(bulk_5m, sym), interval_minutes=5)
                        if sdf5 is not None and len(sdf5) >= 6:
                            stock_5m_dfs[sym] = sdf5
                except Exception as e_5m:
                    print(f"[!] Warning download 5m ORB Alpaca: {e_5m}")

                # Telemetry v2 di ciclo (solo registrazione): beta/residuo vs SPY e VRP
                alpaca_tele_cycle: Dict[str, Any] = {}
                try:
                    if spy_df is not None and len(spy_df) >= 35:
                        alpaca_tele_cycle["idio"] = tele_v2.idio_universe(
                            {s_: d_["Close"] for s_, d_ in stock_dfs.items()}, spy_df["Close"], window=140,
                        )
                        alpaca_tele_cycle["vrp_spread"] = tele_v2.vrp_spread(vix_val, spy_df)
                except Exception:
                    alpaca_tele_cycle = {}

                def _rank_stock(sym: str) -> float:
                    sdf = stock_dfs.get(sym)
                    if sdf is None or len(sdf) < 8:
                        return 0.0
                    sc = sdf["Close"]
                    alpha = (((float(sc.iloc[-1]) - float(sc.iloc[-7])) / float(sc.iloc[-7])) * 100.0) - spy_24h_ch
                    return -alpha if eq_bias in ["BULLISH", "NEUTRAL"] else alpha

                for sym in sorted(stock_dfs.keys(), key=_rank_stock):
                    if sym in active_syms or len(active_syms) >= max_conc:
                        continue
                    spent = _evaluate_and_trade_alpaca_candidate(
                        sym=sym, df_sym_1h=stock_dfs[sym], eq_bias=eq_bias, vix_val=vix_val,
                        vix_delta_pct=vix_delta_pct, spy_24h_ch=spy_24h_ch, equity_alpaca=equity_alpaca,
                        base_notional=base_notional_alpaca, available_budget=available_risk_budget_alpaca,
                        positions=open_positions_active, adaptive_params=adaptive_params,
                        notification_events=notification_events,
                        df_sym_5m=stock_5m_dfs.get(sym),
                        telemetry_cycle=alpaca_tele_cycle,
                        minutes_to_close=session_minutes_to_close,
                    )
                    if spent > 0.0:
                        active_syms.add(sym)
                        available_risk_budget_alpaca = max(0.0, available_risk_budget_alpaca - spent)
                        if available_risk_budget_alpaca < 500.0:
                            break
            except Exception as e_screening:
                print(f"[!] Errore screening equities Alpaca: {e_screening}")

    except Exception as e_main:
        print(f"[!] Errore sync equities worker: {e_main}")

    return notification_events

_META_GATE = None
_META_GATE_LOADED = False


def _get_meta_gate():
    """Carica una sola volta il MetaGate se QUANT_META_GATE_PATH e' impostata (default OFF)."""
    global _META_GATE, _META_GATE_LOADED
    if _META_GATE_LOADED:
        return _META_GATE
    _META_GATE_LOADED = True
    path = os.environ.get("QUANT_META_GATE_PATH")
    if not path or not os.path.exists(path):
        return None
    try:
        from quant.live.gate import MetaGate
        _META_GATE = MetaGate.load(path)
        print(f"[MetaGate] caricato da {path}")
    except Exception as e:
        print(f"[!] MetaGate disabilitato: {e}")
        _META_GATE = None
    return _META_GATE


def _meta_gate_check(b_sym, df, side):
    """Ritorna (allow, scala_notional). Con gate non configurato: (True, 1.0)."""
    gate = _get_meta_gate()
    if gate is None:
        return True, 1.0
    try:
        from quant.core import crypto_perp
        bars = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        dec = gate.decide(bars, crypto_perp(b_sym, "bybit"), "15m", side)
        if not dec.get("allow"):
            print(f"[MetaGate] {b_sym} scartato: {dec.get('reason')} (p={dec.get('p')})")
            return False, 1.0
        sf = dec.get("size_frac")
        scale = min(1.0, float(sf) / 0.10) if sf else 1.0
        return True, scale
    except Exception as e:
        print(f"[!] MetaGate errore su {b_sym}, disabilito: {e}")
        global _META_GATE
        _META_GATE = None
        return True, 1.0


_RISK_CFG = risk_limits.RiskConfig.from_env()
_DEFAULT_RISK_CFG_REF = _RISK_CFG
_RISK_STATE = risk_limits.RiskState(_RISK_CFG.state_path)


def _risk_observe(broker, equity):
    """Registra l'equity di inizio giornata (primo rilevamento del giorno UTC)."""
    if not _RISK_CFG.enabled:
        return
    try:
        _RISK_STATE.rec(broker, None, equity)
    except Exception as e:
        print(f"[!] Risk observe: {e}")


def _risk_gate(broker, sym, equity, positions, entry, stop, tp, qty, notification_events, is_notional=False):
    """Circuit breaker pre-trade (solo ingressi). True = ordine consentito. Mai usato per le uscite."""
    if not _RISK_CFG.enabled:
        return True
    try:
        ok, reason = risk_limits.check_entry(_RISK_CFG, _RISK_STATE, broker, equity, positions, entry, stop, tp, qty, None, is_notional)
    except Exception as e:
        print(f"[!] Risk check errore ({e}): ingresso consentito (fail-open).")
        return True
    if ok:
        return True
    print(f"🚧 [Risk Circuit Breaker {broker}] {sym}: ingresso bloccato -> {reason}")
    try:
        if _RISK_STATE.should_notify(broker, risk_limits.reason_key(reason)):
            notification_events.append(f"🚧 *RISK CIRCUIT BREAKER ({broker})*\n• Ingressi bloccati: `{reason}`\n• Ultimo tentativo: `{sym}`. Le uscite restano sempre attive.")
    except Exception as e:
        print(f"[!] Risk notify: {e}")
    return False


_risk_gate.cfg = _RISK_CFG  # expose RiskConfig cleanly without breaking call signature


def _get_max_concurrent_trades() -> int:
    """Legge dinamicamente max_concurrent_trades da RiskConfig (fallback sicuro >= 1)."""
    try:
        cfg = getattr(_risk_gate, "cfg", None)
        if _RISK_CFG is not None and (cfg is None or cfg is _DEFAULT_RISK_CFG_REF):
            cfg = _RISK_CFG
        val = int(getattr(cfg, "max_concurrent_trades", 6) or 6)
        return max(1, val)
    except Exception:
        return 6


def _risk_opened(broker, equity=None):
    try:
        risk_limits.record_open(_RISK_CFG, _RISK_STATE, broker, equity)
    except Exception as e:
        print(f"[!] Risk record_open: {e}")


def _risk_closed(broker, pnl):
    try:
        risk_limits.record_close(_RISK_CFG, _RISK_STATE, broker, float(pnl or 0.0))
    except Exception as e:
        print(f"[!] Risk record_close: {e}")


def _has_open_position(b_sym) -> bool:
    """Race guard: rilegge le posizioni Bybit prima di aprire. In caso di errore di lettura, blocca (fail-safe)."""
    try:
        return any(p.get("symbol") == b_sym for p in bybit_service.get_open_positions([b_sym]))
    except Exception as e:
        print(f"[!] Race guard: lettura posizioni fallita per {b_sym}: {e}. Ordine saltato.")
        return True


def _collect_bybit_signals(
    *,
    b_sym: str,
    b_yf: str,
    macro_bias: str,
    c_funding: float,
    spread_bps: float,
    rome_hour: int,
) -> Optional[Dict[str, Any]]:
    """Scarica candele chiuse 15m/1h/4h e seleziona il miglior segnale tra i 3 motori quantitativi."""
    df_15m = _fetch_bybit_closed_ohlcv(b_sym, b_yf, "15", 15, limit=180)
    if df_15m is None or len(df_15m) < 35:
        return None
    df_1h = _fetch_bybit_closed_ohlcv(b_sym, b_yf, "60", 60, limit=120)
    if df_1h is None or df_1h.empty:
        df_1h = _resample_ohlcv(df_15m, "1h")
    df_4h = _fetch_bybit_closed_ohlcv(b_sym, b_yf, "240", 240, limit=100)
    if df_4h is None or df_4h.empty:
        df_4h = _resample_ohlcv(df_1h, "4h") if (df_1h is not None and not df_1h.empty) else _resample_ohlcv(df_15m, "4h")

    close = df_15m["Close"]
    vol = df_15m["Volume"]
    last_c = float(close.iloc[-1])
    if last_c <= 0.0:
        return None
    try:  # Telemetry v2 (solo registrazione): OFI BVC + funding/OI pubblici dalla cache non bloccante
        _set_telemetry_ctx("BYBIT", b_sym, {
            **tele_v2.safe_telemetry(tele_v2.ofi_bvc, df_15m),
            **tele_v2.safe_telemetry(_bybit_public_state().get, b_sym),
        })
    except Exception:
        pass
    avg_vol = float(vol.rolling(20).mean().iloc[-1] or 1.0)
    vol_ratio = float(vol.iloc[-1] or 0.0) / (avg_vol + 1e-5)
    atr_pct = _compute_closed_df_atr_pct(df_15m, fallback=1.0)

    adx_src = df_1h if (df_1h is not None and len(df_1h) >= 28) else df_15m
    adx_1h = float(compute_adx(adx_src["High"], adx_src["Low"], adx_src["Close"], 14).iloc[-1] or 20.0)

    cycle_data: Dict[str, Any] = {}
    try:
        from services.deep_trade_analysis_service import get_deep_trade_forecast
        cycle_data = get_deep_trade_forecast(b_sym, tf="1h").get("cycle", {}) or {}
    except Exception:
        cycle_data = {}

    cvd_info: Dict[str, Any] = {"bias": "NEUTRAL", "ratio": 1.0}
    try:
        cvd_info = bybit_service.get_cumulative_volume_delta(b_sym, limit=50) or cvd_info
    except Exception:
        pass
    obi_info: Dict[str, Any] = {"bias": "BALANCED", "imbalance": 0.0}
    try:
        obi_info = bybit_service.get_orderbook_imbalance(b_sym) or obi_info
    except Exception:
        pass

    route = regime_router(macro_bias, adx_1h, atr_pct, funding_rate=c_funding, spread_bps=spread_bps)
    allowed_engines = set(route.get("allowed_engines") or [])
    prefer_limit = bool(route.get("prefer_limit", False))
    is_overnight = (0 <= rome_hour < 7)

    candidates: List[Dict[str, Any]] = []
    if ENGINE_TREND_PULLBACK in allowed_engines and df_4h is not None and df_1h is not None and len(df_4h) >= 20 and len(df_1h) >= 20:
        sig_tp = engine_trend_pullback_4h1d(
            df_4h, df_1h, macro_bias, cycle_data=cycle_data, funding_rate=c_funding,
            interval_minutes_4h=240, interval_minutes_1h=60,
        )
        if sig_tp:
            candidates.append(sig_tp)

    if ENGINE_LIQUIDITY_SWEEP in allowed_engines:
        sig_mr = engine_liquidity_sweep_mr(
            df_15m, cvd_info, obi_info, c_funding, macro_bias, interval_minutes=15,
        )
        if sig_mr:
            candidates.append(sig_mr)

    if ENGINE_INTRADAY_MOMENTUM in allowed_engines:
        sig_mom = engine_intraday_momentum(
            df_15m, macro_bias, cycle_data, cvd_info, obi_info, c_funding, vol_ratio,
            is_overnight=is_overnight, is_equities=False, adx_min=16.0, interval_minutes=15,
        )
        if sig_mom.get("triggered"):
            candidates.append(sig_mom)
        elif sig_mom.get("reject_reason"):
            _log_shadow_rejection(
                "BYBIT", b_sym, sig_mom.get("side"), ENGINE_INTRADAY_MOMENTUM, macro_bias, atr_pct,
                rome_hour, str(sig_mom.get("reject_reason")), last_c,
                float(sig_mom.get("sl_pct") or 1.2), float(sig_mom.get("tp_pct") or 3.6), sig_mom.get("features"),
            )

    best_sig = select_best_signal(candidates)
    if not best_sig:
        return None
    return {
        "signal": best_sig, "df_15m": df_15m, "last_c": last_c, "atr_pct": atr_pct,
        "prefer_limit": prefer_limit, "cycle_data": cycle_data, "cvd_info": cvd_info, "vol_ratio": vol_ratio,
    }


def _evaluate_and_trade_bybit_candidate(
    *,
    b_sym: str,
    b_yf: str,
    b_name: str,
    macro_bias: str,
    c_funding: float,
    c_alpha: float,
    spread_bps: float,
    bybit_equity: float,
    base_notional: float,
    available_budget: float,
    bybit_positions: List[Dict[str, Any]],
    adaptive_params: Optional[Dict[str, Any]],
    notification_events: List[str],
) -> float:
    """Valuta un candidato Bybit con 3 motori, Sentinel, MetaGate, Allocator Bayesiano, Race Guard e RiskGate."""
    rome_hour = datetime.now(ZoneInfo("Europe/Rome")).hour
    pack = _collect_bybit_signals(
        b_sym=b_sym, b_yf=b_yf, macro_bias=macro_bias,
        c_funding=c_funding, spread_bps=spread_bps, rome_hour=rome_hour,
    )
    if not pack:
        return 0.0

    best_sig = pack["signal"]
    df_15m = pack["df_15m"]
    last_c = float(pack["last_c"])
    atr_pct = float(pack["atr_pct"])
    prefer_limit = bool(pack["prefer_limit"])
    cycle_data = pack["cycle_data"]
    cvd_info = pack["cvd_info"]
    vol_ratio = float(pack["vol_ratio"])

    sig_side = str(best_sig["side"]).upper()
    chosen_engine = str(best_sig.get("engine") or ENGINE_INTRADAY_MOMENTUM).upper()
    ratchet_entry = compute_atr_ratchet_levels(atr_pct, sig_side, last_c, adaptive_params=adaptive_params)
    sl_pct = float(ratchet_entry["sl_pct"] if adaptive_params else best_sig.get("sl_pct", ratchet_entry["sl_pct"]))
    tp_pct = float(ratchet_entry["tp_pct"] if adaptive_params else best_sig.get("tp_pct", ratchet_entry["tp_pct"]))
    context_key = normalize_context_key("BYBIT", sig_side, macro_bias, atr_pct, rome_hour, chosen_engine)

    sentinel_data = sentinel_svc.get_asset_fundamental_sentiment(b_sym)
    if (sig_side == "SHORT" and sentinel_data.get("sentiment") == "BULLISH" and sentinel_data.get("has_political_interest")) or (
        sig_side == "LONG" and sentinel_data.get("sentiment") == "BEARISH"
    ):
        _log_shadow_rejection(
            "BYBIT", b_sym, sig_side, chosen_engine, macro_bias, atr_pct, rome_hour,
            "SENTINEL_SHIELD", last_c, sl_pct, tp_pct, best_sig.get("features"), context_key_override=context_key,
        )
        return 0.0

    gate_ok, gate_scale = _meta_gate_check(b_sym, df_15m, (1 if sig_side == "LONG" else -1))
    if not gate_ok:
        _log_shadow_rejection(
            "BYBIT", b_sym, sig_side, chosen_engine, macro_bias, atr_pct, rome_hour,
            "META_GATE", last_c, sl_pct, tp_pct, best_sig.get("features"), context_key_override=context_key,
        )
        return 0.0

    alloc_ok, eff_notional, alloc_info = _apply_context_allocation(
        context_key, base_notional, available_budget, min_notional=1000.0, gate_scale=gate_scale,
    )
    if not alloc_ok:
        _log_shadow_rejection(
            "BYBIT", b_sym, sig_side, chosen_engine, macro_bias, atr_pct, rome_hour,
            "SHADOW_ALLOCATOR", last_c, sl_pct, tp_pct, best_sig.get("features"), context_key_override=context_key,
        )
        return 0.0

    if _has_open_position(b_sym):
        print(f"[Race Guard] {b_sym}: posizione gia' aperta, ordine {sig_side} saltato.")
        return 0.0

    raw_otype = str(best_sig.get("order_type") or ("Limit" if prefer_limit else "Market")).strip().lower()
    is_limit = raw_otype == "limit"
    order_type = "Limit" if is_limit else "Market"
    limit_price = best_sig.get("limit_price")
    if is_limit and (limit_price is None or float(limit_price) <= 0.0):
        limit_price = last_c * (0.999 if sig_side == "LONG" else 1.001)
    ref_p = float(limit_price) if (is_limit and limit_price) else last_c
    sl_p = ref_p * (1 - sl_pct / 100.0) if sig_side == "LONG" else ref_p * (1 + sl_pct / 100.0)
    tp_p = ref_p * (1 + tp_pct / 100.0) if sig_side == "LONG" else ref_p * (1 - tp_pct / 100.0)

    tm_ok, tm_res = _timemachine_precheck_or_reject(
        broker="BYBIT", symbol=b_sym, df_bars=df_15m,
        side=sig_side, engine=chosen_engine, macro_bias=macro_bias, atr_pct=atr_pct,
        rome_hour=rome_hour, signal_price=ref_p, sl_pct=sl_pct, tp_pct=tp_pct,
        features=best_sig.get("features"), context_key=context_key,
        fee_rt_pct=0.12, interval_minutes=15, horizon_bars=24,
        replay_max_bars=24, session_bound=False,
    )
    if not tm_ok:
        return 0.0

    if not _risk_gate(
        "BYBIT", b_sym, bybit_equity,
        [{"entry_price": bp.get("entry_price"), "size": bp.get("size"), "stop_loss": bp.get("stop_loss")} for bp in bybit_positions],
        ref_p, sl_p, tp_p, eff_notional, notification_events, is_notional=True,
    ):
        _log_shadow_rejection(
            "BYBIT", b_sym, sig_side, chosen_engine, macro_bias, atr_pct, rome_hour,
            "RISK_GATE", ref_p, sl_pct, tp_pct, best_sig.get("features"), context_key_override=context_key,
        )
        return 0.0

    link_id = make_order_link_id(b_sym, ("L" if sig_side == "LONG" else "S"), df_15m.index[-1])
    order_res = bybit_service.place_order(
        b_sym, side=("Buy" if sig_side == "LONG" else "Sell"), notional_usd=eff_notional,
        take_profit_pct=tp_pct, stop_loss_pct=sl_pct, order_link_id=link_id,
        order_type=order_type, limit_price=(float(limit_price) if is_limit and limit_price else None),
        post_only=is_limit,
    )
    if not isinstance(order_res, dict) or order_res.get("duplicate") or "error" in order_res:
        return 0.0

    _risk_opened("BYBIT", bybit_equity)
    fill_p = float(order_res.get("price") or ref_p)
    try:
        trade_journal_svc.record_entry(
            broker="BYBIT", symbol=b_sym, side=sig_side, entry_price=fill_p, notional_usd=eff_notional,
            context={
                "macro_bias": macro_bias, "cycle_tempo": cycle_data.get("tempo_battleplan", ""),
                "hurst_fld": float(cycle_data.get("hurst_fld_value", 0.0) or 0.0),
                "funding_rate": c_funding, "alpha_btc": c_alpha,
                "cvd_ratio": cvd_info.get("ratio", 1.0), "rsi": best_sig.get("features", {}).get("rsi"),
                "vol_ratio": round(vol_ratio, 2), "sl_pct": sl_pct, "tp_pct": tp_pct,
                "atr_pct": round(atr_pct, 3), "engine": chosen_engine, "context_key": context_key,
                "order_type": order_type, "alloc_mode": alloc_info.get("mode"), "alloc_scale": alloc_info.get("scale"),
                "sentinel_sentiment": sentinel_data.get("sentiment"), "sentinel_reasons": sentinel_data.get("reasons", []),
                **_telemetry_ctx("BYBIT", b_sym),
                **_tm_journal_fields(tm_res), "signal_score": best_sig.get("score"),
            },
            client_order_id=link_id, engine=chosen_engine, context_key=context_key,
        )
    except Exception as e_j:
        print(f"[!] Warning trade journal entry: {e_j}")

    boost_txt = f"\n• *Sentinella Macro/News:* `{sentinel_data.get('sentiment')}` ({', '.join(sentinel_data.get('reasons', ['Allineato']))})" if sentinel_data.get("reasons") else ""
    tm_txt = _tm_notification_text(tm_res, None)
    notification_events.append((
        f"{'🟢' if sig_side == 'LONG' else '🔻'} *NUOVO ORDINE {sig_side} APERTO ({chosen_engine})*\n"
        f"────────────────────────\n"
        f"• *Asset:* `{b_sym}` ({b_name}) | `{order_type}`\n"
        f"• *Notionale Dinamico (Cap 70%):* `${eff_notional:,.0f}` (Alloc `{alloc_info.get('mode', 'STANDARD')}` {float(alloc_info.get('scale', 1.0)):.2f}x)\n"
        f"• *Macro Regime:* `{macro_bias}` | *Funding:* `{c_funding:+.4f}%` | *Alpha BTC:* `{c_alpha:+.2f}%`\n"
        f"• *Target ATR:* TP `+{tp_pct:.2f}%` | SL `-{sl_pct:.2f}%`{tm_txt}{boost_txt}"
    ))
    return float(eff_notional)


def _sync_crypto_risk_and_screening():
    """Motore quantitativo istituzionale: allineamento Macro BTC, Dynamic Compounding Sizing e Risk Alerts."""
    global _LAST_NOTIFIED_MACRO_BIAS
    notification_events = []
    try:
        _maybe_deduplicate_journal()
        try:
            closed_res = bybit_service.session.get_closed_pnl(category="linear", limit=30)
            raw_closed = closed_res.get("result", {}).get("list", []) if isinstance(closed_res, dict) and closed_res.get("retCode") == 0 else []
            if raw_closed:
                _reconcile_broker_closed_trades("BYBIT", raw_closed)
        except Exception as e_rec_b:
            print(f"[!] Warning riconciliazione Bybit: {e_rec_b}")

        # 1. Leggi trend macro da BTC (Timeframe 4 Ore)
        macro_bias = _get_btc_macro_bias()
        print(f"🌊 [Macro Bias BTC 4H] Direzione di mercato: {macro_bias}")

        # Inizializza al primo ciclo senza spammare la notifica di avvio
        if _LAST_NOTIFIED_MACRO_BIAS is None:
            _LAST_NOTIFIED_MACRO_BIAS = macro_bias
        elif macro_bias in ["BULLISH", "BEARISH", "NEUTRAL"] and _LAST_NOTIFIED_MACRO_BIAS != macro_bias:
            if macro_bias == "BULLISH":
                bias_icon = "🟢"
                bias_title = "RIALZISTA (BULLISH)"
                bias_allowed = "Apertura esclusiva di posizioni LONG su breakout di forza"
            elif macro_bias == "BEARISH":
                bias_icon = "🔻"
                bias_title = "RIBASSISTA (BEARISH)"
                bias_allowed = "Apertura esclusiva di posizioni SHORT su breakout di debolezza"
            else:
                bias_icon = "⚖️"
                bias_title = "NEUTRO / TRANSIZIONE (NEUTRAL)"
                bias_allowed = "Flessibilità selettiva Long/Short con filtro ciclico Hurst & Battleplan attivo"

            notification_events.append((
                f"{bias_icon} *MACRO TREND SHIELD BTC: {bias_title}*\n"
                f"────────────────────────\n"
                f"• *Nuova Direzionalità:* `{macro_bias}`\n"
                f"• *Regola Portafoglio:* {bias_allowed}.\n"
                f"• *Asset Scudo:* BTCUSDT (4H Strutturale + 1H Tattico).\n"
                f"💡 _Protezione attiva: sincronizzazione multi-timeframe e ciclica._"
            ))
            _LAST_NOTIFIED_MACRO_BIAS = macro_bias

        # 2. Gestione posizioni aperte Bybit (Ratchet Stop Dinamico ATR-Adattivo & Exit Frontier)
        bybit_positions = bybit_service.get_open_positions()
        current_symbols = {bp["symbol"] for bp in bybit_positions}
        for s in [s for s in _POSITION_RISK_STAGE if s not in current_symbols]:
            del _POSITION_RISK_STAGE[s]

        adaptive_params = _get_approved_exit_params()
        for bp in bybit_positions:
            bsym = bp["symbol"]
            pnl_pct = float(bp.get("pnl_pct", 0.0) or 0.0)
            unrealized = float(bp.get("unrealized_pnl", 0.0) or 0.0)
            bside = str(bp.get("side", "BUY")).upper()
            entry_p = float(bp.get("entry_price", 0.0) or 0.0)
            curr_p = float(bp.get("current_price", 0.0) or entry_p)
            curr_sl = float(bp.get("stop_loss", 0.0) or 0.0)
            notional_p = abs(float(bp.get("position_value") or (float(bp.get("size", 0.0) or 0.0) * entry_p)))

            pos_df = _fetch_bybit_closed_ohlcv(bsym, None, "15", 15, limit=60)
            atr_pct = _compute_closed_df_atr_pct(pos_df, fallback=1.0)
            _apply_dynamic_ratchet_and_exits(
                broker="BYBIT",
                symbol=bsym,
                side_norm=("LONG" if bside == "BUY" else "SHORT"),
                entry_price=entry_p,
                current_price=curr_p,
                current_sl=curr_sl,
                pnl_pct=pnl_pct,
                unrealized_usd=unrealized,
                notional_usd=notional_p,
                atr_pct=atr_pct,
                macro_bias=macro_bias,
                stage_map=_POSITION_RISK_STAGE,
                update_sl_fn=bybit_service.update_stop_loss,
                close_fn=bybit_service.close_position,
                bar_minutes=15,
                adaptive_params=adaptive_params,
                notification_events=notification_events,
                macro_close_thresh=-0.10,
            )

        # 3. Dynamic Capital Exposure & Flexible Position Sizing (Fino al 70% del Capitale Bybit)
        wallet = bybit_service.get_wallet_summary()
        bybit_equity = float(wallet.get("total_equity", 160000.0) or 160000.0)

        _risk_observe("BYBIT", bybit_equity)
        bybit_positions = bybit_service.get_open_positions()
        active_bybit_syms = {bp["symbol"] for bp in bybit_positions}

        current_invested_bybit = sum(float(bp.get("size", 0.0) or 0.0) * float(bp.get("entry_price", 0.0) or 0.0) for bp in bybit_positions)
        max_allowed_exposure_bybit = bybit_equity * 0.70
        available_risk_budget_bybit = max(0.0, max_allowed_exposure_bybit - current_invested_bybit)
        base_notional = round(min(max(1000.0, bybit_equity * 0.10), available_risk_budget_bybit), 0)
        max_conc = _get_max_concurrent_trades()

        # Screening ingressi multi-engine (fino al cap 70% ed a RiskConfig.max_concurrent_trades)
        if available_risk_budget_bybit >= 1000.0 and macro_bias in ["BULLISH", "BEARISH", "NEUTRAL"]:
            bybit_candidates = [
                ("SOLUSDT", "SOL-USD", "Solana"),
                ("BTCUSDT", "BTC-USD", "Bitcoin"),
                ("ETHUSDT", "ETH-USD", "Ethereum"),
                ("LINKUSDT", "LINK-USD", "Chainlink"),
                ("AVAXUSDT", "AVAX-USD", "Avalanche"),
                ("XRPUSDT", "XRP-USD", "Ripple"),
                ("ADAUSDT", "ADA-USD", "Cardano"),
                ("SUIUSDT", "SUI-USD", "Sui"),
                ("NEARUSDT", "NEAR-USD", "Near Protocol"),
                ("DOGEUSDT", "DOGE-USD", "Dogecoin"),
            ]

            ticker_data_map: Dict[str, Dict[str, float]] = {}
            btc_24h_change = 0.0
            try:
                t_res = bybit_service.session.get_tickers(category="linear")
                t_list = t_res.get("result", {}).get("list", []) if isinstance(t_res, dict) else []
                for t_item in t_list:
                    sym = t_item.get("symbol")
                    bid_p = float(t_item.get("bid1Price", 0.0) or 0.0)
                    ask_p = float(t_item.get("ask1Price", 0.0) or 0.0)
                    ticker_data_map[sym] = {
                        "funding_rate_pct": float(t_item.get("fundingRate", 0.0) or 0.0) * 100.0,
                        "change_24h_pct": float(t_item.get("price24hPcnt", 0.0) or 0.0) * 100.0,
                        "spread_bps": compute_spread_bps(bid_p, ask_p) if (bid_p > 0.0 and ask_p > 0.0) else 0.0,
                    }
                btc_24h_change = ticker_data_map.get("BTCUSDT", {}).get("change_24h_pct", 0.0)
            except Exception as e_t:
                print(f"[!] Warning recupero tickers funding/alpha: {e_t}")

            def _rank_candidate(cand):
                c_alpha = ticker_data_map.get(cand[0], {}).get("change_24h_pct", 0.0) - btc_24h_change
                return -c_alpha if macro_bias in ["BULLISH", "NEUTRAL"] else c_alpha

            for b_sym, b_yf, b_name in sorted(bybit_candidates, key=_rank_candidate):
                if b_sym in active_bybit_syms or len(active_bybit_syms) >= max_conc:
                    continue
                try:
                    c_info = ticker_data_map.get(b_sym, {})
                    c_funding = float(c_info.get("funding_rate_pct", 0.0) or 0.0)
                    c_alpha = float(c_info.get("change_24h_pct", 0.0) or 0.0) - btc_24h_change
                    c_spread_bps = float(c_info.get("spread_bps", 0.0) or 0.0)
                    spent = _evaluate_and_trade_bybit_candidate(
                        b_sym=b_sym, b_yf=b_yf, b_name=b_name, macro_bias=macro_bias,
                        c_funding=c_funding, c_alpha=c_alpha, spread_bps=c_spread_bps,
                        bybit_equity=bybit_equity, base_notional=base_notional,
                        available_budget=available_risk_budget_bybit, bybit_positions=bybit_positions,
                        adaptive_params=adaptive_params, notification_events=notification_events,
                    )
                    if spent > 0.0:
                        active_bybit_syms.add(b_sym)
                        available_risk_budget_bybit = max(0.0, available_risk_budget_bybit - spent)
                        if available_risk_budget_bybit < 1000.0:
                            break
                except Exception as ex:
                    print(f"[!] Errore screening {b_sym}: {ex}")
    except Exception as e:
        print(f"[!] Errore sync crypto worker: {e}")

    return notification_events

async def crypto_auto_risk_manager_job(application):
    """Delega l'elaborazione del risk manager al worker thread e invia notifiche Telegram se scattano eventi."""
    import asyncio
    events = await asyncio.to_thread(_sync_crypto_risk_and_screening)
    if events and application and application.bot:
        target_ids = get_target_chat_ids()
        for event_msg in events:
            clean_msg = clean_telegram_markdown(event_msg)
            for uid in target_ids:
                try:
                    await application.bot.send_message(chat_id=uid, text=clean_msg, parse_mode="Markdown")
                except Exception as e_send:
                    try:
                        await application.bot.send_message(chat_id=uid, text=strip_markdown(event_msg))
                    except Exception:
                        pass

async def alpaca_auto_risk_manager_job(application):
    """Monitor continuo e risk management istituzionale per Wall Street (Alpaca Equities)."""
    import asyncio
    events = await asyncio.to_thread(_sync_alpaca_risk_and_screening)
    if events and application and application.bot:
        target_ids = get_target_chat_ids()
        for event_msg in events:
            clean_msg = clean_telegram_markdown(event_msg)
            for uid in target_ids:
                try:
                    await application.bot.send_message(chat_id=uid, text=clean_msg, parse_mode="Markdown")
                except Exception as e_send:
                    try:
                        await application.bot.send_message(chat_id=uid, text=strip_markdown(event_msg))
                    except Exception:
                        pass

async def sentinel_watchdog_job(application):
    """Esegue il controllo proattivo periodico della sentinella."""
    try:
        res = await sentinel_svc.run_sentinel_watchdog(application)
        if res and res != "no_triggers":
            print(f"🛡️ [Sentinel] Risultato watchdog: {res}")
    except Exception as e:
        print(f"[!] Errore sentinel_watchdog_job: {e}")


# ---------------------------------------------------------------- LAB (paper trading, nessun ordine reale)
LAB_RUNNER = None
LAB_STORAGE = None
LAB_STRATEGIES = []


def _lab_build():
    """Costruisce il lab in modo lazy; se i moduli mancano o falliscono il lab resta disabilitato."""
    global LAB_RUNNER, LAB_STORAGE, LAB_STRATEGIES
    if os.getenv("LAB_ENABLED", "true").strip().lower() not in ("1", "true", "yes", "on"):
        return None
    try:
        from quant.lab.runner import LabRunner
        from quant.lab.storage import make_storage
        from quant.lab.marketdata import LiveMarketData
        from quant.lab.broker import PaperBroker
        from quant.lab.strategies import default_strategies
        LAB_STORAGE = make_storage()
        data = LiveMarketData()
        LAB_STRATEGIES = default_strategies()
        LAB_RUNNER = LabRunner(LAB_STRATEGIES, LAB_STORAGE, data, PaperBroker(LAB_STORAGE, data))
        print(f"[lab] attivo (paper): {', '.join(s.name for s in LAB_STRATEGIES)}")
    except Exception as e:
        LAB_RUNNER = None
        print(f"[!] Lab disabilitato: {e}")
    return LAB_RUNNER


async def lab_run_due_job():
    if LAB_RUNNER is None:
        return
    try:
        from datetime import datetime, timezone
        res = await asyncio.to_thread(LAB_RUNNER.run_due, datetime.now(timezone.utc))
        if res:
            print(f"[lab] run_due: {res}")
    except Exception as e:
        print(f"[!] Errore lab_run_due_job: {e}")


async def lab_weekly_review_job(application):
    if LAB_RUNNER is None:
        return
    try:
        from datetime import datetime, timezone
        from quant.lab.review import weekly_review
        text = await asyncio.to_thread(weekly_review, LAB_STORAGE, LAB_STRATEGIES, datetime.now(timezone.utc))
        for chat_id in get_target_chat_ids():
            try:
                await application.bot.send_message(chat_id=chat_id, text=text[:4000], parse_mode="Markdown")
            except Exception:
                await application.bot.send_message(chat_id=chat_id, text=text[:4000])
    except Exception as e:
        print(f"[!] Errore lab_weekly_review_job: {e}")


async def _lab_reply(update, text):
    try:
        await update.effective_message.reply_text(text[:4000], parse_mode="Markdown")
    except Exception:
        await update.effective_message.reply_text(text[:4000])


async def lab_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ACTIVE_CHAT_IDS.add(update.effective_user.id)
    if LAB_RUNNER is None:
        await _lab_reply(update, "Lab non attivo (LAB_ENABLED=false o moduli non disponibili).")
        return
    try:
        from quant.lab.review import scorecard
        text = await asyncio.to_thread(scorecard, LAB_STORAGE, LAB_STRATEGIES)
    except Exception as e:
        text = f"Errore scorecard lab: {e}"
    await _lab_reply(update, text)


async def lab_log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ACTIVE_CHAT_IDS.add(update.effective_user.id)
    if LAB_RUNNER is None:
        await _lab_reply(update, "Lab non attivo (LAB_ENABLED=false o moduli non disponibili).")
        return
    import json as _json
    name = context.args[0] if context.args else None
    try:
        rows = await asyncio.to_thread(LAB_STORAGE.query, "decisions", name, 10)
        if not rows:
            await _lab_reply(update, "Nessuna decisione registrata.")
            return
        out = [f"Ultime {len(rows)} decisioni" + (f" di {name}" if name else "")]
        for r in rows:
            out.append(f"\n{r.get('ts', '')[:16]} {r.get('strategy')} v{r.get('version')}: {r.get('note', '')}")
            try:
                tg = _json.loads(r.get("targets_json") or "[]")
            except Exception:
                tg = []
            tg = [x for x in tg if abs(float(x.get("weight", 0) or 0)) > 1e-9][:5]
            for x in tg:
                out.append(f"  {x.get('key') or x.get('instrument')}: {float(x.get('weight', 0)):+.3f} - {str(x.get('reason', ''))[:120]}")
        await _lab_reply(update, "\n".join(out))
    except Exception as e:
        await _lab_reply(update, f"Errore lab_log: {e}")

def _learning_ohlcv_fetcher(
    broker: str,
    symbol: str,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    interval: str = "15m",
    limit: int = 120,
):
    """Fornisce candele chiuse (Bybit/yfinance) per la valutazione MFE/MAE & shadow forward simulation."""
    tf_map = {"15m": ("15", 15), "1h": ("60", 60), "4h": ("240", 240)}
    interval_str, interval_min = tf_map.get(str(interval or "15m").lower(), ("15", 15))
    broker_u = str(broker or "").strip().upper()
    sym_u = str(symbol or "").strip().upper()

    if broker_u == "BYBIT":
        yf_sym = f"{sym_u[:-4]}-USD" if sym_u.endswith("USDT") else sym_u
        return _fetch_bybit_closed_ohlcv(sym_u, yf_sym, interval_str, interval_min, limit=max(120, int(limit or 120)))

    try:
        import yfinance as yf
        yf_int = "15m" if interval_min == 15 else "1h"
        yf_period = "1mo" if yf_int == "15m" else "3mo"
        raw_df = yf.download(sym_u, period=yf_period, interval=yf_int, progress=False)
        if raw_df is not None and not raw_df.empty:
            if hasattr(raw_df.columns, "levels") and len(raw_df.columns.levels) > 1:
                raw_df.columns = raw_df.columns.get_level_values(0)
            return prepare_closed_bars(raw_df, interval_minutes=interval_min)
    except Exception:
        pass
    return None


async def learning_eval_job(application: Any = None):
    """Job periodico (30m): valuta MFE/MAE dei trade chiusi, shadow pendenti e controlla drift MetaGate."""
    try:
        def _run_eval():
            eval_res = learning_engine.run_evaluation_cycle(_learning_ohlcv_fetcher, db_path=trade_journal_svc.db_path)
            summary = learning_engine.get_learning_dashboard_summary(
                db_path=trade_journal_svc.db_path, meta_gate_path=os.getenv("QUANT_META_GATE_PATH"),
            )
            return eval_res, summary

        eval_res, summary = await asyncio.to_thread(_run_eval)
        qd = summary.get("quant_drift", {}) if isinstance(summary, dict) else {}
        rs = summary.get("real_stats", {}) if isinstance(summary, dict) else {}
        if qd.get("active"):
            brier_val = qd.get("brier")
            base_rate = qd.get("base_rate")
            real_wr = (float(rs.get("win_rate", 0.0) or 0.0) / 100.0) if int(rs.get("total", 0) or 0) >= 15 else None
            if not qd.get("deployable") or (brier_val is not None and float(brier_val) > 0.25) or (
                real_wr is not None and base_rate is not None and abs(real_wr - float(base_rate)) > 0.20
            ):
                print(f"⚠️ [MetaGate Brier Drift] Warning calibrazione/drift: {qd}")
        print(f"🧠 [Learning Eval] Ciclo completato: {eval_res}")
        return eval_res
    except Exception as e:
        print(f"[!] Errore learning_eval_job: {e}")
        return {}


async def weekly_learning_audit_job(application: Any = None):
    """Job settimanale (Domenica 20:00 CET): genera report learning netto fee e lo invia via Telegram HTML."""
    try:
        _, summary_text = await asyncio.to_thread(learning_engine.build_weekly_learning_report, trade_journal_svc.db_path)
        bot = getattr(application, "bot", None)
        if bot is not None:
            html_msg = f"<b>🧠 WEEKLY LEARNING AUDIT</b>\n<pre>{html.escape(str(summary_text))}</pre>"
            for cid in _resolve_learning_chat_ids():
                try:
                    await bot.send_message(chat_id=cid, text=html_msg, parse_mode="HTML")
                except Exception:
                    try:
                        await bot.send_message(chat_id=cid, text=str(summary_text))
                    except Exception:
                        pass
        return summary_text
    except Exception as e:
        print(f"[!] Errore weekly_learning_audit_job: {e}")
        return ""


async def learning_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler interattivo /learning e /audit con verifica chat autorizzata e output HTML sicuro."""
    target_msg = get_target_msg(update)
    if not _is_chat_authorized(update):
        await target_msg.reply_text("⛔ Accesso non autorizzato a questo comando.")
        return
    try:
        summary = await asyncio.to_thread(
            learning_engine.get_learning_dashboard_summary,
            trade_journal_svc.db_path,
            os.getenv("QUANT_META_GATE_PATH"),
        )
        rs = summary.get("real_stats", {})
        sh = summary.get("shadow_stats", {})
        ef = summary.get("exit_frontier", {})
        qd = summary.get("quant_drift", {})
        allocs = summary.get("context_allocations", [])[:5]
        engines = summary.get("engines_breakdown", {})

        lines = [
            "<b>🧠 MARKET SENTINEL — LEARNING ENGINE</b>",
            f"• <b>Trade Reali:</b> <code>{int(rs.get('total', 0))}</code> | WR <code>{float(rs.get('win_rate', 0.0)):.1f}%</code> | PF Netto <code>{float(rs.get('profit_factor_net', 0.0)):.2f}</code>",
            f"• <b>Expectancy Netta:</b> <code>{float(rs.get('expectancy_r', 0.0)):+.3f}R</code> (<code>${float(rs.get('expectancy_usd', 0.0)):+.2f}</code>/trade) | Fee <code>${float(rs.get('total_fees_usd', 0.0)):.2f}</code>",
            f"• <b>Path MFE/MAE:</b> MFE <code>+{float(rs.get('avg_mfe_pct', 0.0)):.2f}%</code> | MAE <code>{float(rs.get('avg_mae_pct', 0.0)):.2f}%</code> | CapEff <code>{float(rs.get('avg_capture_eff', 0.0)):.2f}</code> | Edge <code>{float(rs.get('avg_edge_ratio', 0.0)):.2f}</code>",
            f"• <b>Shadow Signals:</b> <code>{int(sh.get('evaluated', 0))}</code> eval (<code>{int(sh.get('pending', 0))}</code> pending) | WR <code>{float(sh.get('shadow_win_rate', 0.0)):.1f}%</code> | Exp <code>{float(sh.get('shadow_expectancy_r', 0.0)):+.3f}R</code>",
            f"• <b>Exit Frontier:</b> <code>{'APPROVATA' if ef.get('approved') else 'IN ATTESA'}</code> (N={int(ef.get('n_samples', 0))}, LCB <code>{float(ef.get('best_lcb_r', 0.0)):+.3f}R</code>) — {html.escape(str(ef.get('reason', '')))}",
            f"• <b>MetaGate Drift:</b> <code>{'ATTIVO' if qd.get('active') else 'OFF'}</code> | Deployable <code>{bool(qd.get('deployable', False))}</code> ({html.escape(str(qd.get('verdict', '')))})",
        ]
        if engines:
            eng_parts = [f"<code>{html.escape(str(k))}</code>: {int(v.get('total', 0))}t ({float(v.get('expectancy_r', 0.0)):+.2f}R)" for k, v in engines.items()]
            lines.append("• <b>Motori:</b> " + " | ".join(eng_parts))
        if allocs:
            lines.append("• <b>Top Context Allocator:</b>")
            for a in allocs:
                lines.append(
                    f"  - <code>{html.escape(str(a.get('context_key', '')))}</code> → <b>{html.escape(str(a.get('mode', 'STANDARD')))}</b> ({float(a.get('scale', 1.0)):.2f}x, N_eff={float(a.get('n_eff', 0.0)):.1f})"
                )
        msg_html = "\n".join(lines)
        try:
            await target_msg.reply_text(msg_html, parse_mode="HTML")
        except Exception:
            await target_msg.reply_text(re.sub(r"<[^>]+>", "", msg_html))
    except Exception as e:
        await target_msg.reply_text(f"⚠️ Errore lettura learning summary: {e}")

async def post_init(application):
    """Configura il menu dei comandi nativo di Telegram con i soli comandi effettivamente usati e pertinenti."""
    bot_commands = [
        BotCommand("alpaca", "⚡ Trading live: saldo, posizioni attive e chiuse"),
        BotCommand("portafoglio", "💼 Diagnosi del portafoglio titoli Trade Republic"),
        BotCommand("briefing", "🌅 Quadro di mercato Wall Street ed Europa"),
        BotCommand("crypto", "🪙 Crypto trading 24/7 (BTC, ETH, SOL)"),
        BotCommand("scanner", "⚡ Day trader chart scanner (breakout & setup)"),
        BotCommand("pelosi", "🏛️ Trades Capitol Hill & Congress Tracker"),
        BotCommand("occasioni", "💎 Top occasioni a forte sconto"),
        BotCommand("sentinel", "🛡️ Stato radar sentinella proattiva 24/7"),
        BotCommand("learning", "🧠 Metriche learning, MFE/MAE & allocator"),
        BotCommand("help", "ℹ️ Guida alle funzioni e comandi del bot"),
        BotCommand("lab", "🧪 Lab paper trading: scorecard strategie")
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
        # Auto-Flatten Day-Trade sull'orologio di New York: ogni minuto 12:50-12:59 e 15:50-15:59 ET;
        # il job agisce solo negli ultimi AUTO_FLATTEN_LEAD_MINUTES della seduta di OGGI
        # (chiusura regolare 16:00 o anticipata 13:00), immune allo sfasamento DST USA/UE.
        scheduler.add_job(
            auto_flatten_overnight_job,
            CronTrigger(day_of_week="mon-fri", hour="12,15", minute="50-59", timezone="America/New_York"),
            args=[application],
            id="auto_flatten_ny_close",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        # Report Giornaliero Silenzioso di Fine Giornata alle 22:00 CET
        scheduler.add_job(
            daily_evening_recap_job,
            CronTrigger(hour=22, minute=0, timezone="Europe/Rome"),
            args=[application],
            id="daily_evening_recap_2200",
            replace_existing=True
        )
        # Watchdog proattivo della Sentinella ad alta frequenza ogni 2 minuti (Flash Squawk sub-minuto & Fact-Checking)
        scheduler.add_job(
            sentinel_watchdog_job,
            CronTrigger(minute="*/2", timezone="Europe/Rome"),
            args=[application],
            id="sentinel_watchdog_2min",
            replace_existing=True
        )
        # Monitor Scalping e Risk Management Crypto 24/7 continuo (ogni 2 minuti)
        scheduler.add_job(
            crypto_auto_risk_manager_job,
            CronTrigger(minute="*/2", timezone="Europe/Rome"),
            args=[application],
            id="crypto_risk_mgr_2min",
            replace_existing=True
        )
        # Monitor Risk Management e Screening Wall Street (Alpaca) ogni 2 minuti
        scheduler.add_job(
            alpaca_auto_risk_manager_job,
            CronTrigger(minute="*/2", timezone="Europe/Rome"),
            args=[application],
            id="alpaca_risk_mgr_2min",
            replace_existing=True
        )
        # Lab paper trading: run_due ogni 5 minuti + review settimanale domenica 18:00 (Roma)
        if _lab_build() is not None:
            scheduler.add_job(
                lab_run_due_job,
                CronTrigger(minute="*/5", timezone="Europe/Rome"),
                id="lab_run_due_5min",
                replace_existing=True
            )
            scheduler.add_job(
                lab_weekly_review_job,
                CronTrigger(day_of_week="sun", hour=18, minute=0, timezone="Europe/Rome"),
                args=[application],
                id="lab_weekly_review",
                replace_existing=True
            )
        # Ciclo apprendimento causale MFE/MAE & Shadow Forward ogni 30 minuti
        scheduler.add_job(
            learning_eval_job,
            IntervalTrigger(minutes=30),
            args=[application],
            id="learning_eval_30min",
            replace_existing=True
        )
        # Audit settimanale learning netto commissioni (Domenica 20:00 CET)
        scheduler.add_job(
            weekly_learning_audit_job,
            CronTrigger(day_of_week="sun", hour=20, minute=0, timezone="Europe/Rome"),
            args=[application],
            id="weekly_learning_audit_sun20",
            replace_existing=True
        )
        scheduler.start()
        application.bot_data["briefing_scheduler"] = scheduler
        print("⏰ [Scheduler] Programmato: Briefing 07:00 / 15:00 CET | Watchdog Sentinella ogni 20 minuti!")
    except Exception as e:
        print(f"[!] Errore configurazione scheduler in post_init: {e}")

    # Avvio Server Web Dashboard in background (aiohttp su porta PORT/8080)
    try:
        web_port = int(os.getenv("PORT", 8080))
        async def _trigger_briefing_cb(slot):
            await send_scheduled_briefing(application, slot=slot, force=True)

        web_app = create_web_app(bybit_service, alpaca_service, briefing_callback=_trigger_briefing_cb)
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=web_port)
        await site.start()
        application.bot_data["web_runner"] = runner
        print(f"🌐 [Dashboard Web] Server HTTP Live avviato su http://0.0.0.0:{web_port}")
    except Exception as e:
        print(f"[!] Errore avvio Dashboard Web server: {e}")

async def crypto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quadro e quotazioni in tempo reale delle principali Crypto con Long e Short nativo (Bybit & Alpaca)."""
    target_msg = get_target_msg(update)
    status_msg = await target_msg.reply_text("🪙 *Interrogo i mercati Crypto 24/7 (Alpaca & Bybit Futures)...*", parse_mode="Markdown")

    bars = alpaca_service.get_crypto_latest_bars(["BTC/USD", "ETH/USD", "SOL/USD"]) if alpaca_service is not None else {}
    bybit_wallet = bybit_service.get_wallet_summary()
    bybit_positions = bybit_service.get_open_positions()
    eur_usd = MarketDataService.get_eur_usd_rate() or 1.08

    lines = [
        "🪙 *CRYPTO TRADING 24/7 (LONG & SHORT REALTIME)*",
        "────────────────────────",
        "⚡ *Mercati attivi 24/7 anche nel Weekend!*",
        f"💶 *Tasso EUR/USD live:* `1.00 € = ${eur_usd:.4f}`\n",
        "📊 *QUOTAZIONI CRYPTO LIVE:*"
    ]

    crypto_catalog = [
        ("BTC/USD", "Bitcoin", "BTC"),
        ("ETH/USD", "Ethereum", "ETH"),
        ("SOL/USD", "Solana", "SOL")
    ]

    for pair, name, short_name in crypto_catalog:
        bar = bars.get(pair, {})
        price_usd = float(bar.get("c", 0.0))
        price_eur = price_usd / eur_usd if price_usd > 0 else 0.0
        p_usd_str = f"${price_usd:,.2f}" if price_usd > 0 else "N/D"
        p_eur_str = f"€{price_eur:,.2f}" if price_eur > 0 else "N/D"
        lines.append(f"• *{name}* (`{pair}`): `{p_usd_str}` (`{p_eur_str}`)")

    # Stato posizioni Bybit Futures (Short/Long)
    lines.append("\n🔻 *POSIZIONI BYBIT FUTURES DEMO (LONG & SHORT):*")
    if bybit_positions:
        for bp in bybit_positions:
            sign_pnl = "🟢 +" if bp['unrealized_pnl'] >= 0 else "🔴 "
            side_icon = "🟢 LONG" if bp['side'] == "BUY" else "🔻 SHORT"
            lines.append(f"• `{bp['symbol']}` [{side_icon}]: Qty `{bp['size']}` | In `${bp['entry_price']:.2f}` | *{sign_pnl}${bp['unrealized_pnl']:.2f}* ({bp['pnl_pct']:+.2f}%)")
    else:
        lines.append("• _Nessuna posizione aperta su Bybit al momento._")

    bybit_equity = bybit_wallet.get("total_equity", 0.0)
    lines.append(f"\n💼 *Saldo Demo Bybit:* `${bybit_equity:,.2f} USDT`")

    lines.append("\n💡 *Come Operare con Ordine Diretto:*")
    lines.append("Puoi digitare liberamente in chat sia Long che Short con sicurezza:")
    lines.append("• _\"Shorta Bitcoin con 2500$\"_")
    lines.append("• _\"Short Solana su Bybit\"_")
    lines.append("• _\"Compra 2500$ di Ethereum\"_")
    lines.append("• _\"Chiudi posizione Solana\"_")

    keyboard = [
        [
            InlineKeyboardButton("🔄 Aggiorna Crypto", callback_data="cmd_crypto"),
            InlineKeyboardButton("⚡ Saldo Alpaca", callback_data="alpaca_refresh")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await status_msg.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=reply_markup)

async def commodities_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quadro e quotazioni in tempo reale di Metalli e Petrolio."""
    target_msg = get_target_msg(update)
    status_msg = await target_msg.reply_text("🛢️ *Interrogo i mercati delle Materie Prime (Oro, Argento, Petrolio, Rame)...*", parse_mode="Markdown")

    assets = [
        ("GLD", "Oro Fisico (Gold ETF)"),
        ("SLV", "Argento Fisico (Silver ETF)"),
        ("USO", "Petrolio WTI (US Oil Fund)"),
        ("BNO", "Petrolio Brent (Brent Oil)"),
        ("CPER", "Rame (Copper Index)"),
        ("UNG", "Gas Naturale (Natural Gas)")
    ]

    lines = [
        "🛢️ *COMMODITIES & METALLI PREZIOSI (ALPACA TRADABLE)*\n"
        "────────────────────────\n"
    ]

    keyboard = []
    for sym, name in assets:
        quote = MarketDataService.get_realtime_quote(sym)
        p = quote.get("price") if quote else None
        p_str = f"${p:.2f}" if p else "N/D"
        lines.append(f"• *{name}* (`{sym}`): `{p_str}`")

    lines.append("\n💡 *Come Operare via Chat:*")
    lines.append("Puoi digitare direttamente in chat:")
    lines.append("• _\"Compra 10 azioni di Oro\"_ o _\"Compra 500$ di GLD\"_")
    lines.append("• _\"Compra 20 azioni di Petrolio\"_ o _\"Compra 500$ di USO\"_")
    lines.append("• _\"Short 15 quote di Argento\"_ o _\"Vendi SLV\"_")

    keyboard.append([
        InlineKeyboardButton("⚡ Saldo Alpaca", callback_data="alpaca_refresh"),
        InlineKeyboardButton("💼 Portafoglio", callback_data="cmd_portfolio")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await status_msg.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=reply_markup)

def build_alpaca_dashboard_text(summary: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    """Genera in modo unificato il messaggio e la tastiera per la dashboard di Alpaca con posizioni e movimenti odierni."""
    acc = summary.get("account", {})
    clock = summary.get("clock", {})
    positions = summary.get("positions", [])
    recent_closed = summary.get("recent_closed_trades", [])

    is_open = "APERTA 🟢" if clock.get("is_open") else "CHIUSA 🔴"
    now_rome = datetime.now(ZoneInfo("Europe/Rome"))
    is_weekend = now_rome.weekday() >= 5
    market_note = ""
    if is_weekend:
        market_note = "\n⚠️ *Weekend: I mercati azionari sono CHIUSI, ma il mercato Crypto è ATTIVO 24/7!*\nPuoi negoziare BTC, ETH e SOL senza interruzioni.\n"

    val = float(acc.get("portfolio_value", 0))
    cash = float(acc.get("cash", 0))
    buying_power = float(acc.get("buying_power", 0))

    msg = (
        "⚡ *ALPACA EXECUTION & DAY TRADER*\n"
        "────────────────────────\n"
        f"• *Stato Borsa USA:* {is_open}\n"
        f"• *Valore Portafoglio:* `${val:,.2f}`\n"
        f"• *Liquidità Libera (Cash):* `${cash:,.2f}`\n"
        f"• *Buying Power:* `${buying_power:,.2f}`\n"
        f"{market_note}\n"
    )

    keyboard = []
    if positions:
        msg += f"📈 *POSIZIONI ATTIVE A MERCATO ALPACA ({len(positions)}):*\n"
        for p in positions:
            sym = p['symbol']
            side = p['side'].upper()
            qty = p['qty']
            pl = float(p['unrealized_pl'])
            plpc = float(p['unrealized_plpc']) * 100
            curr = float(p['current_price'])
            entry_p = float(p.get('avg_entry_price', 0))
            sign = "🟢 +" if pl >= 0 else "🔴 "
            msg += f"  • `{sym}` ({side} x{qty}): Carico `${entry_p:.2f}` -> Attuale `${curr:.2f}` | P&L: {sign}${pl:.2f} ({plpc:+.2f}%)\n"
        keyboard.append([InlineKeyboardButton("🚨 Chiudi Tutte le Posizioni Alpaca", callback_data="alpaca_close_all")])
    else:
        msg += "💤 *Nessuna azione Wall Street aperta su Alpaca (100% Cash USD).*\n"

    # Mostra anche le posizioni Crypto attive su Bybit Demo per non lasciare dubbi
    try:
        b_pos = bybit_service.get_open_positions()
        if b_pos:
            msg += f"\n🪙 *POSIZIONI CRYPTO ATTIVE SU BYBIT DEMO ({len(b_pos)}):*\n"
            for bp in b_pos:
                b_sign = "🟢 +" if bp['unrealized_pnl'] >= 0 else "🔴 "
                b_side = "LONG" if bp['side'] == "BUY" else "SHORT"
                msg += f"  • `{bp['symbol']}` [{b_side}]: P&L: *{b_sign}${bp['unrealized_pnl']:.2f}* ({bp['pnl_pct']:+.2f}%)\n"
    except Exception:
        pass

    # Sezione Movimenti e Trade Chiusi Recenti (Ultime sessioni / Giornata)
    if recent_closed:
        from collections import defaultdict
        grouped = defaultdict(lambda: {"qty": 0.0, "pnl": 0.0, "entry_sum": 0.0, "exit_sum": 0.0, "side": "", "date": "", "time": ""})
        for ct in recent_closed:
            key = (ct["symbol"], ct["side"], ct.get("date", ""), ct.get("time", ""))
            grouped[key]["qty"] += ct["qty"]
            grouped[key]["pnl"] += ct["pnl"]
            grouped[key]["entry_sum"] += (ct["entry_price"] * ct["qty"])
            grouped[key]["exit_sum"] += (ct["exit_price"] * ct["qty"])
            grouped[key]["side"] = ct["side"]
            grouped[key]["date"] = ct.get("date", "")
            grouped[key]["time"] = ct.get("time", "")

        tot_pnl = sum(v["pnl"] for v in grouped.values())
        sign_tot = "🟢 +" if tot_pnl >= 0 else "🔴 "
        msg += f"\n📋 *MOVIMENTI & ULTIMI TRADE CHIUSI:* (Realizzato: {sign_tot}${tot_pnl:,.2f})\n"
        for (sym, s_side, c_date, c_time), v in grouped.items():
            avg_in = v["entry_sum"] / v["qty"] if v["qty"] else 0.0
            avg_out = v["exit_sum"] / v["qty"] if v["qty"] else 0.0
            pnl = v["pnl"]
            sign_p = "🟢 +" if pnl >= 0 else "🔴 "
            pnl_pct = ((avg_in - avg_out) / avg_in * 100) if s_side == "SHORT" and avg_in else (((avg_out - avg_in) / avg_in * 100) if avg_in else 0.0)
            date_label = f" [{c_date} {c_time}]" if c_date and c_time else ""
            msg += f"  • `{sym}` [{s_side} x{v['qty']:.0f}]: In `${avg_in:.2f}` -> Out `${avg_out:.2f}` | *{sign_p}${pnl:.2f}* ({pnl_pct:+.2f}%){date_label}\n"

    if is_weekend:
        keyboard.append([InlineKeyboardButton("🪙 Crypto Trading 24/7", callback_data="cmd_crypto")])
    else:
        keyboard.append([InlineKeyboardButton("⚡ Esegui Scanner Day-Trade", callback_data="alpaca_run_scanner")])
    keyboard.append([InlineKeyboardButton("🔄 Aggiorna Saldo", callback_data="alpaca_refresh")])

    return msg, InlineKeyboardMarkup(keyboard)

async def alpaca_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando per visualizzare lo stato di Alpaca Trading e gestire le posizioni."""
    target_msg = get_target_msg(update)
    if alpaca_service is None:
        await target_msg.reply_text("Alpaca non configurato.")
        return
    try:
        summary = alpaca_service.get_account_summary()
        acc = summary.get("account", {})
        if "error" in acc:
            await send_safe_text(update, f"⚠️ Errore connessione Alpaca: {acc['error']}")
            return

        msg, markup = build_alpaca_dashboard_text(summary)
        await send_safe_text(update, msg, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"[!] Errore alpaca_cmd: {e}")
        await send_safe_text(update, f"⚠️ Errore consultazione Alpaca: {str(e)}")

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
    app.add_handler(CommandHandler("trump", pelosi_cmd))
    app.add_handler(CommandHandler("djt", pelosi_cmd))
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
    app.add_handler(CommandHandler("alpaca", alpaca_cmd))
    app.add_handler(CommandHandler("trade", alpaca_cmd))
    app.add_handler(CommandHandler("crypto", crypto_cmd))
    app.add_handler(CommandHandler("bitcoin", crypto_cmd))
    app.add_handler(CommandHandler("btc", crypto_cmd))
    app.add_handler(CommandHandler("eth", crypto_cmd))
    app.add_handler(CommandHandler("sol", crypto_cmd))
    app.add_handler(CommandHandler("materieprime", commodities_cmd))
    app.add_handler(CommandHandler("commodities", commodities_cmd))
    app.add_handler(CommandHandler("oro", commodities_cmd))
    app.add_handler(CommandHandler("petrolio", commodities_cmd))
    app.add_handler(CommandHandler("profilo", profile_cmd))
    app.add_handler(CommandHandler("memoria", memoria_cmd))
    app.add_handler(CommandHandler("learning", learning_command))
    app.add_handler(CommandHandler("audit", learning_command))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("lab", lab_cmd))
    app.add_handler(CommandHandler("lab_log", lab_log_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE | filters.ANIMATION, handle_video))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))

    print("🤖 Bot Telegram Market Sentinel (Senior Edition - Full Italian & EUR) avviato...")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
