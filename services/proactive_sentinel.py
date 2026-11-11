"""
Proactive Sentinel & Market Watchdog Service for Market Sentinel.
Monitors dynamic portfolio assets, Tier-1 global mega-caps, macro barometers,
geopolitical breaking shocks, and Congressional insider disclosures.
Delivers timely, forward-looking wealth-coaching alerts to Michele via Telegram
with early-detection thresholds (catch moves in time without noise).
"""

from __future__ import annotations
import os
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Set, Optional

from services.market_data import MarketDataService
from services.supabase_service import SupabaseService
from services.ensemble_predictor import EnsemblePredictorEngine
from services.day_trader_service import DayTraderService
from services.news_sentiment import NewsSentimentService
from services.llm_reasoning import LLMReasoningService, clean_telegram_markdown

logger = logging.getLogger(__name__)

ROME_TZ = ZoneInfo("Europe/Rome")


class ProactiveSentinelService:
    def __init__(self):
        self.supabase_svc = SupabaseService()
        self.day_trader_svc = DayTraderService()
        self.llm_svc = LLMReasoningService()

        # Cooldown per ticker (timestamp dell'ultimo alert inviato)
        self.ticker_cooldowns: Dict[str, float] = {}
        # Cooldown standard: 4 ore (14400 secondi) per lo stesso ticker
        self.cooldown_seconds = 14400

        # Tracciamento alert geopolitici e macro shock
        self.last_geopolitical_title: Optional[str] = None
        self.last_geopolitical_ts: float = 0.0
        self.geopolitical_cooldown_seconds = 10800  # 3 ore

        # Tracciamento giornaliero alert
        self.today_date_str = ""
        self.alerts_sent_today = 0
        self.max_alerts_per_day = 5  # Fino a 5 alert giornalieri per massima tempestività

        # Ultimo doc_id Pelosi notificato
        self.last_pelosi_doc_id: Optional[str] = None
        self._init_last_pelosi()

    def _init_last_pelosi(self):
        """Memorizza il doc_id iniziale per non inviare alert su vecchi report già noti."""
        try:
            reports = self.day_trader_svc.get_congress_trades(member="pelosi", max_reports=1)
            if reports:
                self.last_pelosi_doc_id = reports[0].get("doc_id")
        except Exception as e:
            logger.warning(f"Inizializzazione Pelosi doc_id: {e}")

    def _is_active_hours(self) -> bool:
        """Verifica se l'orario attuale è compreso nella finestra attiva (08:00 - 22:00 CET)."""
        now = datetime.now(ROME_TZ)
        return 8 <= now.hour < 22

    def _reset_daily_counter_if_needed(self):
        today_str = datetime.now(ROME_TZ).strftime("%Y-%m-%d")
        if self.today_date_str != today_str:
            self.today_date_str = today_str
            self.alerts_sent_today = 0

    async def run_sentinel_watchdog(self, app) -> Optional[str]:
        """
        Ciclo autonomo di sorveglianza eseguito periodicamente (ogni 15-20 minuti) in background.
        Scansiona:
        1. Disclosure insider Capitol Hill (Nancy Pelosi & STOCK Act)
        2. Shock geopolitici e macro sistemici critici dalle breaking news wire
        3. Portafoglio reale di Michele con soglie calibrate (ETF 1.2%, Azioni 2.2%, Crypto 3.5%)
        4. I Grandi Asset Mondiali Fuori Portafoglio (Tier-1 Mega-Cap 2.8%, Oro 1.5%, Brent 2.2%, VIX +8%)
        """
        if not self._is_active_hours():
            logger.info("[Sentinel] Fuori orario di mercato attivo (08:00 - 22:00 CET). Vigilanza silente.")
            return None

        self._reset_daily_counter_if_needed()
        if self.alerts_sent_today >= self.max_alerts_per_day:
            logger.info(f"[Sentinel] Raggiunto limite massimo giornaliero di alert ({self.max_alerts_per_day}). Silenzio anti-spam attivo.")
            return None

        chat_ids = self.supabase_svc.get_active_chat_ids()
        if not chat_ids:
            return None

        now_ts = time.time()
        primary_chat_id = list(chat_ids)[0]
        user_portfolio = self.supabase_svc.get_portfolio(primary_chat_id) or []
        user_profile = self.supabase_svc.get_user_profile(primary_chat_id) or {}
        memory_context = self.supabase_svc.get_long_term_summary(primary_chat_id) or ""

        # ---------------------------------------------------------
        # 1. VERIFICA NUOVE DISCLOSURE CONGRESSO USA (Nancy Pelosi)
        # ---------------------------------------------------------
        try:
            reports = self.day_trader_svc.get_congress_trades(member="pelosi", max_reports=1)
            if reports:
                top_report = reports[0]
                doc_id = top_report.get("doc_id")
                if doc_id and self.last_pelosi_doc_id and doc_id != self.last_pelosi_doc_id:
                    self.last_pelosi_doc_id = doc_id
                    txns = top_report.get("transactions", [])
                    txn_summary = ""
                    if txns:
                        txn_summary = f"{txns[0].get('type', 'operazione')} su {txns[0].get('ticker', 'titolo')} ({txns[0].get('amount', 'importo')})"

                    msg = (
                        "🏛️ *ALERT PROATTIVO CAPITOL HILL (STOCK ACT)*\n\n"
                        f"È appena stata depositata una *nuova disclosure ufficiale* da parte di **Hon. Nancy Pelosi** (Doc #{doc_id}).\n"
                        f"• *Dettaglio:* {txn_summary or 'Operazione registrata'}\n"
                        f"• *Data Deposito:* {top_report.get('filed', 'recente')}\n"
                        f"• *Documento Ufficiale:* [Visualizza PDF House Clerk]({top_report.get('url')})\n\n"
                        "💡 *Nota del CIO:* I report PTR per legge possono essere comunicati fino a 30-45 giorni dopo l'operazione. Scrivimi `/pelosi` per visualizzare la perizia completa e l'impatto sul mercato."
                    )
                    await self._broadcast_alert(app, chat_ids, msg)
                    self.alerts_sent_today += 1
                    return "pelosi_alert_dispatched"
                elif not self.last_pelosi_doc_id and doc_id:
                    self.last_pelosi_doc_id = doc_id
        except Exception as e:
            logger.warning(f"[Sentinel] Errore verifica Congress trades: {e}")

        # ---------------------------------------------------------
        # 2. VERIFICA SHOCK GEOPOLITICI & MACRO-SISTEMICI
        # ---------------------------------------------------------
        if (now_ts - self.last_geopolitical_ts) > self.geopolitical_cooldown_seconds:
            try:
                shock = NewsSentimentService.detect_geopolitical_macro_shock(max_age_hours=4.0)
                if shock and shock.get("title") != self.last_geopolitical_title:
                    self.last_geopolitical_title = shock.get("title")
                    self.last_geopolitical_ts = now_ts

                    alert_text = self.llm_svc.generate_sentinel_alert(
                        alert_type="geopolitical_macro_shock",
                        payload=shock,
                        user_portfolio=user_portfolio,
                        user_profile=user_profile,
                        memory_context=memory_context
                    )
                    if not alert_text:
                        alert_text = (
                            f"🚨 *RADAR SENTINELLA: SHOCK GEOPOLITICO / MACRO*\n\n"
                            f"• *Evento Rilevato:* {shock.get('title')}\n"
                            f"• *Fonte:* {shock.get('source')} ({shock.get('published')})\n"
                            f"• *Intensità:* Severità {shock.get('severity_score')}/10\n\n"
                            f"💡 *Nota del CIO:* I mercati potrebbero registrare volatilità a breve termine. Ricorda che il portafoglio è strutturato su indici globali diversificati: evita reazioni emotive o vendite in panico. Scrivimi per monitorare l'evoluzione."
                        )

                    await self._broadcast_alert(app, chat_ids, alert_text)
                    self.alerts_sent_today += 1
                    logger.info(f"[Sentinel] Shock geopolitico notificato: {shock.get('title')}")
                    return "geopolitical_alert_dispatched"
            except Exception as e_geo:
                logger.warning(f"[Sentinel] Errore verifica shock geopolitico: {e_geo}")

        # ---------------------------------------------------------
        # 3. VERIFICA PORTAFOGLIO REALE DI MICHELE (Soglie Anticipate)
        # ---------------------------------------------------------
        # Se il portafoglio su Supabase è vuoto, usa i titoli core di default
        portfolio_items = user_portfolio if user_portfolio else [
            {"ticker": "XDWD.DE", "name": "MSCI World Core", "asset_type": "etf"},
            {"ticker": "XDEM.DE", "name": "MSCI World Momentum", "asset_type": "etf"},
            {"ticker": "BYDDF", "name": "BYD Co.", "asset_type": "stock"},
            {"ticker": "BTC-EUR", "name": "Bitcoin", "asset_type": "crypto"},
            {"ticker": "ADA-EUR", "name": "Cardano", "asset_type": "crypto"}
        ]

        for item in portfolio_items:
            ticker = item.get("ticker")
            if not ticker:
                continue

            # Cooldown per asset
            last_alert = self.ticker_cooldowns.get(ticker, 0.0)
            if now_ts - last_alert < self.cooldown_seconds:
                continue

            try:
                quote = MarketDataService.get_realtime_quote(ticker)
                last_price = quote.get("last_price", 0.0)
                change_pct = quote.get("change_pct", 0.0)

                if last_price <= 0:
                    continue

                # Calibrazione soglie anticipate per asset class
                raw_type = (item.get("asset_type") or "").lower()
                is_etf = "etf" in raw_type or ticker in ["XDWD.DE", "XDEM.DE", "SWDA.MI", "CSSPX.MI", "SXR8.DE", "VWCE.DE"]
                is_crypto = "crypto" in raw_type or "BTC" in ticker or "ADA" in ticker or "ETH" in ticker

                if is_etf:
                    threshold = 1.2  # Soglia reattiva ETF: 1.2%
                elif is_crypto:
                    threshold = 3.5  # Soglia reattiva Crypto: 3.5%
                else:
                    threshold = 2.2  # Soglia reattiva Azioni: 2.2%

                if abs(change_pct) >= threshold:
                    forecast = EnsemblePredictorEngine.generate_ensemble_forecast(ticker)
                    asset_name = item.get("name") or forecast.get("asset_name", ticker)

                    payload = {
                        "ticker": ticker,
                        "asset_name": asset_name,
                        "price_eur": last_price,
                        "change_pct": change_pct,
                        "threshold_triggered": threshold,
                        "user_pmc_eur": item.get("average_buy_price"),
                        "user_shares": item.get("shares"),
                        "ensemble": forecast
                    }

                    alert_msg = self.llm_svc.generate_sentinel_alert(
                        alert_type="portfolio_movement",
                        payload=payload,
                        user_portfolio=user_portfolio,
                        user_profile=user_profile,
                        memory_context=memory_context
                    )

                    if not alert_msg:
                        direction_sym = "🟢" if change_pct < 0 else "🚀"
                        action_txt = "Finestra favorevole di accumulo per abbassare il PMC" if change_pct < 0 else "Spinta decisa al rialzo: lascia correre i profitti con ordine limite"
                        alert_msg = (
                            f"⚡ *ALERT SENTINELLA PORTAFOGLIO: {asset_name.upper()}* (`{ticker}`)\n\n"
                            f"{direction_sym} *Movimento Anticipato Rilevato:* Variazione intraday del *{change_pct:+.2f}%* a quota *{last_price:.2f} €* (soglia sentinella: {threshold}%).\n\n"
                            f"🧭 *Scenario Quantitativo:*\n"
                            f"• *Bias Modello:* {forecast.get('bias_direction', 'In consolidamento')}\n"
                            f"• *Target Primario (TP1):* `{forecast.get('target_tp1_eur', 0.0):.2f} €`\n"
                            f"• *Stop Loss Strutturale:* `{forecast.get('stop_loss_eur', 0.0):.2f} €`\n\n"
                            f"💡 *Guida per Michele su Trade Republic:*\n"
                            f"{action_txt}. Ricorda di impostare un *Ordine Limite* per neutralizzare lo spread di Lang & Schwarz.\n\n"
                            f"Scrivimi *'{ticker}'* per consultare la perizia completa."
                        )

                    await self._broadcast_alert(app, chat_ids, alert_msg)
                    self.ticker_cooldowns[ticker] = now_ts
                    self.alerts_sent_today += 1
                    logger.info(f"[Sentinel] Alert portafoglio inviato per {ticker} ({change_pct:+.2f}%)!")
                    return f"portfolio_alert_{ticker}"

            except Exception as e_port:
                logger.warning(f"[Sentinel] Errore verifica portafoglio {ticker}: {e_port}")

        # ---------------------------------------------------------
        # 4. VERIFICA GRANDI ASSET MONDIALI (Mega-Cap & Macro Barometers)
        # ---------------------------------------------------------
        # Solo i Grandi della Terra, Zero Spazzatura
        major_assets = [
            # Mega-Cap Tech & AI Leaders
            {"ticker": "NVDA", "name": "NVIDIA Corp.", "threshold": 2.8, "type": "megacap"},
            {"ticker": "TSLA", "name": "Tesla Inc.", "threshold": 2.8, "type": "megacap"},
            {"ticker": "AAPL", "name": "Apple Inc.", "threshold": 2.8, "type": "megacap"},
            {"ticker": "MSFT", "name": "Microsoft Corp.", "threshold": 2.8, "type": "megacap"},
            {"ticker": "AMZN", "name": "Amazon.com Inc.", "threshold": 2.8, "type": "megacap"},
            {"ticker": "GOOGL", "name": "Alphabet Inc.", "threshold": 2.8, "type": "megacap"},
            {"ticker": "META", "name": "Meta Platforms", "threshold": 2.8, "type": "megacap"},
            {"ticker": "PLTR", "name": "Palantir Technologies", "threshold": 3.0, "type": "growth_leader"},
            # Termometri Macroeconomici & Materie Prime
            {"ticker": "GC=F", "name": "Oro Spot / Gold", "threshold": 1.5, "type": "commodity"},
            {"ticker": "BZ=F", "name": "Petrolio Brent", "threshold": 2.2, "type": "commodity"},
            {"ticker": "^VIX", "name": "Indice Volatilità VIX", "threshold": 8.0, "type": "vix_spike"},
            {"ticker": "^TNX", "name": "Rendimento US 10Y Treasury", "threshold": 2.5, "type": "yield"},
            {"ticker": "^GSPC", "name": "Indice S&P 500", "threshold": 1.2, "type": "benchmark"},
            {"ticker": "^IXIC", "name": "Indice Nasdaq Composite", "threshold": 1.2, "type": "benchmark"}
        ]

        for ma in major_assets:
            ticker = ma["ticker"]
            last_alert = self.ticker_cooldowns.get(ticker, 0.0)
            if now_ts - last_alert < self.cooldown_seconds:
                continue

            try:
                quote = MarketDataService.get_realtime_quote(ticker)
                last_price = quote.get("last_price", 0.0)
                change_pct = quote.get("change_pct", 0.0)

                if last_price <= 0:
                    continue

                threshold = ma["threshold"]
                is_trigger = False

                if ma.get("type") == "vix_spike":
                    # Il VIX scatta solo su spike rialzista (impennata della paura di mercato)
                    is_trigger = change_pct >= threshold
                else:
                    is_trigger = abs(change_pct) >= threshold

                if is_trigger:
                    payload = {
                        "ticker": ticker,
                        "asset_name": ma["name"],
                        "price_eur": last_price,
                        "change_pct": change_pct,
                        "threshold_triggered": threshold,
                        "asset_type": ma["type"],
                        "note": "Movimento significativo sui grandi asset globali con potenziale contagio su liquidità e portafoglio."
                    }

                    alert_msg = self.llm_svc.generate_sentinel_alert(
                        alert_type="major_asset_outlier",
                        payload=payload,
                        user_portfolio=user_portfolio,
                        user_profile=user_profile,
                        memory_context=memory_context
                    )

                    if not alert_msg:
                        dir_icon = "📈" if change_pct > 0 else "📉"
                        alert_msg = (
                            f"🌍 *RADAR SENTINELLA MACRO: {ma['name'].upper()}* (`{ticker}`)\n\n"
                            f"{dir_icon} *Anomalia Rilevata:* Movimento del *{change_pct:+.2f}%* a quota *{last_price:.2f}* (soglia reattiva: {threshold}%).\n\n"
                            f"💡 *Cosa significa per Michele:*\n"
                            f"Questo scostamento su un pilastro globale può influenzare la liquidità e i pesi del tuo portafoglio (in particolare l'ETF MSCI World Momentum XDEM e la componente azionaria). "
                            f"Valuta con lucidità senza inseguire le code della volatilità.\n\n"
                            f"Scrivimi *'{ticker}'* per esaminare la correlazione e i livelli tecnici."
                        )

                    await self._broadcast_alert(app, chat_ids, alert_msg)
                    self.ticker_cooldowns[ticker] = now_ts
                    self.alerts_sent_today += 1
                    logger.info(f"[Sentinel] Alert grande asset inviato per {ticker} ({change_pct:+.2f}%)!")
                    return f"major_asset_alert_{ticker}"

            except Exception as e_ma:
                logger.warning(f"[Sentinel] Errore verifica grande asset {ticker}: {e_ma}")

        return "no_triggers"

    async def _broadcast_alert(self, app, chat_ids: Set[int], message_text: str):
        """Invia in modo sicuro il messaggio formattato a tutti gli utenti attivi con fallback testuale."""
        cleaned_text = clean_telegram_markdown(message_text)
        for chat_id in chat_ids:
            try:
                await app.bot.send_message(chat_id=chat_id, text=cleaned_text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"[Sentinel] Errore invio alert formattato a {chat_id} ({e}): fallback plain text")
                try:
                    await app.bot.send_message(chat_id=chat_id, text=message_text)
                except Exception as e2:
                    logger.error(f"[Sentinel] Errore critico invio alert a {chat_id}: {e2}")

    def get_sentinel_dashboard(self) -> Dict[str, Any]:
        """Restituisce lo stato operativo completo e dettagliato della sentinella per il comando /sentinel."""
        now = datetime.now(ROME_TZ)
        return {
            "status": "Vigilante e Operativo 24/7",
            "active_hours": "08:00 - 22:00 CET",
            "current_time_cet": now.strftime("%H:%M:%S"),
            "alerts_sent_today": f"{self.alerts_sent_today}/{self.max_alerts_per_day}",
            "cooldown_period": "4 ore per singolo asset | 3 ore geopolitica",
            "monitored_assets": [
                "MSCI World Core (XDWD)", "MSCI World Momentum (XDEM)",
                "BYD Co. (BYDDF)", "Bitcoin (BTC)", "Cardano (ADA)",
                "NVIDIA (NVDA)", "Tesla (TSLA)", "Apple (AAPL)", "Microsoft (MSFT)",
                "Amazon (AMZN)", "Alphabet (GOOGL)", "Meta (META)", "Palantir (PLTR)",
                "Oro Spot (GC=F / SGLD)", "Petrolio Brent (BZ=F)", "Indice VIX (^VIX)", "US 10Y Yield (^TNX)"
            ],
            "active_triggers": [
                "Variazione ETF Core anticipata (|Δ| >= 1.2%)",
                "Variazione Azioni portafoglio (|Δ| >= 2.2%)",
                "Variazione Crypto portafoglio (|Δ| >= 3.5%)",
                "Mega-Cap Tech & AI Leader (|Δ| >= 2.8%)",
                "Materie Prime & Macro (Oro 1.5%, Brent 2.2%, VIX Spike >= +8.0%)",
                "Detector Geopolitico & Macro Shock (Wire terminal FinancialJuice & Breaking)",
                "Capitol Hill STOCK Act Disclosures (Nancy Pelosi PTR)"
            ],
            "detection_pillars": [
                {
                    "name": "💼 Portafoglio Dinamico (Supabase)",
                    "rule": "ETF Core: |Δ| >= 1.2% | Azioni: |Δ| >= 2.2% | Crypto: |Δ| >= 3.5%"
                },
                {
                    "name": "🌍 Grandi della Terra (Mega-Cap & AI Leaders)",
                    "rule": "NVDA, TSLA, AAPL, MSFT, AMZN, GOOGL, META, PLTR (|Δ| >= 2.8%)"
                },
                {
                    "name": "⚖️ Termometri Macro & Materie Prime",
                    "rule": "Oro: |Δ| >= 1.5% | Brent: |Δ| >= 2.2% | VIX: Spike >= +8.0% | US 10Y: |Δ| >= 2.5%"
                },
                {
                    "name": "🚨 Detector Geopolitico & Macro Shock",
                    "rule": "Scansione continua wire terminal (FinancialJuice) & breaking news su guerre, dazi, tassi e banche"
                },
                {
                    "name": "🏛️ Capitol Hill Disclosure Tracker",
                    "rule": "Intercettazione tempestiva report STOCK Act (Hon. Nancy Pelosi & Congresso USA)"
                }
            ]
        }
