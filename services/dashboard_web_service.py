"""
Web Dashboard Service for Market Sentinel.
Design: Native iPhone First & Desktop Pro Financial Terminal
- Ottimizzato al 100% per iPhone con Safe Area Insets (iOS Dynamic Island / Home Bar)
- Bottom Navigation Bar mobile-first con tap target di 48px
- Grafico Chart.js touch-responsive calibrato per viewport stretti (375px - 430px)
- Zero orizzontal scroll indesiderato, contrasti AAA su display OLED Retina
- Card compatte ad alta densità con badge di stato grandi e leggibili con il pollice
"""

import json
from aiohttp import web
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any

from services.bybit_execution_service import BybitExecutionService
from services.alpaca_execution_service import AlpacaExecutionService
from services.perf_metrics_tracker import perf_tracker

_bybit_service: BybitExecutionService = None
_alpaca_service: AlpacaExecutionService = None

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="it" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="theme-color" content="#080B11">
    <title>SENTINEL // DESK TRADING</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Roboto+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['"Inter"', '-apple-system', 'BlinkMacSystemFont', '"SF Pro Display"', 'Roboto', 'sans-serif'],
                        mono: ['"Roboto Mono"', 'ui-monospace', 'monospace'],
                    },
                    colors: {
                        desk: {
                            bg: '#080B11',
                            card: '#0F141F',
                            elevated: '#161D2C',
                            border: '#1F293D',
                            borderSubtle: '#172030',
                            textMuted: '#94A3B8',
                            textDim: '#64748B',
                            textMain: '#F1F5F9',
                            textBright: '#FFFFFF',
                            bybitTag: '#F59E0B',
                            alpacaTag: '#3B82F6',
                            long: '#10B981',
                            short: '#EF4444'
                        }
                    }
                }
            }
        }
    </script>
    <style>
        * {
            -webkit-tap-highlight-color: transparent;
            box-sizing: border-box;
        }
        body {
            background-color: #080B11;
            color: #F1F5F9;
            font-family: 'Inter', -apple-system, sans-serif;
            font-feature-settings: "cv02", "cv03", "cv04", "cv11", "tnum";
            padding-top: env(safe-area-inset-top, 0px);
            padding-bottom: calc(env(safe-area-inset-bottom, 20px) + 72px);
            overflow-x: hidden;
        }
        .mono-val {
            font-family: 'Roboto Mono', monospace;
            font-feature-settings: "tnum" 1, "zero" 1;
        }
        .desk-card {
            background-color: #0F141F;
            border: 1px solid #1F293D;
        }
        .touch-target {
            min-height: 48px;
            min-width: 48px;
            touch-action: manipulation;
        }
        /* Bottom bar for iOS */
        .bottom-nav {
            padding-bottom: env(safe-area-inset-bottom, 12px);
        }
        .bottom-nav-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            flex: 1;
            min-height: 52px;
            touch-action: manipulation;
            color: #64748B;
            transition: all 0.15s ease;
        }
        .bottom-nav-item.active {
            color: #10B981;
        }
        .bottom-nav-item.active i {
            transform: scale(1.1);
        }
        .bottom-nav-item.bybit-active.active {
            color: #F59E0B;
        }
        .bottom-nav-item.alpaca-active.active {
            color: #3B82F6;
        }
        /* Clean touch active state */
        .tap-press:active {
            transform: scale(0.97);
            opacity: 0.9;
        }
        .no-scrollbar::-webkit-scrollbar { display: none; }
        .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
    </style>
