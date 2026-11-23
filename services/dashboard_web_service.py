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
from services.deep_trade_analysis_service import get_deep_trade_forecast

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

        /* MODAL FORECAST QUANTITATIVO (HURST, MIGLIORINO, ELLIOTT, MONTE CARLO) */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(15, 23, 42, 0.75);
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
            z-index: 1000;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 14px;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.25s ease;
        }
        .modal-overlay.active {
            opacity: 1;
            pointer-events: auto;
        }
        .modal-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            width: 100%;
            max-width: 580px;
            max-height: 90vh;
            overflow-y: auto;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3);
            display: flex;
            flex-direction: column;
            animation: modalSlideUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        }
        @keyframes modalSlideUp {
            from { transform: translateY(20px) scale(0.97); }
            to { transform: translateY(0) scale(1); }
        }
        .modal-header {
            padding: 16px 18px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            background: var(--surface);
            z-index: 2;
        }
        .modal-title-row {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .modal-title {
            font-size: 15px;
            font-weight: 800;
            color: var(--text-main);
        }
        .modal-close-btn {
            background: var(--surface-elevated);
            border: 1px solid var(--border);
            border-radius: 50%;
            width: 32px;
            height: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 16px;
            transition: all 0.2s;
        }
        .modal-close-btn:hover {
            color: var(--text-main);
            background: var(--border);
        }
        .modal-body {
            padding: 16px 18px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }
        .forecast-chart-container {
            position: relative;
            height: 220px;
            width: 100%;
            background: var(--surface-elevated);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 8px;
        }
        .diag-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        @media (max-width: 480px) {
            .diag-grid { grid-template-columns: 1fr; }
        }
        .diag-card {
            background: var(--surface-elevated);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 12px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .diag-card-title {
            font-size: 10px;
            font-weight: 700;
            color: var(--text-dim);
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }
        .diag-card-val {
            font-size: 12px;
            font-weight: 700;
            color: var(--text-main);
        }
        .diag-card-desc {
            font-size: 11px;
            color: var(--text-muted);
            line-height: 1.4;
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
            bottom: calc(100% + 8px);
            left: 50%;
            transform: translateX(-50%);
            padding: 7px 11px;
            border-radius: 7px;
            background: #0f172a;
            color: #f8fafc;
            font-size: 11px;
            line-height: 1.4;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-weight: 500;
            white-space: normal;
            width: max-content;
            max-width: 250px;
            text-align: center;
            z-index: 99999;
            box-shadow: 0 6px 16px rgba(0,0,0,0.35);
            pointer-events: none;
            border: 1px solid rgba(255,255,255,0.18);
        }
        [data-tip]:hover::before,
        [data-tip]:focus::before {
            content: '';
            position: absolute;
            bottom: calc(100% + 2px);
            left: 50%;
            transform: translateX(-50%);
            border: 6px solid transparent;
            border-top-color: #0f172a;
            z-index: 99999;
            pointer-events: none;
        }

        /* Tooltip con posizionamento in basso (per elementi in alto a rischio clipping) */
        [data-tip-pos="bottom"]:hover::after,
        [data-tip-pos="bottom"]:focus::after {
            bottom: auto;
            top: calc(100% + 8px);
        }
        [data-tip-pos="bottom"]:hover::before,
        [data-tip-pos="bottom"]:focus::before {
            bottom: auto;
            top: calc(100% + 2px);
            border-top-color: transparent;
            border-bottom-color: #0f172a;
        }

        /* Tooltip allineati a destra (evitano overflow a destra su schermi stretti) */
        [data-tip-pos="right"]:hover::after,
        [data-tip-pos="right"]:focus::after {
            left: auto;
            right: 0;
            transform: none;
        }
        [data-tip-pos="right"]:hover::before,
        [data-tip-pos="right"]:focus::before {
            left: auto;
            right: 14px;
            transform: none;
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
                <div data-tip="Health &amp; Alignment Score (0-100): indice sintetico dello stato di salute del trading quantitativo. Misura la convergenza di Win Rate, Profit Factor, Expected Value e allineamento con lo Scudo Macro BTC 4H. Sopra 60 = assetto solido ed efficiente; sotto 40 = scatta la protezione conservativa.">
                    <div style="font-size: 9px; color: var(--text-muted); text-transform: uppercase;" class="mono">Health &amp; Alignment Score</div>
                    <div class="compass-score-wrap mono">
                        <span class="compass-score" id="compass-score-val">--</span>
                        <span style="font-size: 12px; color: var(--text-dim);">/ 100</span>
                    </div>
                </div>
                <div id="compass-badge-el" class="compass-badge badge-amber mono" data-tip="Verdetto sintetico del Trading Compass sullo stato complessivo dell'operatività in corso">CALCOLO</div>
            </div>
            <div class="compass-desc" id="compass-desc-el">
                Inizializzazione diagnostica probabilistica...
            </div>

            <!-- 4 Metric Cards: Expected Value, Realized R:R, In-The-Money Ratio, Profit Factor -->
            <div class="diag-grid mono">
                <div class="diag-cell">
                    <div class="diag-label" data-tip-pos="bottom" data-tip="Valore monetario medio atteso per singola operazione (Expected Value). Se positivo certifica un reale vantaggio matematico cumulativo nel lungo periodo.">Expected Value (EV)</div>
                    <div class="diag-val" id="diag-ev-val">$0.00</div>
                    <div class="diag-sub">Utile atteso per trade</div>
                </div>
                <div class="diag-cell">
                    <div class="diag-label" data-tip-pos="bottom" data-tip="Rapporto Rischio/Rendimento reale calcolato a mercato vs target teorico (1:3.0). Indica quanti dollari incassi in media per ogni dollaro rischiato sullo Stop Loss.">R:R Reale vs Target</div>
                    <div class="diag-val" id="diag-rr-val">1:0.0</div>
                    <div class="diag-sub">Target min: 1:2.5</div>
                </div>
                <div class="diag-cell">
                    <div class="diag-label" data-tip-pos="bottom" data-tip="Percentuale e conteggio dei contratti aperti attualmente in profitto, con dettaglio delle posizioni già protette a rischio zero (Break-Even Safe).">Posizioni in Gain</div>
                    <div class="diag-val" id="diag-itm-val">0%</div>
                    <div class="diag-sub" id="diag-prot-sub">0 protette Break-Even</div>
                </div>
                <div class="diag-cell">
                    <div class="diag-label" data-tip-pos="bottom" data-tip="Rapporto tra profitti lordi totali e perdite lorde totali. Valori superiori a 1.50 confermano una strategia quantitativa ad alta efficienza statistica.">Profit Factor</div>
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
                <div class="tf-header" data-tip-pos="bottom" data-tip="Variazione netta del capitale/PnL negli ultimi 3 secondi (tick ad altissima frequenza in tempo reale)">Ogni 3s</div>
                <div class="tf-delta" id="delta-3s-val">$0.00</div>
                <div class="tf-pct" id="delta-3s-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1m" onclick="setTimeframe('1m')">
                <div class="tf-header" data-tip-pos="bottom" data-tip="Variazione netta registrata nell'ultimo minuto di contrattazione">1 Minuto</div>
                <div class="tf-delta" id="delta-1m-val">$0.00</div>
                <div class="tf-pct" id="delta-1m-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1h" onclick="setTimeframe('1h')">
                <div class="tf-header" data-tip-pos="bottom" data-tip="Variazione cumulativa netta registrata negli ultimi 60 minuti">1 Ora</div>
                <div class="tf-delta" id="delta-1h-val">$0.00</div>
                <div class="tf-pct" id="delta-1h-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1d" onclick="setTimeframe('1d')">
                <div class="tf-header" data-tip-pos="bottom" data-tip="Rendimento cumulativo delle ultime 24 ore rispetto al saldo della sessione precedente">1 Giorno</div>
                <div class="tf-delta" id="delta-1d-val">$0.00</div>
                <div class="tf-pct" id="delta-1d-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1w" onclick="setTimeframe('1w')">
                <div class="tf-header" data-tip-pos="bottom" data-tip="Performance progressiva cumulativa negli ultimi 7 giorni di trading">1 Settimana</div>
                <div class="tf-delta" id="delta-1w-val">$0.00</div>
                <div class="tf-pct" id="delta-1w-pct">0.00%</div>
            </div>
            <div class="tf-card" id="card-tf-1M" onclick="setTimeframe('1M')">
                <div class="tf-header" data-tip-pos="bottom" data-tip="Rendimento netto consolidato a 30 giorni">1 Mese</div>
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
            <!-- Toggle Modalità: Patrimonio Wallet vs PnL Operativo Bot & Scala ($ vs %) -->
            <div class="chart-controls mono">
                <button class="tf-btn active" id="btn-view-wallet" onclick="setChartMetric('wallet')" data-tip="Mostra la traiettoria del capitale totale comprensivo dei depositi spot in wallet">💼 PATRIMONIO</button>
                <button class="tf-btn" id="btn-view-pnl" onclick="setChartMetric('pnl')" data-tip="Isola e mostra esclusivamente la curva dei profitti e perdite generati dalle operazioni dei bot">🎯 PnL OPERATIVO</button>
                <span style="border-left: 1px solid var(--border); margin: 0 4px; height: 16px;"></span>
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
            <div class="metric-item" data-tip-pos="bottom" data-tip="Media matematica netta guadagnata o persa per singolo trade chiuso"><span>Trade Medio:</span><strong id="metric-avg-trade">$0.00</strong></div>
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
            <div style="display: flex; gap: 8px; align-items: center;">
                <span class="mono" style="font-size: 10px; color: var(--blue);" id="history-avg-label">Trade Medio: $0.00</span>
                <span class="mono" style="font-size: 10px; color: var(--text-muted);" id="closed-count-label">0 eseguiti</span>
            </div>
        </div>
        <table class="clean-table mono">
            <thead>
                <tr>
                    <th>Ora</th>
                    <th>Simbolo</th>
                    <th>Lato</th>
                    <th>Investito ($)</th>
                    <th>Prezzi</th>
                    <th>Fee</th>
                    <th>PnL Netto</th>
                    <th>Resa %</th>
                </tr>
            </thead>
            <tbody id="history-tbody">
                <tr>
                    <td colspan="8" style="text-align: center; padding: 20px 0; color: var(--text-dim);">
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

            <!-- Card 4: Saldo Conto Unificato Bybit (UTA) vs Credito Demo Iniziale -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">4. Patrimonio Bybit UTA e Composizione del Credito Demo</strong>
                    <span class="badge mono" style="background: var(--blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">BYBIT UTA</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    La card <strong>BYBIT UTA</strong> mostra il valore del conto Unificato:<br>
                    <strong>• Cifra Principale (es. $162,260.09):</strong> È l'<strong>Equity Totale Consolidata</strong> (Total Equity), che somma a prezzi di mercato correnti tutti gli asset del conto (1 BTC spot ~ $60,700, 1 ETH spot ~ $1,710, 50,000 USDC e USDT).<br>
                    <strong>• Disponibile (es. $49,764 USDT):</strong> È la liquidità cash in stablecoin USDT libera da vincoli di margine, utilizzabile per aprire nuovi contratti futures.<br>
                    <strong>• Credito Demo Iniziale Assegnato da Bybit:</strong> All'attivazione del conto Demo UTA, Bybit accredita di default un pacchetto multi-asset composto da <strong>50,000 USDT</strong>, <strong>50,000 USDC</strong>, <strong>1 BTC</strong> e <strong>1 ETH</strong>. Le variazioni dell'equity totale riflettono sia le oscillazioni del valore di mercato di BTC/ETH sia i profitti e le perdite realizzati dal bot.<br>
                    <strong>• Capitale Investito, PnL &amp; Resa % nello Storico:</strong> Nella tab <strong>Storico Trade</strong> viene indicata la colonna <strong>Investito ($)</strong> (notionale del trade aperto, circa $15,000 pari al 10% dell'equity), il <strong>PnL Netto</strong> monetario e la <strong>Resa %</strong> (percentuale netta di guadagno o perdita calcolata sul capitale investito nell'operazione). In alto è sempre visibile il <strong>Trade Medio</strong> (media matematica per singolo trade concluso).
                </div>
            </div>

            <!-- Card 5: Separazione dei Broker (Crypto vs Wall Street) -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">5. Separazione dei Broker (Crypto vs Wall Street)</strong>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    <strong>• Bybit Futures (UTA):</strong> Opera 24/7 (weekend compreso) sui derivati crypto liquidi (BTC, ETH, SOL, LINK, AVAX, XRP).<br>
                    <strong>• Alpaca Securities (USA):</strong> Opera esclusivamente sulle azioni di Wall Street (NYSE e NASDAQ) dal lunedì al venerdì (15:30 - 22:00 CET). Durante il weekend è giustamente fermo con posizioni chiuse e liquidità protetta in dollari cash.<br>
                    <strong>• Grafici Separati:</strong> Cliccando sui pulsanti sopra il grafico puoi isolare il rendimento del solo broker crypto o delle sole azioni americane.
                </div>
            </div>

            <!-- Card 6: Timeframe e Grafico Zoomabile -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">6. Timeframe e Zoom Interattivo</strong>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    <strong>• Timeframe (3S, 1M, 1H, 1D, 1W, 1MO):</strong> Permette di visualizzare sia il micro-tick in tempo reale che l'andamento a lungo termine fino a 30 giorni.<br>
                    <strong>• Zoom su iPhone:</strong> Pizzica con due dita direttamente sul grafico per ingrandire o rimpicciolire qualsiasi candela. Clicca <code>🔍 RESET ZOOM</code> per tornare alla panoramica.<br>
                    <strong>• Tooltip al Tocco:</strong> Tocca con il dito qualsiasi punto o numero per leggere la guida contestuale immediata.
                </div>
            </div>

            <!-- Card 7: Mini-Sparklines & Target R:R Progress -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">7. Mini-Sparklines &amp; Barra Progresso R:R 1:3</strong>
                    <span class="badge mono" style="background: var(--blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">REAL-TIME</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Sotto ogni posizione aperta è presente un box tecnico grafico ad alta densità:<br>
                    <strong>• Mini-Sparkline (15m):</strong> Mostra il trend a 15 minuti del sottostante con il punto live del prezzo corrente.<br>
                    <strong>• Livelli Prezzo TP &amp; SL:</strong> Riporta a schermo il valore esatto in dollari di Take Profit (+3.60%) e Stop Loss (-1.20%).<br>
                    <strong>• Barra di Progresso:</strong> Indica visivamente la percentuale di completamento verso il profitto netto target e la distanza rimanente.
                </div>
            </div>

            <!-- Card 8: Notifiche Push Telegram Smart -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">8. Notifiche Push Telegram Intelligenti (Zero Spam) &amp; Recap 22:00</strong>
                    <span class="badge mono" style="background: var(--green); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">ALERT 24/7</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Il bot comunica su Telegram esclusivamente nei momenti chiave di transizione del rischio:<br>
                    <strong>• Inversione Macro BTC 4H:</strong> Notifica quando il trend generale passa da Bullish a Bearish.<br>
                    <strong>• Break-Even Safe (+0.80%):</strong> Avviso quando lo stop viene alzato sopra l'ingresso a rischio zero.<br>
                    <strong>• Trailing Profit Lock (+1.60%):</strong> Avviso quando viene garantito l'incasso di almeno il +1.00% netto.<br>
                    <strong>• Chiusura TP / SL Dinamico:</strong> Riepilogo immediato con dollari incassati e PnL percentuale basato su 1.4x ATR.<br>
                    <strong>• Report Giornaliero Silenzioso (22:00 CET):</strong> Un unico messaggio serale con il bilancio netto della giornata, win-rate, posizioni notturne attive e Health Score.
                </div>
            </div>

            <!-- Card 9: Diagnostica Ciclica (Hurst/Migliorino), Onde di Elliott e Monte Carlo -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">9. Analisi Ciclica, Onde di Elliott, Timeframe &amp; Previsione Monte Carlo</strong>
                    <span class="badge mono" style="background: var(--blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">QUANT PRO</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Toccando qualsiasi riga di trade aperto si apre il pannello di analisi quantitativa approfondita:<br>
                    <strong>• Selettore Timeframe Dinamico (1D / 4H / 1H):</strong> Permette di alternare all'istante l'analisi tra visione Macro (1D), Swing (4H) e Tattica Intraday (1H).<br>
                    <strong>• Confluenza Microstruttura (OBI &amp; ATR):</strong> Gli ingressi verificano l'Order Book Imbalance (muri di liquidità Bid/Ask) e calcolano Stop Loss e Take Profit proporzionati alla volatilità reale ATR.<br>
                    <strong>• Grafico Sovrapposto a Più Curve:</strong> Mostra in tempo reale la serie storica reale (azzurro), la curva di traslazione <strong>Hurst FLD</strong> (oro tratteggiato), la sinusoide a 4 tempi del <strong>Battleplan Migliorino</strong> (ciano) e il cono stocastico <strong>Monte Carlo P50</strong> con intervallo di confidenza al 95%.<br>
                    <strong>• Hurst FLD (Future Line of Demarcation):</strong> Trasla il prezzo di mezzo periodo (T/2). Se il prezzo incrocia la FLD dal basso, convalida il minimo ciclico proiettando il target al rialzo; se la buca dall'alto, avverte di debolezza ciclica verso il minimo.<br>
                    <strong>• Battleplan &amp; Vincoli di Migliorino:</strong> Mostra il tempo ciclico su 4 tempi (T, T+1, T+2, T+3) e segnala se il ciclo è libero o vincolato al ribasso (un ciclo che rompe il proprio minimo di partenza non può più superare il proprio massimo).<br>
                    <strong>• Onde di Elliott Frattali &amp; Target Fibonacci:</strong> Riconosce la fase frattale (Onda 1-2-3-4-5 d'impulso o correzione A-B-C) e calcola in tempo reale i livelli di ritracciamento di Fibonacci (38.2%, 50.0% Mediana e 61.8% Golden Pocket).<br>
                    <strong>• Simulazione Monte Carlo a 15 Giorni:</strong> Calcola su 10.000 iterazioni stocastiche la distribuzione di probabilità con percentili P05, P50 e P95.
                </div>
            </div>

        </div>
    </div>

    <!-- MODAL POPUP ANALISI TRADE AVANZATA -->
    <div class="modal-overlay" id="trade-modal" onclick="closeTradeModal(event)">
        <div class="modal-card mono" onclick="event.stopPropagation()">
            <div class="modal-header">
                <div class="modal-title-row">
                    <span id="modal-trade-sym" class="modal-title">BTCUSDT</span>
                    <span id="modal-trade-side" class="trade-side-short">SHORT</span>
                    <span id="modal-trade-tf" class="badge mono" style="background: rgba(59, 130, 246, 0.15); color: var(--blue); font-size: 10px; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(59, 130, 246, 0.3);">TF: 1D (Giornaliero - 6 Mesi)</span>
                    <span id="modal-trade-price" style="font-size: 12px; color: var(--text-muted);">$0.00</span>
                </div>
                <button class="modal-close-btn" onclick="closeTradeModal()">&times;</button>
            </div>
            <div class="modal-body">
                <!-- Grafico Previsionale Stocastico Monte Carlo, Hurst FLD & Battleplan Migliorino -->
                <div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; flex-wrap: wrap; gap: 4px;">
                        <div style="display: flex; gap: 4px; align-items: center;">
                            <span style="font-size: 11px; font-weight: 700; color: var(--text-main);">Traiettoria Monte Carlo, FLD &amp; Battleplan</span>
                            <!-- Timeframe Selector nel Modal -->
                            <div style="display: flex; gap: 3px; margin-left: 6px;">
                                <button class="tf-btn active" id="modal-tf-1d" onclick="switchModalTimeframe('1d')" style="padding: 2px 7px; font-size: 9px;">1D</button>
                                <button class="tf-btn" id="modal-tf-4h" onclick="switchModalTimeframe('4h')" style="padding: 2px 7px; font-size: 9px;">4H</button>
                                <button class="tf-btn" id="modal-tf-1h" onclick="switchModalTimeframe('1h')" style="padding: 2px 7px; font-size: 9px;">1H</button>
                            </div>
                        </div>
                        <div style="display: flex; gap: 6px; align-items: center;">
                            <span id="modal-tf-badge" class="badge mono" style="background: var(--surface-elevated); color: var(--text-muted); font-size: 9px; padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border);">1D • MACRO</span>
                            <span id="modal-mc-prob" class="badge mono" style="background: var(--green-bg); color: var(--green); font-size: 10px; padding: 2px 6px; border-radius: 4px;">Prob. Up: 50%</span>
                        </div>
                    </div>
                    <div class="forecast-chart-container">
                        <canvas id="forecastChart"></canvas>
                    </div>
                    <!-- Legenda Grafica Dettagliata -->
                    <div style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 6px; font-size: 9px; color: var(--text-dim); margin-top: 6px; padding: 4px 6px; background: var(--surface-elevated); border-radius: 4px;">
                        <span style="color: #38bdf8;">━ Prezzo Storico</span>
                        <span style="color: #f59e0b;">╌╌ Hurst FLD (T/2)</span>
                        <span style="color: #06b6d4;">··· Battleplan Migliorino</span>
                        <span style="color: #a855f7;">╌╌ Mediana Monte Carlo P50</span>
                        <span style="color: #10b981;">░ Fascia Confidenza 95%</span>
                    </div>
                </div>

                <!-- Griglia Diagnostica Quantitativa Avanzata -->
                <div class="diag-grid">
                    <!-- Hurst FLD -->
                    <div class="diag-card">
                        <span class="diag-card-title">Ciclica di Hurst (FLD)</span>
                        <span class="diag-card-val" id="modal-hurst-val">FLD: $0.00</span>
                        <span class="diag-card-desc" id="modal-hurst-desc">Calcolo centratura ciclica in corso...</span>
                    </div>

                    <!-- Giuseppe Migliorino -->
                    <div class="diag-card">
                        <span class="diag-card-title">Battleplan &amp; Vincolo Migliorino</span>
                        <span class="diag-card-val" id="modal-migliorino-val">1° Tempo (T+2)</span>
                        <span class="diag-card-desc" id="modal-migliorino-desc">Analisi rottura minimi e vincolo...</span>
                    </div>

                    <!-- Onde di Elliott -->
                    <div class="diag-card">
                        <span class="diag-card-title">Struttura Onde di Elliott</span>
                        <span class="diag-card-val" id="modal-elliott-val">Onda 4 Correttiva</span>
                        <span class="diag-card-desc" id="modal-elliott-desc">Diagnostica frattale del trend...</span>
                    </div>

                    <!-- Monte Carlo & Wyckoff -->
                    <div class="diag-card">
                        <span class="diag-card-title">Distribuzione Statistica (MC)</span>
                        <span class="diag-card-val" id="modal-mc-val">Target Mediano: $0.00</span>
                        <span class="diag-card-desc" id="modal-mc-desc">Range al 95% di confidenza.</span>
                    </div>
                </div>

                <!-- Schema Onde di Elliott & Guida Visiva alle Onde e Cicli -->
                <div style="background: var(--surface-elevated); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-size: 11px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <strong style="color: var(--text-main);">Mappatura Frattale Onde (1-2-3-4-5 &amp; A-B-C):</strong>
                        <span id="modal-wave-fib" class="mono" style="font-size: 10px; color: var(--blue);">Fib: --</span>
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; text-align: center; margin-bottom: 6px; font-size: 10px;">
                        <div id="wave-box-impulse" style="background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 4px 2px;">
                            <div style="color: var(--text-muted); font-size: 8px;">IMPULSO (1-3-5)</div>
                            <div id="wave-impulse-status" style="font-weight: 700; color: var(--green);">Onda 3</div>
                        </div>
                        <div id="wave-box-correct" style="background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 4px 2px;">
                            <div style="color: var(--text-muted); font-size: 8px;">CORREZIONE (2-4)</div>
                            <div id="wave-correct-status" style="font-weight: 700; color: var(--text-muted);">Attesa</div>
                        </div>
                        <div id="wave-box-hurst" style="background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 4px 2px;">
                            <div style="color: var(--text-muted); font-size: 8px;">HURST FLD</div>
                            <div id="wave-hurst-status" style="font-weight: 700; color: var(--amber);">Rialzista</div>
                        </div>
                        <div id="wave-box-migl" style="background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 4px 2px;">
                            <div style="color: var(--text-muted); font-size: 8px;">MIGLIORINO</div>
                            <div id="wave-migl-status" style="font-weight: 700; color: var(--cyan);">T+2 (32gg)</div>
                        </div>
                    </div>

                    <!-- Griglia Target Ritracciamento Fibonacci & Golden Pocket -->
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; text-align: center; margin-top: 6px; margin-bottom: 6px; font-size: 10px;">
                        <div style="background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 3px 2px;">
                            <div style="color: var(--text-muted); font-size: 8px;">FIB 38.2%</div>
                            <div id="fib-382-val" style="font-weight: 700; color: var(--text-main); font-size: 9px;">--</div>
                        </div>
                        <div style="background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 3px 2px;">
                            <div style="color: var(--text-muted); font-size: 8px;">FIB 50.0% (MEDIANA)</div>
                            <div id="fib-500-val" style="font-weight: 700; color: var(--blue); font-size: 9px;">--</div>
                        </div>
                        <div style="background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 3px 2px;">
                            <div style="color: var(--text-muted); font-size: 8px;">GOLDEN POCKET 61.8%</div>
                            <div id="fib-618-val" style="font-weight: 700; color: var(--amber); font-size: 9px;">--</div>
                        </div>
                    </div>

                    <div id="modal-elliott-deep-desc" style="color: var(--text-dim); font-size: 10px; line-height: 1.4;">
                        Analisi frattale automatica basata sul modello a 8 onde di Ralph Nelson Elliott combinata con la Future Line of Demarcation (FLD) di J.M. Hurst e i 4 sottocicli del Battleplan di Giuseppe Migliorino.
                    </div>
                </div>

                <!-- Raccomandazione Quantitativa Sintetica -->
                <div style="background: var(--surface-elevated); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-size: 11px; margin-top: 8px;">
                    <strong style="color: var(--text-main);">Verdetto Ciclico &amp; Operativo:</strong>
                    <div id="modal-advice-text" style="color: var(--text-muted); margin-top: 4px; line-height: 1.45;">
                        Caricamento sintesi operativa...
                    </div>
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
        let chartMetric = 'wallet'; // 'wallet' | 'pnl'

        function setChartMetric(metric) {
            chartMetric = metric;
            document.getElementById('btn-view-wallet').classList.toggle('active', metric === 'wallet');
            document.getElementById('btn-view-pnl').classList.toggle('active', metric === 'pnl');
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }
            fetchData();
        }

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

                // Se chartMetric è 'pnl', plottiamo la curva del Net PnL (realizzato + fluttuante) per isolare l'operatività del trading
                if (chartMetric === 'pnl') {
                    if (chartMode === 'pct') {
                        equity = snapshots.map(s => parseFloat(((s.cumulative_realized_pnl + (s.unrealized_pnl || 0)) / baseEq * 100).toFixed(3)));
                        labelName = 'Trading Net PnL (%)';
                    } else {
                        equity = snapshots.map(s => parseFloat((s.cumulative_realized_pnl + (s.unrealized_pnl || 0)).toFixed(2)));
                        labelName = 'Trading Net PnL ($)';
                    }
                    pnl = snapshots.map(s => parseFloat(s.cumulative_realized_pnl.toFixed(2)));
                    pnlName = 'PnL Chiuso ($)';
                } else if (chartMode === 'pct') {
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
                            } else if (chartMetric === 'pnl') {
                                hudRange.innerText = `L: $${minVal.toFixed(1)} • H: $${maxVal.toFixed(1)}`;
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

            // 3. Variazioni Multi-Timeframe (Separazione Istanza Istantanea e PnL Trading)
            ['3s', '1m', '1h', '1d', '1w', '1M'].forEach(tf => {
                const baseV = variations[tf] || { delta_equity: 0, delta_equity_pct: 0, delta_trading_pnl: 0 };
                let targetDelta = baseV.delta_equity;
                let targetPct = baseV.delta_equity_pct;
                let tradingPnlDelta = typeof baseV.delta_trading_pnl === 'number' ? baseV.delta_trading_pnl : baseV.delta_pnl;

                if (currentInstance === 'bybit' && baseV.bybit) {
                    targetDelta = baseV.bybit.delta_equity;
                    targetPct = baseV.bybit.delta_equity_pct;
                    if (typeof baseV.bybit.delta_trading_pnl === 'number') {
                        tradingPnlDelta = baseV.bybit.delta_trading_pnl;
                    }
                } else if (currentInstance === 'alpaca' && baseV.alpaca) {
                    targetDelta = baseV.alpaca.delta_equity;
                    targetPct = baseV.alpaca.delta_equity_pct;
                    tradingPnlDelta = baseV.delta_pnl;
                }

                const vVal = document.getElementById(`delta-${tf}-val`);
                const vPct = document.getElementById(`delta-${tf}-pct`);
                if (vVal && vPct) {
                    // Quando visualizziamo Bybit Crypto, usiamo tradingPnlDelta per riflettere l'operatività reale dei contratti
                    const displayDelta = (currentInstance === 'bybit' && typeof tradingPnlDelta === 'number') ? tradingPnlDelta : targetDelta;
                    const dSign = displayDelta >= 0 ? '+' : '';
                    vVal.innerText = `${dSign}$${displayDelta.toFixed(2)}`;
                    
                    const pctVal = (currentInstance === 'bybit' && bEq > 0) ? (displayDelta / (bEq || 1) * 100) : targetPct;
                    vPct.innerText = `${dSign}${pctVal.toFixed(2)}%`;

                    const vClass = displayDelta > 0 ? 'val-up' : (displayDelta < 0 ? 'val-down' : 'val-neutral');
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

            // Calcolo Trade Medio
            const avgTrade = bClosed.length > 0 ? (cumPnl / bClosed.length) : 0;
            const avgEl = document.getElementById('metric-avg-trade');
            if (avgEl) {
                avgEl.innerText = `${avgTrade >= 0 ? '+' : ''}$${avgTrade.toFixed(2)}`;
                avgEl.className = avgTrade >= 0 ? 'val-up' : 'val-down';
            }
            const histAvgEl = document.getElementById('history-avg-label');
            if (histAvgEl) {
                histAvgEl.innerText = `Trade Medio: ${avgTrade >= 0 ? '+' : ''}$${avgTrade.toFixed(2)}`;
                histAvgEl.style.color = avgTrade >= 0 ? 'var(--green)' : 'var(--red)';
            }

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

                    let guardHtml = `<span class="trade-guard" data-tip-pos="right" data-tip="Stop Loss dinamico (1.4x ATR): protezione automatica calibrata sulla volatilità del mercato">SL -1.20%</span>`;
                    if (p.pnl_pct >= 1.60) {
                        guardHtml = `<span class="trade-guard guard-lock" data-tip-pos="right" data-tip="Trailing Profit Lock attivo: stop rialzato per blindare almeno il +1.00% netto di profitto">LOCK +1.00%</span>`;
                    } else if (p.pnl_pct >= 0.80) {
                        guardHtml = `<span class="trade-guard guard-be" data-tip-pos="right" data-tip="Break-Even Safe attivo: rischio trade azzerato, stop spostato a +0.20% per coprire tutte le fee">BE SAFE +0.20%</span>`;
                    }

                    // Calcolo Target Progress Bar
                    const entry = p.entry_price || 1;
                    const mark = p.mark_price || entry;
                    const sl = p.stop_loss || (isLong ? entry * 0.988 : entry * 1.012);
                    const tp = p.take_profit || (isLong ? entry * 1.036 : entry * 0.964);

                    // Calcolo percentuale di completamento verso TP (+3.60% teorico di trade o distanza TP)
                    const pctGain = typeof p.pnl_pct === 'number' ? p.pnl_pct : 0;
                    const tpProgress = Math.max(0, Math.min(100, (pctGain / 3.60) * 100));
                    const progressColor = pctGain >= 1.60 ? 'var(--amber)' : (pctGain > 0 ? 'var(--green)' : 'var(--red)');
                    const distTp = (3.60 - pctGain).toFixed(2);

                    // Canvas ID per mini-candlestick / sparkline
                    const sparkId = `sparkline-pos-${idx}`;

                    return `
                        <div class="trade-row mono" onclick="openTradeModal('${p.symbol}', '${sideText}', ${entry}, ${mark})" style="cursor: pointer;" title="Tocca per visualizzare la diagnostica ciclica (Hurst/Migliorino), Elliott e Monte Carlo">
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
                                    <div class="trade-pnl ${pnlClass}" data-tip-pos="right" data-tip="PnL non realizzato fluttuante in dollari sulla posizione aperta">
                                        ${pSign}$${p.unrealized_pnl.toFixed(2)}
                                    </div>
                                    <div style="font-size: 11px;" class="${pnlClass}" data-tip-pos="right" data-tip="Rendimento percentuale netto calcolato sul capitale investito (10% equity)">
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
                                    <div class="target-bar-bg" data-tip-pos="bottom" data-tip="Avanzamento grafico verso il Take Profit istituzionale (R:R 1:3). Scala dinamica verde/ambra">
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

            // 7. History Table (Ordinamento Rigoroso: Più Recente in Alto)
            const sortedClosed = [...bClosed].sort((a, b) => parseInt(b.updatedTime || 0) - parseInt(a.updatedTime || 0));
            document.getElementById('closed-count-label').innerText = `${sortedClosed.length} eseguiti`;
            const hBody = document.getElementById('history-tbody');
            if (sortedClosed.length === 0) {
                hBody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 20px 0; color: var(--text-dim);">Nessun trade chiuso recente.</td></tr>`;
            } else {
                hBody.innerHTML = sortedClosed.slice(0, 20).map(c => {
                    const pVal = parseFloat(c.closedPnl || 0);
                    const pClass = pVal >= 0 ? 'val-up' : 'val-down';
                    const pSign = pVal >= 0 ? '+' : '';
                    const timeStr = c.updatedTime ? new Date(parseInt(c.updatedTime)).toLocaleTimeString('it-IT') : '--:--';
                    
                    // Quantitativo economico investito (Notionale = cumEntryValue o closedSize * avgEntryPrice)
                    const invested = parseFloat(c.cumEntryValue || 0) || (parseFloat(c.closedSize || 0) * parseFloat(c.avgEntryPrice || 0));
                    const investedStr = invested > 0 ? '$' + Math.round(invested).toLocaleString('en-US') : '--';

                    // Calcolo Resa Percentuale sul Capitale Investito
                    let pctStr = '--';
                    if (invested > 0) {
                        const pct = (pVal / invested) * 100;
                        pctStr = `${pSign}${pct.toFixed(2)}%`;
                    }

                    return `
                        <tr>
                            <td style="color: var(--text-muted); font-weight: 500;">${timeStr}</td>
                            <td style="font-weight: 700; color: var(--text-main);">${c.symbol}</td>
                            <td>${c.side}</td>
                            <td style="color: var(--text-main); font-weight: 600;">${investedStr}</td>
                            <td>$${parseFloat(c.avgEntryPrice || 0).toFixed(3)} &rarr; $${parseFloat(c.avgExitPrice || 0).toFixed(3)}</td>
                            <td style="color: var(--text-dim);">$${(parseFloat(c.openFee || 0) + parseFloat(c.closeFee || 0)).toFixed(2)}</td>
                            <td class="${pClass}">${pSign}$${pVal.toFixed(2)}</td>
                            <td class="${pClass}">${pctStr}</td>
                        </tr>
                    `;
                }).join('');
            }
        }

        let forecastChartInstance = null;
        let currentModalSymbol = 'BTCUSDT';
        let currentModalSide = 'LONG';
        let currentModalTf = '1d';

        async function switchModalTimeframe(tf) {
            currentModalTf = tf;
            ['1d', '4h', '1h'].forEach(t => {
                const btn = document.getElementById(`modal-tf-${t}`);
                if (btn) btn.classList.toggle('active', t === tf);
            });
            await loadModalForecast(currentModalSymbol, currentModalSide, currentModalTf);
        }

        async function openTradeModal(symbol, side, entry, mark) {
            const modal = document.getElementById('trade-modal');
            modal.classList.add('active');

            currentModalSymbol = symbol;
            currentModalSide = side;
            currentModalTf = '1d';
            ['1d', '4h', '1h'].forEach(t => {
                const btn = document.getElementById(`modal-tf-${t}`);
                if (btn) btn.classList.toggle('active', t === '1d');
            });

            document.getElementById('modal-trade-sym').innerText = symbol;
            const sideEl = document.getElementById('modal-trade-side');
            sideEl.innerText = side;
            sideEl.className = side === 'LONG' ? 'trade-side-long' : 'trade-side-short';
            document.getElementById('modal-trade-price').innerText = `Entry: $${entry.toFixed(4)} | Mark: $${mark.toFixed(4)}`;

            await loadModalForecast(symbol, side, '1d');
        }

        async function loadModalForecast(symbol, side, tf) {
            // Reset testi a loading
            document.getElementById('modal-mc-prob').innerText = 'Calcolo in corso...';
            document.getElementById('modal-hurst-val').innerText = 'Caricamento FLD...';
            document.getElementById('modal-hurst-desc').innerText = 'Recupero serie storiche e centratura ciclica...';
            document.getElementById('modal-migliorino-val').innerText = 'Battleplan...';
            document.getElementById('modal-migliorino-desc').innerText = 'Verifica rottura minimi di partenza...';
            document.getElementById('modal-elliott-val').innerText = 'Analisi Frattale...';
            document.getElementById('modal-elliott-desc').innerText = 'Misurazione ritracciamento Fibonacci...';
            document.getElementById('modal-mc-val').innerText = 'Simulazione 10.000 scenari...';
            document.getElementById('modal-mc-desc').innerText = 'Estrazione percentili P05, P50, P95...';
            document.getElementById('modal-advice-text').innerText = 'Analisi quantitativa multi-modello in elaborazione...';

            try {
                const res = await fetch(`/api/trade-forecast?symbol=${symbol}&tf=${tf}`);
                const data = await res.json();
                if (data.error) {
                    document.getElementById('modal-advice-text').innerText = data.error;
                    return;
                }

                // Popola Hurst
                const c = data.cycle || {};
                document.getElementById('modal-hurst-val').innerText = `FLD: $${(c.hurst_fld_value || 0).toFixed(4)}`;
                document.getElementById('modal-hurst-desc').innerText = c.hurst_fld_signal || 'FLD attiva';

                // Popola Migliorino
                document.getElementById('modal-migliorino-val').innerText = c.tempo_battleplan || 'Ciclo T+2';
                document.getElementById('modal-migliorino-desc').innerText = `${c.vincolo_migliorino || 'LIBERO'}: ${c.descrizione_battleplan || ''}`;

                // Popola Elliott
                const el = data.elliott || {};
                document.getElementById('modal-elliott-val').innerText = el.wave_label || 'Struttura Frattale';
                document.getElementById('modal-elliott-desc').innerText = el.analysis || 'Onde di Elliott in sviluppo.';

                // Popola Timeframe badge
                const tfBadge = document.getElementById('modal-trade-tf');
                if (tfBadge && data.timeframe) {
                    tfBadge.innerText = `TF: ${data.timeframe}`;
                }
                const tfMini = document.getElementById('modal-tf-badge');
                if (tfMini && data.timeframe) {
                    tfMini.innerText = data.timeframe.toUpperCase();
                }

                // Popola Mappatura Frattale Onde
                const waveImp = document.getElementById('wave-impulse-status');
                const waveCorr = document.getElementById('wave-correct-status');
                const waveHurst = document.getElementById('wave-hurst-status');
                const waveMigl = document.getElementById('wave-migl-status');
                const waveFib = document.getElementById('modal-wave-fib');
                const deepDesc = document.getElementById('modal-elliott-deep-desc');

                if (waveFib && el.fib_retrace) {
                    waveFib.innerText = `Fib: ${(el.fib_retrace * 100).toFixed(1)}%`;
                }
                if (waveImp && el.wave_label) {
                    waveImp.innerText = el.wave_label.includes('Onda') ? el.wave_label : 'Fase Attiva';
                    waveImp.style.color = (side === 'LONG') ? 'var(--green)' : 'var(--red)';
                }
                if (waveCorr && el.correction_type) {
                    waveCorr.innerText = el.correction_type;
                }
                if (waveHurst && c.cycle_direction) {
                    waveHurst.innerText = c.cycle_direction;
                    waveHurst.style.color = c.cycle_direction.includes('Rialz') ? 'var(--green)' : 'var(--amber)';
                }
                if (waveMigl && c.tempo_battleplan) {
                    waveMigl.innerText = c.tempo_battleplan;
                }
                if (deepDesc && el.analysis) {
                    deepDesc.innerText = `${el.analysis} ${c.descrizione_battleplan || ''}`;
                }

                // Popola Target Fibonacci
                const fibObj = el.fib_levels || {};
                const fib382El = document.getElementById('fib-382-val');
                const fib500El = document.getElementById('fib-500-val');
                const fib618El = document.getElementById('fib-618-val');
                if (fib382El && fibObj.fib_382) fib382El.innerText = `$${Number(fibObj.fib_382).toLocaleString('en-US', {maximumFractionDigits: 2})}`;
                if (fib500El && fibObj.fib_500) fib500El.innerText = `$${Number(fibObj.fib_500).toLocaleString('en-US', {maximumFractionDigits: 2})}`;
                if (fib618El && fibObj.fib_618) fib618El.innerText = `$${Number(fibObj.fib_618).toLocaleString('en-US', {maximumFractionDigits: 2})}`;

                // Popola Monte Carlo
                const mc = data.monte_carlo || {};
                document.getElementById('modal-mc-prob').innerText = `Prob. Up: ${mc.probability_positive || '50%'}`;
                document.getElementById('modal-mc-val').innerText = `Mediana: $${(mc.median_forecast || 0).toFixed(4)}`;
                document.getElementById('modal-mc-desc').innerText = `Intervallo 95% CI: ${mc.ci_95_range || ''} (Vol: ${mc.annualized_vol || 0}%)`;

                // Sintesi operativa
                document.getElementById('modal-advice-text').innerText = `${c.consiglio_pratico || ''} Setup: ${side === 'LONG' ? 'Rialzista' : 'Ribassista'} su ${symbol}.`;

                // Renderizza Grafico Multimodello (Storico + FLD + Battleplan + Monte Carlo)
                initForecastChart(data.chart_data);
            } catch (err) {
                console.error("Forecast fetch error:", err);
                document.getElementById('modal-advice-text').innerText = 'Errore di connessione al motore predittivo.';
            }
        }

        function closeTradeModal(e) {
            if (e && e.target && e.target !== document.getElementById('trade-modal') && !e.target.classList.contains('modal-close-btn')) {
                return;
            }
            const modal = document.getElementById('trade-modal');
            modal.classList.remove('active');
            if (forecastChartInstance) {
                forecastChartInstance.destroy();
                forecastChartInstance = null;
            }
        }

        function initForecastChart(chartData) {
            if (!chartData) return;
            const canvas = document.getElementById('forecastChart');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');

            if (forecastChartInstance) {
                forecastChartInstance.destroy();
                forecastChartInstance = null;
            }

            const hist = chartData.historical || [];
            const hurstFld = chartData.hurst_fld || [];
            const battleplan = chartData.battleplan_migliorino || [];
            const p50 = chartData.forecast_p50 || [];
            const p05 = chartData.forecast_p05 || [];
            const p95 = chartData.forecast_p95 || [];

            // Combina etichette
            const labels = (chartData.historical_labels || []).concat((chartData.forecast_labels || []).slice(1));
            
            // Allinea serie storiche e previsionali
            const histSeries = hist.concat(new Array(p50.length - 1).fill(null));
            const hurstSeries = hurstFld.concat(new Array(p50.length - 1).fill(null));
            const battleplanSeries = battleplan.concat(new Array(p50.length - 1).fill(null));

            const pad = new Array(hist.length - 1).fill(null);
            const p50Series = pad.concat(p50);
            const p05Series = pad.concat(p05);
            const p95Series = pad.concat(p95);

            forecastChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Storico Prezzo',
                            data: histSeries,
                            borderColor: '#38bdf8',
                            borderWidth: 2,
                            pointRadius: 0,
                            pointHoverRadius: 4,
                            tension: 0.1
                        },
                        {
                            label: 'Hurst FLD (T/2)',
                            data: hurstSeries,
                            borderColor: '#f59e0b',
                            borderWidth: 1.8,
                            borderDash: [4, 3],
                            pointRadius: 0,
                            pointHoverRadius: 3,
                            tension: 0.2
                        },
                        {
                            label: 'Battleplan Migliorino (T+2)',
                            data: battleplanSeries,
                            borderColor: '#06b6d4',
                            borderWidth: 1.6,
                            borderDash: [2, 2],
                            pointRadius: 0,
                            pointHoverRadius: 3,
                            tension: 0.3
                        },
                        {
                            label: 'Monte Carlo Mediana (P50)',
                            data: p50Series,
                            borderColor: '#a855f7',
                            borderWidth: 2.2,
                            borderDash: [5, 4],
                            pointRadius: 0,
                            pointHoverRadius: 4,
                            tension: 0.2
                        },
                        {
                            label: 'Banda Superiore (P95)',
                            data: p95Series,
                            borderColor: 'rgba(16, 185, 129, 0.4)',
                            borderWidth: 1,
                            backgroundColor: 'transparent',
                            pointRadius: 0,
                            tension: 0.2
                        },
                        {
                            label: 'Banda Inferiore (P05)',
                            data: p05Series,
                            borderColor: 'rgba(239, 68, 68, 0.4)',
                            borderWidth: 1,
                            backgroundColor: 'rgba(168, 85, 247, 0.08)',
                            fill: '-1',
                            pointRadius: 0,
                            tension: 0.2
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    if (context.parsed.y !== null) {
                                        return `${context.dataset.label}: $${context.parsed.y.toFixed(4)}`;
                                    }
                                    return '';
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            ticks: { maxTicksLimit: 7, font: { family: 'ui-monospace, monospace', size: 9 }, color: '#94a3b8' },
                            grid: { display: false }
                        },
                        y: {
                            ticks: { font: { family: 'ui-monospace, monospace', size: 9 }, color: '#94a3b8' },
                            grid: { color: 'rgba(148, 163, 184, 0.1)' }
                        }
                    }
                }
            });
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
        b_closed_res = _bybit_service.session.get_closed_pnl(category="linear", limit=50)
        raw_closed = b_closed_res.get("result", {}).get("list", [])
        # Ordina esplicitamente dal più recente al più vecchio (epoch timestamp descrescente)
        b_closed = sorted(raw_closed, key=lambda c: int(c.get("updatedTime", 0) or 0), reverse=True)
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
    variations = perf_tracker.get_variations(tot_eq, cum_real, bybit_eq=b_eq, alpaca_eq=a_eq, current_unrealized_pnl=unreal_pnl)
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

async def handle_trade_forecast_api(request):
    """Restituisce l'analisi ciclica (Hurst/Migliorino), onde di Elliott e simulazione Monte Carlo per un asset."""
    symbol = request.query.get("symbol", "BTCUSDT")
    tf = request.query.get("tf", "1d")
    data = await asyncio.to_thread(get_deep_trade_forecast, symbol, tf)
    return web.json_response(data)

def create_web_app(bybit_svc=None, alpaca_svc=None):
    global _bybit_service, _alpaca_service
    if bybit_svc:
        _bybit_service = bybit_svc
    if alpaca_svc:
        _alpaca_service = alpaca_svc

    app = web.Application()
    app.router.add_get("/", handle_dashboard_page)
    app.router.add_get("/api/dashboard", handle_dashboard_api)
    app.router.add_get("/api/trade-forecast", handle_trade_forecast_api)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    return app
