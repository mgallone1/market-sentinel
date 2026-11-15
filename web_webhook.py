import os
import asyncio
from aiohttp import web

PORT = int(os.environ.get("PORT", 8080))

async def handle_all(request):
    return web.Response(text="Render instance decommissioned. Migrated to Railway Cloud.", status=200)

async def main():
    app = web.Application()
    app.router.add_route('*', '/{tail:.*}', handle_all)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Render decommission dummy server active on port {PORT}", flush=True)
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
