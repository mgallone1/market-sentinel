"""
Lightweight Webhook Server for Render Free Web Service
Render free web services require binding to an HTTP port ($PORT) to stay active.
This script sets up a Telegram Webhook or runs the bot alongside a lightweight health-check HTTP server.
"""

import os
import asyncio
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.environ.get("PORT", 8080))

async def health_check(request):
    return web.Response(text="Market Sentinel Bot is running 24/7 on Render Free!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/healthz", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Health-check server running on port {PORT}")

async def main():
    await start_web_server()
    # Import and run telegram bot polling alongside
    import telegram_bot
    # The application from telegram_bot
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    from apscheduler.schedulers.background import BackgroundScheduler

    app = ApplicationBuilder().token(token).post_init(telegram_bot.post_init).build()
    app.add_handler(CommandHandler("start", telegram_bot.start_cmd))
    app.add_handler(CommandHandler("help", telegram_bot.start_cmd))
    app.add_handler(CommandHandler("briefing", telegram_bot.briefing_cmd))
    app.add_handler(CommandHandler("occasioni", telegram_bot.occasioni_cmd))
    app.add_handler(CommandHandler("cicli", telegram_bot.cicli_cmd))
    app.add_handler(CommandHandler("simula", telegram_bot.simula_cmd))
    app.add_handler(CommandHandler("portafoglio", telegram_bot.portfolio_cmd))
    app.add_handler(CommandHandler("memoria", telegram_bot.memoria_cmd))
    app.add_handler(CommandHandler("add", telegram_bot.add_cmd))
    app.add_handler(CallbackQueryHandler(telegram_bot.handle_callback_query))
    app.add_handler(MessageHandler(filters.PHOTO, telegram_bot.handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), telegram_bot.handle_text_message))

    scheduler = BackgroundScheduler()
    scheduler.start()

    print("🤖 Bot Telegram avviato in modalità 24/7 con server HTTP attivo...")
    async with app:
        await app.start()
        await app.updater.start_polling()
        # Keep alive
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
