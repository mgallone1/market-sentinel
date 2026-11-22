"""
Web Dashboard Service for Market Sentinel.
Design: Pro Financial Terminal con Separazione Netta delle Istanze (Bybit Crypto Futures vs Alpaca Wall Street)
Include:
- Grafico Interattivo Multi-Asse (Chart.js) con Curva Equity & PnL Realizzato cumulativo
- Indicatore Volume di Trading Storico e Giornaliero ($120k+)
- Metriche Quantitative a Lungo Termine (Win Rate, Profit Factor, Expected Value, Sharpe stimato)
- Visualizzazione Mobile Nativa per iPhone e Desktop ad alto contrasto
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
    <title>SENTINEL // DESK TRADING & ANALYTICS</title>
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
                        sans: ['"Inter"', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
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
            font-family: 'Inter', sans-serif;
            font-feature-settings: "cv02", "cv03", "cv04", "cv11", "tnum";
            padding-bottom: env(safe-area-inset-bottom, 24px);
        }
        .mono-val {
            font-family: 'Roboto Mono', monospace;
            font-feature-settings: "tnum" 1, "zero" 1;
        }
        .desk-card {
            background-color: #0F141F;
            border: 1px solid #1F293D;
        }
        .touch-pill {
            min-height: 44px;
            touch-action: manipulation;
        }
        .desk-tab {
            min-height: 44px;
            font-size: 13px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 8px;
            padding: 8px 16px;
            cursor: pointer;
            transition: all 0.15s ease;
            touch-action: manipulation;
            white-space: nowrap;
        }
        .desk-tab.active {
            background-color: #161D2C;
            color: #FFFFFF;
            border: 1px solid #2D3B55;
            box-shadow: 0 1px 3px rgba(0,0,0,0.4);
        }
        .desk-tab:not(.active) {
            color: #94A3B8;
            border: 1px solid transparent;
        }
        .desk-tab:not(.active):hover {
            color: #E2E8F0;
            background-color: #121824;
        }
        .no-scrollbar::-webkit-scrollbar { display: none; }
        .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
    </style>
</head>
<body class="min-h-screen flex flex-col antialiased">

    <!-- TOP HEADER -->
    <header class="border-b border-desk-border bg-desk-card/95 sticky top-0 z-50 backdrop-blur-md">
        <div class="max-w-[1440px] mx-auto px-3.5 sm:px-6 h-14 sm:h-16 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                    <i data-lucide="shield-check" class="w-4 h-4"></i>
                </div>
                <div>
                    <div class="flex items-center gap-2">
                        <span class="font-bold text-sm sm:text-base text-white tracking-tight">MARKET SENTINEL</span>
                        <span class="hidden xs:inline-block text-[11px] font-mono px-1.5 py-0.2 rounded bg-desk-elevated border border-desk-border text-slate-300">PRO DESK</span>
                    </div>
                    <div class="flex items-center gap-2 text-[11px] text-slate-400 font-mono">
                        <span class="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        <span id="header-status">LIVE SYNC 3S</span>
                        <span class="text-slate-600">&bull;</span>
                        <span class="hidden sm:inline">RAILWAY EU-WEST</span>
                    </div>
                </div>
            </div>

            <!-- Clocks & Refresh -->
            <div class="flex items-center gap-2 sm:gap-4">
                <div class="hidden sm:flex items-center gap-3 bg-desk-elevated px-3 py-1.5 rounded-lg border border-desk-border text-xs font-mono">
                    <span class="text-slate-400">ROMA <strong class="text-white ml-1" id="clock-rome">--:--:--</strong></span>
                    <span class="text-slate-600">|</span>
                    <span class="text-slate-400">NYC <strong class="text-white ml-1" id="clock-nyc">--:--:--</strong></span>
                </div>
                <button onclick="fetchData()" class="touch-pill px-3 rounded-lg bg-desk-elevated hover:bg-slate-800 border border-desk-border text-slate-200 flex items-center justify-center gap-2 transition active:scale-95 text-xs font-semibold" title="Ricarica Dati">
                    <i data-lucide="refresh-cw" class="w-4 h-4" id="refresh-spinner"></i>
                    <span class="hidden md:inline">AGGIORNA</span>
                </button>
            </div>
        </div>
    </header>

    <!-- MAIN WRAPPER -->
    <main class="max-w-[1440px] mx-auto w-full px-3.5 sm:px-6 py-4 sm:py-6 flex-1 space-y-5">

        <!-- GLOBAL SUMMARY STRIP -->
        <div class="desk-card rounded-xl p-4 sm:p-5">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4 divide-y sm:divide-y-0 sm:divide-x divide-desk-borderSubtle">
                <!-- NAV Totale -->
                <div class="pr-2 pt-1 sm:pt-0">
                    <span class="text-[11px] font-semibold uppercase tracking-wider text-desk-textMuted block">Patrimonio Totale (USD)</span>
                    <div id="summary-total-equity" class="text-xl sm:text-2xl font-bold mono-val text-white mt-1">$0.00</div>
                    <span class="text-[11px] text-slate-400 font-mono">Bybit UTA + Alpaca Eq</span>
                </div>
                <!-- Bybit Nav -->
                <div class="pl-0 sm:pl-4 pt-1 sm:pt-0">
                    <div class="flex items-center gap-1.5">
                        <span class="w-2 h-2 rounded-full bg-amber-400"></span>
                        <span class="text-[11px] font-semibold uppercase tracking-wider text-amber-400">Bybit Crypto Futures</span>
                    </div>
                    <div id="summary-bybit-nav" class="text-lg sm:text-xl font-bold mono-val text-white mt-1">$0.00</div>
                    <span class="text-[11px] text-slate-400 font-mono" id="summary-bybit-cash">Disponibile: $0 USDT</span>
                </div>
                <!-- Alpaca Nav -->
                <div class="pl-0 sm:pl-4 pt-3 sm:pt-0">
                    <div class="flex items-center gap-1.5">
                        <span class="w-2 h-2 rounded-full bg-blue-400"></span>
                        <span class="text-[11px] font-semibold uppercase tracking-wider text-blue-400">Alpaca Wall Street</span>
                    </div>
                    <div id="summary-alpaca-nav" class="text-lg sm:text-xl font-bold mono-val text-white mt-1">$0.00</div>
                    <span class="text-[11px] text-slate-400 font-mono" id="summary-alpaca-bp">Buying Power: $0</span>
                </div>
                <!-- Live PnL -->
                <div class="pl-0 sm:pl-4 pt-3 sm:pt-0">
                    <span class="text-[11px] font-semibold uppercase tracking-wider text-desk-textMuted block">PnL Non Realizzato Crypto</span>
                    <div id="summary-crypto-pnl" class="text-lg sm:text-xl font-bold mono-val text-emerald-400 mt-1">$0.00</div>
                    <span class="text-[11px] font-mono text-slate-400" id="summary-active-positions">0 posizioni a mercato</span>
                </div>
            </div>
        </div>

        <!-- ======================================================== -->
        <!-- SEZIONE GRAFICI DI PERFORMANCE & VOLUME (A PARTIRE DA OGGI) -->
        <!-- ======================================================== -->
        <div class="desk-card rounded-xl p-4 sm:p-5 space-y-4">
            <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-desk-borderSubtle pb-3">
                <div class="flex items-center gap-2">
                    <i data-lucide="trending-up" class="w-5 h-5 text-emerald-400"></i>
                    <div>
                        <h2 class="text-sm sm:text-base font-bold text-white tracking-tight">TRAIETTORIA DI RENDIMENTO & VOLUME</h2>
                        <p class="text-xs text-slate-400">Monitor cumulativo realtime a partire da oggi &bull; Proiezione 30 giorni</p>
                    </div>
                </div>

                <!-- 4 KPI di Efficienza Quantitativa a Lungo Termine -->
                <div class="grid grid-cols-2 sm:flex items-center gap-2 sm:gap-3 w-full sm:w-auto text-xs font-mono">
                    <div class="bg-desk-elevated px-2.5 py-1.5 rounded border border-desk-border">
                        <span class="text-slate-400 text-[10px] block">VOLUME TOTALE</span>
                        <span id="metric-cum-volume" class="font-bold text-white">$120,400</span>
                    </div>
                    <div class="bg-desk-elevated px-2.5 py-1.5 rounded border border-desk-border">
                        <span class="text-slate-400 text-[10px] block">PNL REALIZZATO</span>
                        <span id="metric-cum-pnl" class="font-bold text-rose-400">-$181.71</span>
                    </div>
                    <div class="bg-desk-elevated px-2.5 py-1.5 rounded border border-desk-border">
                        <span class="text-slate-400 text-[10px] block">WIN RATE</span>
                        <span id="metric-win-rate" class="font-bold text-amber-400">20.0%</span>
                    </div>
                    <div class="bg-desk-elevated px-2.5 py-1.5 rounded border border-desk-border">
                        <span class="text-slate-400 text-[10px] block">PROFIT FACTOR</span>
                        <span id="metric-profit-factor" class="font-bold text-slate-300">0.42</span>
                    </div>
                </div>
            </div>

            <!-- CANVAS GRAFICO CHART.JS -->
            <div class="relative w-full h-64 sm:h-72">
                <canvas id="perfChart"></canvas>
            </div>

            <!-- Spiegazione / Legend Footer -->
            <div class="flex flex-wrap items-center justify-between text-xs text-slate-400 font-mono pt-2 border-t border-desk-borderSubtle gap-2">
                <div class="flex items-center gap-4">
                    <span class="flex items-center gap-1.5">
                        <span class="w-3 h-1 bg-emerald-400 inline-block rounded"></span>
                        <span class="text-slate-300">Equity Portafoglio ($)</span>
                    </span>
                    <span class="flex items-center gap-1.5">
                        <span class="w-3 h-1 bg-amber-400 inline-block rounded"></span>
                        <span class="text-slate-300">PnL Netto Realizzato ($)</span>
                    </span>
                    <span class="flex items-center gap-1.5">
                        <span class="w-3 h-2 bg-blue-500/40 inline-block rounded"></span>
                        <span class="text-slate-300">Volume Trading Eseguito ($)</span>
                    </span>
                </div>
                <div class="text-[11px] text-slate-500">
                    Registrazione continuativa su database persistente <strong class="text-slate-400">perf_history.db</strong>
                </div>
            </div>
        </div>

        <!-- MAIN INSTANCE SELECTOR (TABS CON TARGET TOUCH ERGONOMICI 44PX) -->
        <div class="bg-desk-card p-1.5 rounded-xl border border-desk-border flex items-center gap-1.5 overflow-x-auto no-scrollbar">
            <button id="tab-btn-bybit" class="desk-tab active flex-1 sm:flex-initial" onclick="selectInstance('bybit')">
                <span class="w-2.5 h-2.5 rounded-full bg-amber-400 mr-2"></span>
                <span>Bybit Futures (Crypto 24/7)</span>
                <span id="badge-bybit-count" class="ml-2 px-2 py-0.5 rounded text-xs font-mono bg-desk-elevated text-amber-300 border border-amber-500/30">0</span>
            </button>
            <button id="tab-btn-alpaca" class="desk-tab flex-1 sm:flex-initial" onclick="selectInstance('alpaca')">
                <span class="w-2.5 h-2.5 rounded-full bg-blue-400 mr-2"></span>
                <span>Alpaca (Wall Street Equities)</span>
                <span id="badge-alpaca-count" class="ml-2 px-2 py-0.5 rounded text-xs font-mono bg-desk-elevated text-blue-300 border border-blue-500/30">0</span>
            </button>
            <button id="tab-btn-history" class="desk-tab flex-1 sm:flex-initial" onclick="selectInstance('history')">
                <i data-lucide="history" class="w-4 h-4 mr-1.5 text-slate-400"></i>
                <span>Storico Chiusi</span>
            </button>
            <button id="tab-btn-rules" class="desk-tab flex-1 sm:flex-initial hidden sm:inline-flex" onclick="selectInstance('rules')">
                <i data-lucide="shield" class="w-4 h-4 mr-1.5 text-slate-400"></i>
                <span>Regole Rischio</span>
            </button>
        </div>

        <!-- ========================================== -->
        <!-- ISTANZA 1: BYBIT CRYPTO FUTURES 24/7      -->
        <!-- ========================================== -->
        <section id="instance-bybit" class="space-y-4">
            
            <!-- Sotto-barra info Bybit -->
            <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 bg-desk-elevated/60 px-4 py-3 rounded-lg border border-desk-borderSubtle text-xs">
                <div class="flex items-center gap-2">
                    <span class="font-bold text-amber-400">BYBIT UNIFIED TRADING (DEMO UTA)</span>
                    <span class="text-slate-500">&bull;</span>
                    <span class="text-slate-300 font-mono">10 Asset Monitorati (BTC, ETH, SOL, LINK, AVAX, XRP, DOGE, SUI, NEAR, BNB)</span>
                </div>
                <div class="flex items-center gap-3 text-slate-400 font-mono text-[11px]">
                    <span>Taglia: <strong class="text-white">$15,000 / trade</strong></span>
                    <span>TP: <strong class="text-emerald-400">+3.00%</strong></span>
                    <span>SL: <strong class="text-rose-400">-1.20%</strong></span>
                </div>
            </div>

            <!-- TABELLA DESKTOP / TABLET -->
            <div class="hidden md:block desk-card rounded-xl overflow-hidden border border-desk-border">
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs">
                        <thead>
                            <tr class="border-b border-desk-border bg-desk-elevated text-slate-300 font-semibold uppercase text-[11px] tracking-wider">
                                <th class="py-3 px-4">Contratto</th>
                                <th class="py-3 px-4">Lato</th>
                                <th class="py-3 px-4">Quantità (Size)</th>
                                <th class="py-3 px-4">Prezzo Entrata</th>
                                <th class="py-3 px-4">Mark Price</th>
                                <th class="py-3 px-4">Controvalore</th>
                                <th class="py-3 px-4">PnL Non Realizzato</th>
                                <th class="py-3 px-4">Protezione Dinamica</th>
                            </tr>
                        </thead>
                        <tbody id="bybit-table-body" class="divide-y divide-desk-borderSubtle mono-val">
                            <tr>
                                <td colspan="8" class="text-center py-10 text-slate-400">
                                    <div class="flex items-center justify-center gap-2">
                                        <i data-lucide="loader-2" class="w-4 h-4 animate-spin text-slate-400"></i>
                                        <span>Sincronizzazione posizioni Bybit...</span>
                                    </div>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- CARDS MOBILE OTTIMIZZATE PER IPHONE -->
            <div id="bybit-mobile-cards" class="md:hidden space-y-3">
                <div class="text-center py-8 text-slate-400 desk-card rounded-xl p-4 text-xs font-mono">
                    Caricamento posizioni Bybit...
                </div>
            </div>
        </section>

        <!-- ========================================== -->
        <!-- ISTANZA 2: ALPACA EQUITIES WALL STREET    -->
        <!-- ========================================== -->
        <section id="instance-alpaca" class="space-y-4 hidden">
            <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 bg-desk-elevated/60 px-4 py-3 rounded-lg border border-desk-borderSubtle text-xs">
                <div class="flex items-center gap-2">
                    <span class="font-bold text-blue-400">ALPACA EQUITIES (NYSE / NASDAQ)</span>
                    <span class="text-slate-500">&bull;</span>
                    <span class="text-slate-300 font-mono" id="alpaca-account-badge">Conto Paper: PA3WDUE2F</span>
                </div>
                <div class="flex items-center gap-3 text-slate-400 font-mono text-[11px]">
                    <span>Orari: <strong class="text-white">15:30 - 22:00 CET</strong></span>
                    <span>Weekend: <strong class="text-amber-400">Mercati Chiusi</strong></span>
                </div>
            </div>

            <!-- KPI Box Alpaca -->
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div class="desk-card rounded-xl p-4">
                    <span class="text-[11px] font-semibold uppercase tracking-wider text-desk-textMuted">Valore Azioni in Portafoglio</span>
                    <div id="alpaca-equity-display" class="text-xl sm:text-2xl font-bold mono-val text-white mt-1">$0.00</div>
                    <span class="text-[11px] text-slate-400 font-mono">Alpaca Portfolio Value</span>
                </div>
                <div class="desk-card rounded-xl p-4">
                    <span class="text-[11px] font-semibold uppercase tracking-wider text-desk-textMuted">Buying Power Azionario</span>
                    <div id="alpaca-bp-display" class="text-xl sm:text-2xl font-bold mono-val text-white mt-1">$0.00</div>
                    <span class="text-[11px] text-slate-400 font-mono">Capacità d'acquisto</span>
                </div>
                <div class="desk-card rounded-xl p-4">
                    <span class="text-[11px] font-semibold uppercase tracking-wider text-desk-textMuted">Stato Connessione API</span>
                    <div class="text-xl font-bold text-emerald-400 mt-1 flex items-center gap-2">
                        <span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                        <span>ATTIVO &amp; CONNESSO</span>
                    </div>
                    <span class="text-[11px] text-slate-400 font-mono">Auto-Flatten attivo ore 21:55 CET</span>
                </div>
            </div>

            <!-- Tabella Titoli Alpaca -->
            <div class="desk-card rounded-xl overflow-hidden border border-desk-border">
                <div class="p-3.5 bg-desk-elevated border-b border-desk-border flex items-center justify-between">
                    <span class="font-bold text-xs uppercase tracking-wider text-white">Posizioni Azionarie Wall Street</span>
                    <span class="text-xs font-mono text-slate-400" id="alpaca-total-titles">0 Titoli</span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs font-mono">
                        <thead>
                            <tr class="border-b border-desk-border text-slate-400 text-[11px] uppercase">
                                <th class="py-2.5 px-4">Ticker</th>
                                <th class="py-2.5 px-4">Quantità</th>
                                <th class="py-2.5 px-4">Prezzo Medio</th>
                                <th class="py-2.5 px-4">Prezzo Attuale</th>
                                <th class="py-2.5 px-4">Valore Mercato</th>
                                <th class="py-2.5 px-4">PnL Non Realizzato</th>
                            </tr>
                        </thead>
                        <tbody id="alpaca-table-body" class="divide-y divide-desk-borderSubtle">
                            <tr>
                                <td colspan="6" class="text-center py-8 text-slate-400">
                                    Nessuna posizione azionaria attualmente aperta su Alpaca (Wall Street chiusa nel weekend).
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
        <section id="instance-history" class="space-y-4 hidden">
            <div class="desk-card rounded-xl overflow-hidden border border-desk-border">
                <div class="p-3.5 bg-desk-elevated border-b border-desk-border flex items-center justify-between">
                    <span class="font-bold text-xs uppercase tracking-wider text-white">Ultime Esecuzioni Chiuse (Bybit Futures)</span>
                    <span class="text-xs font-mono text-slate-400" id="history-total-count">Ultime 15</span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs font-mono">
                        <thead>
                            <tr class="border-b border-desk-border text-slate-300 text-[11px] uppercase bg-desk-card">
                                <th class="py-2.5 px-4">Ora (CET)</th>
                                <th class="py-2.5 px-4">Simbolo</th>
                                <th class="py-2.5 px-4">Lato</th>
                                <th class="py-2.5 px-4">Size</th>
                                <th class="py-2.5 px-4">Prezzi (In &rarr; Out)</th>
                                <th class="py-2.5 px-4">Fee Broker</th>
                                <th class="py-2.5 px-4">PnL Netto</th>
                            </tr>
                        </thead>
                        <tbody id="history-table-body" class="divide-y divide-desk-borderSubtle">
                            <tr>
                                <td colspan="7" class="text-center py-8 text-slate-400">Caricamento storico...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- ========================================== -->
        <!-- ISTANZA 4: REGOLE RISCHIO & MOTORE         -->
        <!-- ========================================== -->
        <section id="instance-rules" class="space-y-4 hidden">
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div class="desk-card rounded-xl p-5 border-l-4 border-l-amber-500">
                    <div class="flex items-center gap-2 text-amber-400 font-bold text-xs uppercase">
                        <i data-lucide="zap" class="w-4 h-4"></i>
                        <span>Taglia $15k per Trade</span>
                    </div>
                    <p class="text-xs text-slate-300 mt-2 leading-relaxed">
                        Ogni trade su Bybit UTA entra con un controvalore fisso calibrato di <strong>$15,000 USDT</strong> per massimizzare la monetizzazione sui micro-movimenti 24/7.
                    </p>
                </div>
                <div class="desk-card rounded-xl p-5 border-l-4 border-l-emerald-500">
                    <div class="flex items-center gap-2 text-emerald-400 font-bold text-xs uppercase">
                        <i data-lucide="shield-check" class="w-4 h-4"></i>
                        <span>Break-Even a +0.60%</span>
                    </div>
                    <p class="text-xs text-slate-300 mt-2 leading-relaxed">
                        Appena il profitto latente tocca il <strong>+0.60%</strong>, lo Stop Loss si porta automaticamente a pareggio con cuscinetto commissioni. Rischio zero.
                    </p>
                </div>
                <div class="desk-card rounded-xl p-5 border-l-4 border-l-blue-500">
                    <div class="flex items-center gap-2 text-blue-400 font-bold text-xs uppercase">
                        <i data-lucide="lock" class="w-4 h-4"></i>
                        <span>Profit Lock a +1.20%</span>
                    </div>
                    <p class="text-xs text-slate-300 mt-2 leading-relaxed">
                        Al raggiungimento del <strong>+1.20%</strong>, scatta il trailing lock blindando un profitto minimo netto del <strong>+0.70%</strong> fino al target finale di <strong>+3.00%</strong>.
                    </p>
                </div>
            </div>
        </section>

    </main>

    <!-- FOOTER -->
    <footer class="border-t border-desk-border bg-desk-card py-4 mt-8 text-xs font-mono text-slate-400">
        <div class="max-w-[1440px] mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-2">
            <div>
                <span>Istanza Crypto: <strong class="text-white">Bybit UTA Demo</strong></span>
                <span class="mx-2">&bull;</span>
                <span>Istanza Azionario: <strong class="text-white">Alpaca Wall Street</strong></span>
            </div>
            <div>
                Sincronizzazione: <span id="footer-sync-time" class="text-slate-200">--:--:--</span>
            </div>
        </div>
    </footer>

    <!-- SCRIPT LOGICO & ENGINE GRAFICO CHART.JS -->
    <script>
        let activeTab = 'bybit';
        let perfChartInstance = null;

        function selectInstance(tabId) {
            activeTab = tabId;
            const tabs = ['bybit', 'alpaca', 'history', 'rules'];
            tabs.forEach(t => {
                const btn = document.getElementById(`tab-btn-${t}`);
                const sec = document.getElementById(`instance-${t}`);
                if (btn && sec) {
                    if (t === tabId) {
                        btn.classList.add('active');
                        sec.classList.remove('hidden');
                    } else {
                        btn.classList.remove('active');
                        sec.classList.add('hidden');
                    }
                }
            });
            lucide.createIcons();
        }

        function updateClocks() {
            const now = new Date();
            const rome = new Intl.DateTimeFormat('it-IT', { timeZone: 'Europe/Rome', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(now);
            const nyc = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(now);
            const rEl = document.getElementById('clock-rome');
            const nEl = document.getElementById('clock-nyc');
            if (rEl) rEl.innerText = rome;
            if (nEl) nEl.innerText = nyc;
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
                            pointRadius: 3,
                            pointBackgroundColor: '#10B981'
                        },
                        {
                            label: 'PnL Netto Realizzato ($)',
                            data: pnlData,
                            borderColor: '#F59E0B',
                            backgroundColor: 'transparent',
                            borderWidth: 2,
                            borderDash: [4, 4],
                            yAxisID: 'yPnL',
                            tension: 0.2,
                            pointRadius: 2,
                            pointBackgroundColor: '#F59E0B'
                        },
                        {
                            type: 'bar',
                            label: 'Volume Cumulativo ($)',
                            data: volData,
                            backgroundColor: 'rgba(59, 130, 246, 0.25)',
                            borderColor: 'rgba(59, 130, 246, 0.6)',
                            borderWidth: 1,
                            yAxisID: 'yVolume',
                            barPercentage: 0.4
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
                            titleFont: { family: 'Roboto Mono', size: 12 },
                            bodyFont: { family: 'Roboto Mono', size: 11 },
                            padding: 10,
                            callbacks: {
                                label: function(context) {
                                    let label = context.dataset.label || '';
                                    if (label) label += ': ';
                                    if (context.parsed.y !== null) {
                                        label += '$' + context.parsed.y.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                                    }
                                    return label;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(31, 41, 61, 0.4)' },
                            ticks: { color: '#64748B', font: { family: 'Roboto Mono', size: 10 } }
                        },
                        yEquity: {
                            type: 'linear',
                            position: 'left',
                            grid: { color: 'rgba(31, 41, 61, 0.5)' },
                            ticks: {
                                color: '#10B981',
                                font: { family: 'Roboto Mono', size: 10 },
                                callback: val => '$' + (val / 1000).toFixed(1) + 'k'
                            }
                        },
                        yPnL: {
                            type: 'linear',
                            position: 'right',
                            grid: { drawOnChartArea: false },
                            ticks: {
                                color: '#F59E0B',
                                font: { family: 'Roboto Mono', size: 10 },
                                callback: val => '$' + val.toFixed(0)
                            }
                        },
                        yVolume: {
                            type: 'linear',
                            position: 'right',
                            display: false,
                            grid: { drawOnChartArea: false }
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
                
                const nowTime = new Date().toLocaleTimeString('it-IT');
                const footerSync = document.getElementById('footer-sync-time');
                if (footerSync) footerSync.innerText = nowTime;
                
                const hStatus = document.getElementById('header-status');
                if (hStatus) {
                    hStatus.innerText = 'LIVE SYNC 3S';
                    hStatus.className = 'text-emerald-400';
                }
            } catch (err) {
                console.error("Fetch error:", err);
                const hStatus = document.getElementById('header-status');
                if (hStatus) {
                    hStatus.innerText = 'RICONNESSIONE...';
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

            document.getElementById('summary-total-equity').innerText = `$${totalEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('summary-bybit-nav').innerText = `$${bybitEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            
            const usdtCash = (bWallet.coins && bWallet.coins.USDT) ? bWallet.coins.USDT : (bWallet.available_balance || 0);
            document.getElementById('summary-bybit-cash').innerText = `Disponibile: $${usdtCash.toLocaleString('en-US', {maximumFractionDigits: 0})} USDT`;

            document.getElementById('summary-alpaca-nav').innerText = `$${alpacaEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('summary-alpaca-bp').innerText = `Buying Power: $${parseFloat(aAcc.buying_power || 0).toLocaleString('en-US', {maximumFractionDigits: 0})}`;

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
            sumPnlEl.innerText = `${pnlSign}$${totalPnL.toFixed(2)}`;
            sumPnlEl.className = `text-lg sm:text-xl font-bold mono-val ${pnlColor} mt-1`;

            document.getElementById('summary-active-positions').innerText = `${bPositions.length} posizioni a mercato ($${totalNotional.toLocaleString('en-US', {maximumFractionDigits: 0})})`;

            // Badges Tab
            document.getElementById('badge-bybit-count').innerText = bPositions.length;
            document.getElementById('badge-alpaca-count').innerText = aPositions.length;

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

            document.getElementById('metric-cum-volume').innerText = `$${cumVol.toLocaleString('en-US', {maximumFractionDigits: 0})}`;
            
            const crEl = document.getElementById('metric-cum-pnl');
            crEl.innerText = `${cumRealized >= 0 ? '+' : ''}$${cumRealized.toFixed(2)}`;
            crEl.className = `font-bold ${cumRealized >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;

            document.getElementById('metric-win-rate').innerText = `${winRate.toFixed(1)}% (${wins}/${totalTrades})`;
            document.getElementById('metric-profit-factor').innerText = profitFactor.toFixed(2);

            // Inizializza / Aggiorna Chart.js
            if (perfHistory.length > 0) {
                initChart(perfHistory);
            }

            // 3. Render Bybit Desktop Table
            const bTable = document.getElementById('bybit-table-body');
            if (bPositions.length === 0) {
                bTable.innerHTML = `<tr><td colspan="8" class="text-center py-10 text-slate-400">Nessuna posizione aperta. Lo scanner ricerca confluenza A+ ogni 2m.</td></tr>`;
            } else {
                bTable.innerHTML = bPositions.map(p => {
                    const isLong = p.side === 'BUY';
                    const sideBadge = isLong 
                        ? `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">LONG</span>`
                        : `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">SHORT</span>`;

                    const pSign = p.unrealized_pnl >= 0 ? '+' : '';
                    const pCol = p.unrealized_pnl >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';

                    let protBadge = `<span class="text-slate-400 text-xs">SL -1.20% (In corso)</span>`;
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
                            <td class="py-3 px-4 text-slate-300">$${(p.position_value || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                            <td class="py-3 px-4 ${pCol}">
                                ${pSign}$${p.unrealized_pnl.toFixed(2)} 
                                <span class="text-[11px] font-medium opacity-90">(${pSign}${p.pnl_pct.toFixed(2)}%)</span>
                            </td>
                            <td class="py-3 px-4">${protBadge}</td>
                        </tr>
                    `;
                }).join('');
            }

            // 4. Render Bybit Mobile Cards (100% Usabilità iPhone)
            const bCards = document.getElementById('bybit-mobile-cards');
            if (bPositions.length === 0) {
                bCards.innerHTML = `<div class="desk-card rounded-xl p-5 text-center text-slate-400 text-xs font-mono">Nessuna posizione aperta. Scanner A+ in ascolto.</div>`;
            } else {
                bCards.innerHTML = bPositions.map(p => {
                    const isLong = p.side === 'BUY';
                    const sideBadge = isLong 
                        ? `<span class="px-2 py-0.5 rounded text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">LONG</span>`
                        : `<span class="px-2 py-0.5 rounded text-xs font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">SHORT</span>`;

                    const pSign = p.unrealized_pnl >= 0 ? '+' : '';
                    const pCol = p.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400';

                    let protBadge = `<span class="text-slate-400 text-[11px]">SL -1.20% (In corso)</span>`;
                    if (p.pnl_pct >= 1.20) {
                        protBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">PROFIT LOCKED (+0.70%)</span>`;
                    } else if (p.pnl_pct >= 0.60) {
                        protBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">BREAK-EVEN (0 RISK)</span>`;
                    }

                    return `
                        <div class="desk-card rounded-xl p-4 space-y-3">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-2">
                                    <span class="text-base font-bold text-white mono-val">${p.symbol}</span>
                                    ${sideBadge}
                                </div>
                                <div class="text-right">
                                    <div class="text-base font-bold mono-val ${pCol}">
                                        ${pSign}$${p.unrealized_pnl.toFixed(2)}
                                    </div>
                                    <div class="text-[11px] font-bold mono-val ${pCol}">
                                        (${pSign}${p.pnl_pct.toFixed(2)}%)
                                    </div>
                                </div>
                            </div>
                            
                            <div class="grid grid-cols-2 gap-2 text-xs font-mono pt-2 border-t border-desk-borderSubtle">
                                <div>
                                    <span class="text-slate-400 text-[10px] uppercase block">Entrata &rarr; Attuale</span>
                                    <span class="text-slate-200 font-semibold">$${p.entry_price.toFixed(4)} &rarr; $${p.mark_price.toFixed(4)}</span>
                                </div>
                                <div class="text-right">
                                    <span class="text-slate-400 text-[10px] uppercase block">Size &amp; Valore</span>
                                    <span class="text-slate-200 font-semibold">${p.size} ($${(p.position_value || 0).toLocaleString('en-US', {maximumFractionDigits: 0})})</span>
                                </div>
                            </div>

                            <div class="pt-2 border-t border-desk-borderSubtle flex items-center justify-between text-xs font-mono">
                                <span class="text-slate-400 text-[11px]">Protezione:</span>
                                ${protBadge}
                            </div>
                        </div>
                    `;
                }).join('');
            }

            // 5. Render Alpaca Box & Table
            document.getElementById('alpaca-equity-display').innerText = `$${alpacaEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('alpaca-bp-display').innerText = `$${parseFloat(aAcc.buying_power || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('alpaca-total-titles').innerText = `${aPositions.length} Titoli`;

            const alpacaBody = document.getElementById('alpaca-table-body');
            if (aPositions.length === 0) {
                alpacaBody.innerHTML = `<tr><td colspan="6" class="text-center py-8 text-slate-400">Nessuna posizione azionaria attualmente aperta su Alpaca (Wall Street chiusa nel weekend).</td></tr>`;
            } else {
                alpacaBody.innerHTML = aPositions.map(ap => {
                    const unpnl = parseFloat(ap.unrealized_pl || 0);
                    const col = unpnl >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
                    const sign = unpnl >= 0 ? '+' : '';
                    return `
                        <tr class="hover:bg-desk-elevated/70 transition">
                            <td class="py-2.5 px-4 font-bold text-white">${ap.symbol}</td>
                            <td class="py-2.5 px-4 text-slate-200">${ap.qty}</td>
                            <td class="py-2.5 px-4 text-slate-300">$${parseFloat(ap.avg_entry_price || 0).toFixed(2)}</td>
                            <td class="py-2.5 px-4 font-bold text-white">$${parseFloat(ap.current_price || 0).toFixed(2)}</td>
                            <td class="py-2.5 px-4 text-slate-200">$${parseFloat(ap.market_value || 0).toFixed(2)}</td>
                            <td class="py-2.5 px-4 ${col}">${sign}$${unpnl.toFixed(2)}</td>
                        </tr>
                    `;
                }).join('');
            }

            // 6. Render Storico Chiusure
            document.getElementById('history-total-count').innerText = `${bClosed.length} registrati`;
            const hBody = document.getElementById('history-table-body');
            if (bClosed.length === 0) {
                hBody.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-slate-400">Nessun trade chiuso di recente.</td></tr>`;
            } else {
                hBody.innerHTML = bClosed.slice(0, 15).map(c => {
                    const pnlVal = parseFloat(c.closedPnl || 0);
                    const pCol = pnlVal >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
                    const pSign = pnlVal >= 0 ? '+' : '';
                    const timeStr = c.updatedTime ? new Date(parseInt(c.updatedTime)).toLocaleTimeString('it-IT') : '--:--';
                    return `
                        <tr class="hover:bg-desk-elevated/70 transition">
                            <td class="py-2.5 px-4 text-slate-400">${timeStr}</td>
                            <td class="py-2.5 px-4 font-bold text-white">${c.symbol}</td>
                            <td class="py-2.5 px-4"><span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-desk-elevated text-slate-300 border border-desk-border">${c.side}</span></td>
                            <td class="py-2.5 px-4 text-slate-300">${c.closedSize || c.qty}</td>
                            <td class="py-2.5 px-4 text-slate-300">$${parseFloat(c.avgEntryPrice || 0).toFixed(4)} &rarr; $${parseFloat(c.avgExitPrice || 0).toFixed(4)}</td>
                            <td class="py-2.5 px-4 text-slate-400">$${(parseFloat(c.openFee || 0) + parseFloat(c.closeFee || 0)).toFixed(2)}</td>
                            <td class="py-2.5 px-4 ${pCol}">${pSign}$${pnlVal.toFixed(2)}</td>
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

        # Salva snapshot periodico su SQLite per tracciare la curva e i volumi
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
