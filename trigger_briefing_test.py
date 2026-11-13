import urllib.request
import json

url = "https://market-sentinel-bot.onrender.com/api/trigger-briefing?slot=afternoon&key=market-sentinel-secret-2026"
req = urllib.request.Request(url, method="POST")
try:
    with urllib.request.urlopen(req) as resp:
        print("TRIGGER RESP:", resp.read().decode())
except Exception as e:
    print("ERR:", e)
