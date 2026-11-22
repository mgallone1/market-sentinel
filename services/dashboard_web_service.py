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
            height: 180px;
            position: relative;
            margin-top: 8px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 8px;
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
            padding: 10px 14px;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 1px 2px rgba(0,0,0,0.02);
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
                <div class="diag-cell">
                    <div class="diag-label">Expected Value (EV)</div>
                    <div class="diag-val" id="diag-ev-val">$0.00</div>
                    <div class="diag-sub">Utile atteso per trade</div>
                </div>
                <div class="diag-cell">
                    <div class="diag-label">R:R Reale vs Target</div>
                    <div class="diag-val" id="diag-rr-val">1:0.0</div>
                    <div class="diag-sub">Target min: 1:2.5</div>
                </div>
                <div class="diag-cell">
                    <div class="diag-label">Posizioni in Gain</div>
                    <div class="diag-val" id="diag-itm-val">0%</div>
                    <div class="diag-sub" id="diag-prot-sub">0 protette Break-Even</div>
                </div>
                <div class="diag-cell">
                    <div class="diag-label">Profit Factor</div>
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
                <div class="acc-label">Equity Totale</div>
                <div class="acc-val" id="total-equity">$0.00</div>
                <div class="acc-sub">Bybit + Alpaca</div>
            </div>
            <div class="acc-cell">
                <div class="acc-label">Bybit UTA</div>
                <div class="acc-val" id="bybit-equity">$0.00</div>
                <div class="acc-sub" id="bybit-cash">Disponibile: $0</div>
            </div>
            <div class="acc-cell">
                <div class="acc-label">Alpaca Equities</div>
                <div class="acc-val" id="alpaca-equity">$0.00</div>
                <div class="acc-sub" id="alpaca-bp">BP: $0</div>
            </div>
            <div class="acc-cell">
                <div class="acc-label">PnL Non Realizzato</div>
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
                <div class="tf-header">Ogni 3s</div>
                <div class="tf-delta" id="delta-3s-val">$0.00</div>
                <div class="tf-pct" id="delta-3s-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1m" onclick="setTimeframe('1m')">
                <div class="tf-header">1 Minuto</div>
                <div class="tf-delta" id="delta-1m-val">$0.00</div>
                <div class="tf-pct" id="delta-1m-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1h" onclick="setTimeframe('1h')">
                <div class="tf-header">1 Ora</div>
                <div class="tf-delta" id="delta-1h-val">$0.00</div>
                <div class="tf-pct" id="delta-1h-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1d" onclick="setTimeframe('1d')">
                <div class="tf-header">1 Giorno</div>
                <div class="tf-delta" id="delta-1d-val">$0.00</div>
                <div class="tf-pct" id="delta-1d-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1w" onclick="setTimeframe('1w')">
                <div class="tf-header">1 Settimana</div>
                <div class="tf-delta" id="delta-1w-val">$0.00</div>
                <div class="tf-pct" id="delta-1w-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1M" onclick="setTimeframe('1M')">
                <div class="tf-header">1 Mese</div>
                <div class="tf-delta" id="delta-1M-val">$0.00</div>
                <div class="tf-pct" id="delta-1M-pct">0.00%</div>
            </div>
        </div>
    </div>

    <!-- 4. INTERACTIVE CHART CON CONTROLLO TIMEFRAME -->
    <div class="section">
        <div class="section-header">
            <span class="section-title">Traiettoria Grafico</span>
            <div class="chart-controls mono">
                <button class="tf-btn active" id="btn-tf-3s" onclick="setTimeframe('3s')">3S</button>
                <button class="tf-btn" id="btn-tf-1m" onclick="setTimeframe('1m')">1M</button>
                <button class="tf-btn" id="btn-tf-1h" onclick="setTimeframe('1h')">1H</button>
                <button class="tf-btn" id="btn-tf-1d" onclick="setTimeframe('1d')">1D</button>
                <button class="tf-btn" id="btn-tf-1w" onclick="setTimeframe('1w')">1W</button>
                <button class="tf-btn" id="btn-tf-1M" onclick="setTimeframe('1M')">1MO</button>
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
            <span class="mono" style="font-size: 10px; color: var(--text-muted);">Size: $15k / TP: +3% / SL: -1.2%</span>
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

    <!-- 8. TAB 4: REGOLE TRADING -->
    <div class="section hidden" id="view-rules">
        <div class="section-header">
            <span class="section-title">Parametri di Esecuzione Quantitativa</span>
        </div>
        <div style="display: flex; flex-direction: column; gap: 8px;">
            <div class="acc-cell">
                <div class="acc-label">Taglia &amp; Frequenza</div>
                <div style="font-size: 12px; color: var(--text-main);"><strong>$15,000 USDT</strong> per ordine. Scan ogni 2 min sui 10 asset liquidi.</div>
            </div>
            <div class="acc-cell">
                <div class="acc-label">Filtro Confluenza A+</div>
                <div style="font-size: 12px; color: var(--text-main);">Ingresso solo con <strong>EMA 20/50 + RSI + Volume Ratio &ge; 1.1x</strong> concordi.</div>
            </div>
            <div class="acc-cell">
                <div class="acc-label">Risk Management Asimmetrico (1:2.5)</div>
                <div style="font-size: 12px; color: var(--text-main);">Take Profit a <strong>+3.00% ($450)</strong>. Stop Loss a <strong>-1.20%</strong>. Break-even a <strong>+0.60%</strong>. Trailing Lock a <strong>+1.20%</strong>.</div>
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
        <button class="tab-item" id="tab-btn-rules" onclick="showTab('rules')">
            <span>Regole</span>
            <span class="dot"></span>
        </button>
    </nav>

    <script>
        let chartInstance = null;
        let currentTimeframe = '3s';

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
            ['bybit', 'alpaca', 'history', 'rules'].forEach(t => {
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
                const gridColor = isDark ? 'rgba(35, 49, 80, 0.4)' : 'rgba(226, 232, 240, 0.8)';
                const tickColor = isDark ? '#94a3b8' : '#64748b';

                const labels = snapshots.map(s => {
                    const d = new Date(s.epoch * 1000);
                    if (currentTimeframe === '1d' || currentTimeframe === '1w' || currentTimeframe === '1M') {
                        return d.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' }) + ' ' + d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
                    }
                    return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: (currentTimeframe === '3s' ? '2-digit' : undefined) });
                });
                const equity = snapshots.map(s => s.total_equity);
                const pnl = snapshots.map(s => s.cumulative_realized_pnl);

                if (chartInstance) {
                    chartInstance.data.labels = labels;
                    chartInstance.data.datasets[0].data = equity;
                    chartInstance.data.datasets[1].data = pnl;
                    chartInstance.update('none');
                    return;
                }

                chartInstance = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                label: 'Equity ($)',
                                data: equity,
                                borderColor: '#15803d',
                                borderWidth: 2,
                                backgroundColor: isDark ? 'rgba(34, 197, 94, 0.05)' : 'rgba(21, 128, 61, 0.05)',
                                pointRadius: 1.5,
                                tension: 0.15,
                                fill: true,
                                yAxisID: 'y'
                            },
                            {
                                label: 'PnL ($)',
                                data: pnl,
                                borderColor: '#b45309',
                                borderWidth: 1.8,
                                borderDash: [3, 3],
                                backgroundColor: 'transparent',
                                pointRadius: 1.5,
                                tension: 0.1,
                                yAxisID: 'y1'
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        plugins: {
                            legend: { display: false }
                        },
                        scales: {
                            x: {
                                grid: { color: gridColor },
                                ticks: { color: tickColor, font: { family: 'SF Mono, monospace', size: 9 }, maxTicksLimit: 5 }
                            },
                            y: {
                                position: 'left',
                                grid: { color: gridColor },
                                ticks: {
                                    color: '#15803d',
                                    font: { family: 'SF Mono, monospace', size: 9 },
                                    callback: val => '$' + (val / 1000).toFixed(1) + 'k'
                                }
                            },
                            y1: {
                                position: 'right',
                                grid: { drawOnChartArea: false },
                                ticks: {
                                    color: '#b45309',
                                    font: { family: 'SF Mono, monospace', size: 9 },
                                    callback: val => '$' + val.toFixed(0)
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

            // 3. Variazioni Multi-Timeframe
            ['3s', '1m', '1h', '1d', '1w', '1M'].forEach(tf => {
                const v = variations[tf] || { delta_equity: 0, delta_equity_pct: 0 };
                const vVal = document.getElementById(`delta-${tf}-val`);
                const vPct = document.getElementById(`delta-${tf}-pct`);
                if (vVal && vPct) {
                    const dSign = v.delta_equity >= 0 ? '+' : '';
                    vVal.innerText = `${dSign}$${v.delta_equity.toFixed(2)}`;
                    vPct.innerText = `${dSign}${v.delta_equity_pct.toFixed(2)}%`;

                    const vClass = v.delta_equity > 0 ? 'val-up' : (v.delta_equity < 0 ? 'val-down' : 'val-neutral');
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
                listEl.innerHTML = bPositions.map(p => {
                    const isLong = p.side === 'BUY';
                    const sideClass = isLong ? 'trade-side-long' : 'trade-side-short';
                    const sideText = isLong ? 'LONG' : 'SHORT';
                    const pSign = p.unrealized_pnl >= 0 ? '+' : '';
                    const pnlClass = p.unrealized_pnl >= 0 ? 'val-up' : 'val-down';

                    let guardHtml = `<span class="trade-guard">SL -1.20%</span>`;
                    if (p.pnl_pct >= 1.20) {
                        guardHtml = `<span class="trade-guard guard-lock">LOCK +0.70%</span>`;
                    } else if (p.pnl_pct >= 0.60) {
                        guardHtml = `<span class="trade-guard guard-be">BE SAFE</span>`;
                    }

                    return `
                        <div class="trade-row mono">
                            <div class="trade-left">
                                <div class="trade-symbol-row">
                                    <span class="trade-symbol">${p.symbol}</span>
                                    <span class="${sideClass}">${sideText}</span>
                                </div>
                                <div class="trade-detail">
                                    In: $${p.entry_price.toFixed(4)} &rarr; Mark: $${p.mark_price.toFixed(4)}
                                </div>
                                <div class="trade-detail" style="color: var(--text-dim);">
                                    Size: ${p.size} ($${(p.position_value || 0).toLocaleString('en-US', {maximumFractionDigits: 0})})
                                </div>
                            </div>
                            <div class="trade-right">
                                <div class="trade-pnl ${pnlClass}">
                                    ${pSign}$${p.unrealized_pnl.toFixed(2)}
                                </div>
                                <div style="font-size: 11px;" class="${pnlClass}">
                                    ${pSign}${p.pnl_pct.toFixed(2)}%
                                </div>
                                ${guardHtml}
                            </div>
                        </div>
                    `;
                }).join('');
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
        setInterval(fetchData, 3000);
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
_CACHE_TTL = 1.8  # Risposte istantanee in <10ms riutilizzando la cache recente di 1.8s

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
    variations = perf_tracker.get_variations(tot_eq, cum_real)
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
