import urllib.request
import json

token = "9070559372:AAEsCUsDnb-xlgDzq3JakX4_9icIgMhPCAA"
chat_id = 424093845

msg = (
    "🛢️ *NUOVO COMPARTO ATTIVO: COMMODITIES & METALLI PREZIOSI*\n"
    "────────────────────────\n"
    "Ora puoi negoziare materie prime su Alpaca Paper (sia Long che Short):\n\n"
    "• 🥇 *Oro Fisico* (`GLD`): SPDR Gold Shares\n"
    "• 🥈 *Argento Fisico* (`SLV`): iShares Silver Trust\n"
    "• 🛢️ *Petrolio WTI* (`USO`): United States Oil Fund\n"
    "• ⛽ *Petrolio Brent* (`BNO`): Brent Oil Fund\n"
    "• 🔥 *Gas Naturale* (`UNG`): Natural Gas Fund\n"
    "• 🧱 *Rame* (`CPER`): Copper Index\n\n"
    "💡 *Come usarlo dal telefono:*\n"
    "1. Digita il comando `/materieprime` (oppure `/oro` o `/petrolio`)\n"
    "2. Oppure scrivi in linguaggio naturale:\n"
    "   _\"Compra 10 azioni di Oro\"_ o _\"Compra 500$ di Petrolio\"_\n"
    "3. O clicca direttamente sui pulsanti touch sotto:"
)

keyboard = {
    "inline_keyboard": [
        [
            {"text": "🥇 Compra Oro (GLD)", "callback_data": "buy_gld"},
            {"text": "🛢️ Compra Petrolio (USO)", "callback_data": "buy_uso"}
        ],
        [
            {"text": "🥈 Compra Argento (SLV)", "callback_data": "buy_slv"},
            {"text": "⚡ Saldo Alpaca", "callback_data": "alpaca_refresh"}
        ]
    ]
}

payload = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown", "reply_markup": keyboard}
req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req) as resp:
    print("DELIVERED:", resp.read().decode())
