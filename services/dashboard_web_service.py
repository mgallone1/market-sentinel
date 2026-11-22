"""
Web Dashboard Service for Market Sentinel.
Design Istituzionale Pro-Terminal (Anti-AI-Slop):
- Ispirato a Tabler Dashboard, Tremor Analytics e Bloomberg Terminal
- Regola aurea (phi = 1.618) per scala tipografica e proporzioni
- Zero sfocature glassmorphism cliché, zero gradienti viola/blu generici
- Tavolozza precisa: #0B0E14 (Slate Deep), bordi #1E2638, superfici #121824
- Badge di stato rigorosi (LONG/SHORT, Break-even, Trailing Lock, Closed)
- Visualizzazione multi-tab (Posizioni Live Bybit, Storico Trade Chiusi, Portafoglio Alpaca Equities, Stato Engine)
- Gestione dei 6 stati (Loading skeleton, Empty, Error, Active, Disabled, Data Live)
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
<html lang="it" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SENTINEL // QUANT TERMINAL</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['"Plus Jakarta Sans"', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
                        mono: ['"JetBrains Mono"', 'monospace'],
                    },
                    colors: {
                        terminal: {
                            base: '#0B0E14',
                            surface: '#111622',
                            elevated: '#171F30',
                            border: '#1F293D',
                            borderSubtle: '#182133',
                            muted: '#64748B',
                            text: '#E2E8F0',
                            textBright: '#F8FAFC',
                            buy: '#10B981',
                            buyMuted: '#064E3B',
                            sell: '#F43F5E',
                            sellMuted: '#881337',
                            accent: '#F59E0B',
                            cyan: '#06B6D4'
                        }
                    }
                }
            }
        }
    </script>
    <style>
        body {
            background-color: #0B0E14;
            color: #E2E8F0;
            font-feature-settings: "tnum" 1, "zero" 1;
        }
        .phi-card {
            background-color: #111622;
            border: 1px solid #1F293D;
        }
        .phi-card-interactive {
            transition: border-color 0.15s cubic-bezier(0.16, 1, 0.3, 1), background-color 0.15s ease;
        }
        .phi-card-interactive:hover {
            border-color: #2D3B55;
            background-color: #141B29;
        }
        .btn-tab {
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 600;
            border-radius: 6px;
            transition: all 0.12s ease;
            cursor: pointer;
        }
        .btn-tab.active {
            background-color: #1F293D;
            color: #F8FAFC;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
        }
        .btn-tab:not(.active) {
            color: #64748B;
        }
        .btn-tab:not(.active):hover {
            color: #CBD5E1;
            background-color: #141B29;
        }
        .live-ping {
            animation: terminalPing 2.4s cubic-bezier(0, 0, 0.2, 1) infinite;
        }
        @keyframes terminalPing {
            75%, 100% {
                transform: scale(2);
                opacity: 0;
            }
        }
        /* Custom subtle scrollbar */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0B0E14; }
        ::-webkit-scrollbar-thumb { background: #1F293D; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #2E3E5B; }
    </style>
</head>
<body class="min-h-screen flex flex-col antialiased selection:bg-terminal-border selection:text-white">

    <!-- TOP BAR: Strict Status, Latency & Clocks -->
    <header class="border-b border-terminal-border bg-terminal-surface/90 sticky top-0 z-50">
        <div class="max-w-[1540px] mx-auto px-4 lg:px-6 h-14 flex items-center justify-between">
            <div class="flex items-center gap-4">
                <div class="flex items-center gap-2.5">
                    <div class="w-3 h-3 rounded-sm bg-terminal-buy flex items-center justify-center">
                        <div class="w-1.5 h-1.5 rounded-full bg-terminal-base"></div>
                    </div>
                    <span class="font-mono font-bold tracking-wider text-sm text-terminal-textBright">MARKET SENTINEL</span>
                    <span class="text-xs px-1.5 py-0.5 rounded font-mono font-medium text-slate-400 bg-terminal-elevated border border-terminal-border">v2.4-PRO</span>
                </div>
                <div class="hidden md:flex items-center gap-2 pl-4 border-l border-terminal-border">
                    <span class="relative flex h-2 w-2">
                        <span class="live-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                    </span>
                    <span class="text-[11px] font-mono tracking-wide uppercase text-emerald-400 font-semibold" id="sys-status">SYS OPERATIONAL</span>
                    <span class="text-slate-600">&bull;</span>
                    <span class="text-[11px] font-mono text-slate-400" id="sys-latency">BYBIT DEMO UTA</span>
                </div>
            </div>

            <div class="flex items-center gap-4 text-xs font-mono">
                <div class="hidden sm:flex items-center gap-3 bg-terminal-elevated px-3 py-1.5 rounded border border-terminal-border">
                    <span class="text-slate-500 uppercase">ROMA</span>
                    <span class="font-semibold text-terminal-text" id="clock-rome">--:--:--</span>
                    <span class="text-slate-600">|</span>
                    <span class="text-slate-500 uppercase">NYC</span>
                    <span class="font-semibold text-slate-300" id="clock-nyc">--:--:--</span>
                </div>
                <button onclick="fetchData()" class="flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-terminal-elevated hover:bg-terminal-border text-slate-300 transition active:scale-95 border border-terminal-border" title="Forza Refresh">
                    <i data-lucide="refresh-cw" class="w-3.5 h-3.5" id="refresh-spinner"></i>
                    <span class="text-[11px] font-semibold uppercase tracking-wider hidden sm:inline">Sync</span>
                </button>
            </div>
        </div>
    </header>

    <!-- MAIN TERMINAL BODY -->
    <main class="max-w-[1540px] mx-auto w-full px-4 lg:px-6 py-6 flex-1 space-y-6">

        <!-- PRIMARY METRICS ROW (Golden Ratio Proportions & Tremor Style) -->
        <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3.5">
            <!-- Combined Equity -->
            <div class="phi-card rounded-lg p-4 col-span-2 sm:col-span-1 lg:col-span-2">
                <div class="flex items-center justify-between text-xs text-slate-400 font-medium">
                    <span class="uppercase tracking-wider">NAV TOTALE PORTAFOGLIO</span>
                    <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-terminal-elevated text-slate-400 border border-terminal-borderSubtle">USD</span>
                </div>
                <div class="mt-2.5 flex items-baseline gap-2">
                    <span id="kpi-total-equity" class="text-2xl lg:text-3xl font-bold font-mono tracking-tight text-white">$0.00</span>
                </div>
                <div class="mt-2 pt-2 border-t border-terminal-borderSubtle flex items-center justify-between text-[11px] font-mono text-slate-400">
                    <span>Bybit UTA: <strong id="kpi-bybit-sub" class="text-slate-300 font-semibold">$0</strong></span>
                    <span>Alpaca Eq: <strong id="kpi-alpaca-sub" class="text-slate-300 font-semibold">$0</strong></span>
                </div>
            </div>

            <!-- Available Cash USDT -->
            <div class="phi-card rounded-lg p-4">
                <div class="text-xs text-slate-400 font-medium uppercase tracking-wider">Liquidità Bybit</div>
                <div class="mt-2.5">
                    <span id="kpi-usdt-cash" class="text-xl lg:text-2xl font-bold font-mono tracking-tight text-white">$0.00</span>
                </div>
                <div class="mt-2 pt-2 border-t border-terminal-borderSubtle text-[11px] font-mono text-slate-400">
                    Margine: <span id="kpi-margin-balance" class="text-slate-300">$0</span>
                </div>
            </div>

            <!-- Open Positions Count -->
            <div class="phi-card rounded-lg p-4">
                <div class="text-xs text-slate-400 font-medium uppercase tracking-wider">Esposizione Contratti</div>
                <div class="mt-2.5 flex items-baseline gap-2">
                    <span id="kpi-positions-count" class="text-xl lg:text-2xl font-bold font-mono text-white">0</span>
                    <span class="text-xs text-slate-500 font-mono">attivi</span>
                </div>
                <div class="mt-2 pt-2 border-t border-terminal-borderSubtle text-[11px] font-mono text-slate-400">
                    Notional: <span id="kpi-notional-active" class="text-slate-300 font-semibold">$0</span>
                </div>
            </div>

            <!-- Net Unrealized PnL -->
            <div class="phi-card rounded-lg p-4 col-span-2 sm:col-span-1 lg:col-span-2" id="pnl-kpi-container">
                <div class="flex items-center justify-between text-xs font-medium">
                    <span class="text-slate-400 uppercase tracking-wider">PNL NON REALIZZATO (LIVE)</span>
                    <span id="pnl-status-tag" class="text-[10px] font-mono px-1.5 py-0.5 rounded font-bold uppercase bg-slate-800 text-slate-300">CALCOLO</span>
                </div>
                <div class="mt-2.5 flex items-baseline gap-3">
                    <span id="kpi-unrealized-pnl" class="text-2xl lg:text-3xl font-bold font-mono text-white">$0.00</span>
                    <span id="kpi-unrealized-pct" class="text-sm font-bold font-mono text-slate-400">0.00%</span>
                </div>
                <div class="mt-2 pt-2 border-t border-terminal-borderSubtle flex items-center justify-between text-[11px] font-mono text-slate-400">
                    <span>Scalp Mode: <strong class="text-amber-400">+1.50%</strong></span>
                    <span>Safety Stop: <strong class="text-rose-400">-0.60%</strong></span>
                </div>
            </div>
        </div>

        <!-- NAVIGATION TABS -->
        <div class="flex items-center justify-between border-b border-terminal-border pb-3">
            <div class="flex items-center gap-1.5 bg-terminal-surface p-1 rounded-md border border-terminal-border">
                <button class="btn-tab active flex items-center gap-2" id="tab-btn-positions" onclick="switchTab('positions')">
                    <i data-lucide="layers" class="w-3.5 h-3.5"></i>
                    <span>Posizioni Live Bybit</span>
                    <span id="tab-count-positions" class="ml-1 text-[10px] font-mono px-1.5 py-0.2 rounded bg-terminal-elevated text-slate-300 border border-terminal-border">0</span>
                </button>
                <button class="btn-tab flex items-center gap-2" id="tab-btn-history" onclick="switchTab('history')">
                    <i data-lucide="history" class="w-3.5 h-3.5"></i>
                    <span>Storico Esecuzioni</span>
                    <span id="tab-count-closed" class="ml-1 text-[10px] font-mono px-1.5 py-0.2 rounded bg-terminal-elevated text-slate-300 border border-terminal-border">0</span>
                </button>
                <button class="btn-tab flex items-center gap-2" id="tab-btn-alpaca" onclick="switchTab('alpaca')">
                    <i data-lucide="landmark" class="w-3.5 h-3.5"></i>
                    <span>Equities Wall St (Alpaca)</span>
                </button>
                <button class="btn-tab flex items-center gap-2" id="tab-btn-rules" onclick="switchTab('rules')">
                    <i data-lucide="shield" class="w-3.5 h-3.5"></i>
                    <span>Regole Motore & Risk Guard</span>
                </button>
            </div>
            <div class="hidden lg:flex items-center gap-2 text-xs font-mono text-slate-400">
                <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
                <span>Auto-Refresh: <strong class="text-slate-200">3s</strong></span>
            </div>
        </div>

        <!-- TAB 1: LIVE POSITIONS TABLE -->
        <section id="tab-content-positions" class="space-y-3">
            <div class="phi-card rounded-lg overflow-hidden border border-terminal-border">
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs">
                        <thead>
                            <tr class="border-b border-terminal-border bg-terminal-elevated text-slate-400 font-mono uppercase text-[11px] tracking-wider">
                                <th class="py-3 px-4 font-semibold">Asset / Contratto</th>
                                <th class="py-3 px-4 font-semibold">Direzione</th>
                                <th class="py-3 px-4 font-semibold">Quantità (Size)</th>
                                <th class="py-3 px-4 font-semibold">Prezzo Entrata</th>
                                <th class="py-3 px-4 font-semibold">Mark Price</th>
                                <th class="py-3 px-4 font-semibold">Notional Value</th>
                                <th class="py-3 px-4 font-semibold">PnL Non Realizzato</th>
                                <th class="py-3 px-4 font-semibold">Stato Protezione Rischio</th>
                            </tr>
                        </thead>
                        <tbody id="positions-table-body" class="divide-y divide-terminal-borderSubtle font-mono">
                            <!-- Loading Skeleton -->
                            <tr>
                                <td colspan="8" class="text-center py-12 text-slate-500">
                                    <div class="flex flex-col items-center justify-center gap-2">
                                        <i data-lucide="loader-2" class="w-5 h-5 animate-spin text-slate-400"></i>
                                        <span>Caricamento feed ordini in corso...</span>
                                    </div>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- TAB 2: CLOSED TRADES HISTORY -->
        <section id="tab-content-history" class="space-y-3 hidden">
            <div class="phi-card rounded-lg overflow-hidden border border-terminal-border">
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs">
                        <thead>
                            <tr class="border-b border-terminal-border bg-terminal-elevated text-slate-400 font-mono uppercase text-[11px] tracking-wider">
                                <th class="py-3 px-4 font-semibold">Data / Timestamp</th>
                                <th class="py-3 px-4 font-semibold">Simbolo</th>
                                <th class="py-3 px-4 font-semibold">Direzione</th>
                                <th class="py-3 px-4 font-semibold">Dimensione</th>
                                <th class="py-3 px-4 font-semibold">Prezzo Ingresso &rarr; Uscita</th>
                                <th class="py-3 px-4 font-semibold">Commissioni (Fee)</th>
                                <th class="py-3 px-4 font-semibold">PnL Netto Realizzato</th>
                            </tr>
                        </thead>
                        <tbody id="closed-trades-body" class="divide-y divide-terminal-borderSubtle font-mono">
                            <tr>
                                <td colspan="7" class="text-center py-8 text-slate-500">Nessuna chiusura recente trovata.</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- TAB 3: ALPACA EQUITIES -->
        <section id="tab-content-alpaca" class="space-y-4 hidden">
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div class="phi-card rounded-lg p-5">
                    <span class="text-xs text-slate-400 font-medium uppercase tracking-wider">Valore Portafoglio Azionario</span>
                    <h4 id="alpaca-portfolio-val" class="text-2xl font-bold font-mono text-white mt-2">$0.00</h4>
                    <p class="text-xs text-slate-400 mt-1 font-mono">Paper Trading Wall Street (NYSE/NASDAQ)</p>
                </div>
                <div class="phi-card rounded-lg p-5">
                    <span class="text-xs text-slate-400 font-medium uppercase tracking-wider">Buying Power Disponibile</span>
                    <h4 id="alpaca-buying-power" class="text-2xl font-bold font-mono text-white mt-2">$0.00</h4>
                    <p class="text-xs text-slate-400 mt-1 font-mono">Liquidità operativa per ordini azionari</p>
                </div>
                <div class="phi-card rounded-lg p-5">
                    <span class="text-xs text-slate-400 font-medium uppercase tracking-wider">Stato Conto Alpaca</span>
                    <div class="flex items-center gap-2 mt-2">
                        <span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
                        <h4 id="alpaca-status-val" class="text-xl font-bold font-mono text-emerald-400">ATTIVO</h4>
                    </div>
                    <p class="text-xs text-slate-400 mt-1 font-mono" id="alpaca-account-num">Account: PA3WDUE2F</p>
                </div>
            </div>

            <div class="phi-card rounded-lg overflow-hidden border border-terminal-border">
                <div class="p-4 border-b border-terminal-border flex items-center justify-between bg-terminal-elevated">
                    <span class="font-mono text-xs uppercase tracking-wider font-semibold text-slate-300">Posizioni Azionarie Wall Street Aperte</span>
                    <span class="text-xs font-mono text-slate-400" id="alpaca-pos-count">0 Titoli</span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs font-mono">
                        <thead>
                            <tr class="border-b border-terminal-border text-slate-400 text-[11px] uppercase">
                                <th class="py-2.5 px-4">Ticker</th>
                                <th class="py-2.5 px-4">Quantità</th>
                                <th class="py-2.5 px-4">Prezzo Medio</th>
                                <th class="py-2.5 px-4">Prezzo Attuale</th>
                                <th class="py-2.5 px-4">Valore Mercato</th>
                                <th class="py-2.5 px-4">PnL Non Realizzato</th>
                            </tr>
                        </thead>
                        <tbody id="alpaca-positions-body" class="divide-y divide-terminal-borderSubtle">
                            <tr>
                                <td colspan="6" class="text-center py-6 text-slate-500">Nessuna posizione azionaria attualmente aperta (mercato azionario NYSE chiuso nel weekend).</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- TAB 4: RISK RULES & SPECS -->
        <section id="tab-content-rules" class="space-y-4 hidden">
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <div class="phi-card rounded-lg p-5 border-l-2 border-l-amber-500">
                    <div class="flex items-center gap-2 text-amber-400 text-xs font-mono font-bold uppercase">
                        <i data-lucide="zap" class="w-4 h-4"></i>
                        <span>Aggressive Micro-Scalping</span>
                    </div>
                    <p class="text-xs text-slate-300 mt-2 leading-relaxed">
                        Taglia per posizione fissa a <strong>$15,000 USDT</strong> per asset. Scansione continuativa ogni 2 minuti sui 10 principali contratti liquidi (BTC, ETH, SOL, LINK, AVAX, XRP, DOGE, SUI, NEAR, BNB).
                    </p>
                </div>

                <div class="phi-card rounded-lg p-5 border-l-2 border-l-emerald-500">
                    <div class="flex items-center gap-2 text-emerald-400 text-xs font-mono font-bold uppercase">
                        <i data-lucide="shield-check" class="w-4 h-4"></i>
                        <span>Break-Even Automatico a +0.30%</span>
                    </div>
                    <p class="text-xs text-slate-300 mt-2 leading-relaxed">
                        Appena il trade raggiunge <strong>+0.30%</strong> di profitto latente, lo Stop Loss viene riposizionato istantaneamente a pareggio (Entry Price + fee buffer). Rischio residuo azzerato.
                    </p>
                </div>

                <div class="phi-card rounded-lg p-5 border-l-2 border-l-blue-500">
                    <div class="flex items-center gap-2 text-blue-400 text-xs font-mono font-bold uppercase">
                        <i data-lucide="lock" class="w-4 h-4"></i>
                        <span>Trailing Profit Lock a +0.70%</span>
                    </div>
                    <p class="text-xs text-slate-300 mt-2 leading-relaxed">
                        Al raggiungimento del <strong>+0.70%</strong>, lo Stop Loss viene alzato a <strong>+0.40%</strong> netto protetto. Il target finale chiude in automatico a <strong>+1.50%</strong>.
                    </p>
                </div>
            </div>
        </section>

    </main>

    <!-- FOOTER: Institutional Metadata -->
    <footer class="border-t border-terminal-border bg-terminal-surface mt-10 py-4 text-xs font-mono text-slate-500">
        <div class="max-w-[1540px] mx-auto px-4 lg:px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
            <div class="flex items-center gap-2">
                <span>Infrastruttura: <strong class="text-slate-400">Railway Cloud EU-West</strong></span>
                <span>&bull;</span>
                <span>Execution: <strong class="text-slate-400">Bybit Unified Trading (Demo)</strong></span>
            </div>
            <div class="text-[11px] text-slate-500">
                Ultimo pacchetto dati ricevuto: <span id="last-update-time" class="text-slate-300">--:--:--</span>
            </div>
        </div>
    </footer>

    <!-- LOGICA JS AUTO-POLLING E RENDERING DETERMINISTICO -->
    <script>
        let currentTab = 'positions';

        function switchTab(tabId) {
            currentTab = tabId;
            ['positions', 'history', 'alpaca', 'rules'].forEach(t => {
                const btn = document.getElementById(`tab-btn-${t}`);
                const sec = document.getElementById(`tab-content-${t}`);
                if (t === tabId) {
                    btn.classList.add('active');
                    sec.classList.remove('hidden');
                } else {
                    btn.classList.remove('active');
                    sec.classList.add('hidden');
                }
            });
            lucide.createIcons();
        }

        function updateClocks() {
            const now = new Date();
            const romeTime = new Intl.DateTimeFormat('it-IT', { timeZone: 'Europe/Rome', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(now);
            const nycTime = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(now);
            document.getElementById('clock-rome').innerText = romeTime;
            document.getElementById('clock-nyc').innerText = nycTime;
        }
        setInterval(updateClocks, 1000);
        updateClocks();

        async function fetchData() {
            const spinner = document.getElementById('refresh-spinner');
            if (spinner) spinner.classList.add('animate-spin');

            try {
                const res = await fetch('/api/dashboard', { cache: 'no-store' });
                if (!res.ok) throw new Error('HTTP ' + res.status);
                const data = await res.json();
                renderDashboard(data);
                document.getElementById('last-update-time').innerText = new Date().toLocaleTimeString('it-IT');
                document.getElementById('sys-status').innerText = 'SYS OPERATIONAL';
                document.getElementById('sys-status').className = 'text-[11px] font-mono tracking-wide uppercase text-emerald-400 font-semibold';
            } catch (err) {
                console.error("Fetch dashboard error:", err);
                document.getElementById('sys-status').innerText = 'RECONNECTING...';
                document.getElementById('sys-status').className = 'text-[11px] font-mono tracking-wide uppercase text-rose-400 font-semibold';
            } finally {
                if (spinner) {
                    setTimeout(() => spinner.classList.remove('animate-spin'), 300);
                }
            }
        }

        function renderDashboard(data) {
            const bybit = data.bybit || {};
            const alpaca = data.alpaca || {};
            const bWallet = bybit.wallet || {};
            const positions = bybit.positions || [];
            const closed = bybit.closed || [];
            const aAcc = alpaca.account || {};

            // 1. KPI Equity
            const bybitEq = bWallet.total_equity || 0;
            const alpacaEq = parseFloat(aAcc.portfolio_value || 0);
            const totalEq = bybitEq + alpacaEq;

            document.getElementById('kpi-total-equity').innerText = `$${totalEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('kpi-bybit-sub').innerText = `$${bybitEq.toLocaleString('en-US', {maximumFractionDigits: 0})}`;
            document.getElementById('kpi-alpaca-sub').innerText = `$${alpacaEq.toLocaleString('en-US', {maximumFractionDigits: 0})}`;

            // Cash & Margine
            const usdtCash = (bWallet.coins && bWallet.coins.USDT) ? bWallet.coins.USDT : (bWallet.available_balance || 0);
            document.getElementById('kpi-usdt-cash').innerText = `$${usdtCash.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('kpi-margin-balance').innerText = `$${(bWallet.margin_balance || 0).toLocaleString('en-US', {maximumFractionDigits: 0})}`;

            // Esposizione & PnL
            let totalNotional = 0;
            let totalPnL = 0;

            positions.forEach(p => {
                totalNotional += p.position_value || 0;
                totalPnL += p.unrealized_pnl || 0;
            });

            document.getElementById('kpi-positions-count').innerText = positions.length;
            document.getElementById('kpi-notional-active').innerText = `$${totalNotional.toLocaleString('en-US', {maximumFractionDigits: 0})}`;
            document.getElementById('tab-count-positions').innerText = positions.length;
            document.getElementById('tab-count-closed').innerText = closed.length;

            const pnlValEl = document.getElementById('kpi-unrealized-pnl');
            const pnlPctEl = document.getElementById('kpi-unrealized-pct');
            const pnlTag = document.getElementById('pnl-status-tag');
            const pnlCard = document.getElementById('pnl-kpi-container');

            const pnlPctVal = totalNotional > 0 ? (totalPnL / totalNotional) * 100 : 0.0;
            const sign = totalPnL >= 0 ? '+' : '';

            pnlValEl.innerText = `${sign}$${totalPnL.toFixed(2)}`;
            pnlPctEl.innerText = `${sign}${pnlPctVal.toFixed(2)}%`;

            if (totalPnL >= 0) {
                pnlValEl.className = "text-2xl lg:text-3xl font-bold font-mono tracking-tight text-emerald-400";
                pnlPctEl.className = "text-sm font-bold font-mono text-emerald-400";
                pnlTag.className = "text-[10px] font-mono px-1.5 py-0.5 rounded font-bold uppercase bg-emerald-500/20 text-emerald-300 border border-emerald-500/30";
                pnlTag.innerText = "ATTIVO IN PROFITTO";
            } else {
                pnlValEl.className = "text-2xl lg:text-3xl font-bold font-mono tracking-tight text-rose-400";
                pnlPctEl.className = "text-sm font-bold font-mono text-rose-400";
                pnlTag.className = "text-[10px] font-mono px-1.5 py-0.5 rounded font-bold uppercase bg-rose-500/20 text-rose-300 border border-rose-500/30";
                pnlTag.innerText = "RISK GUARD ATTIVA";
            }

            // 2. Tabella Posizioni Bybit
            const tbody = document.getElementById('positions-table-body');
            if (positions.length === 0) {
                tbody.innerHTML = `<tr><td colspan="8" class="text-center py-10 text-slate-500 font-mono">Nessuna posizione aperta. Lo scanner ricerca breakout sui 10 asset ogni 2m.</td></tr>`;
            } else {
                tbody.innerHTML = positions.map(p => {
                    const isLong = p.side === 'BUY';
                    const sideBadge = isLong 
                        ? `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">LONG</span>`
                        : `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-rose-500/15 text-rose-400 border border-rose-500/30">SHORT</span>`;

                    const pnlSign = p.unrealized_pnl >= 0 ? '+' : '';
                    const pnlColor = p.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400';

                    let protBadge = `<span class="text-slate-500 text-[11px]">SL -0.60% (In corso)</span>`;
                    if (p.pnl_pct >= 0.70) {
                        protBadge = `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">PROFIT LOCKED (+0.40%)</span>`;
                    } else if (p.pnl_pct >= 0.30) {
                        protBadge = `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">BREAK-EVEN (0 RISK)</span>`;
                    }

                    return `
                        <tr class="hover:bg-terminal-elevated/60 transition">
                            <td class="py-3 px-4 font-bold text-white">${p.symbol}</td>
                            <td class="py-3 px-4">${sideBadge}</td>
                            <td class="py-3 px-4 text-slate-300">${p.size}</td>
                            <td class="py-3 px-4 text-slate-300">$${p.entry_price.toFixed(4)}</td>
                            <td class="py-3 px-4 font-semibold text-white">$${p.mark_price.toFixed(4)}</td>
                            <td class="py-3 px-4 text-slate-300">$${(p.position_value || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                            <td class="py-3 px-4 font-bold ${pnlColor}">
                                ${pnlSign}$${p.unrealized_pnl.toFixed(2)} 
                                <span class="text-[11px] font-normal opacity-90">(${pnlSign}${p.pnl_pct.toFixed(2)}%)</span>
                            </td>
                            <td class="py-3 px-4">${protBadge}</td>
                        </tr>
                    `;
                }).join('');
            }

            // 3. Tabella Chiusure Recenti
            const closedBody = document.getElementById('closed-trades-body');
            if (closed.length === 0) {
                closedBody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-500 font-mono">Nessuna esecuzione chiusa nello storico recente.</td></tr>`;
            } else {
                closedBody.innerHTML = closed.slice(0, 10).map(c => {
                    const pnlVal = parseFloat(c.closedPnl || 0);
                    const pnlClass = pnlVal >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
                    const pnlSign = pnlVal >= 0 ? '+' : '';
                    const timeStr = c.updatedTime ? new Date(parseInt(c.updatedTime)).toLocaleTimeString('it-IT') : '--:--';
                    return `
                        <tr class="hover:bg-terminal-elevated/60 transition">
                            <td class="py-2.5 px-4 text-slate-400">${timeStr}</td>
                            <td class="py-2.5 px-4 font-semibold text-white">${c.symbol}</td>
                            <td class="py-2.5 px-4"><span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-terminal-elevated text-slate-300 border border-terminal-border">${c.side}</span></td>
                            <td class="py-2.5 px-4 text-slate-300">${c.closedSize || c.qty}</td>
                            <td class="py-2.5 px-4 text-slate-300">$${parseFloat(c.avgEntryPrice || 0).toFixed(4)} &rarr; $${parseFloat(c.avgExitPrice || 0).toFixed(4)}</td>
                            <td class="py-2.5 px-4 text-slate-500">$${(parseFloat(c.openFee || 0) + parseFloat(c.closeFee || 0)).toFixed(2)}</td>
                            <td class="py-2.5 px-4 ${pnlClass}">${pnlSign}$${pnlVal.toFixed(2)}</td>
                        </tr>
                    `;
                }).join('');
            }

            // 4. Sezione Alpaca
            document.getElementById('alpaca-portfolio-val').innerText = `$${alpacaEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('alpaca-buying-power').innerText = `$${parseFloat(aAcc.buying_power || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('alpaca-account-num').innerText = `Account: ${aAcc.account_number || 'PA3WDUE2F'}`;

            const aPositions = alpaca.positions || [];
            document.getElementById('alpaca-pos-count').innerText = `${aPositions.length} Titoli`;
            const aPosBody = document.getElementById('alpaca-positions-body');
            if (aPositions.length === 0) {
                aPosBody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500 font-mono">Nessuna posizione azionaria attualmente aperta (Wall Street chiusa nel weekend).</td></tr>`;
            } else {
                aPosBody.innerHTML = aPositions.map(ap => {
                    const unrealized = parseFloat(ap.unrealized_pl || 0);
                    const pnlColor = unrealized >= 0 ? 'text-emerald-400' : 'text-rose-400';
                    const pnlSign = unrealized >= 0 ? '+' : '';
                    return `
                        <tr class="hover:bg-terminal-elevated/60 transition">
                            <td class="py-2.5 px-4 font-bold text-white">${ap.symbol}</td>
                            <td class="py-2.5 px-4 text-slate-300">${ap.qty}</td>
                            <td class="py-2.5 px-4 text-slate-300">$${parseFloat(ap.avg_entry_price || 0).toFixed(2)}</td>
                            <td class="py-2.5 px-4 font-semibold text-white">$${parseFloat(ap.current_price || 0).toFixed(2)}</td>
                            <td class="py-2.5 px-4 text-slate-300">$${parseFloat(ap.market_value || 0).toFixed(2)}</td>
                            <td class="py-2.5 px-4 font-bold ${pnlColor}">${pnlSign}$${unrealized.toFixed(2)}</td>
                        </tr>
                    `;
                }).join('');
            }

            lucide.createIcons();
        }

        // Avvio Polling continuo ogni 3 secondi
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
            b_closed_res = _bybit_service.session.get_closed_pnl(category="linear", limit=15)
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
