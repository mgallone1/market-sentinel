"""
Proactive Sentinel & Market Watchdog Service for Market Sentinel.
Monitors portfolio assets, watchlist leaders, and Congressional filings autonomously.
Delivers proactive institutional wealth-coaching alerts to Michele via Telegram
when significant statistical anomalies, oversold setups, or new insider disclosures occur.
"""

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
        # Cooldown standard: 6 ore (21600 secondi) per lo stesso ticker
        self.cooldown_seconds = 21600

        # Tracciamento giornaliero alert
        self.today_date_str = ""
        self.alerts_sent_today = 0
        self.max_alerts_per_day = 3

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
        Ciclo autonomo di sorveglianza eseguito ogni 20-30 minuti in background.
        Scansiona portfolio e watchlist alla ricerca di shock di volatilità o pattern ad alta asimmetria.
        """
        if not self._is_active_hours():
            logger.info("[Sentinel] Fuori orario di mercato attivo (08:00 - 22:00). Sleep.")
            return None

        self._reset_daily_counter_if_needed()
        if self.alerts_sent_today >= self.max_alerts_per_day:
            logger.info(f"[Sentinel] Raggiunto limite massimo giornaliero di alert ({self.max_alerts_per_day}).")
            return None

        chat_ids = self.supabase_svc.get_active_chat_ids()
        if not chat_ids:
            return None

        now_ts = time.time()

        # 1. VERIFICA NUOVE DISCLOSURE CONGRESSO USA (Nancy Pelosi & Capitol Hill)
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

        # 2. VERIFICA ASSET DI PORTAFOGLIO E WATCHLIST TATTICA
        monitored_tickers = [
            # Portafoglio core
            "XDWD.DE", "XDEM.DE", "BYDDF", "BTC-EUR", "ADA-EUR",
            # Watchlist tech e growth ad alta volatilità
            "NVDA", "AAPL", "MSFT", "TSLA", "PLTR", "MSTR"
        ]

        for ticker in monitored_tickers:
            # Check cooldown ticker
            last_alert = self.ticker_cooldowns.get(ticker, 0)
            if now_ts - last_alert < self.cooldown_seconds:
                continue

            try:
                # Recupera dati live
                quote = MarketDataService.get_realtime_quote(ticker)
                last_price = quote.get("last_price", 0.0)
                change_pct = quote.get("change_pct", 0.0)

                if last_price <= 0:
                    continue

                # Criteri di trigger proattivo:
                # A) Forte movimento direzionale intraday (>= 3.8% di ribasso o rialzo)
                # B) Ipervenduto statistico profondo (RSI < 28 o Z-Score <= -2.2)
                is_shock_move = abs(change_pct) >= 3.8
                
                # Se c'è uno shock o un'anomalia, interroga il motore previsionale d'insieme
                if is_shock_move:
                    forecast = EnsemblePredictorEngine.generate_ensemble_forecast(ticker)
                    if forecast.get("error"):
                        continue

                    # Invia solo se c'è una chiara asimmetria o urgenza tattica
                    asset_name = forecast.get("asset_name", ticker)
                    price_eur = forecast.get("current_price_eur", last_price)
                    bias = forecast.get("bias_direction")
                    conviction = forecast.get("conviction_score")
                    tp1 = forecast.get("target_tp1_eur")
                    sl = forecast.get("stop_loss_eur")

                    # Messaggio proattivo sartoriale del CIO
                    direction_emoji = "🟢" if change_pct < 0 else "🚀"
                    thesis_action = "Un'ottima finestra di accumulo a sconto per il tuo PAC o per un ingresso tattico" if change_pct < 0 else "Forte estensione dei prezzi: valuta se proteggere i guadagni o attendere consolidamento"

                    msg = (
                        f"⚡ *ALERT PROATTIVO DEL CIO: {asset_name.upper()}* (`{ticker}`)\n\n"
                        f"{direction_emoji} *Anomalia Rilevata:* Il titolo sta registrando una variazione intraday del *{change_pct:+.2f}%* a quota *{price_eur:.2f} €*.\n\n"
                        f"🧭 *Previsione Quantitativa d'Insieme:*\n"
                        f"• *Scenario Atteso:* {bias}\n"
                        f"• *Livello di Convinzione Modello:* `{conviction}`\n"
                        f"• *Target Proiettato (TP1):* `{tp1:.2f} €`\n"
                        f"• *Stop Loss Strutturale:* `{sl:.2f} €`\n"
                        f"• *Orizzonte Stimato:* {forecast.get('time_horizon')}\n\n"
                        f"💡 *Verdetto Operativo per Michele:*\n"
                        f"{thesis_action}. Su Trade Republic, imposta sempre un *Ordine Limite* per neutralizzare lo spread di Lang & Schwarz.\n\n"
                        f"Scrivimi *'{ticker}'* o premi `/previsione {ticker}` per consultare il quadro completo."
                    )

                    await self._broadcast_alert(app, chat_ids, msg)
                    self.ticker_cooldowns[ticker] = now_ts
                    self.alerts_sent_today += 1
                    logger.info(f"[Sentinel] Alert proattivo inviato con successo per {ticker} ({change_pct:+.2f}%)!")
                    return f"alert_dispatched_{ticker}"

            except Exception as ex:
                logger.warning(f"[Sentinel] Errore verifica ticker {ticker}: {ex}")

        return "no_triggers"

    async def _broadcast_alert(self, app, chat_ids: Set[int], message_text: str):
        """Invia in modo sicuro il messaggio formattato a tutti gli utenti attivi."""
        cleaned_text = clean_telegram_markdown(message_text)
        for chat_id in chat_ids:
            try:
                await app.bot.send_message(chat_id=chat_id, text=cleaned_text, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"[Sentinel] Errore invio alert a {chat_id}: {e}")

    def get_sentinel_dashboard(self) -> Dict[str, Any]:
        """Restituisce lo stato operativo della sentinella per il comando /sentinel."""
        now = datetime.now(ROME_TZ)
        return {
            "status": "Attivo e Vigilante 24/7",
            "active_hours": "08:00 - 22:00 CET",
            "current_time_cet": now.strftime("%H:%M:%S"),
            "alerts_sent_today": f"{self.alerts_sent_today}/{self.max_alerts_per_day}",
            "monitored_assets": [
                "MSCI World Core (XDWD)", "MSCI World Momentum (XDEM)",
                "BYD Co. (BYDDF)", "Bitcoin (BTC)", "Cardano (ADA)",
                "NVIDIA (NVDA)", "Tesla (TSLA)", "Apple (AAPL)", "Microsoft (MSFT)", "Palantir (PLTR)"
            ],
            "active_triggers": [
                "Variazione intraday anomala (|Δ| >= 3.8%)",
                "Ipervenduto estremo (Z-Score <= -2.2 / RSI <= 27)",
                "Breakout istituzionale sui massimi a 20 giorni",
                "Nuove disclosure Congressuali USA (Nancy Pelosi PTR)"
            ]
        }
