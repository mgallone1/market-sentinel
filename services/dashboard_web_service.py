"""
Web Dashboard Service for Market Sentinel.
Design: Professional Dual-Theme Financial Terminal (Light Mode & Dark Mode switchable).
- Light Mode: Elegante, arioso, pulito (sfondo #F8FAFC, card #FFFFFF, bordi #E2E8F0, testo ad alto contrasto #0F172A).
- Dark Mode: Slate istituzionale (sfondo #0F172A, card #1E293B, bordi #334155, testo #F8FAFC).
- Switcher istantaneo a 1-tap in alto a destra (sole/luna) con salvataggio preferenza in localStorage.
- 100% ottimizzato per iPhone e Desktop con grafici Chart.js che adattano colori assi e griglia al tema.
"""

import json
from aiohttp import web
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any

from services.bybit_execution_service import BybitExecutionService
from services.alpaca_execution_service import AlpacaExecutionService
from services.perf_metrics_tracker import perf_tracker
from services.trading_compass_service import trading_compass

_bybit_service: BybitExecutionService = None
_alpaca_service: AlpacaExecutionService = None

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="it" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <title>SENTINEL // DESK TRADING</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js" defer></script>
    <style>
        /* TEMA LIGHT (PREDEFINITO, LUMINOSO E AD ALTA LEGGIBILITÀ) */
        :root {
            --bg: #f8fafc;
            --surface: #ffffff;
            --surface-elevated: #f1f5f9;
            --border: #e2e8f0;
            --border-subtle: #edf2f7;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --text-dim: #94a3b8;
            --green: #15803d;
            --green-bg: #dcfce7;
            --red: #b91c1c;
            --red-bg: #fee2e2;
            --amber: #b45309;
            --amber-bg: #fef3c7;
            --blue: #2563eb;
            --chart-grid: rgba(226, 232, 240, 0.8);
            --chart-tick: #64748b;
        }

        /* TEMA DARK (SLATE ISTITUZIONALE, NON NERO CIECO) */
        [data-theme="dark"] {
            --bg: #0b0f19;
            --surface: #131b2e;
            --surface-elevated: #1a243d;
            --border: #233150;
            --border-subtle: #19243c;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --text-dim: #64748b;
            --green: #22c55e;
            --green-bg: rgba(34, 197, 94, 0.15);
            --red: #ef4444;
            --red-bg: rgba(239, 68, 68, 0.15);
            --amber: #f59e0b;
            --amber-bg: rgba(245, 158, 11, 0.15);
            --blue: #3b82f6;
            --chart-grid: rgba(35, 49, 80, 0.5);
            --chart-tick: #94a3b8;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }
        body {
            background-color: var(--bg);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif;
            font-size: 13px;
            line-height: 1.4;
            padding-top: env(safe-area-inset-top, 0px);
            padding-bottom: calc(env(safe-area-inset-bottom, 20px) + 60px);
            overflow-x: hidden;
            transition: background-color 0.2s ease, color 0.2s ease;
        }
        .mono {
            font-family: "SF Mono", Menlo, Monaco, Consolas, monospace;
            font-feature-settings: "tnum" 1;
        }

        /* Top Bar */
        .topbar {
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            padding: 10px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 50;
            box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        }
        .topbar-title {
            font-weight: 700;
            font-size: 14px;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
            display: inline-block;
        }
        .topbar-actions {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .theme-toggle-btn, .refresh-btn {
            background: var(--surface-elevated);
            border: 1px solid var(--border);
            color: var(--text-main);
            font-size: 11px;
            font-weight: 600;
            padding: 6px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-family: inherit;
            display: flex;
            align-items: center;
            gap: 4px;
            touch-action: manipulation;
        }
        .theme-toggle-btn:active, .refresh-btn:active {
            opacity: 0.8;
            transform: scale(0.97);
        }

        /* Section Container */
        .section {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
        }
        .section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        .section-title {
            font-size: 11px;
            font-weight: 700;
            color: var(--text-muted);
            letter-spacing: 0.8px;
            text-transform: uppercase;
        }

        /* DIRECTIONAL COMPASS BOX */
        .compass-box {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 14px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.02);
        }
        .compass-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border-subtle);
            padding-bottom: 8px;
        }
        .compass-score-wrap {
            display: flex;
            align-items: baseline;
            gap: 6px;
        }
        .compass-score {
            font-size: 26px;
            font-weight: 800;
        }
        .compass-badge {
            font-size: 10px;
            font-weight: 800;
            padding: 4px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .badge-green { background: var(--green-bg); color: var(--green); border: 1px solid var(--green); }
        .badge-amber { background: var(--amber-bg); color: var(--amber); border: 1px solid var(--amber); }
        .badge-red { background: var(--red-bg); color: var(--red); border: 1px solid var(--red); }

        .compass-desc {
            font-size: 11px;
            color: var(--text-muted);
            margin-top: 8px;
            line-height: 1.4;
        }

        /* 4-Cell Diagnostic Edge Grid */
        .diag-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 6px;
            margin-top: 10px;
        }
        @media (min-width: 640px) {
            .diag-grid { grid-template-columns: repeat(4, 1fr); }
        }
        .diag-cell {
            background: var(--surface-elevated);
            border: 1px solid var(--border);
            padding: 8px 10px;
            border-radius: 6px;
        }
        .diag-label {
            font-size: 9px;
            color: var(--text-muted);
            text-transform: uppercase;
            font-weight: 600;
        }
        .diag-val {
            font-size: 14px;
            font-weight: 700;
            color: var(--text-main);
            margin-top: 2px;
        }
        .diag-sub {
            font-size: 9px;
            color: var(--text-dim);
            margin-top: 1px;
        }

        /* Account Summary Row */
        .acc-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
        }
        @media (min-width: 640px) {
            .acc-grid { grid-template-columns: repeat(4, 1fr); }
        }
        .acc-cell {
            background: var(--surface);
            border: 1px solid var(--border);
            padding: 10px 12px;
            border-radius: 8px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.02);
        }
        .acc-label {
            font-size: 10px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
            font-weight: 600;
        }
        .acc-val {
            font-size: 16px;
            font-weight: 700;
            color: var(--text-main);
        }
        .acc-sub {
            font-size: 10px;
            color: var(--text-dim);
            margin-top: 2px;
        }

        /* MULTI-TIMEFRAME VARIATION STRIP */
        .tf-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 6px;
            margin-top: 4px;
        }
        @media (min-width: 640px) {
            .tf-grid { grid-template-columns: repeat(6, 1fr); }
        }
        .tf-card {
            background: var(--surface);
            border: 1px solid var(--border);
            padding: 8px;
            border-radius: 6px;
            text-align: center;
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .tf-card.active {
            border-color: var(--blue);
            background: var(--surface-elevated);
        }
        .tf-header {
            font-size: 10px;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
        }
        .tf-delta {
            font-size: 13px;
            font-weight: 700;
            margin-top: 2px;
        }
        .tf-pct {
            font-size: 10px;
            font-weight: 600;
        }

        /* Chart Controls & Container */
        .chart-controls {
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .tf-btn {
            background: var(--surface-elevated);
            border: 1px solid var(--border);
            color: var(--text-muted);
            font-size: 10px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-family: inherit;
        }
        .tf-btn.active {
            background: var(--blue);
            color: #fff;
            border-color: var(--blue);
        }
        .chart-wrap {
            height: 260px;
            position: relative;
            margin-top: 8px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 12px;
            box-shadow: inset 0 1px 2px rgba(0,0,0,0.02);
        }
        .chart-hud {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 6px 12px;
            background: var(--surface-elevated);
            border: 1px solid var(--border);
            border-radius: 6px;
            margin-bottom: 8px;
            font-size: 11px;
        }
        .chart-hud-stat {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .metrics-bar {
            display: flex;
            gap: 16px;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid var(--border-subtle);
            font-size: 11px;
        }
        .metric-item span { color: var(--text-muted); margin-right: 4px; }
        .metric-item strong { color: var(--text-main); }

        /* Watchlist Row */
        .trade-row {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 14px;
            margin-bottom: 10px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.02);
        }
        .trade-row-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .trade-row:active { background: var(--surface-elevated); }
        .trade-left { display: flex; flex-direction: column; gap: 2px; }
        .trade-symbol-row { display: flex; align-items: center; gap: 6px; }
        .trade-symbol { font-size: 14px; font-weight: 700; color: var(--text-main); }
        .trade-side-long {
            font-size: 9px;
            font-weight: 800;
            color: var(--green);
            background: var(--green-bg);
            padding: 2px 5px;
            border-radius: 4px;
        }
        .trade-side-short {
            font-size: 9px;
            font-weight: 800;
            color: var(--red);
            background: var(--red-bg);
            padding: 2px 5px;
            border-radius: 4px;
        }
        .trade-detail { font-size: 11px; color: var(--text-muted); }
        .trade-right {
            text-align: right;
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 2px;
        }
        .trade-pnl { font-size: 14px; font-weight: 700; }
        .trade-guard {
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
            background: var(--surface-elevated);
            color: var(--text-muted);
            border: 1px solid var(--border);
        }
        .guard-be {
            color: var(--green);
            background: var(--green-bg);
            border-color: var(--green);
            font-weight: 700;
        }
        .guard-lock {
            color: var(--amber);
            background: var(--amber-bg);
            border-color: var(--amber);
            font-weight: 700;
        }
        /* Trade Sparkline & Target Progress */
        .trade-chart-box {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: var(--surface-elevated);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 6px 10px;
            gap: 12px;
        }
        .trade-sparkline-canvas {
            width: 110px;
            height: 30px;
            flex-shrink: 0;
        }
        .trade-target-levels {
            display: flex;
            flex-direction: column;
            gap: 3px;
            flex-grow: 1;
            font-size: 10px;
        }
        .target-level-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .target-bar-bg {
            width: 100%;
            height: 4px;
            background: rgba(148, 163, 184, 0.2);
            border-radius: 2px;
            overflow: hidden;
            position: relative;
        }
        .target-bar-fill {
            height: 100%;
            border-radius: 2px;
            transition: width 0.3s ease;
        }

        
        /* TOOLTIPS INTERATTIVI ELEVATI (HOVER E TAP) */
        [data-tip] {
            position: relative;
            cursor: help;
        }
        [data-tip]:hover::after,
        [data-tip]:focus::after {
            content: attr(data-tip);
            position: absolute;
            bottom: calc(100% + 6px);
            left: 50%;
            transform: translateX(-50%);
            padding: 6px 10px;
            border-radius: 6px;
            background: #0f172a;
            color: #f8fafc;
            font-size: 11px;
            line-height: 1.35;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-weight: 500;
            white-space: normal;
            width: max-content;
            max-width: 230px;
            text-align: center;
            z-index: 999;
            box-shadow: 0 4px 12px rgba(0,0,0,0.25);
            pointer-events: none;
            border: 1px solid rgba(255,255,255,0.15);
        }
        [data-tip]:hover::before,
        [data-tip]:focus::before {
            content: '';
            position: absolute;
            bottom: calc(100% + 1px);
            left: 50%;
            transform: translateX(-50%);
            border: 5px solid transparent;
            border-top-color: #0f172a;
            z-index: 999;
            pointer-events: none;
        }

        /* Bottom Tab Bar */
        .tabbar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            height: 54px;
            background: var(--surface);
            border-top: 1px solid var(--border);
            display: flex;
            z-index: 100;
            padding-bottom: env(safe-area-inset-bottom, 0px);
            box-shadow: 0 -1px 3px rgba(0,0,0,0.03);
        }
        .tab-item {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 600;
            color: var(--text-muted);
            cursor: pointer;
            border: none;
            background: none;
            font-family: inherit;
        }
        .tab-item.active { color: var(--blue); font-weight: 700; }
        .tab-item span.dot {
            width: 4px;
            height: 4px;
            border-radius: 50%;
            background: transparent;
            margin-top: 3px;
        }
        .tab-item.active span.dot { background: var(--blue); }

        .clean-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
            text-align: left;
        }
        .clean-table th {
            color: var(--text-muted);
            font-weight: 600;
            padding: 8px 6px;
            border-bottom: 1px solid var(--border);
            text-transform: uppercase;
            font-size: 10px;
        }
        .clean-table td {
            padding: 8px 6px;
            border-bottom: 1px solid var(--border-subtle);
            color: var(--text-main);
        }
        .val-up { color: var(--green) !important; font-weight: 600; }
        .val-down { color: var(--red) !important; font-weight: 600; }
        .val-neutral { color: var(--text-muted) !important; }
        .hidden { display: none !important; }
    </style>
