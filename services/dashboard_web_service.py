"""
Web Dashboard Service for Market Sentinel.
Fornisce una dashboard web moderna, ultra-veloce, reattiva e auto-aggiornante (polling ogni 3 secondi)
per monitorare in tempo reale le posizioni Bybit Futures, lo stato Alpaca, il bilancio e gli indicatori di rischio.
"""

import json
from aiohttp import web
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any

from services.bybit_execution_service import BybitExecutionService
from services.alpaca_execution_service import AlpacaExecutionService

_bybit_service: BybitExecutionService = None
_alpaca_service: AlpacaExecutionService = None

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Market Sentinel — Live Trading Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap');
        body {
            font-family: 'Inter', sans-serif;
            background-color: #090d16;
            color: #f1f5f9;
        }
        .mono { font-family: 'JetBrains Mono', monospace; }
        .glass-card {
            background: rgba(15, 23, 42, 0.75);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .glass-card-glow {
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(59, 130, 246, 0.25);
            box-shadow: 0 0 25px rgba(59, 130, 246, 0.1);
        }
        .pulse-dot {
            animation: pulseGlow 2s infinite;
        }
        @keyframes pulseGlow {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(1.15); }
        }
    </style>
</head>
<body class="min-h-screen p-4 md:p-8 flex flex-col justify-between">

    <!-- Top Navigation / Header -->
    <header class="max-w-7xl mx-auto w-full mb-8">
        <div class="glass-card rounded-2xl p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div class="flex items-center gap-4">
                <div class="w-12 h-12 rounded-xl bg-blue-500/10 border border-blue-500/30 flex items-center justify-center text-blue-400">
                    <i data-lucide="shield-check" class="w-7 h-7"></i>
                </div>
                <div>
                    <div class="flex items-center gap-3">
                        <h1 class="text-2xl font-bold tracking-tight text-white">Market Sentinel</h1>
                        <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                            <span class="w-2 h-2 rounded-full bg-emerald-400 pulse-dot"></span>
                            LIVE TRADING 24/7
                        </span>
                    </div>
                    <p class="text-sm text-slate-400 mt-0.5">Motore Quantitativo Istituzionale &bull; Bybit Futures (Demo UTA) + Alpaca Equities</p>
                </div>
            </div>
            <div class="flex items-center gap-3 self-end md:self-auto">
                <div class="text-right">
                    <p class="text-xs text-slate-400 font-medium">Ora Server (Roma):</p>
                    <p id="clock-display" class="text-sm font-semibold text-slate-200 mono">--:--:--</p>
                </div>
                <button onclick="fetchData()" class="p-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition" title="Aggiorna Adesso">
                    <i data-lucide="refresh-cw" class="w-4 h-4" id="refresh-icon"></i>
                </button>
            </div>
        </div>
    </header>

    <!-- Main Content -->
    <main class="max-w-7xl mx-auto w-full flex-1 space-y-8">

        <!-- KPI Grid -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            <!-- Total Equity -->
            <div class="glass-card rounded-2xl p-5 border-l-4 border-l-blue-500">
                <div class="flex justify-between items-start">
                    <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">Patrimonio Complessivo</p>
                    <div class="p-2 bg-blue-500/10 rounded-lg text-blue-400"><i data-lucide="wallet" class="w-4 h-4"></i></div>
                </div>
                <h3 id="total-equity" class="text-2xl font-bold mt-2 mono text-white">$0.00</h3>
                <p class="text-xs text-slate-400 mt-2 flex items-center gap-1.5">
                    <span class="text-slate-300 font-medium">Bybit:</span> <span id="bybit-equity-kpi" class="mono text-slate-300">$0</span> &bull; 
                    <span class="text-slate-300 font-medium">Alpaca:</span> <span id="alpaca-equity-kpi" class="mono text-slate-300">$0</span>
                </p>
            </div>

            <!-- Free Cash USDT -->
            <div class="glass-card rounded-2xl p-5 border-l-4 border-l-emerald-500">
                <div class="flex justify-between items-start">
                    <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">Liquidità Libera (Cash)</p>
                    <div class="p-2 bg-emerald-500/10 rounded-lg text-emerald-400"><i data-lucide="coins" class="w-4 h-4"></i></div>
                </div>
                <h3 id="usdt-cash" class="text-2xl font-bold mt-2 mono text-emerald-400">$0.00 USDT</h3>
                <p class="text-xs text-slate-400 mt-2">Disponibile per nuovi trade automatici</p>
            </div>

            <!-- Active Positions Value -->
            <div class="glass-card rounded-2xl p-5 border-l-4 border-l-purple-500">
                <div class="flex justify-between items-start">
                    <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">Capitale a Mercato</p>
                    <div class="p-2 bg-purple-500/10 rounded-lg text-purple-400"><i data-lucide="layers" class="w-4 h-4"></i></div>
                </div>
                <h3 id="active-notional" class="text-2xl font-bold mt-2 mono text-purple-300">$0.00</h3>
                <p id="positions-count-label" class="text-xs text-slate-400 mt-2">0 posizioni attive diversificate</p>
            </div>

            <!-- Total Unrealized PnL -->
            <div class="glass-card rounded-2xl p-5 border-l-4 border-l-amber-500" id="pnl-kpi-card">
                <div class="flex justify-between items-start">
                    <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">P&L Aperto (Live)</p>
                    <div class="p-2 bg-amber-500/10 rounded-lg text-amber-400" id="pnl-kpi-icon"><i data-lucide="trending-up" class="w-4 h-4"></i></div>
                </div>
                <h3 id="total-unrealized-pnl" class="text-2xl font-bold mt-2 mono text-slate-100">$0.00</h3>
                <p class="text-xs text-slate-400 mt-2" id="pnl-status-note">Monitoraggio continuo</p>
            </div>
        </div>

        <!-- Live Positions Table -->
        <div class="glass-card-glow rounded-2xl p-6">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-5 border-b border-slate-800 gap-3">
                <div>
                    <h2 class="text-lg font-bold text-white flex items-center gap-2">
                        <i data-lucide="activity" class="w-5 h-5 text-blue-400"></i>
                        Posizioni Aperte in Tempo Reale (Bybit Futures)
                    </h2>
                    <p class="text-xs text-slate-400 mt-0.5">Sizing standard $15.000 &bull; Take Profit +1.50% &bull; Break-Even al +0.30% &bull; Stop Loss -0.60%</p>
                </div>
                <span id="active-badge" class="px-3 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 self-start sm:self-auto">
                    Caricamento...
                </span>
            </div>

            <div class="overflow-x-auto mt-4">
                <table class="w-full text-left text-sm">
                    <thead>
                        <tr class="text-slate-400 border-b border-slate-800 text-xs uppercase tracking-wider">
                            <th class="py-3 px-4 font-semibold">Asset / Contratto</th>
                            <th class="py-3 px-4 font-semibold">Direzione</th>
                            <th class="py-3 px-4 font-semibold">Size</th>
                            <th class="py-3 px-4 font-semibold">Prezzo Entry</th>
                            <th class="py-3 px-4 font-semibold">Prezzo Mark Live</th>
                            <th class="py-3 px-4 font-semibold">Controvalore</th>
                            <th class="py-3 px-4 font-semibold">P&L Non Realizzato</th>
                            <th class="py-3 px-4 font-semibold">Livello Protezione</th>
                        </tr>
                    </thead>
                    <tbody id="positions-table-body" class="divide-y divide-slate-800/60">
                        <tr>
                            <td colspan="8" class="text-center py-8 text-slate-400">Caricamento delle posizioni in tempo reale...</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Strategy Details & Closed Trades -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Execution Blueprint -->
            <div class="glass-card rounded-2xl p-6 lg:col-span-1 space-y-4">
                <h3 class="text-base font-bold text-white flex items-center gap-2">
                    <i data-lucide="sliders" class="w-5 h-5 text-indigo-400"></i>
                    Protocollo Day-Trader Suite
                </h3>
                <div class="space-y-3 text-xs text-slate-300">
                    <div class="p-3 bg-slate-900/60 rounded-xl border border-slate-800">
                        <span class="font-bold text-emerald-400 uppercase tracking-wide">1. Break-Even Safe Guard (+0.30%)</span>
                        <p class="text-slate-400 mt-1">Appena il trade supera il +0.30%, lo Stop Loss si posiziona automaticamente sopra il prezzo di carico. <strong class="text-slate-200">Rischio Azzerato.</strong></p>
                    </div>
                    <div class="p-3 bg-slate-900/60 rounded-xl border border-slate-800">
                        <span class="font-bold text-blue-400 uppercase tracking-wide">2. Trailing Profit Lock (+0.70%)</span>
                        <p class="text-slate-400 mt-1">Al raggiungimento di +0.70%, lo stop viene alzato a +0.40% bloccando profitto netto sicuro in tasca.</p>
                    </div>
                    <div class="p-3 bg-slate-900/60 rounded-xl border border-slate-800">
                        <span class="font-bold text-amber-400 uppercase tracking-wide">3. Take Profit Target (+1.50%)</span>
                        <p class="text-slate-400 mt-1">Monetizzazione automatica a mercato incassando circa <strong class="text-emerald-400">+$225.00 USDT netti</strong> ad asset.</p>
                    </div>
                </div>
            </div>

            <!-- Recent Closed Trades -->
            <div class="glass-card rounded-2xl p-6 lg:col-span-2">
                <div class="flex items-center justify-between pb-4 border-b border-slate-800">
                    <h3 class="text-base font-bold text-white flex items-center gap-2">
                        <i data-lucide="history" class="w-5 h-5 text-amber-400"></i>
                        Ultimi Trade Eseguiti & Realizzati
                    </h3>
                    <span class="text-xs text-slate-400">Cronologia Bybit Futures</span>
                </div>
                <div class="overflow-x-auto mt-3">
                    <table class="w-full text-left text-xs">
                        <thead>
                            <tr class="text-slate-400 border-b border-slate-800 uppercase tracking-wider">
                                <th class="py-2.5 px-3">Asset</th>
                                <th class="py-2.5 px-3">Operazione</th>
                                <th class="py-2.5 px-3">Quantità</th>
                                <th class="py-2.5 px-3">Entry -> Exit</th>
                                <th class="py-2.5 px-3">P&L Realizzato</th>
                            </tr>
                        </thead>
                        <tbody id="closed-trades-body" class="divide-y divide-slate-800/60">
                            <tr>
                                <td colspan="5" class="text-center py-6 text-slate-400">Caricamento storico...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

    </main>

    <!-- Footer -->
    <footer class="max-w-7xl mx-auto w-full mt-10 text-center text-xs text-slate-500 py-4 border-t border-slate-900 flex flex-col sm:flex-row items-center justify-between gap-2">
        <p>&copy; 2026 Market Sentinel &bull; Proprietary Quantitative Architecture</p>
        <p class="mono text-slate-400">Aggiornamento automatico live ogni 3 secondi</p>
    </footer>

    <!-- Logic JS -->
    <script>
        lucide.createIcons();

        function updateClock() {
            const now = new Date();
            document.getElementById('clock-display').innerText = now.toLocaleTimeString('it-IT');
        }
        setInterval(updateClock, 1000);
        updateClock();

        async function fetchData() {
            const icon = document.getElementById('refresh-icon');
            if (icon) icon.classList.add('animate-spin');

            try {
                const res = await fetch('/api/dashboard');
                const data = await res.json();
                renderData(data);
            } catch (err) {
                console.error("Errore caricamento dati:", err);
            } finally {
                if (icon) setTimeout(() => icon.classList.remove('animate-spin'), 400);
            }
        }

        function renderData(data) {
            // KPI
            const bybit = data.bybit || {};
            const alpaca = data.alpaca || {};
            const positions = bybit.positions || [];
            const closed = bybit.closed || [];

            const bWallet = bybit.wallet || {};
            const aAcc = alpaca.account || {};

            const bybitEq = bWallet.total_equity || 0;
            const alpacaEq = parseFloat(aAcc.portfolio_value || 0);
            const totalEq = bybitEq + alpacaEq;

            document.getElementById('total-equity').innerText = `$${totalEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('bybit-equity-kpi').innerText = `$${bybitEq.toLocaleString('en-US', {maximumFractionDigits: 0})}`;
            document.getElementById('alpaca-equity-kpi').innerText = `$${alpacaEq.toLocaleString('en-US', {maximumFractionDigits: 0})}`;

            const usdtCash = (bWallet.coins && bWallet.coins.USDT) ? bWallet.coins.USDT : (bWallet.available_balance || 0);
            document.getElementById('usdt-cash').innerText = `$${usdtCash.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} USDT`;

            let totalNotional = 0;
            let totalPnL = 0;

            positions.forEach(p => {
                totalNotional += p.position_value || 0;
                totalPnL += p.unrealized_pnl || 0;
            });

            document.getElementById('active-notional').innerText = `$${totalNotional.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('positions-count-label').innerText = `${positions.length} posizioni attive diversificate`;

            const pnlEl = document.getElementById('total-unrealized-pnl');
            const pnlCard = document.getElementById('pnl-kpi-card');
            const pnlSign = totalPnL >= 0 ? '+' : '';
            pnlEl.innerText = `${pnlSign}$${totalPnL.toFixed(2)}`;

            if (totalPnL >= 0) {
                pnlEl.className = "text-2xl font-bold mt-2 mono text-emerald-400";
                pnlCard.className = "glass-card rounded-2xl p-5 border-l-4 border-l-emerald-500";
                document.getElementById('pnl-status-note').innerText = "Attivo in profitto";
            } else {
                pnlEl.className = "text-2xl font-bold mt-2 mono text-rose-400";
                pnlCard.className = "glass-card rounded-2xl p-5 border-l-4 border-l-rose-500";
                document.getElementById('pnl-status-note').innerText = "Controllo rischio attivo";
            }

            document.getElementById('active-badge').innerText = `${positions.length} CONTRATTI ATTIVI`;

            // Tabella Posizioni
            const tbody = document.getElementById('positions-table-body');
            if (positions.length === 0) {
                tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-slate-400">Nessuna posizione aperta al momento. Il bot sta scansionando i breakout.</td></tr>`;
            } else {
                tbody.innerHTML = positions.map(p => {
                    const isLong = p.side === 'BUY';
                    const sideBadge = isLong 
                        ? `<span class="px-2.5 py-1 rounded-md text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">LONG</span>`
                        : `<span class="px-2.5 py-1 rounded-md text-xs font-bold bg-rose-500/15 text-rose-400 border border-rose-500/30">SHORT</span>`;
                    
                    const pnlSign = p.unrealized_pnl >= 0 ? '+' : '';
                    const pnlClass = p.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400';
                    const pnlPctClass = p.pnl_pct >= 0 ? 'text-emerald-400' : 'text-rose-400';

                    let protectionBadge = `<span class="text-xs text-slate-400 font-medium">SL Protettivo (-0.60%)</span>`;
                    if (p.pnl_pct >= 0.70) {
                        protectionBadge = `<span class="px-2 py-0.5 rounded text-xs font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">🔒 Profit Locked (+0.40%)</span>`;
                    } else if (p.pnl_pct >= 0.30) {
                        protectionBadge = `<span class="px-2 py-0.5 rounded text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">🛡️ Break-Even Safe (0 Rischio)</span>`;
                    }

                    return `
                        <tr class="hover:bg-slate-800/40 transition">
                            <td class="py-3.5 px-4 font-bold text-white mono">${p.symbol}</td>
                            <td class="py-3.5 px-4">${sideBadge}</td>
                            <td class="py-3.5 px-4 mono text-slate-300">${p.size}</td>
                            <td class="py-3.5 px-4 mono text-slate-300">$${p.entry_price.toFixed(4)}</td>
                            <td class="py-3.5 px-4 mono font-semibold text-white">$${p.mark_price.toFixed(4)}</td>
                            <td class="py-3.5 px-4 mono text-slate-300">$${(p.position_value || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                            <td class="py-3.5 px-4 mono font-bold ${pnlClass}">
                                ${pnlSign}$${p.unrealized_pnl.toFixed(2)} 
                                <span class="text-xs font-semibold ${pnlPctClass}">(${pnlSign}${p.pnl_pct.toFixed(2)}%)</span>
                            </td>
                            <td class="py-3.5 px-4">${protectionBadge}</td>
                        </tr>
                    `;
                }).join('');
            }

            // Tabella Storico Chiusure
            const closedBody = document.getElementById('closed-trades-body');
            if (closed.length === 0) {
                closedBody.innerHTML = `<tr><td colspan="5" class="text-center py-6 text-slate-400">Nessuna chiusura recente registrata.</td></tr>`;
            } else {
                closedBody.innerHTML = closed.slice(0, 5).map(c => {
                    const pnlVal = parseFloat(c.closedPnl || 0);
                    const pnlClass = pnlVal >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
                    const pnlSign = pnlVal >= 0 ? '+' : '';
                    return `
                        <tr class="hover:bg-slate-800/30 transition">
                            <td class="py-2.5 px-3 font-semibold text-white mono">${c.symbol}</td>
                            <td class="py-2.5 px-3"><span class="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-800 text-slate-300">${c.side}</span></td>
                            <td class="py-2.5 px-3 mono text-slate-400">${c.closedSize || c.qty}</td>
                            <td class="py-2.5 px-3 mono text-slate-400">$${parseFloat(c.avgEntryPrice || 0).toFixed(2)} &rarr; $${parseFloat(c.avgExitPrice || 0).toFixed(2)}</td>
                            <td class="py-2.5 px-3 mono ${pnlClass}">${pnlSign}$${pnlVal.toFixed(2)}</td>
                        </tr>
                    `;
                }).join('');
            }

            lucide.createIcons();
        }

        // Fetch iniziale e polling continuo ogni 3 secondi
        fetchData();
        setInterval(fetchData, 3000);
    </script>
</body>
</html>
"""

async def handle_dashboard_page(request):
    """Serve la pagina HTML della dashboard."""
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")

async def handle_dashboard_api(request):
    """Restituisce il payload JSON completo in tempo reale per alimentare la dashboard."""
    global _bybit_service, _alpaca_service
    if not _bybit_service:
        _bybit_service = BybitExecutionService()
    if not _alpaca_service:
        _alpaca_service = AlpacaExecutionService()

    try:
        b_wallet = _bybit_service.get_wallet_summary()
        b_pos = _bybit_service.get_open_positions()
        try:
            b_closed_res = _bybit_service.session.get_closed_pnl(category="linear", limit=10)
            b_closed = b_closed_res.get("result", {}).get("list", [])
        except Exception:
            b_closed = []
        
        a_summary = _alpaca_service.get_account_summary()
        
        payload = {
            "status": "online",
            "timestamp": datetime.now(ZoneInfo("Europe/Rome")).isoformat(),
            "bybit": {
                "wallet": b_wallet,
                "positions": b_pos,
                "closed": b_closed
            },
            "alpaca": {
                "account": a_summary.get("account", {}),
                "positions": a_summary.get("positions", [])
            }
        }
        return web.json_response(payload)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

def create_web_app(bybit_svc=None, alpaca_svc=None):
    global _bybit_service, _alpaca_service
    if bybit_svc:
        _bybit_service = bybit_svc
    if alpaca_svc:
        _alpaca_service = alpaca_svc

    app = web.Application()
    app.router.add_get("/", handle_dashboard_page)
    app.router.add_get("/api/dashboard", handle_dashboard_api)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    return app
