import asyncio
from services.alpaca_execution_service import AlpacaExecutionService

svc = AlpacaExecutionService()
summary = svc.get_account_summary()
acc = summary.get("account", {})
clock = summary.get("clock", {})
positions = summary.get("positions", [])

is_open = "APERTA 🟢" if clock.get("is_open") else "CHIUSA 🔴"
val = float(acc.get("portfolio_value", 0))
cash = float(acc.get("cash", 0))
buying_power = float(acc.get("buying_power", 0))

msg = (
    "⚡ *ALPACA EXECUTION & DAY TRADER*\n"
    "────────────────────────\n"
    f"• *Stato Borsa USA:* {is_open}\n"
    f"• *Valore Portafoglio:* `${val:,.2f}`\n"
    f"• *Liquidità Libera (Cash):* `${cash:,.2f}`\n"
    f"• *Buying Power:* `${buying_power:,.2f}`\n\n"
)
print("Rendered message:\n", msg)
