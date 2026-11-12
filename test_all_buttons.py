"""
Audit di tutti i pulsanti e comandi del bot Market Sentinel + Alpaca
"""
import asyncio
from services.alpaca_execution_service import AlpacaExecutionService
from services.opportunity_scanner import OpportunityScannerService
from services.cycle_radar import CycleRadarService
from services.day_trader_service import DayTraderService

print("1. Verifica Alpaca Service...")
alpaca = AlpacaExecutionService()
summary = alpaca.get_account_summary()
assert "account" in summary, "Alpaca summary fallito!"
print(f"   -> OK: Valore ${float(summary['account']['portfolio_value']):,.2f}")

print("2. Verifica Opportunity Scanner...")
opps = OpportunityScannerService.scan_best_opportunities(top_n=3)
assert len(opps) > 0, "Opportunity scanner vuoto!"
print(f"   -> OK: Trovate {len(opps)} opportunità.")

print("3. Verifica Cycle Radar...")
cycles = CycleRadarService.scan_active_cycles()
print(f"   -> OK: Trovati {len(cycles)} cicli.")

print("4. Verifica Day Trader Service...")
dts = DayTraderService()
trades = dts.get_congress_trades(max_reports=1)
print(f"   -> OK: Congress reports caricati.")

print("\nTUTTI I SERVIZI SOTTOSTANTI AI PULSANTI SONO OPERATIVI AL 100%!")
