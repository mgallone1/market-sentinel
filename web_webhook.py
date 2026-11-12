"""
Lightweight Webhook Server for Render Free Web Service with Keep-Alive & Cloud Cron Trigger
Render free web services require binding to an HTTP port ($PORT) and periodic inbound requests to avoid sleep.
"""

import os
import asyncio
import aiohttp
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.environ.get("PORT", 8080))
BRIEFING_SECRET = os.environ.get("BRIEFING_SECRET", "market-sentinel-secret-2026")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://market-sentinel-bot.onrender.com")

bot_application = None

async def health_check(request):
    return web.Response(text="Market Sentinel Bot is running 24/7 on Render Free!")

async def trigger_briefing_endpoint(request):
    """
    Endpoint HTTP invocabile da webhook esterni (GitHub Actions, UptimeRobot, cron-job)
    per risvegliare il server ed erogare il briefing anche se Render fosse entrato in standby.
    """
    global bot_application
    slot = request.query.get("slot", "morning").strip().lower()
    secret = request.query.get("key", "").strip()

    if secret != BRIEFING_SECRET:
        return web.json_response({"error": "Unauthorized", "detail": "Invalid secret key"}, status=401)

    if not bot_application:
        return web.json_response({"error": "Service Unavailable", "detail": "Bot application starting up"}, status=503)

    import telegram_bot
    # Esegue il briefing in background
    asyncio.create_task(telegram_bot.send_scheduled_briefing(bot_application, slot=slot, force=True))
    return web.json_response({
        "ok": True,
        "message": f"Briefing for slot '{slot}' triggered successfully!",
        "slot": slot
    })

async def anti_sleep_loop():
    """Effettua un ping HTTP pubblico ogni 8 minuti per impedire a Render di addormentare l'istanza."""
    healthz_url = f"{RENDER_EXTERNAL_URL}/healthz"
    print(f"🔄 [Anti-Sleep] Loop avviato con target: {healthz_url}")
    await asyncio.sleep(45)  # Attende che il server sia completamente pronto

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(healthz_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    print(f"💓 [Anti-Sleep] Keep-alive ping inviato -> status={resp.status}")
            except Exception as e:
                print(f"[!] [Anti-Sleep] Errore ping: {e}")
            await asyncio.sleep(480)  # Ogni 8 minuti (ben sotto il limite dei 15m)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/healthz", health_check)
    app.router.add_get("/ping", health_check)
    app.router.add_get("/api/trigger-briefing", trigger_briefing_endpoint)
    app.router.add_post("/api/trigger-briefing", trigger_briefing_endpoint)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"✅ Health-check & Trigger server attivo su porta {PORT}")

async def main():
    global bot_application
    await start_web_server()

    import telegram
    import telegram_bot
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

    bot_application = ApplicationBuilder().token(token).post_init(telegram_bot.post_init).build()
    
    async def global_telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        if isinstance(context.error, telegram.error.Conflict):
            print("⚠️ [Telegram] Conflitto temporaneo getUpdates (handover istanze cloud Render).")
            return
        print(f"[Telegram] Errore bot: {context.error}")

    bot_application.add_error_handler(global_telegram_error_handler)

    bot_application.add_handler(CommandHandler("start", telegram_bot.start_cmd))
    bot_application.add_handler(CommandHandler("help", telegram_bot.start_cmd))
    bot_application.add_handler(CommandHandler("aiuto", telegram_bot.start_cmd))
    bot_application.add_handler(CommandHandler("briefing", telegram_bot.briefing_cmd))
    bot_application.add_handler(CommandHandler("occasioni", telegram_bot.occasioni_cmd))
    bot_application.add_handler(CommandHandler("pelosi", telegram_bot.pelosi_cmd))
    bot_application.add_handler(CommandHandler("congresso", telegram_bot.pelosi_cmd))
    bot_application.add_handler(CommandHandler("scanner", telegram_bot.scanner_cmd))
    bot_application.add_handler(CommandHandler("daytrade", telegram_bot.scanner_cmd))
    bot_application.add_handler(CommandHandler("previsione", telegram_bot.previsione_cmd))
    bot_application.add_handler(CommandHandler("forecast", telegram_bot.previsione_cmd))
    bot_application.add_handler(CommandHandler("sentinel", telegram_bot.sentinel_cmd))
    bot_application.add_handler(CommandHandler("radar", telegram_bot.sentinel_cmd))
    bot_application.add_handler(CommandHandler("cicli", telegram_bot.cicli_cmd))
    bot_application.add_handler(CommandHandler("simula", telegram_bot.simula_cmd))
    bot_application.add_handler(CommandHandler("portafoglio", telegram_bot.portfolio_cmd))
    bot_application.add_handler(CommandHandler("alpaca", telegram_bot.alpaca_cmd))
    bot_application.add_handler(CommandHandler("trade", telegram_bot.alpaca_cmd))
    bot_application.add_handler(CommandHandler("profilo", telegram_bot.profile_cmd))
    bot_application.add_handler(CommandHandler("memoria", telegram_bot.memoria_cmd))
    bot_application.add_handler(CommandHandler("add", telegram_bot.add_cmd))
    bot_application.add_handler(CallbackQueryHandler(telegram_bot.handle_callback_query))
    bot_application.add_handler(MessageHandler(filters.PHOTO, telegram_bot.handle_photo))
    bot_application.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE | filters.ANIMATION, telegram_bot.handle_video))
    bot_application.add_handler(MessageHandler(filters.Document.ALL, telegram_bot.handle_document))
    bot_application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), telegram_bot.handle_text_message))

    # Avvia il loop di keep-alive in background
    asyncio.create_task(anti_sleep_loop())

    print("🤖 Bot Telegram avviato in modalità 24/7 con server HTTP, keep-alive e trigger cloud attivi...", flush=True)
    async with bot_application:
        await bot_application.start()
        print("🚀 [Telegram] Application.start() completato con successo!", flush=True)
        
        # Connessione polling resiliente ai conflitti del rolling deploy di Render
        for attempt in range(8):
            try:
                print(f"📡 [Polling] Avvio updater.start_polling (tentativo {attempt+1}/8)...", flush=True)
                await bot_application.updater.start_polling(drop_pending_updates=True, bootstrap_retries=5)
                print("✅ [Polling] Updater connesso a Telegram con successo (nessun conflitto)!", flush=True)
                break
            except telegram.error.Conflict:
                print(f"⚠️ [Polling] Conflitto con istanza precedente (tentativo {attempt+1}/8). Attesa 5 secondi che la vecchia istanza termini...", flush=True)
                await asyncio.sleep(5)
            except Exception as pe:
                print(f"⚠️ [Polling] Errore start_polling: {pe}. Attendo 4 secondi...", flush=True)
                await asyncio.sleep(4)

        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
