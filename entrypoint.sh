#!/bin/bash
# Entrypoint supervisor per auto-restart continuo e resilienza a crash/network drops

echo "🛡️ [Market Sentinel Supervisor] Container avviato con auto-restart continuo."

while true; do
    echo "🚀 [$(date '+%Y-%m-%d %H:%M:%S')] Avvio istanza Telegram Bot Market Sentinel..."
    python telegram_bot.py
    EXIT_CODE=$?
    
    echo "⚠️ [$(date '+%Y-%m-%d %H:%M:%S')] Processo terminato con Exit Code ${EXIT_CODE}."
    echo "🔄 Riavvio automatico del bot in corso tra 3 secondi..."
    sleep 3
done
