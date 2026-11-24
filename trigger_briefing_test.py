import urllib.request
import os

secret = os.environ.get("BRIEFING_SECRET", "")
if not secret:
    raise ValueError("BRIEFING_SECRET environment variable is missing!")

url = "https://market-sentinel-bot.onrender.com/api/trigger-briefing?slot=afternoon"
req = urllib.request.Request(
    url, 
    headers={"X-Trigger-Key": secret}, 
    method="POST"
)
try:
    with urllib.request.urlopen(req) as resp:
        print("TRIGGER RESP:", resp.read().decode())
except Exception as e:
    print("ERR:", e)
