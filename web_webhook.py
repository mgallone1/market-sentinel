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
    """Render briefing trigger endpoint disabilitato (migrato a Railway Cloud)."""
    return web.json_response({
        "ok": False,
        "message": "Render instance is decommissioned. All briefings run exclusively on Railway Cloud."
    }, status=410)

async def anti_sleep_loop():
    """Anti-sleep loop disabilitato."""
    pass

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
    print(f"✅ Placeholder health-check server attivo su porta {PORT} (Render dismesso)")

async def main():
    global bot_application
    await start_web_server()

    # Render è stato dismesso in favore di Railway Cloud.
    # Non avviare polling né scheduler per evitare doppi briefing e conflitti getUpdates.
    print("⛔ [Render Deprecated] Questo servizio è migrato su Railway Cloud (24/7). Polling disattivato su Render.", flush=True)
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
