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

    # Render è stato dismesso in favore di Railway Cloud.
    # Non avviare polling né scheduler per evitare doppi briefing e conflitti getUpdates.
    print("⛔ [Render Deprecated] Questo servizio è migrato su Railway Cloud (24/7). Polling disattivato su Render.", flush=True)
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