</head>
<body class="min-h-screen flex flex-col antialiased">

    <!-- IPHONE TOP STATUS & HEADER -->
    <header class="border-b border-desk-border bg-desk-card/95 sticky top-0 z-40 backdrop-blur-md">
        <div class="max-w-[1440px] mx-auto px-4 sm:px-6 h-14 sm:h-16 flex items-center justify-between">
            <div class="flex items-center gap-2.5">
                <div class="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                    <i data-lucide="shield-check" class="w-4 h-4"></i>
                </div>
                <div>
                    <div class="flex items-center gap-1.5">
                        <span class="font-bold text-sm sm:text-base text-white tracking-tight">MARKET SENTINEL</span>
                        <span class="text-[10px] font-mono px-1.5 py-0.2 rounded bg-desk-elevated border border-desk-border text-slate-300">PRO</span>
                    </div>
                    <div class="flex items-center gap-2 text-[10px] sm:text-xs text-slate-400 font-mono">
                        <span class="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        <span id="header-status">SYNC 3S</span>
                        <span class="text-slate-600">&bull;</span>
                        <span class="text-slate-400" id="clock-rome-header">--:--:--</span>
                    </div>
                </div>
            </div>

            <!-- Header Quick Stats & Manual Refresh -->
            <div class="flex items-center gap-2">
                <div class="text-right mr-1">
                    <span class="text-[10px] font-semibold uppercase text-slate-400 block leading-tight">NAV TOTALE</span>
                    <span id="header-nav-value" class="text-xs sm:text-sm font-bold mono-val text-white leading-tight">$0.00</span>
                </div>
                <button onclick="fetchData()" class="touch-target px-3 rounded-lg bg-desk-elevated hover:bg-slate-800 border border-desk-border text-slate-200 flex items-center justify-center transition tap-press text-xs font-semibold" title="Ricarica Dati">
                    <i data-lucide="refresh-cw" class="w-4 h-4" id="refresh-spinner"></i>
                </button>
            </div>
        </div>
    </header>

    <!-- MAIN CONTAINER -->
    <main class="max-w-[1440px] mx-auto w-full px-3.5 sm:px-6 py-3 sm:py-5 flex-1 space-y-4">

        <!-- IPHONE QUICK SUMMARY CARDS (2x2 Grid) -->
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-2.5 sm:gap-4">
            <!-- 1. Bybit Equity -->
            <div class="desk-card rounded-xl p-3.5 border-l-2 border-l-amber-500">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-1">
                        <span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span> BYBIT CRYPTO
                    </span>
                    <span class="text-[10px] font-mono text-slate-400">UTA</span>
                </div>
                <div id="summary-bybit-nav" class="text-lg sm:text-xl font-bold mono-val text-white mt-1">$0.00</div>
                <span class="text-[10px] text-slate-400 font-mono block mt-0.5" id="summary-bybit-cash">USDT: $0</span>
            </div>

            <!-- 2. Alpaca Equity -->
            <div class="desk-card rounded-xl p-3.5 border-l-2 border-l-blue-500">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-semibold uppercase tracking-wider text-blue-400 flex items-center gap-1">
                        <span class="w-1.5 h-1.5 rounded-full bg-blue-400"></span> ALPACA WALL ST
                    </span>
                    <span class="text-[10px] font-mono text-slate-400">NYSE</span>
                </div>
                <div id="summary-alpaca-nav" class="text-lg sm:text-xl font-bold mono-val text-white mt-1">$0.00</div>
                <span class="text-[10px] text-slate-400 font-mono block mt-0.5" id="summary-alpaca-bp">BP: $0</span>
            </div>

            <!-- 3. PnL Non Realizzato Live -->
            <div class="desk-card rounded-xl p-3.5 border-l-2 border-l-emerald-500">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-semibold uppercase tracking-wider text-slate-300">PNL NON REALIZZATO</span>
                    <span class="text-[10px] font-mono text-emerald-400 animate-pulse">LIVE</span>
                </div>
                <div id="summary-crypto-pnl" class="text-lg sm:text-xl font-bold mono-val text-emerald-400 mt-1">$0.00</div>
                <span class="text-[10px] text-slate-400 font-mono block mt-0.5" id="summary-active-positions">0 posizioni</span>
            </div>

            <!-- 4. PnL Realizzato Cumulativo -->
            <div class="desk-card rounded-xl p-3.5 border-l-2 border-l-purple-500">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-semibold uppercase tracking-wider text-slate-300">PNL REALIZZATO</span>
                    <span class="text-[10px] font-mono text-slate-400" id="metric-win-rate-top">WR 0%</span>
                </div>
                <div id="metric-cum-pnl" class="text-lg sm:text-xl font-bold mono-val text-white mt-1">$0.00</div>
                <span class="text-[10px] text-slate-400 font-mono block mt-0.5" id="metric-cum-volume-top">Vol: $0</span>
            </div>
        </div>

        <!-- ======================================================== -->
        <!-- SEZIONE GRAFICO IPHONE-FIRST (PERFORMANCE & VOLUME)       -->
        <!-- ======================================================== -->
        <div class="desk-card rounded-xl p-3.5 sm:p-5 space-y-3">
            <div class="flex items-center justify-between border-b border-desk-borderSubtle pb-2">
                <div class="flex items-center gap-2">
                    <i data-lucide="trending-up" class="w-4 h-4 text-emerald-400"></i>
                    <h2 class="text-xs sm:text-sm font-bold text-white tracking-tight uppercase">TRAIETTORIA EQUITY &amp; VOLUME</h2>
                </div>
                <div class="flex items-center gap-2 text-[10px] font-mono text-slate-400">
                    <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-emerald-400 inline-block"></span> Equity</span>
                    <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-amber-400 inline-block"></span> PnL</span>
                </div>
            </div>

            <!-- Canvas Responsive Ottimizzato per iPhone (Touch fluido senza blocco dello scroll) -->
            <div class="relative w-full h-52 sm:h-64">
                <canvas id="perfChart"></canvas>
            </div>

            <div class="grid grid-cols-3 gap-2 pt-1 border-t border-desk-borderSubtle text-center font-mono text-[11px]">
                <div class="bg-desk-elevated/80 py-1.5 px-1 rounded">
                    <span class="text-slate-400 text-[9px] uppercase block">Volume Scambiato</span>
                    <span id="metric-cum-volume" class="font-bold text-white">$120k</span>
                </div>
                <div class="bg-desk-elevated/80 py-1.5 px-1 rounded">
                    <span class="text-slate-400 text-[9px] uppercase block">Win Rate</span>
                    <span id="metric-win-rate" class="font-bold text-amber-400">--%</span>
                </div>
                <div class="bg-desk-elevated/80 py-1.5 px-1 rounded">
                    <span class="text-slate-400 text-[9px] uppercase block">Profit Factor</span>
                    <span id="metric-profit-factor" class="font-bold text-slate-200">--</span>
                </div>
            </div>
        </div>

        <!-- ======================================================== -->
        <!-- SELETTORE A SCHEDE DESKTOP (Nascosto su iPhone, usa bottom bar) -->
        <!-- ======================================================== -->
        <div class="hidden sm:flex bg-desk-card p-1.5 rounded-xl border border-desk-border items-center gap-1.5 overflow-x-auto no-scrollbar">
            <button id="desk-tab-btn-bybit" class="touch-target px-4 rounded-lg font-semibold text-xs flex items-center gap-2 active transition bg-desk-elevated text-white border border-desk-border" onclick="selectInstance('bybit')">
                <span class="w-2 h-2 rounded-full bg-amber-400"></span>
                <span>Bybit Futures (Crypto 24/7)</span>
                <span id="desk-badge-bybit-count" class="px-1.5 py-0.2 rounded text-[10px] font-mono bg-desk-card text-amber-300">0</span>
            </button>
            <button id="desk-tab-btn-alpaca" class="touch-target px-4 rounded-lg font-semibold text-xs flex items-center gap-2 transition text-slate-400 hover:text-white" onclick="selectInstance('alpaca')">
                <span class="w-2 h-2 rounded-full bg-blue-400"></span>
                <span>Alpaca (Wall Street Equities)</span>
                <span id="desk-badge-alpaca-count" class="px-1.5 py-0.2 rounded text-[10px] font-mono bg-desk-card text-blue-300">0</span>
            </button>
            <button id="desk-tab-btn-history" class="touch-target px-4 rounded-lg font-semibold text-xs flex items-center gap-2 transition text-slate-400 hover:text-white" onclick="selectInstance('history')">
                <i data-lucide="history" class="w-3.5 h-3.5"></i>
                <span>Storico Chiusi</span>
            </button>
            <button id="desk-tab-btn-rules" class="touch-target px-4 rounded-lg font-semibold text-xs flex items-center gap-2 transition text-slate-400 hover:text-white" onclick="selectInstance('rules')">
                <i data-lucide="shield" class="w-3.5 h-3.5"></i>
                <span>Regole Rischio</span>
            </button>
        </div>

        <!-- ========================================== -->
        <!-- ISTANZA 1: BYBIT CRYPTO FUTURES 24/7      -->
        <!-- ========================================== -->
        <section id="instance-bybit" class="space-y-3">
            
            <div class="flex items-center justify-between px-1 text-xs">
                <div class="flex items-center gap-1.5">
                    <span class="font-bold text-amber-400 uppercase text-[11px] sm:text-xs">POSIZIONI BYBIT ATTIVE</span>
                    <span class="text-slate-500">&bull;</span>
                    <span class="text-slate-300 font-mono text-[11px]" id="bybit-active-count-label">0 aperte</span>
                </div>
                <div class="text-slate-400 font-mono text-[10px] sm:text-[11px]">
                    TP: <strong class="text-emerald-400">+3.0%</strong> | SL: <strong class="text-rose-400">-1.2%</strong>
                </div>
            </div>

            <!-- IPHONE CARDS VIEW (PREDEFINITA E PERFETTA SUL TOUCHSCREEN) -->
            <div id="bybit-mobile-cards" class="space-y-2.5">
                <div class="text-center py-6 text-slate-400 desk-card rounded-xl p-4 text-xs font-mono">
                    Caricamento posizioni Bybit...
                </div>
            </div>

            <!-- TABELLA DESKTOP ESTESA -->
            <div class="hidden lg:block desk-card rounded-xl overflow-hidden border border-desk-border mt-3">
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs">
                        <thead>
                            <tr class="border-b border-desk-border bg-desk-elevated text-slate-300 font-semibold uppercase text-[11px] tracking-wider">
                                <th class="py-3 px-4">Contratto</th>
                                <th class="py-3 px-4">Lato</th>
                                <th class="py-3 px-4">Size</th>
                                <th class="py-3 px-4">Entrata</th>
                                <th class="py-3 px-4">Mark Price</th>
                                <th class="py-3 px-4">Controvalore</th>
                                <th class="py-3 px-4">PnL Non Realizzato</th>
                                <th class="py-3 px-4">Protezione Dinamica</th>
                            </tr>
                        </thead>
                        <tbody id="bybit-table-body" class="divide-y divide-desk-borderSubtle mono-val">
                            <tr>
                                <td colspan="8" class="text-center py-6 text-slate-400">Sincronizzazione Bybit...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- ========================================== -->
        <!-- ISTANZA 2: ALPACA EQUITIES WALL STREET    -->
        <!-- ========================================== -->
        <section id="instance-alpaca" class="space-y-3 hidden">
            <div class="flex items-center justify-between px-1 text-xs">
                <span class="font-bold text-blue-400 uppercase text-[11px] sm:text-xs">ALPACA WALL STREET EQUITIES</span>
                <span class="text-slate-400 font-mono text-[10px]">Orario: 15:30 - 22:00 CET</span>
            </div>

            <div class="grid grid-cols-2 gap-2 text-xs font-mono">
                <div class="desk-card rounded-xl p-3">
                    <span class="text-[10px] font-semibold uppercase text-slate-400 block">Valore Titoli</span>
                    <div id="alpaca-equity-display" class="text-base font-bold mono-val text-white mt-1">$0.00</div>
                </div>
                <div class="desk-card rounded-xl p-3">
                    <span class="text-[10px] font-semibold uppercase text-slate-400 block">Buying Power</span>
                    <div id="alpaca-bp-display" class="text-base font-bold mono-val text-white mt-1">$0.00</div>
                </div>
            </div>

            <div class="desk-card rounded-xl overflow-hidden border border-desk-border">
                <div class="p-3 bg-desk-elevated border-b border-desk-border flex items-center justify-between">
                    <span class="font-bold text-[11px] uppercase tracking-wider text-white">Posizioni Azionarie USA</span>
                    <span class="text-[10px] font-mono text-slate-400" id="alpaca-total-titles">0 Titoli</span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs font-mono">
                        <thead>
                            <tr class="border-b border-desk-border text-slate-400 text-[10px] uppercase">
                                <th class="py-2 px-3">Ticker</th>
                                <th class="py-2 px-3">Qty</th>
                                <th class="py-2 px-3">Prezzo Medio</th>
                                <th class="py-2 px-3">Prezzo Attuale</th>
                                <th class="py-2 px-3">Valore</th>
                                <th class="py-2 px-3">PnL</th>
                            </tr>
                        </thead>
                        <tbody id="alpaca-table-body" class="divide-y divide-desk-borderSubtle">
                            <tr>
                                <td colspan="6" class="text-center py-6 text-slate-400">
                                    Nessuna posizione aperta (Wall Street chiusa nel weekend).
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- ========================================== -->
        <!-- ISTANZA 3: STORICO CHIUSURE BYBIT         -->
        <!-- ========================================== -->
        <section id="instance-history" class="space-y-3 hidden">
            <div class="desk-card rounded-xl overflow-hidden border border-desk-border">
                <div class="p-3 bg-desk-elevated border-b border-desk-border flex items-center justify-between">
                    <span class="font-bold text-[11px] uppercase tracking-wider text-white">Ultime Esecuzioni Chiuse</span>
                    <span class="text-[10px] font-mono text-slate-400" id="history-total-count">0 trade</span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs font-mono">
                        <thead>
                            <tr class="border-b border-desk-border text-slate-300 text-[10px] uppercase bg-desk-card">
                                <th class="py-2 px-3">Ora</th>
                                <th class="py-2 px-3">Simbolo</th>
                                <th class="py-2 px-3">Lato</th>
                                <th class="py-2 px-3">Size</th>
                                <th class="py-2 px-3">Prezzo In &rarr; Out</th>
                                <th class="py-2 px-3">Fee</th>
                                <th class="py-2 px-3">PnL Netto</th>
                            </tr>
                        </thead>
                        <tbody id="history-table-body" class="divide-y divide-desk-borderSubtle">
                            <tr>
                                <td colspan="7" class="text-center py-6 text-slate-400">Caricamento storico...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- ========================================== -->
        <!-- ISTANZA 4: REGOLE RISCHIO & MOTORE         -->
        <!-- ========================================== -->
        <section id="instance-rules" class="space-y-3 hidden">
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                <div class="desk-card rounded-xl p-4 border-l-2 border-l-amber-500">
                    <div class="flex items-center gap-1.5 text-amber-400 font-bold text-xs uppercase">
                        <i data-lucide="zap" class="w-3.5 h-3.5"></i>
                        <span>Taglia $15k per Trade</span>
                    </div>
                    <p class="text-[11px] text-slate-300 mt-1.5 leading-relaxed">
                        Controvalore fisso calibrato di <strong>$15,000 USDT</strong> per asset con selezione rigorosa A+ (EMA 20/50 + RSI + Volume).
                    </p>
                </div>
                <div class="desk-card rounded-xl p-4 border-l-2 border-l-emerald-500">
                    <div class="flex items-center gap-1.5 text-emerald-400 font-bold text-xs uppercase">
                        <i data-lucide="shield-check" class="w-3.5 h-3.5"></i>
                        <span>Break-Even a +0.60%</span>
                    </div>
                    <p class="text-[11px] text-slate-300 mt-1.5 leading-relaxed">
                        A <strong>+0.60%</strong> di profitto latente lo Stop Loss passa istantaneamente a pareggio con cuscinetto fee coperto.
                    </p>
                </div>
                <div class="desk-card rounded-xl p-4 border-l-2 border-l-blue-500">
                    <div class="flex items-center gap-1.5 text-blue-400 font-bold text-xs uppercase">
                        <i data-lucide="lock" class="w-3.5 h-3.5"></i>
                        <span>Profit Lock a +1.20%</span>
                    </div>
                    <p class="text-[11px] text-slate-300 mt-1.5 leading-relaxed">
                        Al <strong>+1.20%</strong> scatta il blocco del <strong>+0.70% netto in cassa</strong> con target a <strong>+3.00%</strong>.
                    </p>
                </div>
            </div>
        </section>

    </main>

    <!-- ======================================================== -->
    <!-- IPHONE NATIVE BOTTOM TAB BAR (Pinnata sul fondo dello schermo) -->
    <!-- ======================================================== -->
    <nav class="sm:hidden fixed bottom-0 left-0 right-0 z-50 bg-desk-card/98 border-t border-desk-border backdrop-blur-lg bottom-nav">
        <div class="flex items-center justify-around px-2 pt-1.5">
            <button id="nav-btn-bybit" class="bottom-nav-item bybit-active active tap-press" onclick="selectInstance('bybit')">
                <i data-lucide="bitcoin" class="w-5 h-5 mb-0.5"></i>
                <span class="text-[10px] font-semibold tracking-tight">Bybit Crypto</span>
            </button>
            <button id="nav-btn-alpaca" class="bottom-nav-item alpaca-active tap-press" onclick="selectInstance('alpaca')">
                <i data-lucide="landmark" class="w-5 h-5 mb-0.5"></i>
                <span class="text-[10px] font-semibold tracking-tight">Alpaca USA</span>
            </button>
            <button id="nav-btn-history" class="bottom-nav-item tap-press" onclick="selectInstance('history')">
                <i data-lucide="history" class="w-5 h-5 mb-0.5"></i>
                <span class="text-[10px] font-semibold tracking-tight">Storico</span>
            </button>
            <button id="nav-btn-rules" class="bottom-nav-item tap-press" onclick="selectInstance('rules')">
                <i data-lucide="shield" class="w-5 h-5 mb-0.5"></i>
                <span class="text-[10px] font-semibold tracking-tight">Regole</span>
            </button>
        </div>
    </nav>

    <!-- SCRIPT LOGICO & ENGINE GRAFICO CHART.JS -->
    <script>
        let activeTab = 'bybit';
        let perfChartInstance = null;

        function selectInstance(tabId) {
            activeTab = tabId;
            const tabs = ['bybit', 'alpaca', 'history', 'rules'];
            
            // Aggiorna sezioni visibili
            tabs.forEach(t => {
                const sec = document.getElementById(`instance-${t}`);
                if (sec) {
                    if (t === tabId) sec.classList.remove('hidden');
                    else sec.classList.add('hidden');
                }
            });

            // Aggiorna Bottom Nav iPhone
            tabs.forEach(t => {
                const navBtn = document.getElementById(`nav-btn-${t}`);
                if (navBtn) {
                    if (t === tabId) navBtn.classList.add('active');
                    else navBtn.classList.remove('active');
                }
            });

            // Aggiorna Desktop Tabs
            tabs.forEach(t => {
                const dBtn = document.getElementById(`desk-tab-btn-${t}`);
                if (dBtn) {
                    if (t === tabId) {
                        dBtn.className = "touch-target px-4 rounded-lg font-semibold text-xs flex items-center gap-2 active transition bg-desk-elevated text-white border border-desk-border";
                    } else {
                        dBtn.className = "touch-target px-4 rounded-lg font-semibold text-xs flex items-center gap-2 transition text-slate-400 hover:text-white";
                    }
                }
            });

            lucide.createIcons();
        }

        function updateClocks() {
            const now = new Date();
            const rome = new Intl.DateTimeFormat('it-IT', { timeZone: 'Europe/Rome', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(now);
            const rEl = document.getElementById('clock-rome-header');
            if (rEl) rEl.innerText = rome;
        }
        setInterval(updateClocks, 1000);
        updateClocks();

        function initChart(snapshots) {
            const ctx = document.getElementById('perfChart').getContext('2d');
            
            const labels = snapshots.map(s => {
                const d = new Date(s.epoch * 1000);
                return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
            });
            const equityData = snapshots.map(s => s.total_equity);
            const pnlData = snapshots.map(s => s.cumulative_realized_pnl);
            const volData = snapshots.map(s => s.cumulative_volume_usd);

            if (perfChartInstance) {
                perfChartInstance.data.labels = labels;
                perfChartInstance.data.datasets[0].data = equityData;
                perfChartInstance.data.datasets[1].data = pnlData;
                perfChartInstance.data.datasets[2].data = volData;
                perfChartInstance.update('none');
                return;
            }

            perfChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Equity Portafoglio ($)',
                            data: equityData,
                            borderColor: '#10B981',
                            backgroundColor: 'rgba(16, 185, 129, 0.08)',
                            borderWidth: 2,
                            yAxisID: 'yEquity',
                            fill: true,
                            tension: 0.25,
                            pointRadius: 2,
                            pointBackgroundColor: '#10B981'
                        },
                        {
                            label: 'PnL Realizzato ($)',
                            data: pnlData,
                            borderColor: '#F59E0B',
                            backgroundColor: 'transparent',
                            borderWidth: 1.8,
                            borderDash: [3, 3],
                            yAxisID: 'yPnL',
                            tension: 0.2,
                            pointRadius: 1.5,
                            pointBackgroundColor: '#F59E0B'
                        },
                        {
                            type: 'bar',
                            label: 'Volume ($)',
                            data: volData,
                            backgroundColor: 'rgba(59, 130, 246, 0.20)',
                            borderWidth: 0,
                            yAxisID: 'yVolume',
                            barPercentage: 0.35
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: '#0F141F',
                            titleColor: '#F8FAFC',
                            bodyColor: '#CBD5E1',
                            borderColor: '#1F293D',
                            borderWidth: 1,
                            titleFont: { family: 'Roboto Mono', size: 11 },
                            bodyFont: { family: 'Roboto Mono', size: 10 },
                            padding: 8,
                            callbacks: {
                                label: function(context) {
                                    let label = context.dataset.label || '';
                                    if (label) label += ': ';
                                    if (context.parsed.y !== null) {
                                        label += '$' + context.parsed.y.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
                                    }
                                    return label;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(31, 41, 61, 0.3)' },
                            ticks: { color: '#64748B', font: { family: 'Roboto Mono', size: 9 }, maxTicksLimit: 6 }
                        },
                        yEquity: {
                            type: 'linear',
                            position: 'left',
                            grid: { color: 'rgba(31, 41, 61, 0.4)' },
                            ticks: {
                                color: '#10B981',
                                font: { family: 'Roboto Mono', size: 9 },
                                callback: val => '$' + (val / 1000).toFixed(1) + 'k'
                            }
                        },
                        yPnL: {
                            type: 'linear',
                            position: 'right',
                            grid: { drawOnChartArea: false },
                            ticks: {
                                color: '#F59E0B',
                                font: { family: 'Roboto Mono', size: 9 },
                                callback: val => '$' + val.toFixed(0)
                            }
                        },
                        yVolume: {
                            type: 'linear',
                            position: 'right',
                            display: false
                        }
                    }
                }
            });
        }

        async function fetchData() {
            const spinner = document.getElementById('refresh-spinner');
            if (spinner) spinner.classList.add('animate-spin');

            try {
                const res = await fetch('/api/dashboard', { cache: 'no-store' });
                if (!res.ok) throw new Error('HTTP ' + res.status);
                const data = await res.json();
                renderUI(data);
                
                const hStatus = document.getElementById('header-status');
                if (hStatus) {
                    hStatus.innerText = 'SYNC 3S';
                    hStatus.className = 'text-emerald-400';
                }
            } catch (err) {
                console.error("Fetch error:", err);
                const hStatus = document.getElementById('header-status');
                if (hStatus) {
                    hStatus.innerText = 'RECONNECT...';
                    hStatus.className = 'text-rose-400';
                }
            } finally {
                if (spinner) {
                    setTimeout(() => spinner.classList.remove('animate-spin'), 300);
                }
            }
        }

        function renderUI(data) {
            const bybit = data.bybit || {};
            const alpaca = data.alpaca || {};
            const bWallet = bybit.wallet || {};
            const bPositions = bybit.positions || [];
            const bClosed = bybit.closed || [];
            const aAcc = alpaca.account || {};
            const aPositions = alpaca.positions || [];
            const perfHistory = data.perf_history || [];

            // 1. Summary Strip Superiore
            const bybitEq = bWallet.total_equity || 0;
            const alpacaEq = parseFloat(aAcc.portfolio_value || 0);
            const totalEq = bybitEq + alpacaEq;

            document.getElementById('header-nav-value').innerText = `$${(totalEq/1000).toFixed(1)}k`;
            document.getElementById('summary-bybit-nav').innerText = `$${bybitEq.toLocaleString('en-US', {minimumFractionDigits: 1, maximumFractionDigits: 1})}`;
            
            const usdtCash = (bWallet.coins && bWallet.coins.USDT) ? bWallet.coins.USDT : (bWallet.available_balance || 0);
            document.getElementById('summary-bybit-cash').innerText = `USDT: $${usdtCash.toLocaleString('en-US', {maximumFractionDigits: 0})}`;

            document.getElementById('summary-alpaca-nav').innerText = `$${alpacaEq.toLocaleString('en-US', {minimumFractionDigits: 1, maximumFractionDigits: 1})}`;
            document.getElementById('summary-alpaca-bp').innerText = `BP: $${parseFloat(aAcc.buying_power || 0).toLocaleString('en-US', {maximumFractionDigits: 0})}`;

            // PnL Calcolo Posizioni Bybit
            let totalNotional = 0;
            let totalPnL = 0;
            bPositions.forEach(p => {
                totalNotional += p.position_value || 0;
                totalPnL += p.unrealized_pnl || 0;
            });

            const pnlSign = totalPnL >= 0 ? '+' : '';
            const pnlColor = totalPnL >= 0 ? 'text-emerald-400' : 'text-rose-400';
            const sumPnlEl = document.getElementById('summary-crypto-pnl');
            sumPnlEl.innerText = `${pnlSign}$${totalPnL.toFixed(1)}`;
            sumPnlEl.className = `text-lg sm:text-xl font-bold mono-val ${pnlColor} mt-1`;

            document.getElementById('summary-active-positions').innerText = `${bPositions.length} contratti ($${(totalNotional/1000).toFixed(0)}k)`;
            document.getElementById('bybit-active-count-label').innerText = `${bPositions.length} a mercato`;

            // Badges Tab
            const bBadge = document.getElementById('desk-badge-bybit-count');
            if (bBadge) bBadge.innerText = bPositions.length;
            const aBadge = document.getElementById('desk-badge-alpaca-count');
            if (aBadge) aBadge.innerText = aPositions.length;

            // 2. Metriche Cumulative di Trading & Grafico
            let cumVol = 0;
            let cumRealized = 0;
            let wins = 0;
            let totalTrades = bClosed.length;
            let grossProfit = 0;
            let grossLoss = 0;

            bClosed.forEach(c => {
                const pVal = parseFloat(c.closedPnl || 0);
                cumRealized += pVal;
                cumVol += (parseFloat(c.cumExitValue || 0) + parseFloat(c.cumEntryValue || 0));
                if (pVal > 0) {
                    wins++;
                    grossProfit += pVal;
                } else {
                    grossLoss += Math.abs(pVal);
                }
            });

            const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0.0;
            const profitFactor = grossLoss > 0 ? (grossProfit / grossLoss) : (grossProfit > 0 ? 99.9 : 0.0);

            document.getElementById('metric-cum-volume').innerText = `$${(cumVol/1000).toFixed(0)}k`;
            document.getElementById('metric-cum-volume-top').innerText = `Vol: $${(cumVol/1000).toFixed(0)}k`;
            
            const crEl = document.getElementById('metric-cum-pnl');
            crEl.innerText = `${cumRealized >= 0 ? '+' : ''}$${cumRealized.toFixed(1)}`;
            crEl.className = `text-lg sm:text-xl font-bold mono-val ${cumRealized >= 0 ? 'text-emerald-400' : 'text-rose-400'} mt-1`;

            document.getElementById('metric-win-rate').innerText = `${winRate.toFixed(0)}%`;
            document.getElementById('metric-win-rate-top').innerText = `WR ${winRate.toFixed(0)}%`;
            document.getElementById('metric-profit-factor').innerText = profitFactor.toFixed(2);

            // Inizializza / Aggiorna Chart.js
            if (perfHistory.length > 0) {
                initChart(perfHistory);
            }

            // 3. Render Bybit Desktop Table
            const bTable = document.getElementById('bybit-table-body');
            if (bTable) {
                if (bPositions.length === 0) {
                    bTable.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-slate-400">Nessuna posizione aperta. Lo scanner ricerca confluenza A+ ogni 2m.</td></tr>`;
                } else {
                    bTable.innerHTML = bPositions.map(p => {
                        const isLong = p.side === 'BUY';
                        const sideBadge = isLong 
                            ? `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">LONG</span>`
                            : `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">SHORT</span>`;

                        const pSign = p.unrealized_pnl >= 0 ? '+' : '';
                        const pCol = p.unrealized_pnl >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';

                        let protBadge = `<span class="text-slate-400 text-xs">SL -1.20%</span>`;
                        if (p.pnl_pct >= 1.20) {
                            protBadge = `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">PROFIT LOCKED (+0.70%)</span>`;
                        } else if (p.pnl_pct >= 0.60) {
                            protBadge = `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">BREAK-EVEN (0 RISK)</span>`;
                        }

                        return `
                            <tr class="hover:bg-desk-elevated/70 transition">
                                <td class="py-3 px-4 font-bold text-white">${p.symbol}</td>
                                <td class="py-3 px-4">${sideBadge}</td>
                                <td class="py-3 px-4 text-slate-200">${p.size}</td>
                                <td class="py-3 px-4 text-slate-300">$${p.entry_price.toFixed(4)}</td>
                                <td class="py-3 px-4 font-bold text-white">$${p.mark_price.toFixed(4)}</td>
                                <td class="py-3 px-4 text-slate-300">$${(p.position_value || 0).toLocaleString('en-US', {minimumFractionDigits: 1, maximumFractionDigits: 1})}</td>
                                <td class="py-3 px-4 ${pCol}">
                                    ${pSign}$${p.unrealized_pnl.toFixed(2)} 
                                    <span class="text-[11px] font-medium opacity-90">(${pSign}${p.pnl_pct.toFixed(2)}%)</span>
                                </td>
                                <td class="py-3 px-4">${protBadge}</td>
                            </tr>
                        `;
                    }).join('');
                }
            }

            // 4. Render Bybit Mobile Cards (100% Usabilità iPhone)
            const bCards = document.getElementById('bybit-mobile-cards');
            if (bPositions.length === 0) {
                bCards.innerHTML = `<div class="desk-card rounded-xl p-5 text-center text-slate-400 text-xs font-mono">Nessuna posizione aperta. Motore A+ in ascolto sui breakout.</div>`;
            } else {
                bCards.innerHTML = bPositions.map(p => {
                    const isLong = p.side === 'BUY';
                    const sideBadge = isLong 
                        ? `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">LONG</span>`
                        : `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">SHORT</span>`;

                    const pSign = p.unrealized_pnl >= 0 ? '+' : '';
                    const pCol = p.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400';

                    let protBadge = `<span class="text-slate-400 text-[10px]">SL -1.20%</span>`;
                    if (p.pnl_pct >= 1.20) {
                        protBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">LOCK +0.70%</span>`;
                    } else if (p.pnl_pct >= 0.60) {
                        protBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">BREAK-EVEN (0)</span>`;
                    }

                    return `
                        <div class="desk-card rounded-xl p-3.5 space-y-2.5">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-2">
                                    <span class="text-sm font-bold text-white mono-val">${p.symbol}</span>
                                    ${sideBadge}
                                </div>
                                <div class="text-right">
                                    <div class="text-sm font-bold mono-val ${pCol}">
                                        ${pSign}$${p.unrealized_pnl.toFixed(2)}
                                        <span class="text-[11px] font-semibold">(${pSign}${p.pnl_pct.toFixed(2)}%)</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="grid grid-cols-2 gap-2 text-xs font-mono pt-2 border-t border-desk-borderSubtle">
                                <div>
                                    <span class="text-slate-400 text-[9px] uppercase block">Entrata &rarr; Attuale</span>
                                    <span class="text-slate-200 font-semibold">$${p.entry_price.toFixed(4)} &rarr; $${p.mark_price.toFixed(4)}</span>
                                </div>
                                <div class="text-right">
                                    <span class="text-slate-400 text-[9px] uppercase block">Controvalore</span>
                                    <span class="text-slate-200 font-semibold">$${(p.position_value || 0).toLocaleString('en-US', {maximumFractionDigits: 0})}</span>
                                </div>
                            </div>

                            <div class="pt-1.5 border-t border-desk-borderSubtle flex items-center justify-between text-xs font-mono">
                                <span class="text-slate-400 text-[10px]">Stato Rischio:</span>
                                ${protBadge}
                            </div>
                        </div>
                    `;
                }).join('');
            }

            // 5. Render Alpaca Box & Table
            document.getElementById('alpaca-equity-display').innerText = `$${alpacaEq.toLocaleString('en-US', {minimumFractionDigits: 1, maximumFractionDigits: 1})}`;
            document.getElementById('alpaca-bp-display').innerText = `$${parseFloat(aAcc.buying_power || 0).toLocaleString('en-US', {minimumFractionDigits: 1, maximumFractionDigits: 1})}`;
            document.getElementById('alpaca-total-titles').innerText = `${aPositions.length} Titoli`;

            const alpacaBody = document.getElementById('alpaca-table-body');
            if (aPositions.length === 0) {
                alpacaBody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-400">Nessuna posizione aperta (Wall Street chiusa nel weekend).</td></tr>`;
            } else {
                alpacaBody.innerHTML = aPositions.map(ap => {
                    const unpnl = parseFloat(ap.unrealized_pl || 0);
                    const col = unpnl >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
                    const sign = unpnl >= 0 ? '+' : '';
                    return `
                        <tr class="hover:bg-desk-elevated/70 transition">
                            <td class="py-2 px-3 font-bold text-white">${ap.symbol}</td>
                            <td class="py-2 px-3 text-slate-200">${ap.qty}</td>
                            <td class="py-2 px-3 text-slate-300">$${parseFloat(ap.avg_entry_price || 0).toFixed(2)}</td>
                            <td class="py-2 px-3 font-bold text-white">$${parseFloat(ap.current_price || 0).toFixed(2)}</td>
                            <td class="py-2 px-3 text-slate-200">$${parseFloat(ap.market_value || 0).toFixed(2)}</td>
                            <td class="py-2 px-3 ${col}">${sign}$${unpnl.toFixed(2)}</td>
                        </tr>
                    `;
                }).join('');
            }

            // 6. Render Storico Chiusure
            document.getElementById('history-total-count').innerText = `${bClosed.length} registrati`;
            const hBody = document.getElementById('history-table-body');
            if (bClosed.length === 0) {
                hBody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400">Nessun trade chiuso di recente.</td></tr>`;
            } else {
                hBody.innerHTML = bClosed.slice(0, 15).map(c => {
                    const pnlVal = parseFloat(c.closedPnl || 0);
                    const pCol = pnlVal >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
                    const pSign = pnlVal >= 0 ? '+' : '';
                    const timeStr = c.updatedTime ? new Date(parseInt(c.updatedTime)).toLocaleTimeString('it-IT') : '--:--';
                    return `
                        <tr class="hover:bg-desk-elevated/70 transition">
                            <td class="py-2 px-3 text-slate-400">${timeStr}</td>
                            <td class="py-2 px-3 font-bold text-white">${c.symbol}</td>
                            <td class="py-2 px-3"><span class="px-1 py-0.2 rounded text-[9px] font-semibold bg-desk-elevated text-slate-300 border border-desk-border">${c.side}</span></td>
                            <td class="py-2 px-3 text-slate-300">${c.closedSize || c.qty}</td>
                            <td class="py-2 px-3 text-slate-300">$${parseFloat(c.avgEntryPrice || 0).toFixed(4)} &rarr; $${parseFloat(c.avgExitPrice || 0).toFixed(4)}</td>
                            <td class="py-2 px-3 text-slate-400">$${(parseFloat(c.openFee || 0) + parseFloat(c.closeFee || 0)).toFixed(2)}</td>
                            <td class="py-2 px-3 ${pCol}">${pSign}$${pnlVal.toFixed(2)}</td>
                        </tr>
                    `;
                }).join('');
            }

            lucide.createIcons();
        }

        // Fetch iniziale e loop continuo ogni 3 secondi
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
            b_closed_res = _bybit_service.session.get_closed_pnl(category="linear", limit=25)
            b_closed = b_closed_res.get("result", {}).get("list", [])
        except Exception:
            b_closed = []
        
        a_summary = _alpaca_service.get_account_summary()

        try:
            b_eq = float(b_wallet.get("total_equity", 0.0) or 0.0)
            a_eq = float(a_summary.get("account", {}).get("portfolio_value", 0.0) or 0.0)
            tot_eq = b_eq + a_eq
            unreal_pnl = sum(p.get("unrealized_pnl", 0.0) for p in b_pos)
            cum_real = sum(float(c.get("closedPnl", 0.0)) for c in b_closed)
            cum_vol = sum(float(c.get("cumExitValue", 0.0)) + float(c.get("cumEntryValue", 0.0)) for c in b_closed)
            
            perf_tracker.record_snapshot(
                total_equity=tot_eq,
                bybit_equity=b_eq,
                alpaca_equity=a_eq,
                unrealized_pnl=unreal_pnl,
                cumulative_realized=cum_real,
                cumulative_volume=cum_vol,
                positions_count=len(b_pos)
            )
        except Exception as e_snap:
            print(f"[!] Errore registrazione snapshot: {e_snap}")

        history = perf_tracker.get_history(limit=60)
        
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
            },
            "perf_history": history
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
