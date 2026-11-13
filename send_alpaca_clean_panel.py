import urllib.request
import json
from services.alpaca_execution_service import AlpacaExecutionService

TELEGRAM_TOKEN = "9070559372:AAEsCUsDnb-xlgDzq3JakX4_9icIgMhPCAA"
USER_CHAT_ID = 424093845

alpaca_service = AlpacaExecutionService()
summary = alpaca_service.get_account_summary()
acc = summary.get("account", {})
clock = summary.get("clock", {})
positions = summary.get("positions", [])

is_open = "APERTA 🟢" if clock.get("is_open") else "CHIUSA 🔴"
val = float(acc.get("portfolio_value", 0))
cash = float(acc.get("cash", 0))
buying_power = float(acc.get("buying_power", 0))

msg = (
    "⚡ *PANNELLO DIRETTO ALPACA TRADING*\n"
    "────────────────────────\n"
    f"• *Stato Borsa USA:* {is_open}\n"
    f"• *Valore Portafoglio:* `${val:,.2f}`\n"
    f"• *Liquidità Libera:* `${cash:,.2f}`\n"
    f"• *Buying Power:* `${buying_power:,.2f}`\n\n"
)

keyboard = []
if positions:
    msg += f"📈 *POSIZIONI ATTIVE ({len(positions)}):*\n"
    for p in positions:
        sym = p['symbol']
        side = p['side'].upper()
        qty = p['qty']
        pl = float(p['unrealized_pl'])
        plpc = float(p['unrealized_plpc']) * 100
        curr = float(p['current_price'])
        sign = "🟢 +" if pl >= 0 else "🔴 "
        msg += f"  • `{sym}` ({side} x{qty}): `${curr:.2f}` | P&L: {sign}${pl:.2f} ({plpc:+.2f}%)\n"
    keyboard.append([{"text": "🚨 Chiudi Tutte le Posizioni", "callback_data": "alpaca_close_all"}])
else:
    msg += "💤 *Nessuna posizione aperta.* Capitale 100% protetto in contanti (Cash).\n"

keyboard.append([
    {"text": "🔄 Aggiorna Saldo Live", "callback_data": "alpaca_refresh"},
    {"text": "🛢️ Metalli & Petrolio", "callback_data": "cmd_materieprime"}
])

payload = {
    "chat_id": USER_CHAT_ID,
    "text": msg,
    "parse_mode": "Markdown",
    "reply_markup": {"inline_keyboard": keyboard}
}

req = urllib.request.Request(
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req) as resp:
        print("DELIVERED_OK:", resp.read().decode()[:100])
except Exception as e:
    print("ERR:", e)