</head>
<body>

    <!-- TOPBAR CON CONTROLLI REFRESH E THEME SWITCH -->
    <div class="topbar">
        <div class="topbar-title">
            <span class="status-dot"></span>
            <span>SENTINEL TRADING</span>
            <span class="mono" style="font-size: 10px; color: var(--text-muted);" id="top-clock">--:--:--</span>
        </div>
        <div class="topbar-actions">
            <button class="theme-toggle-btn mono" onclick="toggleTheme()" id="theme-btn">🌙 DARK</button>
            <button class="refresh-btn mono" onclick="fetchData()">SYNC</button>
        </div>
    </div>

    <!-- 1. TRADING COMPASS: DIREZIONE STRATEGICA & HEALTH SCORE -->
    <div class="section">
        <div class="section-header">
            <span class="section-title">Trading Compass (Verifica Vantaggio Quant)</span>
            <span class="mono" style="font-size: 10px; color: var(--text-dim);">EDGE DIAGNOSTICS</span>
        </div>
        <div class="compass-box">
            <div class="compass-top">
                <div>
                    <div style="font-size: 9px; color: var(--text-muted); text-transform: uppercase;" class="mono">Health &amp; Alignment Score</div>
                    <div class="compass-score-wrap mono">
                        <span class="compass-score" id="compass-score-val">--</span>
                        <span style="font-size: 12px; color: var(--text-dim);">/ 100</span>
                    </div>
                </div>
                <div id="compass-badge-el" class="compass-badge badge-amber mono">CALCOLO</div>
            </div>
            <div class="compass-desc" id="compass-desc-el">
                Inizializzazione diagnostica probabilistica...
            </div>

            <!-- 4 Metric Cards: Expected Value, Realized R:R, In-The-Money Ratio, Profit Factor -->
            <div class="diag-grid mono">
                <div class="diag-cell" data-tip="Valore monetario atteso per trade: se positivo indica che la strategia guadagna nel lungo periodo">
                    <div class="diag-label">Expected Value (EV)</div>
                    <div class="diag-val" id="diag-ev-val">$0.00</div>
                    <div class="diag-sub">Utile atteso per trade</div>
                </div>
                <div class="diag-cell" data-tip="Valore monetario atteso per trade: se positivo indica che la strategia guadagna nel lungo periodo">
                    <div class="diag-label" data-tip="Rapporto Rischio/Rendimento: quanto guadagni quando vinci rispetto a quanto perdi quando vieni stoppato (target minimo 1:2.5)">R:R Reale vs Target</div>
                    <div class="diag-val" id="diag-rr-val">1:0.0</div>
                    <div class="diag-sub">Target min: 1:2.5</div>
                </div>
                <div class="diag-cell" data-tip="Valore monetario atteso per trade: se positivo indica che la strategia guadagna nel lungo periodo">
                    <div class="diag-label" data-tip="Percentuale di contratti aperti che si trovano attualmente in profitto non realizzato">Posizioni in Gain</div>
                    <div class="diag-val" id="diag-itm-val">0%</div>
                    <div class="diag-sub" id="diag-prot-sub">0 protette Break-Even</div>
                </div>
                <div class="diag-cell" data-tip="Valore monetario atteso per trade: se positivo indica che la strategia guadagna nel lungo periodo">
                    <div class="diag-label" data-tip="Profitti lordi totali divisi per perdite lorde totali. Superiore a 1.5 indica un forte vantaggio">Profit Factor</div>
                    <div class="diag-val" id="diag-pf-val">0.00</div>
                    <div class="diag-sub">Gross Win / Gross Loss</div>
                </div>
            </div>
        </div>
    </div>

    <!-- 2. ACCOUNTS SUMMARY STRIP -->
    <div class="section">
        <div class="acc-grid mono">
            <div class="acc-cell">
                <div class="acc-label" data-tip="Patrimonio complessivo convertito in USD sommando il conto Bybit Futures e il broker Alpaca Wall Street">Equity Totale</div>
                <div class="acc-val" id="total-equity">$0.00</div>
                <div class="acc-sub">Bybit + Alpaca</div>
            </div>
            <div class="acc-cell">
                <div class="acc-label" data-tip="Capitale su Bybit Unified Trading Account dedicato al trading algoritmico 24/7 sui derivati Crypto">Bybit UTA</div>
                <div class="acc-val" id="bybit-equity">$0.00</div>
                <div class="acc-sub" id="bybit-cash">Disponibile: $0</div>
            </div>
            <div class="acc-cell">
                <div class="acc-label" data-tip="Valore del conto azionario su Alpaca Securities (NYSE & NASDAQ), separato dalle Crypto">Alpaca Equities</div>
                <div class="acc-val" id="alpaca-equity">$0.00</div>
                <div class="acc-sub" id="alpaca-bp">BP: $0</div>
            </div>
            <div class="acc-cell">
                <div class="acc-label" data-tip="Guadagno o perdita fluttuante delle posizioni attualmente aperte a mercato">PnL Non Realizzato</div>
                <div class="acc-val" id="total-unrealized">$0.00</div>
                <div class="acc-sub" id="active-positions-count">0 posizioni</div>
            </div>
        </div>
    </div>

    <!-- 3. MULTI-TIMEFRAME VARIATIONS STRIP (3s, 1m, 1h, 1d, 1w, 1M) -->
    <div class="section">
        <div class="section-header">
            <span class="section-title">Variazione Rendimento Portfolio</span>
            <span class="mono" style="font-size: 10px; color: var(--text-dim);">LIVE DELTA</span>
        </div>
        <div class="tf-grid mono">
            <div class="tf-card active" id="card-tf-3s" onclick="setTimeframe('3s')">
                <div class="tf-header" data-tip="Variazione dell'equity negli ultimi 3 secondi (tick in tempo reale)">Ogni 3s</div>
                <div class="tf-delta" id="delta-3s-val">$0.00</div>
                <div class="tf-pct" id="delta-3s-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1m" onclick="setTimeframe('1m')">
                <div class="tf-header" data-tip="Variazione dell'equity registrata nell'ultimo minuto">1 Minuto</div>
                <div class="tf-delta" id="delta-1m-val">$0.00</div>
                <div class="tf-pct" id="delta-1m-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1h" onclick="setTimeframe('1h')">
                <div class="tf-header" data-tip="Variazione cumulativa del capitale nelle ultime 60 minuti">1 Ora</div>
                <div class="tf-delta" id="delta-1h-val">$0.00</div>
                <div class="tf-pct" id="delta-1h-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1d" onclick="setTimeframe('1d')">
                <div class="tf-header" data-tip="Rendimento delle ultime 24 ore rispetto al saldo della sessione precedente">1 Giorno</div>
                <div class="tf-delta" id="delta-1d-val">$0.00</div>
                <div class="tf-pct" id="delta-1d-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1w" onclick="setTimeframe('1w')">
                <div class="tf-header" data-tip="Performance progressiva cumulativa negli ultimi 7 giorni">1 Settimana</div>
                <div class="tf-delta" id="delta-1w-val">$0.00</div>
                <div class="tf-pct" id="delta-1w-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1M" onclick="setTimeframe('1M')">
                <div class="tf-header" data-tip="Rendimento complessivo a 30 giorni">1 Mese</div>
                <div class="tf-delta" id="delta-1M-val">$0.00</div>
                <div class="tf-pct" id="delta-1M-pct">0.00%</div>
            </div>
        </div>
    </div>

    <!-- 4. INTERACTIVE CHART CON CONTROLLO TIMEFRAME E SEPARAZIONE ISTANZE -->
    <div class="section">
        <div class="section-header" style="flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 6px;">
                <span class="section-title" id="chart-instance-title">Grafico: Bybit Futures (Crypto)</span>
            </div>
            <!-- Selettore Istanza Grafico Separato al 100% -->
            <div class="chart-controls mono">
                <button class="tf-btn active" id="btn-inst-bybit" onclick="setChartInstance('bybit')">🪙 BYBIT FUTURES</button>
                <button class="tf-btn" id="btn-inst-alpaca" onclick="setChartInstance('alpaca')">🏛️ ALPACA WALL ST</button>
                <button class="tf-btn" id="btn-inst-total" onclick="setChartInstance('total')">🌐 TOTALE</button>
            </div>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 6px;">
            <!-- Toggle Modalità Scala: Dollari $ vs Percentuale % -->
            <div class="chart-controls mono">
                <button class="tf-btn active" id="btn-mode-usd" onclick="setChartMode('usd')" data-tip="Mostra il grafico in valori monetari assoluti ($ Dollari)">$ DOLLARI</button>
                <button class="tf-btn" id="btn-mode-pct" onclick="setChartMode('pct')" data-tip="Mostra il grafico in rendimento percentuale progressivo (% Yield)">% PERCENTUALE</button>
            </div>

            <!-- Controlli Timeframe e Reset Zoom -->
            <div class="chart-controls mono">
                <button class="tf-btn" id="btn-reset-zoom" onclick="resetChartZoom()" style="display: none; background: var(--amber); color: #fff; border-color: var(--amber);" data-tip="Ripristina la vista panoramica del grafico originale">🔍 RESET ZOOM</button>
                <button class="tf-btn active" id="btn-tf-3s" onclick="setTimeframe('3s')">3S</button>
                <button class="tf-btn" id="btn-tf-1m" onclick="setTimeframe('1m')">1M</button>
                <button class="tf-btn" id="btn-tf-1h" onclick="setTimeframe('1h')">1H</button>
                <button class="tf-btn" id="btn-tf-1d" onclick="setTimeframe('1d')">1D</button>
                <button class="tf-btn" id="btn-tf-1w" onclick="setTimeframe('1w')">1W</button>
                <button class="tf-btn" id="btn-tf-1M" onclick="setTimeframe('1M')">1MO</button>
            </div>
        </div>
        <!-- HUD Tecnico Istituzionale (Valore Live, Massimo, Minimo) -->
        <div class="chart-hud mono">
            <div class="chart-hud-stat">
                <span style="color: var(--text-muted);">LIVE:</span>
                <strong id="hud-live-val" style="color: var(--blue); font-size: 12px;">$0.00</strong>
            </div>
            <div class="chart-hud-stat">
                <span style="color: var(--text-muted);">RANGE:</span>
                <span id="hud-range-val" style="color: var(--text-main); font-size: 10px;">L: $0 &bull; H: $0</span>
            </div>
            <div class="chart-hud-stat">
                <span style="color: var(--text-muted);">TREND:</span>
                <strong id="hud-trend-badge" class="badge mono" style="font-size: 9px; padding: 2px 5px; border-radius: 3px; background: var(--green-bg); color: var(--green);">STABILE</strong>
            </div>
        </div>

        <div class="chart-wrap">
            <canvas id="perfChart"></canvas>
        </div>
        <div class="metrics-bar mono">
            <div class="metric-item"><span>Vol:</span><strong id="metric-volume">$0</strong></div>
            <div class="metric-item"><span>PnL Chiuso:</span><strong id="metric-realized">$0.00</strong></div>
            <div class="metric-item"><span>Win Rate:</span><strong id="metric-winrate">0%</strong></div>
        </div>
    </div>

    <!-- 5. TAB 1: BYBIT POSITIONS (DEFAULT) -->
    <div class="section" id="view-bybit">
        <div class="section-header">
            <span class="section-title">Posizioni Attive Bybit (Futures 24/7)</span>
            <span class="mono" style="font-size: 10px; color: var(--text-muted);">Size: $15k / Macro BTC Shield / TP: +3.6% (1:3 R:R) / SL: -1.2% / BE: +0.8%</span>
        </div>
        <div id="bybit-positions-list">
            <div style="padding: 20px 0; text-align: center; color: var(--text-dim);" class="mono">
                Caricamento posizioni...
            </div>
        </div>
    </div>

    <!-- 6. TAB 2: ALPACA EQUITIES -->
    <div class="section hidden" id="view-alpaca">
        <div class="section-header">
            <span class="section-title">Alpaca Wall Street (NYSE / NASDAQ)</span>
            <span class="mono" style="font-size: 10px; color: var(--text-muted);">Orari: 15:30 - 22:00 CET</span>
        </div>
        <table class="clean-table mono">
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Qty</th>
                    <th>Ingresso</th>
                    <th>Attuale</th>
                    <th>Valore</th>
                    <th>PnL</th>
                </tr>
            </thead>
            <tbody id="alpaca-tbody">
                <tr>
                    <td colspan="6" style="text-align: center; padding: 20px 0; color: var(--text-dim);">
                        Nessun titolo aperto. Wall Street chiusa nel weekend.
                    </td>
                </tr>
            </tbody>
        </table>
    </div>

    <!-- 7. TAB 3: STORICO CHIUSI -->
    <div class="section hidden" id="view-history">
        <div class="section-header">
            <span class="section-title">Storico Trade Chiusi (Bybit)</span>
            <span class="mono" style="font-size: 10px; color: var(--text-muted);" id="closed-count-label">0 eseguiti</span>
        </div>
        <table class="clean-table mono">
            <thead>
                <tr>
                    <th>Ora</th>
                    <th>Simbolo</th>
                    <th>Lato</th>
                    <th>Prezzi</th>
                    <th>Fee</th>
                    <th>PnL Netto</th>
                </tr>
            </thead>
            <tbody id="history-tbody">
                <tr>
                    <td colspan="6" style="text-align: center; padding: 20px 0; color: var(--text-dim);">
                        Nessun trade chiuso di recente.
                    </td>
                </tr>
            </tbody>
        </table>
    </div>

    <!-- 8. TAB 4: GUIDA COMPLETA & MANUALE OPERATIVO -->
    <div class="section hidden" id="view-guide">
        <div class="section-header">
            <span class="section-title">📖 Guida Operativa &amp; Significato Indicatori</span>
            <span class="mono" style="font-size: 10px; color: var(--text-dim);">MANUALE PRATICO</span>
        </div>
        
        <div style="display: flex; flex-direction: column; gap: 14px;">
            
            <!-- Card 1: Monitoraggio Singole Posizioni -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">1. Come Leggere una Posizione Aperta</strong>
                    <span class="badge mono" style="background: var(--blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">TRADE LIVE</span>
                </div>
                <div style="font-size: 12px; color: var(--text-muted); line-height: 1.5; margin-bottom: 10px;">
                    Ogni riga di trade contiene le informazioni essenziali per monitorare il rischio al centesimo:
                </div>
                <div style="background: var(--surface-elevated); padding: 10px; border-radius: 6px; border: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px; font-size: 11px;">
                    <div><strong>• Sizing Dinamico (10% Equity):</strong> La dimensione di ogni posizione viene ricalcolata automaticamente sull'equity totale Bybit (~$16,000 per trade con compounding esponenziale sui guadagni).</div>
                    <div><strong>• PnL Dollari (es. <code>$-1.62</code>):</strong> Il guadagno o la perdita se chiudessi la posizione adesso. Su una size di ~$16,000, un importo di $1.62 è solo rumore di mercato microscopico (0.01%).</div>
                    <div><strong>• PnL Percentuale (es. <code>-0.01%</code>):</strong> La percentuale esatta di scostamento dal tuo prezzo d'ingresso. Verde = in profitto, Rosso = sotto il prezzo d'ingresso.</div>
                    <div><strong>• Badge <code>SL -1.20%</code>:</strong> Il paracadute di sicurezza. Se il trade scende a -1.20% (~-$190), il bot chiude all'istante la posizione impedendo perdite più grandi. Notifica push immediata su Telegram.</div>
                    <div><strong>• Badge <code>BE SAFE +0.20%</code>:</strong> Scatta appena il trade guadagna +0.80%. Lo stop viene alzato a +0.20%: il rischio è azzerato e le commissioni coperte. Notifica push su Telegram.</div>
                    <div><strong>• Badge <code>LOCK +1.00%</code>:</strong> Scatta al +1.60%. Blocca un profitto netto di +1.00% lasciando correre il trade verso il Take Profit (+3.60%). Notifica push su Telegram.</div>
                </div>
            </div>

            <!-- Card 2: Trading Compass & Metriche Quant -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">2. Trading Compass (Diagnostica del Vantaggio)</strong>
                    <span class="badge mono" style="background: var(--green); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">STATISTICA</span>
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px; font-size: 11px; line-height: 1.45;">
                    <div><strong>• Health &amp; Alignment Score (0-100):</strong> Indice sintetico dello stato di salute del trading. Sopra 60 indica forte allineamento col trend; sotto 40 scatta la protezione conservativa.</div>
                    <div><strong>• Expected Value (EV):</strong> Il valore matematico atteso per ogni trade. Se positivo (es. <code>+$45</code>), ogni operazione genera mediamente 45 dollari di profitto nel tempo.</div>
                    <div><strong>• R:R Reale vs Target:</strong> Rapporto tra vincita media e perdita media. Con Take Profit +3.6% e Stop Loss -1.2%, il rapporto target è <strong>1:3.0</strong> (1 euro di rischio per 3 euro di potenziale utile).</div>
                    <div><strong>• Profit Factor:</strong> Rapporto tra tutti i profitti lordi e tutte le perdite lorde. Valori sopra 1.5 indicano un sistema statistico profittevole.</div>
                    <div><strong>• Posizioni in Gain &amp; Break-Even:</strong> Indica quanti dei contratti aperti sono già in attivo e quanti hanno il rischio totalmente azzerato.</div>
                </div>
            </div>

            <!-- Card 3: Regola Aurea Macro BTC Shield -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">3. Lo Scudo Macro BTC 4H (Zero Conflitti)</strong>
                    <span class="badge mono" style="background: var(--amber); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">TREND FOLLOWING</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Per evitare che le posizioni Long e Short si annullino a vicenda o che il bot compri mentre il mercato crolla, il sistema interroga il trend a 4 Ore di Bitcoin:<br>
                    <strong>• Trend Ribassista (BTC &lt; EMA 50):</strong> Il bot apre <strong>esclusivamente posizioni SHORT</strong> sui breakout di debolezza.<br>
                    <strong>• Trend Rialzista (BTC &gt; EMA 50):</strong> Il bot apre <strong>esclusivamente posizioni LONG</strong> sulla forza.<br>
                    <strong>• Risultato:</strong> Tutto il portafoglio spinge nella stessa direzione, evitando perdite incrociate e azzerando le doppie commissioni.
                </div>
            </div>

            <!-- Card 4: Separazione Bybit e Alpaca -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">4. Separazione dei Broker (Crypto vs Wall Street)</strong>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    <strong>• Bybit Futures (UTA):</strong> Opera 24/7 (weekend compreso) sui derivati crypto liquidi (BTC, ETH, SOL, LINK, AVAX, XRP).<br>
                    <strong>• Alpaca Securities (USA):</strong> Opera esclusivamente sulle azioni di Wall Street (NYSE e NASDAQ) dal lunedì al venerdì (15:30 - 22:00 CET). Durante il weekend è giustamente fermo con posizioni chiuse e liquidità protetta in dollari cash.<br>
                    <strong>• Grafici Separati:</strong> Cliccando sui pulsanti sopra il grafico puoi isolare il rendimento del solo broker crypto o delle sole azioni americane.
                </div>
            </div>

            <!-- Card 5: Timeframe e Grafico Zoomabile -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">5. Timeframe e Zoom Interattivo</strong>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    <strong>• Timeframe (3S, 1M, 1H, 1D, 1W, 1MO):</strong> Permette di visualizzare sia il micro-tick in tempo reale che l'andamento a lungo termine fino a 30 giorni.<br>
                    <strong>• Zoom su iPhone:</strong> Pizzica con due dita direttamente sul grafico per ingrandire o rimpicciolire qualsiasi candela. Clicca <code>🔍 RESET ZOOM</code> per tornare alla panoramica.<br>
                    <strong>• Tooltip al Tocco:</strong> Tocca con il dito qualsiasi punto o numero per leggere la guida contestuale immediata.
                </div>
            </div>

        </div>
    </div>

    <!-- BOTTOM TABBAR IPHONE -->
    <nav class="tabbar">
        <button class="tab-item active" id="tab-btn-bybit" onclick="showTab('bybit')">
            <span>Bybit Futures</span>
            <span class="dot"></span>
        </button>
        <button class="tab-item" id="tab-btn-alpaca" onclick="showTab('alpaca')">
            <span>Alpaca USA</span>
            <span class="dot"></span>
        </button>
        <button class="tab-item" id="tab-btn-history" onclick="showTab('history')">
            <span>Storico</span>
            <span class="dot"></span>
        </button>
        <button class="tab-item" id="tab-btn-guide" onclick="showTab('guide')">
            <span>📖 Guida Desk</span>
            <span class="dot"></span>
        </button>
    </nav>

    <script>
        let chartInstance = null;
        let currentTimeframe = '3s';
        let currentInstance = 'bybit'; // 'bybit' | 'alpaca' | 'total'
        let chartMode = 'usd'; // 'usd' | 'pct'

        function setChartMode(mode) {
            chartMode = mode;
            document.getElementById('btn-mode-usd').classList.toggle('active', mode === 'usd');
            document.getElementById('btn-mode-pct').classList.toggle('active', mode === 'pct');
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }
            fetchData();
        }

        function resetChartZoom() {
            if (chartInstance && typeof chartInstance.resetZoom === 'function') {
                chartInstance.resetZoom();
                const rBtn = document.getElementById('btn-reset-zoom');
                if (rBtn) rBtn.style.display = 'none';
            }
        }

        function setChartInstance(inst) {
            currentInstance = inst;
            ['bybit', 'alpaca', 'total'].forEach(i => {
                const btn = document.getElementById('btn-inst-' + i);
                if (btn) {
                    if (i === inst) btn.classList.add('active');
                    else btn.classList.remove('active');
                }
            });
            const titleEl = document.getElementById('chart-instance-title');
            if (titleEl) {
                if (inst === 'bybit') titleEl.innerText = 'Grafico: Bybit Futures (Crypto 24/7)';
                else if (inst === 'alpaca') titleEl.innerText = 'Grafico: Alpaca (Wall Street USA)';
                else titleEl.innerText = 'Grafico: Portafoglio Totale Consolidato';
            }
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }
            fetchData();
        }

        // GESTIONE TEMA LIGHT / DARK CON LOCALSTORAGE
        function initTheme() {
            const savedTheme = localStorage.getItem('sentinel_theme') || 'light';
            document.documentElement.setAttribute('data-theme', savedTheme);
            updateThemeButtonText(savedTheme);
        }

        function toggleTheme() {
            const current = document.documentElement.getAttribute('data-theme') || 'light';
            const next = current === 'light' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('sentinel_theme', next);
            updateThemeButtonText(next);
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
                fetchData();
            }
        }

        function updateThemeButtonText(theme) {
            const btn = document.getElementById('theme-btn');
            if (btn) {
                btn.innerText = theme === 'light' ? '🌙 DARK' : '☀️ LIGHT';
            }
        }
        initTheme();

        function showTab(tabName) {
            ['bybit', 'alpaca', 'history', 'guide'].forEach(t => {
                const view = document.getElementById('view-' + t);
                const btn = document.getElementById('tab-btn-' + t);
                if (t === tabName) {
                    view.classList.remove('hidden');
                    btn.classList.add('active');
                } else {
                    view.classList.add('hidden');
                    btn.classList.remove('active');
                }
            });
            // Separazione istanze: quando navigo su Bybit o Alpaca sincronizza il grafico corrispondente
            if (tabName === 'bybit') {
                setChartInstance('bybit');
            } else if (tabName === 'alpaca') {
                setChartInstance('alpaca');
            }
        }

        function setTimeframe(tf) {
            currentTimeframe = tf;
            ['3s', '1m', '1h', '1d', '1w', '1M'].forEach(t => {
                const btn = document.getElementById('btn-tf-' + t);
                if (btn) {
                    if (t === tf) btn.classList.add('active');
                    else btn.classList.remove('active');
                }
                const card = document.getElementById('card-tf-' + t);
                if (card) {
                    if (t === tf) card.classList.add('active');
                    else card.classList.remove('active');
                }
            });
            fetchData();
        }

        function updateClock() {
            const now = new Date();
            document.getElementById('top-clock').innerText = now.toLocaleTimeString('it-IT');
        }
        setInterval(updateClock, 1000);
        updateClock();

        function initChart(snapshots) {
            try {
                if (typeof Chart === 'undefined') return;
                const canvas = document.getElementById('perfChart');
                if (!canvas) return;
                const ctx = canvas.getContext('2d');

                const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
                const gridColor = isDark ? 'rgba(35, 49, 80, 0.4)' : 'rgba(226, 232, 240, 0.7)';
                const tickColor = isDark ? '#94a3b8' : '#64748b';

                const labels = snapshots.map(s => {
                    const d = new Date(s.epoch * 1000);
                    if (currentTimeframe === '1d' || currentTimeframe === '1w' || currentTimeframe === '1M') {
                        return d.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' }) + ' ' + d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
                    }
                    return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: (currentTimeframe === '3s' ? '2-digit' : undefined) });
                });
                // Estrazione dati separati al 100% in base all'istanza selezionata
                let equity = [];
                let pnl = [];
                let labelName = 'Capitale Bybit ($)';
                let pnlName = 'PnL Chiuso Bybit ($)';

                const baseEq = (currentInstance === 'bybit' ? snapshots[0].bybit_equity : (currentInstance === 'alpaca' ? snapshots[0].alpaca_equity : snapshots[0].total_equity)) || 1.0;

                if (chartMode === 'pct') {
                    // Modalità %: calcola la variazione percentuale progressiva rispetto all'inizio del grafico
                    if (currentInstance === 'bybit') {
                        equity = snapshots.map(s => parseFloat(((s.bybit_equity - baseEq) / baseEq * 100).toFixed(3)));
                        pnl = snapshots.map(s => parseFloat((s.cumulative_realized_pnl / baseEq * 100).toFixed(3)));
                        labelName = 'Rendimento Bybit (%)';
                        pnlName = 'PnL Chiuso Bybit (%)';
                    } else if (currentInstance === 'alpaca') {
                        equity = snapshots.map(s => parseFloat(((s.alpaca_equity - baseEq) / baseEq * 100).toFixed(3)));
                        pnl = snapshots.map(s => 0);
                        labelName = 'Rendimento Alpaca (%)';
                        pnlName = 'PnL Alpaca (%)';
                    } else {
                        equity = snapshots.map(s => parseFloat(((s.total_equity - baseEq) / baseEq * 100).toFixed(3)));
                        pnl = snapshots.map(s => parseFloat((s.cumulative_realized_pnl / baseEq * 100).toFixed(3)));
                        labelName = 'Rendimento Totale (%)';
                        pnlName = 'PnL Consolidato (%)';
                    }
                } else {
                    // Modalità $: visualizza in Dollari
                    if (currentInstance === 'bybit') {
                        equity = snapshots.map(s => s.bybit_equity);
                        pnl = snapshots.map(s => s.cumulative_realized_pnl);
                        labelName = 'Capitale Bybit ($)';
                        pnlName = 'PnL Realizzato Bybit ($)';
                    } else if (currentInstance === 'alpaca') {
                        equity = snapshots.map(s => s.alpaca_equity);
                        pnl = snapshots.map(s => 0);
                        labelName = 'Portfolio Alpaca ($)';
                        pnlName = 'PnL Alpaca ($)';
                    } else {
                        equity = snapshots.map(s => s.total_equity);
                        pnl = snapshots.map(s => s.cumulative_realized_pnl);
                        labelName = 'Capitale Totale ($)';
                        pnlName = 'PnL Consolidato ($)';
                    }
                }

                // Calcolo statistiche HUD tecnico (Live, Min, Max)
                try {
                    const validEq = equity.filter(v => typeof v === 'number' && !isNaN(v));
                    if (validEq.length > 0) {
                        const curVal = validEq[validEq.length - 1];
                        const minVal = Math.min(...validEq);
                        const maxVal = Math.max(...validEq);
                        const firstVal = validEq[0];
                        const isUp = curVal >= firstVal;

                        const hudLive = document.getElementById('hud-live-val');
                        if (hudLive) {
                            hudLive.innerText = (chartMode === 'pct') ? (curVal >= 0 ? '+' : '') + curVal.toFixed(2) + '%' : '$' + curVal.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                        }
                        const hudRange = document.getElementById('hud-range-val');
                        if (hudRange) {
                            if (chartMode === 'pct') {
                                hudRange.innerText = `L: ${minVal.toFixed(2)}% • H: ${maxVal.toFixed(2)}%`;
                            } else {
                                hudRange.innerText = `L: $${(minVal/1000).toFixed(1)}k • H: $${(maxVal/1000).toFixed(1)}k`;
                            }
                        }
                        const hudTrend = document.getElementById('hud-trend-badge');
                        if (hudTrend) {
                            hudTrend.innerText = isUp ? 'RIALZISTA ↗' : 'FLESSIONE ↘';
                            hudTrend.style.background = isUp ? 'var(--green-bg)' : 'var(--red-bg)';
                            hudTrend.style.color = isUp ? 'var(--green)' : 'var(--red)';
                        }
                    }
                } catch (e_hud) {
                    console.error("HUD error:", e_hud);
                }

                // Media Mobile Semplice a 9 periodi per evidenziare la direzione tecnica del trend
                const smaPeriod = 9;
                const smaData = equity.map((val, idx, arr) => {
                    if (idx < smaPeriod - 1) return null;
                    const slice = arr.slice(idx - smaPeriod + 1, idx + 1);
                    const avg = slice.reduce((a, b) => a + b, 0) / smaPeriod;
                    return parseFloat(avg.toFixed(3));
                });

                const gradient = ctx.createLinearGradient(0, 0, 0, 250);
                if (isDark) {
                    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.28)');
                    gradient.addColorStop(1, 'rgba(59, 130, 246, 0.00)');
                } else {
                    gradient.addColorStop(0, 'rgba(37, 99, 235, 0.16)');
                    gradient.addColorStop(1, 'rgba(37, 99, 235, 0.00)');
                }

                const lineColor = isDark ? '#38bdf8' : '#0284c7';
                const smaColor = isDark ? '#fbbf24' : '#d97706';
                const pnlColor = isDark ? '#4ade80' : '#16a34a';

                if (chartInstance) {
                    chartInstance.data.labels = labels;
                    chartInstance.data.datasets[0].data = equity;
                    chartInstance.data.datasets[0].label = labelName;
                    chartInstance.data.datasets[0].borderColor = lineColor;
                    chartInstance.data.datasets[0].backgroundColor = gradient;
                    chartInstance.data.datasets[1].data = smaData;
                    chartInstance.data.datasets[1].borderColor = smaColor;
                    chartInstance.data.datasets[2].data = pnl;
                    chartInstance.data.datasets[2].label = pnlName;
                    chartInstance.data.datasets[2].borderColor = pnlColor;
                    chartInstance.update('none');
                    return;
                }

                chartInstance = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                label: labelName,
                                data: equity,
                                borderColor: lineColor,
                                borderWidth: 2.4,
                                backgroundColor: gradient,
                                pointRadius: 0,
                                pointHoverRadius: 5,
                                pointHoverBackgroundColor: lineColor,
                                pointHoverBorderColor: '#fff',
                                pointHoverBorderWidth: 2,
                                tension: 0.15,
                                fill: true,
                                yAxisID: 'y'
                            },
                            {
                                label: 'Media Mobile SMA (9)',
                                data: smaData,
                                borderColor: smaColor,
                                borderWidth: 1.6,
                                borderDash: [5, 4],
                                backgroundColor: 'transparent',
                                pointRadius: 0,
                                pointHoverRadius: 0,
                                tension: 0.2,
                                yAxisID: 'y'
                            },
                            {
                                label: pnlName,
                                data: pnl,
                                borderColor: pnlColor,
                                borderWidth: 1.6,
                                backgroundColor: 'transparent',
                                pointRadius: 0,
                                pointHoverRadius: 4,
                                tension: 0.1,
                                yAxisID: 'y1'
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        interaction: {
                            mode: 'index',
                            intersect: false,
                        },
                        plugins: {
                            zoom: {
                                pan: {
                                    enabled: true,
                                    mode: 'x',
                                    onPanComplete: function() {
                                        const rBtn = document.getElementById('btn-reset-zoom');
                                        if (rBtn) rBtn.style.display = 'inline-block';
                                    }
                                },
                                zoom: {
                                    wheel: {
                                        enabled: true,
                                        speed: 0.1
                                    },
                                    pinch: {
                                        enabled: true
                                    },
                                    mode: 'x',
                                    onZoomComplete: function() {
                                        const rBtn = document.getElementById('btn-reset-zoom');
                                        if (rBtn) rBtn.style.display = 'inline-block';
                                    }
                                }
                            },
                            legend: {
                                display: true,
                                position: 'top',
                                align: 'end',
                                labels: {
                                    boxWidth: 8,
                                    boxHeight: 8,
                                    color: tickColor,
                                    font: { family: 'SF Mono, monospace', size: 10 }
                                }
                            },
                            tooltip: {
                                backgroundColor: isDark ? '#1e293b' : '#ffffff',
                                titleColor: isDark ? '#f8fafc' : '#0f172a',
                                bodyColor: isDark ? '#94a3b8' : '#334155',
                                borderColor: isDark ? '#334155' : '#e2e8f0',
                                borderWidth: 1,
                                padding: 10,
                                callbacks: {
                                    label: function(context) {
                                        let label = context.dataset.label || '';
                                        if (label) label += ': ';
                                        if (context.parsed.y !== null) {
                                            if (chartMode === 'pct') {
                                                const s = context.parsed.y >= 0 ? '+' : '';
                                                label += s + context.parsed.y.toFixed(2) + '%';
                                            } else {
                                                label += '$' + context.parsed.y.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                                            }
                                        }
                                        return label;
                                    }
                                }
                            }
                        },
                        scales: {
                            x: {
                                grid: { color: gridColor },
                                ticks: { color: tickColor, font: { family: 'SF Mono, monospace', size: 9 }, maxTicksLimit: 6 }
                            },
                            y: {
                                position: 'left',
                                grid: { color: gridColor },
                                ticks: {
                                    color: lineColor,
                                    font: { family: 'SF Mono, monospace', size: 9 },
                                    callback: function(val) {
                                        if (chartMode === 'pct') {
                                            return (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
                                        }
                                        return '$' + (val / 1000).toFixed(1) + 'k';
                                    }
                                }
                            },
                            y1: {
                                position: 'right',
                                grid: { drawOnChartArea: false },
                                ticks: {
                                    color: pnlColor,
                                    font: { family: 'SF Mono, monospace', size: 9 },
                                    callback: function(val) {
                                        if (chartMode === 'pct') {
                                            return (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
                                        }
                                        return (val >= 0 ? '+' : '') + '$' + val.toFixed(0);
                                    }
                                }
                            }
                        }
                    }
                });
            } catch (errChart) {
                console.error("Chart render error:", errChart);
            }
        }

        let consecutiveErrors = 0;

        async function fetchData() {
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 4000);
                const res = await fetch(`/api/dashboard?tf=${currentTimeframe}`, { cache: 'no-store', signal: controller.signal });
                clearTimeout(timeoutId);
                
                if (!res.ok) throw new Error('HTTP ' + res.status);
                const data = await res.json();
                renderUI(data);
                consecutiveErrors = 0;
                document.querySelector('.status-dot').style.background = 'var(--green)';
            } catch (e) {
                console.error("Dashboard sync error:", e);
                consecutiveErrors++;
                document.querySelector('.status-dot').style.background = 'var(--red)';
                if (consecutiveErrors <= 3) {
                    setTimeout(fetchData, 1500);
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
            const history = data.perf_history || [];
            const variations = data.variations || {};
            const compass = data.compass || {};

            // 1. Trading Compass & Edge Score (RENDERIZZAZIONE IMMEDIATA E PROTETTA)
            try {
                const cScore = typeof compass.health_score === 'number' ? compass.health_score : 50;
                const scoreEl = document.getElementById('compass-score-val');
                if (scoreEl) scoreEl.innerText = cScore;
                
                const badgeEl = document.getElementById('compass-badge-el');
                if (badgeEl) {
                    badgeEl.innerText = compass.verdict || 'ALLINEATO';
                    const col = compass.verdict_color || 'amber';
                    badgeEl.className = 'compass-badge badge-' + col + ' mono';
                    if (scoreEl) {
                        scoreEl.style.color = (col === 'green' ? 'var(--green)' : (col === 'red' ? 'var(--red)' : 'var(--amber)'));
                    }
                }

                const descEl = document.getElementById('compass-desc-el');
                if (descEl) descEl.innerText = compass.verdict_desc || 'Parametri quantitativi monitorati regolarmente.';

                // 4 Diag Metrics
                const evEl = document.getElementById('diag-ev-val');
                if (evEl) {
                    const evVal = compass.expected_value_usd || 0;
                    const evSign = evVal >= 0 ? '+' : '';
                    evEl.innerText = `${evSign}$${evVal.toFixed(2)}`;
                    evEl.className = 'diag-val ' + (evVal >= 0 ? 'val-up' : 'val-down');
                }

                const rrEl = document.getElementById('diag-rr-val');
                if (rrEl) rrEl.innerText = `1:${(compass.realized_rr || 0).toFixed(1)}`;

                const itmEl = document.getElementById('diag-itm-val');
                if (itmEl) itmEl.innerText = `${compass.open_itm_ratio || 0}%`;

                const protSub = document.getElementById('diag-prot-sub');
                if (protSub) protSub.innerText = `${compass.protected_positions_count || 0} a Break-Even`;

                const pfEl = document.getElementById('diag-pf-val');
                if (pfEl) pfEl.innerText = (compass.profit_factor || 0).toFixed(2);
            } catch (errCompass) {
                console.error("Compass render error:", errCompass);
            }

            // 2. Acc Summary
            const bEq = bWallet.total_equity || 0;
            const aEq = parseFloat(aAcc.portfolio_value || 0);
            const totalEq = bEq + aEq;

            document.getElementById('total-equity').innerText = '$' + totalEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            document.getElementById('bybit-equity').innerText = '$' + bEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            
            const usdtCash = (bWallet.coins && bWallet.coins.USDT) ? bWallet.coins.USDT : (bWallet.available_balance || 0);
            document.getElementById('bybit-cash').innerText = 'Disponibile: $' + usdtCash.toLocaleString('en-US', {maximumFractionDigits: 0}) + ' USDT';

            document.getElementById('alpaca-equity').innerText = '$' + aEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            document.getElementById('alpaca-bp').innerText = 'BP: $' + parseFloat(aAcc.buying_power || 0).toLocaleString('en-US', {maximumFractionDigits: 0});

            // PnL & Posizioni Bybit
            let totPnl = 0;
            bPositions.forEach(p => { totPnl += p.unrealized_pnl || 0; });
            const pnlEl = document.getElementById('total-unrealized');
            const sign = totPnl >= 0 ? '+' : '';
            pnlEl.innerText = `${sign}$${totPnl.toFixed(2)}`;
            pnlEl.className = 'acc-val ' + (totPnl >= 0 ? 'val-up' : 'val-down');
            document.getElementById('active-positions-count').innerText = `${bPositions.length} posizioni`;

            // 3. Variazioni Multi-Timeframe (Separazione Istanza Istantanea)
            ['3s', '1m', '1h', '1d', '1w', '1M'].forEach(tf => {
                const baseV = variations[tf] || { delta_equity: 0, delta_equity_pct: 0 };
                let targetDelta = baseV.delta_equity;
                let targetPct = baseV.delta_equity_pct;

                if (currentInstance === 'bybit' && baseV.bybit) {
                    targetDelta = baseV.bybit.delta_equity;
                    targetPct = baseV.bybit.delta_equity_pct;
                } else if (currentInstance === 'alpaca' && baseV.alpaca) {
                    targetDelta = baseV.alpaca.delta_equity;
                    targetPct = baseV.alpaca.delta_equity_pct;
                }

                const vVal = document.getElementById(`delta-${tf}-val`);
                const vPct = document.getElementById(`delta-${tf}-pct`);
                if (vVal && vPct) {
                    const dSign = targetDelta >= 0 ? '+' : '';
                    vVal.innerText = `${dSign}$${targetDelta.toFixed(2)}`;
                    vPct.innerText = `${dSign}${targetPct.toFixed(2)}%`;

                    const vClass = targetDelta > 0 ? 'val-up' : (targetDelta < 0 ? 'val-down' : 'val-neutral');
                    vVal.className = `tf-delta ${vClass}`;
                    vPct.className = `tf-pct ${vClass}`;
                }
            });

            // 4. Metrics & Chart
            let cumVol = 0;
            let cumPnl = 0;
            let wins = 0;
            bClosed.forEach(c => {
                const p = parseFloat(c.closedPnl || 0);
                cumPnl += p;
                cumVol += (parseFloat(c.cumExitValue || 0) + parseFloat(c.cumEntryValue || 0));
                if (p > 0) wins++;
            });
            document.getElementById('metric-volume').innerText = '$' + (cumVol / 1000).toFixed(0) + 'k';
            const rpEl = document.getElementById('metric-realized');
            rpEl.innerText = `${cumPnl >= 0 ? '+' : ''}$${cumPnl.toFixed(2)}`;
            rpEl.className = cumPnl >= 0 ? 'val-up' : 'val-down';

            const wr = bClosed.length > 0 ? (wins / bClosed.length * 100).toFixed(0) : 0;
            document.getElementById('metric-winrate').innerText = `${wr}% (${wins}/${bClosed.length})`;

            if (history.length > 0) {
                initChart(history);
            }

            // 5. Bybit Positions Row-List
            const listEl = document.getElementById('bybit-positions-list');
            if (bPositions.length === 0) {
                listEl.innerHTML = `<div style="padding: 24px 0; text-align: center; color: var(--text-dim);" class="mono">Nessuna posizione aperta. Monitoraggio breakout in corso.</div>`;
            } else {
                listEl.innerHTML = bPositions.map((p, idx) => {
                    const isLong = p.side === 'BUY';
                    const sideClass = isLong ? 'trade-side-long' : 'trade-side-short';
                    const sideText = isLong ? 'LONG' : 'SHORT';
                    const pSign = p.unrealized_pnl >= 0 ? '+' : '';
                    const pnlClass = p.unrealized_pnl >= 0 ? 'val-up' : 'val-down';

                    let guardHtml = `<span class="trade-guard" data-tip="Stop Loss attivo: chiusura automatica protettiva se la posizione perde l'1.20%">SL -1.20%</span>`;
                    if (p.pnl_pct >= 1.60) {
                        guardHtml = `<span class="trade-guard guard-lock" data-tip="Trailing Profit Lock attivo: stop alzato per garantire almeno il +1.00% netto">LOCK +1.00%</span>`;
                    } else if (p.pnl_pct >= 0.80) {
                        guardHtml = `<span class="trade-guard guard-be" data-tip="Break-Even Safe attivo: rischio azzerato, stop a +0.20% netto">BE SAFE +0.20%</span>`;
                    }

                    // Calcolo Target Progress Bar
                    const entry = p.entry_price || 1;
                    const mark = p.mark_price || entry;
                    const sl = p.stop_loss || (isLong ? entry * 0.988 : entry * 1.012);
                    const tp = p.take_profit || (isLong ? entry * 1.036 : entry * 0.964);

                    // Calcolo percentuale di completamento verso TP (+3.60%)
                    const pctGain = p.pnl_pct || 0;
                    const tpProgress = Math.max(0, Math.min(100, (pctGain / 3.60) * 100));
                    const progressColor = pctGain >= 1.60 ? 'var(--amber)' : (pctGain > 0 ? 'var(--green)' : 'var(--red)');

                    // Canvas ID per mini-candlestick / sparkline
                    const sparkId = `sparkline-pos-${idx}`;

                    return `
                        <div class="trade-row mono">
                            <div class="trade-row-top">
                                <div class="trade-left">
                                    <div class="trade-symbol-row">
                                        <span class="trade-symbol">${p.symbol}</span>
                                        <span class="${sideClass}">${sideText}</span>
                                    </div>
                                    <div class="trade-detail">
                                        In: $${entry.toFixed(4)} &rarr; Mark: $${mark.toFixed(4)}
                                    </div>
                                    <div class="trade-detail" style="color: var(--text-dim);">
                                        Size: ${p.size} ($${(p.position_value || 0).toLocaleString('en-US', {maximumFractionDigits: 0})})
                                    </div>
                                </div>
                                <div class="trade-right">
                                    <div class="trade-pnl ${pnlClass}" data-tip="PnL non realizzato fluttuante in dollari">
                                        ${pSign}$${p.unrealized_pnl.toFixed(2)}
                                    </div>
                                    <div style="font-size: 11px;" class="${pnlClass}" data-tip="Rendimento percentuale calcolato sul notionale dinamico (10% equity)">
                                        ${pSign}${p.pnl_pct.toFixed(2)}%
                                    </div>
                                    ${guardHtml}
                                </div>
                            </div>

                            <!-- Mini Sparkline Candlestick & Target R:R Progress -->
                            <div class="trade-chart-box">
                                <canvas id="${sparkId}" class="trade-sparkline-canvas" width="110" height="30"></canvas>
                                <div class="trade-target-levels">
                                    <div class="target-level-row">
                                        <span style="color: var(--text-dim);">TP (+3.6%): <b style="color: var(--green);">$${tp.toFixed(4)}</b></span>
                                        <span style="color: var(--text-dim);">SL (-1.2%): <b style="color: var(--red);">$${sl.toFixed(4)}</b></span>
                                    </div>
                                    <div class="target-bar-bg" data-tip="Avanzamento verso il Target Take Profit istituzionale (+3.60%)">
                                        <div class="target-bar-fill" style="width: ${tpProgress.toFixed(0)}%; background: ${progressColor};"></div>
                                    </div>
                                    <div class="target-level-row" style="color: var(--text-dim); font-size: 9px;">
                                        <span>Distanza TP: ${(3.60 - pctGain).toFixed(2)}%</span>
                                        <span>Progresso: ${tpProgress.toFixed(0)}%</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');

                // Renderizza le mini-sparkline su ciascun canvas
                bPositions.forEach((p, idx) => {
                    const sparkEl = document.getElementById(`sparkline-pos-${idx}`);
                    if (!sparkEl || !p.sparkline || p.sparkline.length < 2) return;
                    const sCtx = sparkEl.getContext('2d');
                    const pts = p.sparkline;
                    const w = sparkEl.width;
                    const h = sparkEl.height;
                    const minP = Math.min(...pts);
                    const maxP = Math.max(...pts);
                    const range = (maxP - minP) || 0.0001;

                    sCtx.clearRect(0, 0, w, h);
                    sCtx.beginPath();
                    sCtx.lineWidth = 1.8;
                    const isGain = p.unrealized_pnl >= 0;
                    sCtx.strokeStyle = isGain ? '#10b981' : '#ef4444';

                    pts.forEach((pt, i) => {
                        const x = (i / (pts.length - 1)) * (w - 6) + 3;
                        const y = h - 4 - ((pt - minP) / range) * (h - 8);
                        if (i === 0) sCtx.moveTo(x, y);
                        else sCtx.lineTo(x, y);
                    });
                    sCtx.stroke();

                    // Disegna punto finale live
                    const lastX = w - 3;
                    const lastY = h - 4 - ((pts[pts.length - 1] - minP) / range) * (h - 8);
                    sCtx.beginPath();
                    sCtx.arc(lastX, lastY, 2.5, 0, Math.PI * 2);
                    sCtx.fillStyle = isGain ? '#10b981' : '#ef4444';
                    sCtx.fill();
                });
            }

            // 6. Alpaca Table
            const aBody = document.getElementById('alpaca-tbody');
            if (aPositions.length === 0) {
                aBody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 20px 0; color: var(--text-dim);">Nessun titolo aperto. Wall Street chiusa nel weekend.</td></tr>`;
            } else {
                aBody.innerHTML = aPositions.map(ap => {
                    const u = parseFloat(ap.unrealized_pl || 0);
                    const uClass = u >= 0 ? 'val-up' : 'val-down';
                    const uSign = u >= 0 ? '+' : '';
                    return `
                        <tr>
                            <td style="font-weight: 700; color: var(--text-main);">${ap.symbol}</td>
                            <td>${ap.qty}</td>
                            <td>$${parseFloat(ap.avg_entry_price || 0).toFixed(2)}</td>
                            <td>$${parseFloat(ap.current_price || 0).toFixed(2)}</td>
                            <td>$${parseFloat(ap.market_value || 0).toFixed(2)}</td>
                            <td class="${uClass}">${uSign}$${u.toFixed(2)}</td>
                        </tr>
                    `;
                }).join('');
            }

            // 7. History Table
            document.getElementById('closed-count-label').innerText = `${bClosed.length} eseguiti`;
            const hBody = document.getElementById('history-tbody');
            if (bClosed.length === 0) {
                hBody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 20px 0; color: var(--text-dim);">Nessun trade chiuso recente.</td></tr>`;
            } else {
                hBody.innerHTML = bClosed.slice(0, 15).map(c => {
                    const pVal = parseFloat(c.closedPnl || 0);
                    const pClass = pVal >= 0 ? 'val-up' : 'val-down';
                    const pSign = pVal >= 0 ? '+' : '';
                    const timeStr = c.updatedTime ? new Date(parseInt(c.updatedTime)).toLocaleTimeString('it-IT') : '--:--';
                    return `
                        <tr>
                            <td style="color: var(--text-muted);">${timeStr}</td>
                            <td style="font-weight: 700; color: var(--text-main);">${c.symbol}</td>
                            <td>${c.side}</td>
                            <td>$${parseFloat(c.avgEntryPrice || 0).toFixed(3)} &rarr; $${parseFloat(c.avgExitPrice || 0).toFixed(3)}</td>
                            <td style="color: var(--text-dim);">$${(parseFloat(c.openFee || 0) + parseFloat(c.closeFee || 0)).toFixed(2)}</td>
                            <td class="${pClass}">${pSign}$${pVal.toFixed(2)}</td>
                        </tr>
                    `;
                }).join('');
            }
        }

        fetchData();
        setInterval(fetchData, 5000);
    </script>
</body>
</html>
"""

async def handle_dashboard_page(request):
    """Serve la pagina HTML della dashboard."""
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")

import asyncio
import time

_CACHE_STORE = {}
_LAST_CACHE_TIME = 0.0
_CACHE_TTL = 3.5  # Stabilizzazione visiva numeri  # Risposte istantanee in <10ms riutilizzando la cache recente di 1.8s

def _fetch_all_live_data_sync(tf: str):
    """Worker sincrono eseguito in thread worker per chiamare Bybit e Alpaca senza bloccare l'event loop."""
    global _bybit_service, _alpaca_service
    if not _bybit_service:
        _bybit_service = BybitExecutionService()
    if not _alpaca_service:
        _alpaca_service = AlpacaExecutionService()

    try:
        b_wallet = _bybit_service.get_wallet_summary()
    except Exception:
        b_wallet = {}

    try:
        b_pos = _bybit_service.get_open_positions()
    except Exception:
        b_pos = []

    try:
        b_closed_res = _bybit_service.session.get_closed_pnl(category="linear", limit=25)
        b_closed = b_closed_res.get("result", {}).get("list", [])
    except Exception:
        b_closed = []

    try:
        a_summary = _alpaca_service.get_account_summary()
    except Exception:
        a_summary = {}

    b_eq = float(b_wallet.get("total_equity", 0.0) or 0.0)
    a_eq = float(a_summary.get("account", {}).get("portfolio_value", 0.0) or 0.0)
    tot_eq = b_eq + a_eq
    unreal_pnl = sum(p.get("unrealized_pnl", 0.0) for p in b_pos)
    cum_real = sum(float(c.get("closedPnl", 0.0)) for c in b_closed)
    cum_vol = sum(float(c.get("cumExitValue", 0.0)) + float(c.get("cumEntryValue", 0.0)) for c in b_closed)

    try:
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

    history = perf_tracker.get_timeframe_history(tf)
    variations = perf_tracker.get_variations(tot_eq, cum_real, bybit_eq=b_eq, alpaca_eq=a_eq)
    compass_metrics = trading_compass.compute_edge_metrics(b_closed, b_pos, tot_eq)

    return {
        "status": "online",
        "timestamp": datetime.now(ZoneInfo("Europe/Rome")).isoformat(),
        "timeframe": tf,
        "compass": compass_metrics,
        "bybit": {
            "wallet": b_wallet,
            "positions": b_pos,
            "closed": b_closed
        },
        "alpaca": {
            "account": a_summary.get("account", {}),
            "positions": a_summary.get("positions", [])
        },
        "perf_history": history,
        "variations": variations
    }

async def handle_dashboard_api(request):
    """Restituisce il payload JSON iper-reattivo in <10ms via thread pool asincrono e cache intelligente."""
    global _CACHE_STORE, _LAST_CACHE_TIME
    tf = request.query.get("tf", "3s")
    now_t = time.time()

    # Se abbiamo un payload recente in cache con lo stesso timeframe, restituiscilo ISTANTANEAMENTE
    if tf in _CACHE_STORE and (now_t - _CACHE_STORE[tf]["cached_at"]) < _CACHE_TTL:
        return web.json_response(_CACHE_STORE[tf]["data"])

    try:
        # Offload in thread separato per evitare qualsiasi lag dell'event loop
        data = await asyncio.to_thread(_fetch_all_live_data_sync, tf)
        _CACHE_STORE[tf] = {
            "data": data,
            "cached_at": now_t
        }
        return web.json_response(data)
    except Exception as e:
        # Se c'è errore ma abbiamo una cache precedente, rispondi con quella (Zero Downtime / Zero Schermata Bianca)
        if tf in _CACHE_STORE:
            return web.json_response(_CACHE_STORE[tf]["data"])
        return web.json_response({"error": str(e), "status": "recovering"}, status=200)

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
