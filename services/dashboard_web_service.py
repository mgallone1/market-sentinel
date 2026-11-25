"""
Web Dashboard Service for Market Sentinel.
Design: Professional Dual-Theme Financial Terminal (Light Mode & Dark Mode switchable).
- Light Mode: Elegante, arioso, pulito (sfondo #F8FAFC, card #FFFFFF, bordi #E2E8F0, testo ad alto contrasto #0F172A).
- Dark Mode: Slate istituzionale (sfondo #0F172A, card #1E293B, bordi #334155, testo #F8FAFC).
- Switcher istantaneo a 1-tap in alto a destra (sole/luna) con salvataggio preferenza in localStorage.
- 100% ottimizzato per iPhone e Desktop con grafici Chart.js che adattano colori assi e griglia al tema.
"""

import os
import json
import hmac
import sqlite3
from pathlib import Path
from aiohttp import web
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional

from services.bybit_execution_service import BybitExecutionService
from services.alpaca_execution_service import AlpacaExecutionService
from services.perf_metrics_tracker import perf_tracker
from services.trading_compass_service import trading_compass
from services.deep_trade_analysis_service import get_deep_trade_forecast
from services.trade_journal_service import TradeJournalService
from services.learning_engine_service import learning_engine

_bybit_service: BybitExecutionService = None
_alpaca_service: AlpacaExecutionService = None
_trade_journal_service: TradeJournalService = TradeJournalService()

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="it" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Sentinel &bull; Institutional Terminal</title>
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="theme-color" content="#000000">

    <!-- SF Pro System Fonts via CDN & Lucide Icons -->
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=SF+Pro+Display:wght@400;500;600;700;800&family=SF+Pro+Text:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap">

    <!-- Chart.js + Zoom plugin -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>

    <style>
        /* ==========================================================================
           APPLE HUMAN INTERFACE GUIDELINES & GOLDEN RATIO (φ = 1.618) DESIGN SYSTEM
           ========================================================================== */
        :root {
            --bg-canvas: #000000;
            --bg-secondary: #0c0c0e;
            --surface: rgba(28, 28, 30, 0.75);
            --surface-elevated: rgba(44, 44, 46, 0.85);
            --surface-card: rgba(30, 30, 32, 0.65);
            --surface-glass: rgba(255, 255, 255, 0.05);
            --border: rgba(255, 255, 255, 0.10);
            --border-subtle: rgba(255, 255, 255, 0.06);
            --border-focus: rgba(10, 132, 255, 0.5);

            /* Apple System Color Palette */
            --apple-blue: #0A84FF;
            --apple-blue-rgb: 10, 132, 255;
            --apple-green: #30D158;
            --apple-green-bg: rgba(48, 209, 88, 0.15);
            --apple-red: #FF453A;
            --apple-red-bg: rgba(255, 69, 58, 0.15);
            --apple-amber: #FF9F0A;
            --apple-amber-bg: rgba(255, 159, 10, 0.15);
            --apple-purple: #BF5AF2;

            /* Standard variables for script compatibility */
            --blue: var(--apple-blue);
            --green: var(--apple-green);
            --green-bg: var(--apple-green-bg);
            --red: var(--apple-red);
            --red-bg: var(--apple-red-bg);
            --amber: var(--apple-amber);

            /* Typography */
            --text-primary: #FFFFFF;
            --text-secondary: rgba(235, 235, 245, 0.68);
            --text-tertiary: rgba(235, 235, 245, 0.40);
            --text-main: var(--text-primary);
            --text-muted: var(--text-secondary);
            --text-dim: var(--text-tertiary);

            /* Golden Ratio Radius & Spacing */
            --radius-card: 16px;
            --radius-pill: 9999px;
            --radius-sm: 8px;
            --radius-md: 12px;

            /* Shadows & Blurs */
            --apple-blur: blur(25px) saturate(190%);
            --shadow-subtle: 0 4px 20px rgba(0, 0, 0, 0.25);
            --shadow-float: 0 12px 36px rgba(0, 0, 0, 0.45);
        }

        [data-theme="light"] {
            --bg-canvas: #F2F2F7;
            --bg-secondary: #E5E5EA;
            --surface: #FFFFFF;
            --surface-elevated: #FFFFFF;
            --surface-card: #FFFFFF;
            --surface-glass: rgba(0, 0, 0, 0.04);
            --border: rgba(60, 60, 67, 0.18);
            --border-subtle: rgba(60, 60, 67, 0.12);
            --border-focus: rgba(0, 122, 255, 0.5);

            /* Contrasto rinforzato per perfetta leggibilità in Light Mode (WCAG AAA) */
            --apple-blue: #0062D2;
            --apple-green: #248A3D;
            --apple-green-bg: rgba(36, 138, 61, 0.14);
            --apple-red: #D70015;
            --apple-red-bg: rgba(215, 0, 21, 0.12);
            --apple-amber: #B25000;
            --apple-amber-bg: rgba(178, 80, 0, 0.14);
            --apple-purple: #8944AB;

            --text-primary: #1C1C1E;
            --text-secondary: #48484A;
            --text-tertiary: #6C6C70;
            --text-main: var(--text-primary);
            --text-muted: var(--text-secondary);
            --text-dim: var(--text-tertiary);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }

        html, body {
            background: var(--bg-canvas);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Inter", -apple-system-subheadline, "Helvetica Neue", Arial, sans-serif;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            padding-bottom: calc(76px + env(safe-area-inset-bottom, 20px));
            overscroll-behavior-y: none;
            user-select: none;
            -webkit-user-select: none;
            letter-spacing: -0.015em;
        }

        /* TIPOGRAFIA APPLE HIG: TABULAR NUMBERS CON SAN FRANCISCO (ZERO FONT TERMINALE VINTAGE) */
        .mono {
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Inter", "Helvetica Neue", Arial, sans-serif !important;
            font-variant-numeric: tabular-nums lining-nums;
            -webkit-font-feature-settings: "tnum" 1, "lnum" 1;
            font-feature-settings: "tnum" 1, "lnum" 1;
            letter-spacing: -0.02em;
        }

        /* APP CONTAINER WITH MAX WIDTH DESKTOP CENTERED */
        .app-container {
            max-width: 680px;
            margin: 0 auto;
            padding: 0 16px;
        }

        /* ==========================================================================
           1. APPLE NAVIGATION BAR & HEADER
           ========================================================================== */
        .apple-nav {
            position: sticky;
            top: 0;
            z-index: 1000;
            background: rgba(0, 0, 0, 0.72);
            backdrop-filter: var(--apple-blur);
            -webkit-backdrop-filter: var(--apple-blur);
            border-bottom: 0.5px solid var(--border);
            padding: calc(env(safe-area-inset-top, 12px) + 6px) 16px 10px 16px;
            transition: all 0.25s ease;
        }
        [data-theme="light"] .apple-nav {
            background: rgba(242, 242, 247, 0.82);
        }
        .apple-nav-inner {
            max-width: 680px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .nav-leading {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .nav-pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--apple-green);
            box-shadow: none;
            animation: pulse-apple 2s infinite ease-in-out;
        }
        @keyframes pulse-apple {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.2); opacity: 0.7; }
        }
        .nav-title-group {
            display: flex;
            flex-direction: column;
        }
        .nav-title {
            font-size: 17px;
            font-weight: 700;
            letter-spacing: -0.4px;
        }
        .nav-subtitle {
            font-size: 11px;
            color: var(--text-secondary);
            font-weight: 500;
        }
        .nav-trailing {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .apple-nav-btn {
            background: var(--surface-glass);
            border: 0.5px solid var(--border);
            border-radius: var(--radius-pill);
            padding: 6px 12px;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-primary);
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 5px;
            transition: background 0.15s ease, transform 0.1s ease;
        }
        .apple-nav-btn:active {
            transform: scale(0.95);
            background: rgba(255, 255, 255, 0.15);
        }

        /* ==========================================================================
           2. TOTAL HERO PORTFOLIO VALUE (APPLE STOCKS STYLE)
           ========================================================================== */
        .hero-equity-card {
            padding: 20px 4px 14px 4px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .hero-equity-label {
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: var(--text-secondary);
        }
        .hero-equity-amount {
            font-size: 38px;
            font-weight: 800;
            letter-spacing: -0.8px;
            line-height: 1.1;
        }
        .hero-accounts-split {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 12px;
            margin-bottom: 2px;
        }
        .hero-sub-account {
            background: var(--surface);
            border: 0.5px solid var(--border);
            border-radius: var(--radius-card);
            padding: 10px 12px;
            display: flex;
            flex-direction: column;
            gap: 3px;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .hero-sub-account:active {
            transform: scale(0.98);
        }
        .hero-sub-account.active-acc {
            border-color: var(--apple-blue);
            background: rgba(10, 132, 255, 0.08);
        }
        .hero-sub-label {
            font-size: 11px;
            font-weight: 600;
            color: var(--text-secondary);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .hero-sub-amount {
            font-size: 16px;
            font-weight: 700;
            letter-spacing: -0.4px;
            color: var(--text-primary);
        }
        .hero-sub-meta {
            font-size: 10px;
            color: var(--text-tertiary);
        }
        .hero-delta-strip {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 4px;
            font-size: 14px;
            font-weight: 600;
        }
        .hero-delta-badge {
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
        }

        /* ==========================================================================
           3. APPLE SEGMENTED CONTROL (TIMEFRAME & SUB-VIEWS)
           ========================================================================== */
        .apple-segmented {
            background: var(--surface);
            border: 0.5px solid var(--border);
            border-radius: var(--radius-pill);
            padding: 3px;
            display: flex;
            gap: 2px;
            position: relative;
            margin: 8px 0 16px 0;
            backdrop-filter: var(--apple-blur);
            -webkit-backdrop-filter: var(--apple-blur);
        }
        .apple-segment-item {
            flex: 1;
            padding: 7px 4px;
            text-align: center;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-secondary);
            border: none;
            background: none;
            border-radius: var(--radius-pill);
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            font-family: inherit;
        }
        .apple-segment-item.active {
            background: var(--surface-elevated);
            color: var(--text-primary);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.28);
            font-weight: 700;
        }
        .apple-segment-item.active-bybit {
            background: rgba(10, 132, 255, 0.22);
            color: var(--apple-blue);
            border: 0.5px solid rgba(10, 132, 255, 0.4);
            box-shadow: none;
            font-weight: 700;
        }
        .apple-segment-item.active-alpaca {
            background: rgba(255, 159, 10, 0.22);
            color: var(--apple-amber);
            border: 0.5px solid rgba(255, 159, 10, 0.4);
            box-shadow: none;
            font-weight: 700;
        }
        .apple-segment-item.active-total {
            background: rgba(191, 90, 242, 0.22);
            color: #BF5AF2;
            border: 0.5px solid rgba(191, 90, 242, 0.4);
            box-shadow: none;
            font-weight: 700;
        }

        
        /* APPLE NATIVE SEGMENTED CONTROL (SLIDING PILL & PHYSICAL DEPTH) */
        .tf-pills-row {
            display: flex;
            background: rgba(118, 118, 128, 0.18);
            border-radius: 9px;
            padding: 2px;
            gap: 2px;
            margin-bottom: 12px;
            position: relative;
        }
        [data-theme="light"] .tf-pills-row {
            background: rgba(118, 118, 128, 0.12);
        }
        .tf-pill {
            flex: 1;
            padding: 5px 0;
            background: transparent;
            border: none;
            border-radius: 7px;
            color: var(--text-secondary);
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            text-align: center;
        }
        .tf-pill.active {
            background: #636366;
            color: #FFFFFF;
            font-weight: 700;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        }
        [data-theme="light"] .tf-pill.active {
            background: #FFFFFF;
            color: #000000;
            box-shadow: 0 2px 6px rgba(0,0,0,0.15);
        }

        .apple-segmented {
            display: flex;
            background: rgba(118, 118, 128, 0.18);
            border-radius: 9px;
            padding: 2px;
            gap: 2px;
        }
        [data-theme="light"] .apple-segmented {
            background: rgba(118, 118, 128, 0.12);
        }
        .apple-segment-item {
            flex: 1;
            padding: 6px 4px;
            background: transparent;
            border: none;
            border-radius: 7px;
            color: var(--text-secondary);
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            text-align: center;
        }
        .apple-segment-item.active {
            background: #636366;
            color: #FFFFFF;
            font-weight: 700;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        }
        [data-theme="light"] .apple-segment-item.active {
            background: #FFFFFF;
            color: #000000;
            box-shadow: 0 2px 6px rgba(0,0,0,0.15);
        }

/* ==========================================================================
           4. TIME RANGE PICKER PILLS (3S, 1M, 1H, 1D, 1W, 1M)
           ========================================================================== */
        .tf-pills-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 12px;
            gap: 6px;
        }
        .tf-pill {
            flex: 1;
            padding: 6px 0;
            background: var(--surface-glass);
            border: 0.5px solid var(--border);
            border-radius: 8px;
            color: var(--text-secondary);
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .tf-pill.active {
            background: var(--apple-blue);
            color: #ffffff;
            border-color: var(--apple-blue);
            font-weight: 700;
        }

        /* ==========================================================================
           5. APPLE INTERACTIVE CHART CONTAINER
           ========================================================================== */
        .apple-chart-card {
            background: var(--surface);
            backdrop-filter: var(--apple-blur);
            -webkit-backdrop-filter: var(--apple-blur);
            border: 0.5px solid var(--border);
            border-radius: var(--radius-card);
            padding: 14px 12px 10px 12px;
            margin-bottom: 18px;
            box-shadow: var(--shadow-subtle);
        }
        .chart-hud-apple {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            font-size: 11px;
            font-weight: 600;
            color: var(--text-secondary);
        }
        .chart-hud-stat strong {
            color: var(--text-primary);
            font-size: 12px;
        }
        .chart-container-inner {
            position: relative;
            height: 220px;
            width: 100%;
            touch-action: pan-y !important;
        }
        #perfChart {
            touch-action: pan-y !important;
        }
        .chart-quick-metrics {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 6px;
            margin-top: 10px;
            border-top: 0.5px solid var(--border-subtle);
            padding-top: 10px;
            text-align: center;
        }
        .quick-metric-cell {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .quick-metric-cell span {
            font-size: 9px;
            color: var(--text-tertiary);
            text-transform: uppercase;
            font-weight: 600;
        }
        .quick-metric-cell strong {
            font-size: 11px;
            font-weight: 700;
        }

        
        /* PREDICTION ENGINE LAYERS SELECTOR & TACTICAL CARD */
        .layer-pills {
            display: flex;
            gap: 4px;
            overflow-x: auto;
            padding: 4px 0 8px 0;
            -webkit-overflow-scrolling: touch;
        }
        .layer-btn {
            background: var(--surface-elevated);
            border: 0.5px solid var(--border);
            color: var(--text-secondary);
            font-size: 10px;
            font-weight: 600;
            padding: 5px 11px;
            border-radius: 999px;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex;
            align-items: center;
            gap: 5px;
        }
        .layer-btn:hover {
            color: var(--text-primary);
            border-color: var(--border-focus);
        }
        .layer-btn.active {
            background: var(--apple-blue);
            color: #FFFFFF !important;
            border-color: var(--apple-blue);
            font-weight: 700;
            box-shadow: 0 2px 10px rgba(10, 132, 255, 0.35);
        }

        .tf-btn {
            background: var(--surface-elevated);
            border: 0.5px solid var(--border);
            color: var(--text-secondary);
            cursor: pointer;
            border-radius: 6px;
            font-weight: 600;
            transition: all 0.15s ease;
        }
        .tf-btn:hover {
            color: var(--text-primary);
        }
        .tf-btn.active {
            background: var(--apple-blue);
            color: #FFFFFF !important;
            border-color: var(--apple-blue);
            font-weight: 700;
        }
        .tactical-decision-box {
            background: linear-gradient(135deg, rgba(48, 209, 88, 0.08) 0%, rgba(10, 132, 255, 0.06) 100%);
            border: 0.5px solid rgba(48, 209, 88, 0.3);
            border-radius: 12px;
            padding: 12px 14px;
            margin-bottom: 12px;
        }
        .tactical-decision-box.short {
            background: linear-gradient(135deg, rgba(255, 69, 58, 0.08) 0%, rgba(255, 159, 10, 0.06) 100%);
            border-color: rgba(255, 69, 58, 0.3);
        }
        .tactical-decision-box.neutral {
            background: linear-gradient(135deg, rgba(255, 159, 10, 0.08) 0%, rgba(191, 90, 242, 0.06) 100%);
            border-color: rgba(255, 159, 10, 0.3);
        }
        .tactical-grid-3 {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 0.5px solid rgba(255,255,255,0.08);
            text-align: center;
        }
        .tactical-grid-3 > div {
            background: rgba(0,0,0,0.18);
            border-radius: 6px;
            padding: 6px 4px;
        }

        /* ==========================================================================
           6. APPLE INSET GROUPED LIST & CARDS (IOS HIG COMPLIANT)
           ========================================================================== */
        .section-header-apple {
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
            margin: 20px 4px 8px 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .apple-group-card {
            background: var(--surface);
            backdrop-filter: var(--apple-blur);
            -webkit-backdrop-filter: var(--apple-blur);
            border: 0.5px solid var(--border);
            border-radius: var(--radius-card);
            overflow: visible;
            box-shadow: var(--shadow-subtle);
            margin-bottom: 16px;
        }
        .apple-group-card > .apple-cell:first-child,
        .apple-group-card > .wallet-item:first-child {
            border-top-left-radius: var(--radius-card);
            border-top-right-radius: var(--radius-card);
        }
        .apple-group-card > .apple-cell:last-child,
        .apple-group-card > .wallet-item:last-child {
            border-bottom-left-radius: var(--radius-card);
            border-bottom-right-radius: var(--radius-card);
        }
        .acc-cell {
            background: var(--surface);
            backdrop-filter: var(--apple-blur);
            -webkit-backdrop-filter: var(--apple-blur);
            border: 0.5px solid var(--border);
            border-radius: var(--radius-card);
            box-shadow: var(--shadow-subtle);
        }
        .apple-cell {
            padding: 12px 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 0.5px solid var(--border-subtle);
            transition: background 0.15s ease;
        }
        .apple-cell:last-child {
            border-bottom: none;
        }
        .apple-cell:active {
            background: rgba(255, 255, 255, 0.05);
        }
        .cell-leading {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .cell-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-primary);
        }
        .cell-subtitle {
            font-size: 11px;
            color: var(--text-secondary);
        }
        .cell-trailing {
            text-align: right;
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 2px;
        }
        .cell-value {
            font-size: 14px;
            font-weight: 700;
        }

        /* ==========================================================================
           7. POSITION CARDS (TRADE LIVE NATIVE)
           ========================================================================== */
        .trade-card-apple {
            background: var(--surface);
            backdrop-filter: var(--apple-blur);
            -webkit-backdrop-filter: var(--apple-blur);
            border: 0.5px solid var(--border);
            border-radius: var(--radius-card);
            padding: 14px;
            margin-bottom: 10px;
            box-shadow: var(--shadow-subtle);
            cursor: pointer;
            transition: transform 0.1s ease, border-color 0.15s ease;
        }
        .trade-card-apple:active {
            transform: scale(0.985);
            border-color: var(--apple-blue);
        }
        .trade-card-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 8px;
        }
        .trade-badge-side {
            font-size: 10px;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 5px;
            letter-spacing: 0.3px;
        }
        .side-long { background: var(--apple-green-bg); color: var(--apple-green); }
        .side-short { background: var(--apple-red-bg); color: var(--apple-red); }

        .trade-guard-pill {
            font-size: 10px;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: var(--radius-pill);
            display: inline-block;
        }
        .guard-sl { background: var(--apple-red-bg); color: var(--apple-red); }
        .guard-be { background: rgba(10, 132, 255, 0.15); color: var(--apple-blue); }
        .guard-lock { background: var(--apple-amber-bg); color: var(--apple-amber); }

        .trade-target-progress-bar {
            height: 4px;
            border-radius: 2px;
            background: var(--surface-glass);
            overflow: hidden;
            margin: 6px 0;
            position: relative;
        }
        .trade-target-fill {
            height: 100%;
            border-radius: 2px;
            transition: width 0.3s ease;
        }

        /* ==========================================================================
           8. APPLE BOTTOM TABBAR (BLURRED FROSTED GLASS & HAPTIC TOUCH TARGET)
           ========================================================================== */
        .tabbar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            height: calc(54px + env(safe-area-inset-bottom, 20px));
            background: rgba(18, 18, 20, 0.78);
            backdrop-filter: blur(28px) saturate(210%);
            -webkit-backdrop-filter: blur(28px) saturate(210%);
            border-top: 0.5px solid var(--border);
            display: flex;
            justify-content: space-around;
            align-items: flex-start;
            padding-top: 6px;
            padding-bottom: env(safe-area-inset-bottom, 20px);
            z-index: 9999;
        }
        [data-theme="light"] .tabbar {
            background: rgba(249, 249, 249, 0.88);
            border-top: 0.5px solid rgba(0, 0, 0, 0.15);
        }
        .tab-item {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 3px;
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 10px;
            font-weight: 500;
            cursor: pointer;
            padding: 2px 0;
            transition: color 0.15s ease;
            position: relative;
        }
        .tab-item svg {
            width: 21px;
            height: 21px;
            stroke-width: 2.1;
            transition: stroke 0.15s ease, transform 0.15s ease;
        }
        .tab-item.active {
            color: var(--apple-blue);
            font-weight: 700;
        }
        .tab-item.active svg {
            stroke: var(--apple-blue);
            transform: scale(1.08);
        }
        .tab-item span.dot {
            position: absolute;
            top: -6px;
            width: 16px;
            height: 2.5px;
            border-radius: 1.5px;
            background: transparent;
            transition: background 0.2s ease;
        }
        .tab-item.active span.dot {
            background: var(--apple-blue);
        }

        /* ==========================================================================
           9. TOAST NOTIFICATION (APPLE DYNAMIC ISLAND / SYSTEM TOAST STYLE)
           ========================================================================== */
        .toast-tooltip-mobile {
            position: fixed;
            bottom: calc(70px + env(safe-area-inset-bottom, 20px));
            left: 14px;
            right: 14px;
            background: rgba(28, 28, 30, 0.94);
            color: #FFFFFF;
            backdrop-filter: blur(25px);
            -webkit-backdrop-filter: blur(25px);
            border: 0.5px solid rgba(255, 255, 255, 0.15);
            border-radius: 14px;
            padding: 12px 14px;
            font-size: 12px;
            line-height: 1.45;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            gap: 10px;
            z-index: 10001;
            opacity: 0;
            pointer-events: none;
            transform: translateY(12px) scale(0.98);
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .toast-tooltip-mobile.show {
            opacity: 1;
            pointer-events: auto;
            transform: translateY(0) scale(1);
        }
        .toast-tooltip-close {
            background: rgba(255, 255, 255, 0.15);
            border: none;
            color: #fff;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            flex-shrink: 0;
        }

        /* UTILITY & VALUE CLASSES */
        .val-up { color: var(--apple-green) !important; font-weight: 600; }
        .val-down { color: var(--apple-red) !important; font-weight: 600; }
        .val-neutral { color: var(--text-secondary) !important; }
        .hidden { display: none !important; }

        /* DESKTOP TABLE & MODAL SYSTEM RETAINED */
        .table-responsive-container {
            width: 100%;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }
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

        @media (max-width: 640px) {
            .mobile-hide-table { display: none !important; }
            .mobile-card-list { display: flex !important; flex-direction: column; gap: 8px; }
        }
        @media (min-width: 641px) {
            .mobile-card-list { display: none !important; }
        }

        .mobile-trade-card {
            background: var(--surface);
            border: 0.5px solid var(--border);
            border-radius: var(--radius-card);
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            box-shadow: var(--shadow-subtle);
        }
        .mobile-trade-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 0.5px solid var(--border-subtle);
            padding-bottom: 6px;
        }
        .mobile-trade-card-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 4px 10px;
            font-size: 11px;
        }

        
        /* ==========================================================================
           APPLE HIG ULTRA: INSET CARDS, ASSET AVATARS, BOTTOM SHEET, SCRUBBING
           ========================================================================== */
        :root {
            --apple-card-radius: 20px;
            --apple-subtle-border: rgba(255, 255, 255, 0.08);
            --apple-divider: rgba(255, 255, 255, 0.06);
            --apple-glass-bg: rgba(26, 26, 28, 0.72);
            --apple-haptic-active: scale(0.975);
        }
        [data-theme="light"] {
            --apple-subtle-border: rgba(60, 60, 67, 0.12);
            --apple-divider: rgba(60, 60, 67, 0.08);
            --apple-glass-bg: rgba(255, 255, 255, 0.82);
        }

        /* Asset Avatar Badge in Apple Wallet Style */
        .asset-avatar {
            width: 38px;
            height: 38px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            font-weight: 800;
            color: #fff;
            flex-shrink: 0;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            letter-spacing: -0.5px;
        }
        .avatar-btc { background: linear-gradient(135deg, #F7931A 0%, #D87205 100%); }
        .avatar-eth { background: linear-gradient(135deg, #627EEA 0%, #3B55B8 100%); }
        .avatar-sol { background: linear-gradient(135deg, #14F195 0%, #9945FF 100%); }
        .avatar-xrp { background: linear-gradient(135deg, #23292F 0%, #008CE7 100%); }
        .avatar-link { background: linear-gradient(135deg, #375BD2 0%, #1A3E9C 100%); }
        .avatar-avax { background: linear-gradient(135deg, #E84142 0%, #A81B1C 100%); }
        .avatar-stock { background: linear-gradient(135deg, #0A84FF 0%, #0056B3 100%); }
        .avatar-generic { background: linear-gradient(135deg, #3A3A3C 0%, #1C1C1E 100%); }

        /* Wallet Row Inset */
        .wallet-item {
            padding: 12px 14px;
            display: flex;
            align-items: center;
            gap: 12px;
            border-bottom: 0.5px solid var(--apple-divider);
            cursor: pointer;
            transition: background 0.15s ease, transform 0.1s ease;
        }
        .wallet-item:last-child {
            border-bottom: none;
        }
        .wallet-item:active {
            background: rgba(255, 255, 255, 0.05);
            transform: var(--apple-haptic-active);
        }
        .wallet-item-content {
            flex: 1;
            min-width: 0;
        }
        .wallet-title-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 2px;
        }
        .wallet-symbol {
            font-size: 15px;
            font-weight: 700;
            color: var(--text-primary);
        }
        .wallet-val {
            font-size: 15px;
            font-weight: 700;
            text-align: right;
        }
        .wallet-sub-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 12px;
            color: var(--text-secondary);
        }

        /* Apple Stocks Style Scrubbing Info Callout */
        .scrub-overlay {
            position: absolute;
            top: 6px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(28, 28, 30, 0.92);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 0.5px solid rgba(255, 255, 255, 0.18);
            border-radius: 9999px;
            padding: 4px 12px;
            font-size: 11px;
            font-weight: 600;
            color: #fff;
            display: none;
            z-index: 20;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
            white-space: nowrap;
            pointer-events: none;
        }

        /* Apple Bottom Sheet Modal */
        .modal-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.65);
            backdrop-filter: blur(20px) saturate(180%);
            -webkit-backdrop-filter: blur(20px) saturate(180%);
            z-index: 100000;
            display: none;
            align-items: flex-end;
            justify-content: center;
            padding: 0;
            opacity: 0;
            transition: opacity 0.28s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .modal-overlay.active {
            display: flex;
            opacity: 1;
        }
        .modal-card {
            background: rgba(24, 24, 26, 0.94);
            backdrop-filter: blur(35px) saturate(190%);
            -webkit-backdrop-filter: blur(35px) saturate(190%);
            border-top: 0.5px solid rgba(255, 255, 255, 0.15);
            border-left: 0.5px solid rgba(255, 255, 255, 0.08);
            border-right: 0.5px solid rgba(255, 255, 255, 0.08);
            border-bottom: none;
            border-radius: 28px 28px 0 0;
            max-width: 640px;
            width: 100%;
            max-height: 88vh;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            box-shadow: 0 -12px 40px rgba(0, 0, 0, 0.65);
            padding: 10px 16px calc(24px + env(safe-area-inset-bottom, 20px)) 16px;
            transform: translateY(100%);
            transition: transform 0.32s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .modal-overlay.active .modal-card {
            transform: translateY(0);
        }
        [data-theme="light"] .modal-card {
            background: rgba(246, 246, 249, 0.95);
            border-top: 0.5px solid rgba(0, 0, 0, 0.15);
        }

        /* Apple Sheet Grabber / Drag Handle */
        .sheet-grabber {
            width: 36px;
            height: 5px;
            border-radius: 2.5px;
            background: rgba(255, 255, 255, 0.3);
            margin: 0 auto 12px auto;
        }
        [data-theme="light"] .sheet-grabber {
            background: rgba(0, 0, 0, 0.2);
        }

        /* MODAL STYLES */
        .modal-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            z-index: 100000;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 16px;
        }
        .modal-overlay.show, .modal-overlay.active { display: flex; }
        .modal-card {
            background: var(--surface-elevated);
            border: 0.5px solid var(--border);
            border-radius: 20px;
            max-width: 540px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            box-shadow: var(--shadow-float);
            padding: 16px;
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 0.5px solid var(--border-subtle);
            padding-bottom: 10px;
            margin-bottom: 12px;
        }
        .modal-close-btn {
            background: var(--surface-glass);
            border: none;
            color: var(--text-secondary);
            font-size: 20px;
            border-radius: 50%;
            width: 28px;
            height: 28px;
            cursor: pointer;
        }
        .forecast-chart-container {
            position: relative;
            height: 200px;
            width: 100%;
            background: var(--bg-canvas);
            border-radius: 12px;
            border: 0.5px solid var(--border);
            padding: 6px;
            margin-bottom: 12px;
        }
        .diag-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }
        .diag-card {
            background: var(--surface);
            border: 0.5px solid var(--border);
            border-radius: 10px;
            padding: 8px 10px;
        }
        .diag-card-title {
            font-size: 10px;
            color: var(--text-secondary);
            text-transform: uppercase;
        }
        .diag-card-val {
            font-size: 12px;
            font-weight: 700;
            margin-top: 2px;
        }
        .diag-card-desc {
            font-size: 10px;
            color: var(--text-tertiary);
            margin-top: 2px;
            line-height: 1.3;
        }

        /* SEMANTIC BADGES, TRADE GUARDS & COMPASS STATUS */
        .compass-badge, .badge {
            font-size: 9px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 5px;
            letter-spacing: 0.2px;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            white-space: nowrap;
        }
        .badge-green { background: var(--apple-green-bg); color: var(--apple-green); }
        .badge-amber { background: var(--apple-amber-bg); color: var(--apple-amber); }
        .badge-red { background: var(--apple-red-bg); color: var(--apple-red); }
        .badge-blue { background: rgba(10, 132, 255, 0.15); color: var(--apple-blue); }
        .badge-purple { background: rgba(191, 90, 242, 0.16); color: var(--apple-purple); }
        .badge-neutral { background: var(--surface-glass); color: var(--text-secondary); }
        .diag-val { font-size: 14px; font-weight: 700; }

        .trade-side-long { background: var(--apple-green-bg); color: var(--apple-green); }
        .trade-side-short { background: var(--apple-red-bg); color: var(--apple-red); }
        .trade-guard {
            font-size: 9px;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: var(--radius-pill);
            display: inline-flex;
            align-items: center;
            background: var(--apple-red-bg);
            color: var(--apple-red);
            border: 0.5px solid rgba(255, 69, 58, 0.28);
            white-space: nowrap;
        }
        .trade-guard.guard-tight {
            background: rgba(48, 209, 88, 0.12);
            color: var(--apple-green);
            border-color: rgba(48, 209, 88, 0.35);
        }
        .trade-guard.guard-be {
            background: rgba(10, 132, 255, 0.15);
            color: var(--apple-blue);
            border-color: rgba(10, 132, 255, 0.35);
        }
        .trade-guard.guard-lock {
            background: var(--apple-amber-bg);
            color: var(--apple-amber);
            border-color: rgba(255, 159, 10, 0.35);
        }

        /* ==========================================================================
           10. INTERACTIVE TOOLTIPS ([data-tip]) — DESKTOP HOVER + KEYBOARD + EDGE SAFE
           ========================================================================== */
        [data-tip] {
            position: relative;
            cursor: help;
        }
        @media (hover: hover) and (pointer: fine) {
            [data-tip]:hover::after,
            [data-tip]:focus-visible::after {
                content: attr(data-tip);
                position: absolute;
                bottom: calc(100% + 8px);
                left: 50%;
                transform: translateX(-50%);
                width: max-content;
                max-width: min(260px, 80vw);
                padding: 8px 11px;
                border-radius: 10px;
                background: rgba(28, 28, 30, 0.97);
                color: #F2F2F7;
                border: 0.5px solid rgba(255, 255, 255, 0.20);
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.36);
                font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
                font-size: 11px;
                font-weight: 500;
                line-height: 1.42;
                text-transform: none;
                letter-spacing: normal;
                text-align: left;
                white-space: normal;
                pointer-events: none;
                z-index: 99999;
                opacity: 1;
            }
            [data-theme="light"] [data-tip]:hover::after,
            [data-theme="light"] [data-tip]:focus-visible::after {
                background: #FFFFFF;
                color: #1C1C1E;
                border-color: rgba(60, 60, 67, 0.22);
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.14);
            }
            [data-tip-pos="bottom"]:hover::after,
            [data-tip-pos="bottom"]:focus-visible::after {
                top: calc(100% + 8px);
                bottom: auto;
                left: 50%;
                right: auto;
                transform: translateX(-50%);
            }
            [data-tip-pos="top-left"]:hover::after,
            [data-tip-pos="top-left"]:focus-visible::after {
                bottom: calc(100% + 8px);
                top: auto;
                left: 0;
                right: auto;
                transform: none;
            }
            [data-tip-pos="top-right"]:hover::after,
            [data-tip-pos="top-right"]:focus-visible::after {
                bottom: calc(100% + 8px);
                top: auto;
                right: 0;
                left: auto;
                transform: none;
            }
            [data-tip-pos="bottom-left"]:hover::after,
            [data-tip-pos="bottom-left"]:focus-visible::after {
                top: calc(100% + 8px);
                bottom: auto;
                left: 0;
                right: auto;
                transform: none;
            }
            [data-tip-pos="bottom-right"]:hover::after,
            [data-tip-pos="bottom-right"]:focus-visible::after {
                top: calc(100% + 8px);
                bottom: auto;
                right: 0;
                left: auto;
                transform: none;
            }
            [data-tip-pos="right"]:hover::after,
            [data-tip-pos="right"]:focus-visible::after {
                top: 50%;
                bottom: auto;
                left: calc(100% + 8px);
                right: auto;
                transform: translateY(-50%);
            }
            [data-tip-pos="left"]:hover::after,
            [data-tip-pos="left"]:focus-visible::after {
                top: 50%;
                bottom: auto;
                right: calc(100% + 8px);
                left: auto;
                transform: translateY(-50%);
            }
        }

        /* ==========================================================================
           11. SELF-LEARNING & PATH INTELLIGENCE INSET UI (GOLDEN RATIO φ = 1.618)
           ========================================================================== */
        .learning-section {
            padding: 12px 14px;
            border-bottom: 0.5px solid var(--border-subtle);
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .learning-section:last-child {
            border-bottom: none;
        }
        .learning-section-hdr {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            flex-wrap: wrap;
        }
        .learning-section-title {
            font-size: 12px;
            font-weight: 700;
            color: var(--text-primary);
            letter-spacing: -0.01em;
        }
        .learning-section-sub {
            font-size: 10px;
            color: var(--text-secondary);
        }
        .learning-grid-4 {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 8px;
        }
        .learning-grid-3 {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 8px;
        }
        @media (max-width: 520px) {
            .learning-grid-4 {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .learning-grid-3 {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        .learning-metric-tile {
            background: var(--surface-glass);
            border: 0.5px solid var(--border-subtle);
            border-radius: 10px;
            padding: 8px 10px;
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .learning-metric-label {
            font-size: 9px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            color: var(--text-tertiary);
        }
        .learning-metric-val {
            font-size: 14px;
            font-weight: 700;
            color: var(--text-primary);
        }
        .learning-banner-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            flex-wrap: wrap;
            padding: 8px 10px;
            border-radius: 10px;
            background: var(--surface-glass);
            border: 0.5px solid var(--border-subtle);
            font-size: 11px;
            line-height: 1.38;
            color: var(--text-secondary);
        }
        .learning-bucket-list {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .learning-bucket-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 8px 10px;
            border-radius: 10px;
            background: var(--surface-glass);
            border: 0.5px solid var(--border-subtle);
        }
        .learning-bucket-main {
            min-width: 0;
            flex: 1.618;
            display: flex;
            flex-direction: column;
            gap: 3px;
        }
        .learning-bucket-key {
            font-size: 11px;
            font-weight: 600;
            color: var(--text-primary);
            word-break: break-word;
        }
        .learning-bucket-tags {
            display: flex;
            align-items: center;
            gap: 5px;
            flex-wrap: wrap;
        }
        .learning-bucket-stats {
            flex: 1;
            text-align: right;
            font-size: 10px;
            color: var(--text-secondary);
            white-space: nowrap;
        }
        .learning-audit-details {
            background: var(--surface-glass);
            border: 0.5px solid var(--border-subtle);
            border-radius: 10px;
            padding: 8px 10px;
        }
        .learning-audit-details summary {
            cursor: pointer;
            font-size: 11px;
            font-weight: 600;
            color: var(--text-primary);
            display: flex;
            align-items: center;
            justify-content: space-between;
            list-style: none;
        }
        .learning-audit-details summary::-webkit-details-marker {
            display: none;
        }
        .learning-audit-body {
            margin-top: 8px;
            padding-top: 8px;
            border-top: 0.5px solid var(--border-subtle);
            font-size: 11px;
            line-height: 1.45;
            color: var(--text-secondary);
            white-space: pre-wrap;
            word-break: break-word;
        }

        /* HIDDEN SKELETON CONTAINERS PRESERVING SCRIPT BINDING */
        .ghost-dom-binder {
            display: none !important;
        }
    </style>
</head>
<body>

    <!-- 1. APPLE NAVIGATION BAR -->
    <header class="apple-nav">
        <div class="apple-nav-inner">
            <div class="nav-leading">
                <span class="nav-pulse-dot"></span>
                <div class="nav-title-group">
                    <span class="nav-title">Sentinel Trading</span>
                    <span class="nav-subtitle mono" id="top-clock">--:--:--</span>
                </div>
            </div>
            <div class="nav-trailing">
                <button class="apple-nav-btn mono" onclick="toggleTheme()" id="theme-btn">LIGHT</button>
                <button class="apple-nav-btn mono" onclick="fetchData()">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                    SYNC
                </button>
            </div>
        </div>
    </header>

    <main class="app-container">

        <!-- 2. TOTAL HERO PORTFOLIO STATS & CONTI SEPARATI -->
        <section class="hero-equity-card">
            <div class="hero-equity-label" id="hero-main-label" data-tip-pos="bottom" data-tip="Patrimonio complessivo convertito in USD sommando il conto Bybit Futures e il broker Alpaca Wall Street">Patrimonio Consolidato</div>
            <div class="hero-equity-amount mono" id="total-equity">$0.00</div>
            <div class="hero-delta-strip mono">
                <span id="hero-delta-display" class="val-up">+0.00%</span>
                <span style="color: var(--text-tertiary);">&bull;</span>
                <span id="total-unrealized" style="color: var(--text-secondary); font-size: 12px;">+$0.00 fluttuante</span>
                <span class="hero-delta-badge" id="hud-trend-badge" style="background: var(--apple-green-bg); color: var(--apple-green);">STABILE</span>
            </div>

            <!-- Due Conti Distinti con Patrimoni Separati -->
            <div class="hero-accounts-split mono">
                <div class="hero-sub-account active-acc" id="sub-acc-bybit" onclick="showTab('bybit')">
                    <div class="hero-sub-label">
                        <span>BYBIT (CRYPTO)</span>
                        <span style="color: var(--apple-blue); font-size: 9px;">24/7</span>
                    </div>
                    <div class="hero-sub-amount" id="hero-bybit-amount">$0.00</div>
                    <div class="hero-sub-meta" id="hero-bybit-sub">Disponibile: $0 USDT</div>
                </div>
                <div class="hero-sub-account" id="sub-acc-alpaca" onclick="showTab('alpaca')">
                    <div class="hero-sub-label">
                        <span>ALPACA (USA)</span>
                        <span style="color: var(--apple-amber); font-size: 9px;">WALL ST</span>
                    </div>
                    <div class="hero-sub-amount" id="hero-alpaca-amount">$0.00</div>
                    <div class="hero-sub-meta" id="hero-alpaca-sub">BP: $0</div>
                </div>
            </div>
        </section>

        <!-- 3. APPLE INTERACTIVE CHART CARD -->
        <section class="apple-chart-card">
            <!-- Mercato controllato direttamente dalla Tab attiva (Zero duplicazione pulsanti) -->

            <!-- Timeframe Selector Pills -->
            <div class="tf-pills-row mono">
                <button class="tf-pill active" id="btn-tf-3s" onclick="setTimeframe('3s')">3S</button>
                <button class="tf-pill" id="btn-tf-1m" onclick="setTimeframe('1m')">1M</button>
                <button class="tf-pill" id="btn-tf-1h" onclick="setTimeframe('1h')">1H</button>
                <button class="tf-pill" id="btn-tf-1d" onclick="setTimeframe('1d')">1D</button>
                <button class="tf-pill" id="btn-tf-1w" onclick="setTimeframe('1w')">1W</button>
                <button class="tf-pill" id="btn-tf-1M" onclick="setTimeframe('1M')">1MO</button>
            </div>

            <!-- HUD Informazioni Live Chart -->
            <div class="chart-hud-apple mono">
                <div class="chart-hud-stat">
                    <span>LIVE: </span><strong id="hud-live-val" style="color: var(--apple-blue);">$0.00</strong>
                </div>
                <div class="chart-hud-stat">
                    <span id="hud-range-val" style="color: var(--text-secondary);">L: $0 &bull; H: $0</span>
                </div>
                <div class="chart-hud-stat">
                    <span id="chart-instance-title" style="color: var(--apple-blue);">BYBIT FUTURES (24/7)</span>
                </div>
            </div>

            <!-- Canvas Chart.js -->
            <div class="chart-container-inner">
                <div class="scrub-overlay" id="chart-scrub-badge"></div>
                <canvas id="perfChart"></canvas>
            </div>

            <!-- Segmented Control Modalità Grafico: Patrimonio vs PnL & Valuta vs Percentuale -->
            <div class="apple-segmented mono" style="margin-top: 10px; margin-bottom: 4px;">
                <button class="apple-segment-item active" id="btn-view-pnl" onclick="setChartMetric('pnl')">PnL Operativo</button>
                <button class="apple-segment-item" id="btn-view-wallet" onclick="setChartMetric('wallet')">Patrimonio</button>
                <button class="apple-segment-item active" id="btn-mode-pct" onclick="setChartMode('pct')">% Percentuale</button>
                <button class="apple-segment-item" id="btn-mode-usd" onclick="setChartMode('usd')">$ Dollari</button>
            </div>

            <!-- Quick Metrics Grid (Dinamico per Mercato Selezionato) -->
            <div class="chart-quick-metrics mono">
                <div class="quick-metric-cell" id="qcell-1" data-tip-pos="top-left" data-tip="Volume nozionale cumulato scambiato dai trade">
                    <span id="qlabel-1">Volume</span>
                    <strong id="metric-volume">$0</strong>
                </div>
                <div class="quick-metric-cell" id="qcell-2" data-tip="Profit &amp; Loss netto consolidato delle operazioni chiuse">
                    <span id="qlabel-2">PnL Chiuso</span>
                    <strong id="metric-realized">$0.00</strong>
                </div>
                <div class="quick-metric-cell" id="qcell-3" data-tip="Percentuale di operazioni chiuse con profitto positivo">
                    <span id="qlabel-3">Win Rate</span>
                    <strong id="metric-winrate">0%</strong>
                </div>
                <div class="quick-metric-cell" id="qcell-4" data-tip-pos="top-right" data-tip="Media matematica netta guadagnata o persa per singolo trade">
                    <span id="qlabel-4">Trade Medio</span>
                    <strong id="metric-avg-trade">$0.00</strong>
                </div>
            </div>
            <button id="btn-reset-zoom" onclick="resetChartZoom()" style="display: none;"></button>
        </section>

        <!-- ====================================================================
             TAB 1: BYBIT FUTURES & QUANTITATIVE COMPASS (ACTIVE DEFAULT)
             ==================================================================== -->
        <div id="view-bybit">
            <!-- Active Positions Section -->
            <div class="section-header-apple">
                <span>Posizioni Attive (Futures 24/7)</span>
                <span id="active-positions-count" class="mono" style="font-size: 11px; color: var(--apple-blue);">0 attive</span>
            </div>
            <div id="bybit-positions-list">
                <div style="padding: 24px 0; text-align: center; color: var(--text-tertiary);" class="mono">
                    Caricamento posizioni...
                </div>
            </div>

            <!-- SELETTORE ASSET RAPIDO: APRE LA SCHEDA PREVISIONI/CICLICA AL TOCCO -->
            <div class="section-header-apple">
                <span>Analisi &amp; Previsioni al Tocco</span>
                <span class="mono" style="font-size: 10px; color: var(--text-secondary);">Tocca un asset</span>
            </div>
            <div class="apple-group-card" style="padding: 10px 14px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                    <div class="mono" style="font-size: 11px; color: var(--text-secondary);">Crypto Watchlist:</div>
                    <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                        <button class="tf-pill" onclick="openTradeModal('BTCUSDT', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-blue);">BTC</button>
                        <button class="tf-pill" onclick="openTradeModal('ETHUSDT', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-blue);">ETH</button>
                        <button class="tf-pill" onclick="openTradeModal('SOLUSDT', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-blue);">SOL</button>
                        <button class="tf-pill" onclick="openTradeModal('XRPUSDT', 'SHORT', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-blue);">XRP</button>
                        <button class="tf-pill" onclick="openTradeModal('LINKUSDT', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-blue);">LINK</button>
                        <button class="tf-pill" onclick="openTradeModal('AVAXUSDT', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-blue);">AVAX</button>
                    </div>
                </div>
            </div>

            <!-- Quantitative Trading Compass & Setup Readiness Radar -->
            <div class="section-header-apple">Metriche di Portafoglio &amp; Setup Pre-Trade</div>
            <div class="apple-group-card">
                <div class="apple-cell" data-tip="Misura la convergenza statistica e salute dei trade aperti. A mercato flat rimane giustamente sul benchmark neutro di 50.">
                    <div class="cell-leading">
                        <span class="cell-title">Health &amp; Alignment Score</span>
                        <span class="cell-subtitle" id="compass-desc-el">Fase di consolidamento del mercato</span>
                    </div>
                    <div class="cell-trailing">
                        <span class="cell-value mono" id="compass-score-val" style="font-size: 18px; color: var(--apple-amber);">50</span>
                        <span class="badge mono" id="compass-badge-el" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: var(--apple-amber-bg); color: var(--apple-amber);">HOLD</span>
                    </div>
                </div>
                
                <div class="apple-cell" data-tip="Radar pre-trade: monitora l'avvicinamento al trigger d'ingresso tramite Macro Bias, Ciclica Hurst, RSI e Order Book OBI.">
                    <div class="cell-leading">
                        <span class="cell-title">Indice di Confluenza Pre-Trade</span>
                        <span class="cell-subtitle" id="readiness-desc-el">Accumulo in corso</span>
                        <div style="width: 140px; height: 4px; background: var(--surface-glass); border-radius: 2px; overflow: hidden; margin-top: 6px;">
                            <div id="readiness-bar-fill" style="width: 50%; height: 100%; background: var(--apple-blue); transition: width 0.3s ease;"></div>
                        </div>
                    </div>
                    <div class="cell-trailing">
                        <span class="cell-value mono" id="readiness-score-val" style="font-size: 18px; color: var(--apple-blue);">50</span>
                        <span class="badge mono" id="readiness-badge-el" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(10, 132, 255, 0.15); color: var(--apple-blue);">WAIT</span>
                    </div>
                </div>

                <div class="apple-cell" style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 10px 14px;">
                    <div class="mono" style="font-size: 11px;" data-tip-pos="top-left" data-tip="Pilastro Macro (0-25): allineamento strutturale 4H e 1H dell'asset guida BTC"><span style="color: var(--text-tertiary);">Macro:</span> <b id="readiness-p-macro">0/25</b></div>
                    <div class="mono" style="font-size: 11px;" data-tip-pos="top-right" data-tip="Pilastro Ciclica (0-25): fase del Battleplan T+2 e distanza dalla FLD di Hurst"><span style="color: var(--text-tertiary);">Ciclica:</span> <b id="readiness-p-cycle">0/25</b></div>
                    <div class="mono" style="font-size: 11px;" data-tip-pos="top-left" data-tip="Pilastro RSI (0-25): spinta e posizione di Wilder RSI rispetto alle bande operative"><span style="color: var(--text-tertiary);">RSI:</span> <b id="readiness-p-rsi">0/25</b></div>
                    <div class="mono" style="font-size: 11px;" data-tip-pos="top-right" data-tip="Pilastro Order Book (0-25): squilibrio Bid/Ask (OBI) e pressione CVD aggressiva"><span style="color: var(--text-tertiary);">OrderBook:</span> <b id="readiness-p-book">0/25</b></div>
                </div>

                <!-- 4 Diagnostic Metrics -->
                <div class="apple-cell" style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 12px 14px;">
                    <div data-tip-pos="top-left" data-tip="Valore monetario medio atteso per singola operazione Bybit calcolato su base storica.">
                        <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase;">Expected Value</div>
                        <div class="mono" id="diag-ev-val" style="font-size: 14px; font-weight: 700; color: var(--apple-green);">+$0.00</div>
                    </div>
                    <div data-tip-pos="top-right" data-tip="Rapporto tra vincita media e perdita media reale crypto confrontato con il target 1:3.0 (TP 3.0x SL ATR).">
                        <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase;">R:R Reale vs Target</div>
                        <div class="mono" id="diag-rr-val" style="font-size: 14px; font-weight: 700;">1:3.0</div>
                    </div>
                    <div data-tip-pos="top-left" data-tip="Percentuale e conteggio dei contratti Futures aperti attualmente in utile non realizzato.">
                        <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase;">Posizioni in Gain</div>
                        <div class="mono" id="diag-itm-val" style="font-size: 14px; font-weight: 700;">0%</div>
                        <span id="diag-prot-sub" style="font-size: 9px; color: var(--text-tertiary);">0 a Break-Even</span>
                    </div>
                    <div data-tip-pos="top-right" data-tip="Rapporto tra profitti lordi e perdite lorde chiuse su Bybit. Valori sopra 1.50 confermano edge statistico.">
                        <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase;">Profit Factor</div>
                        <div class="mono" id="diag-pf-val" style="font-size: 14px; font-weight: 700;">0.00</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ====================================================================
             TAB 2: ALPACA EQUITIES (WALL STREET)
             ==================================================================== -->
        <div id="view-alpaca" class="hidden">
            <div class="section-header-apple">
                <span>Posizioni Azionarie Wall Street</span>
                <span class="mono" style="font-size: 11px; color: var(--apple-amber);">NYSE / NASDAQ</span>
            </div>
            <div id="alpaca-cards-list" class="mobile-card-list mono"></div>

            <!-- SELETTORE RAPIDO WALL STREET: APRE LA SCHEDA PREVISIONI/CICLICA AL TOCCO -->
            <div class="section-header-apple">
                <span>Analisi &amp; Previsioni al Tocco</span>
                <span class="mono" style="font-size: 10px; color: var(--text-secondary);">Tocca un titolo</span>
            </div>
            <div class="apple-group-card" style="padding: 10px 14px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                    <div class="mono" style="font-size: 11px; color: var(--text-secondary);">Equities Watchlist:</div>
                    <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                        <button class="tf-pill" onclick="openTradeModal('NVDA', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-amber);">NVDA</button>
                        <button class="tf-pill" onclick="openTradeModal('AAPL', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-amber);">AAPL</button>
                        <button class="tf-pill" onclick="openTradeModal('MSFT', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-amber);">MSFT</button>
                        <button class="tf-pill" onclick="openTradeModal('TSLA', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-amber);">TSLA</button>
                        <button class="tf-pill" onclick="openTradeModal('AMZN', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-amber);">AMZN</button>
                        <button class="tf-pill" onclick="openTradeModal('GOOGL', 'LONG', 0, 0)" style="padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--apple-amber);">GOOGL</button>
                    </div>
                </div>
            </div>

            <!-- METRICHE PORTAFOGLIO & SETUP PRE-TRADE (ALPACA WALL STREET) -->
            <div class="section-header-apple">
                <span>Metriche di Portafoglio &amp; Setup Pre-Trade</span>
            </div>
            <div class="apple-group-card">
                <div class="apple-cell" style="padding: 12px 14px;" data-tip="Indice sintetico Wall Street (0-100): valuta allineamento, win rate e protezione delle posizioni azionarie USA aperte.">
                    <div class="cell-leading">
                        <span class="cell-title">Health &amp; Alignment Score</span>
                        <span class="cell-subtitle" id="alpaca-compass-verdict-desc">Analisi strutturale Wall Street (SPY/VIX).</span>
                    </div>
                    <div class="cell-trailing">
                        <span class="cell-value mono" id="alpaca-compass-score-val" style="color: var(--apple-blue); font-size: 20px;">--</span>
                        <span class="badge mono" id="alpaca-compass-verdict-badge" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(10,132,255,0.14); color: var(--apple-blue);">CARICAMENTO</span>
                    </div>
                </div>
                <div class="apple-cell" style="padding: 12px 14px; flex-direction: column; align-items: stretch; gap: 8px;" data-tip="Radar pre-trade NYSE/NASDAQ: combina trend SPY, ciclica 1H, RSI e regime di volatilita VIX Shield.">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div class="cell-title">Indice di Confluenza Pre-Trade</div>
                            <div style="font-size: 11px; color: var(--text-secondary);" id="alpaca-readiness-movement">Verifica SPY, Ciclica 1H e VIX Shield...</div>
                        </div>
                        <div style="text-align: right;">
                            <span class="cell-value mono" id="alpaca-readiness-score-val" style="font-size: 18px; color: var(--apple-amber);">--</span>
                            <div class="badge mono" id="alpaca-readiness-verdict-badge" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(255,159,10,0.14); color: var(--apple-amber); margin-top: 2px;">ANALISI</div>
                        </div>
                    </div>
                    <div class="progress-track" style="height: 4px; background: var(--fill-tertiary); border-radius: 2px; overflow: hidden;">
                        <div id="alpaca-readiness-progress-bar" style="width: 0%; height: 100%; background: var(--apple-amber); transition: width 0.4s ease;"></div>
                    </div>
                </div>
                <div class="apple-cell" style="padding: 10px 14px;">
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; font-size: 11px;">
                        <div data-tip-pos="top-left" data-tip="Pilastro Macro SPY (0-25): direzione strutturale dell'indice S&amp;P 500 sulle finestre 4H/1H"><span style="color: var(--text-secondary);">Macro SPY:</span> <b class="mono" id="alpaca-bd-macro">--/25</b></div>
                        <div data-tip-pos="top-right" data-tip="Pilastro Ciclica 1H (0-25): centratura Hurst/Battleplan sul benchmark azionario"><span style="color: var(--text-secondary);">Ciclica 1H:</span> <b class="mono" id="alpaca-bd-cycle">--/25</b></div>
                        <div data-tip-pos="top-left" data-tip="Pilastro RSI Azionario (0-25): momentum relativo e assenza di ipercomprato estremo"><span style="color: var(--text-secondary);">RSI:</span> <b class="mono" id="alpaca-bd-rsi">--/25</b></div>
                        <div data-tip-pos="top-right" data-tip="VIX Volatility Shield (0-25): blocca automaticamente i nuovi LONG quando il VIX supera 24 o accelera oltre +2%"><span style="color: var(--text-secondary);">VIX Shield:</span> <b class="mono" id="alpaca-bd-book">--/25</b></div>
                    </div>
                </div>
                <div class="apple-cell" style="padding: 12px 14px;">
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; width: 100%;">
                        <div data-tip-pos="top-left" data-tip="Valore monetario medio atteso per trade azionario Wall Street su storico chiuso Alpaca.">
                            <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase;">Expected Value</div>
                            <div class="mono" id="alpaca-diag-ev-val" style="font-size: 15px; font-weight: 700;">$0.00</div>
                        </div>
                        <div data-tip-pos="top-right" data-tip="Rapporto rischio-rendimento realizzato su azioni USA rispetto al target dinamico 1:3.0 ATR.">
                            <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase;">R:R Reale vs Target</div>
                            <div class="mono" id="alpaca-diag-rr-val" style="font-size: 15px; font-weight: 700;">1:0.0</div>
                        </div>
                        <div data-tip-pos="top-left" data-tip="Quota di azioni USA in portafoglio attualmente in profitto e numero di titoli gia protetti a break-even.">
                            <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase;">Posizioni in Gain</div>
                            <div class="mono" id="alpaca-diag-win-val" style="font-size: 15px; font-weight: 700;">0%</div>
                            <div style="font-size: 10px; color: var(--text-tertiary);" id="alpaca-diag-be-sub">0 a Break-Even</div>
                        </div>
                        <div data-tip-pos="top-right" data-tip="Rapporto tra guadagni e perdite lorde sui titoli azionari USA chiusi su Alpaca.">
                            <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase;">Profit Factor</div>
                            <div class="mono" id="alpaca-diag-pf-val" style="font-size: 15px; font-weight: 700;">0.00</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ====================================================================
             TAB 3: STORICO OPERAZIONI E TRADE CHIUSI
             ==================================================================== -->
        <div id="view-history" class="hidden">
            <!-- Apple Style Group Card: Motore di Apprendimento Strutturale -->
            <div class="apple-group-card" id="journal-intelligence-card" style="margin-bottom: 16px;">
                <div class="apple-cell" style="padding: 12px 14px;" data-tip="Riepilogo globale delle esecuzioni reali chiuse e stato del motore auto-adattivo.">
                    <div class="cell-leading">
                        <span class="cell-title">Motore di Apprendimento Strutturale</span>
                        <span class="cell-subtitle">Path MFE/MAE, Shadow Ledger, Allocazione Bayesiana e Drift</span>
                    </div>
                    <div class="cell-trailing">
                        <span class="cell-value mono" id="journal-winrate-val" style="color: var(--apple-green);">0%</span>
                        <span class="badge mono" id="journal-stats-badge" style="font-size: 9px; padding: 1px 6px; background: rgba(255, 255, 255, 0.08); color: var(--text-secondary); border-radius: 4px;">Cap 70%</span>
                    </div>
                </div>

                <!-- 1. Path Quality (MFE / MAE / Capture Efficiency) & Exit Frontier -->
                <div class="learning-section" id="learning-path-section">
                    <div class="learning-section-hdr">
                        <div>
                            <div class="learning-section-title">Path Quality &amp; Exit Frontier</div>
                            <div class="learning-section-sub">Efficienza delle escursioni di prezzo nette delle fee</div>
                        </div>
                        <span class="badge badge-amber mono" id="learning-frontier-badge" data-tip-pos="top-right" data-tip="Gate Anti-Overfitting: attiva i livelli Ratchet adattivi solo con N >= 15 trade valutati e miglioramento LCB >= +0.05R netti.">RACCOLTA CAMPIONI</span>
                    </div>
                    <div class="learning-grid-4 mono">
                        <div class="learning-metric-tile" data-tip-pos="top-left" data-tip="Maximum Favorable Excursion media: picco massimo di profitto potenziale raggiunto durante i trade.">
                            <span class="learning-metric-label">Avg MFE</span>
                            <strong class="learning-metric-val val-up" id="learning-avg-mfe">+0.00%</strong>
                        </div>
                        <div class="learning-metric-tile" data-tip="Maximum Adverse Excursion media: drawdown massimo intraday toccato prima della chiusura.">
                            <span class="learning-metric-label">Avg MAE</span>
                            <strong class="learning-metric-val val-down" id="learning-avg-mae">0.00%</strong>
                        </div>
                        <div class="learning-metric-tile" data-tip="Capture Efficiency: percentuale dell'MFE massimo effettivamente convertita in profitto realizzato.">
                            <span class="learning-metric-label">Capture Eff</span>
                            <strong class="learning-metric-val" id="learning-capture-eff" style="color: var(--apple-blue);">0.0%</strong>
                        </div>
                        <div class="learning-metric-tile" data-tip-pos="top-right" data-tip="Edge Ratio (MFE / |MAE|): misura l'asimmetria favorevole del timing d'ingresso; valori >= 1.50x indicano forte edge.">
                            <span class="learning-metric-label">Edge Ratio</span>
                            <strong class="learning-metric-val" id="learning-edge-ratio">0.00x</strong>
                        </div>
                    </div>
                    <div class="learning-banner-row" id="learning-frontier-row">
                        <span id="learning-frontier-desc">Raccolta campioni MFE/MAE in corso (richiesti N &ge; 15 e LCB &ge; +0.05R netti).</span>
                    </div>
                </div>

                <!-- 2. Causal Shadow Ledger & Segnali Scartati -->
                <div class="learning-section" id="learning-shadow-section">
                    <div class="learning-section-hdr">
                        <div>
                            <div class="learning-section-title">Shadow Ledger &amp; Segnali Scartati</div>
                            <div class="learning-section-sub">Simulazione causale su barre future chiuse (SL prima di TP, netto fee)</div>
                        </div>
                        <span class="badge badge-neutral mono" id="learning-shadow-badge" data-tip-pos="top-right" data-tip="Conteggio degli shadow signal gia valutati rispetto a quelli ancora in attesa di maturazione (>= 90m).">0 VALUTATI</span>
                    </div>
                    <div class="learning-grid-3 mono">
                        <div class="learning-metric-tile" data-tip-pos="top-left" data-tip="Numero di segnali scartati dai filtri gia valutati su barre future rispetto al totale tracciato.">
                            <span class="learning-metric-label">Tracciati</span>
                            <strong class="learning-metric-val" id="learning-shadow-total">0 / 0</strong>
                        </div>
                        <div class="learning-metric-tile" data-tip="Aspettativa virtuale media in multipli di R dei segnali bloccati dai filtri di rischio.">
                            <span class="learning-metric-label">Virtual Avg R</span>
                            <strong class="learning-metric-val" id="learning-shadow-avg-r">+0.00R</strong>
                        </div>
                        <div class="learning-metric-tile" data-tip-pos="top-right" data-tip="Percentuale di segnali scartati che avrebbero raggiunto un esito virtuale positivo.">
                            <span class="learning-metric-label">Shadow Win Rate</span>
                            <strong class="learning-metric-val" id="learning-shadow-winrate">0.0%</strong>
                        </div>
                    </div>
                    <div class="learning-banner-row" id="learning-shadow-verdict" data-tip="Confronto tra opportunita profittevoli scartate (Missed Alpha) e trade perdenti evitati dai filtri (Capitale Salvato).">
                        <span>Nessun segnale scartato ancora valutato su barre future chiuse.</span>
                    </div>
                </div>

                <!-- 3. Allocazione Bayesiana Contestuale -->
                <div class="learning-section" id="learning-buckets-section">
                    <div class="learning-section-hdr">
                        <div>
                            <div class="learning-section-title">Allocazione Bayesiana Contestuale</div>
                            <div class="learning-section-sub">Shrinkage Normal-Gamma, half-life 35g e auto-riabilitazione Shadow</div>
                        </div>
                        <span class="badge badge-blue mono" id="learning-buckets-count" data-tip-pos="top-right" data-tip="Pesi dinamici per contesto: BOOST 1.25x, NORMAL 1.00x, CAUTIOUS 0.50x, SHADOW 0.00x (blocco virtuale).">0 CONTESTI</span>
                    </div>
                    <div id="learning-context-buckets-list" class="learning-bucket-list">
                        <div class="learning-banner-row">
                            <span>Nessun bucket contestuale consolidato: prior neutro 1.00x attivo.</span>
                        </div>
                    </div>
                </div>

                <!-- 4. Breakdown Motori + MetaGate Drift + Audit Settimanale -->
                <div class="learning-section" id="learning-audit-section">
                    <div class="learning-section-hdr">
                        <div>
                            <div class="learning-section-title">Performance Motori, MetaGate &amp; Self-Audit</div>
                            <div class="learning-section-sub">Ripartizione strategie, stato drift quant e ultimo report domenicale</div>
                        </div>
                        <span class="badge badge-neutral mono" id="learning-metagate-badge" data-tip-pos="top-right" data-tip="Stato del filtro secondario MetaGate per il monitoraggio del drift statistico sulle esecuzioni.">METAGATE OFF</span>
                    </div>
                    <div id="learning-engines-list" class="learning-bucket-list"></div>
                    <div class="learning-banner-row" id="learning-metagate-row">
                        <span id="learning-metagate-desc">MetaGate non configurato (modalita base multi-motore attiva).</span>
                    </div>
                    <details class="learning-audit-details" id="learning-audit-details">
                        <summary>
                            <span>Report Self-Audit Settimanale (Domenica 20:00 CET)</span>
                            <span class="badge badge-neutral mono" id="learning-audit-status">IN ATTESA</span>
                        </summary>
                        <div class="learning-audit-body mono" id="learning-audit-summary">Nessun audit settimanale registrato finora. Usa /learning su Telegram per generarlo su richiesta.</div>
                    </details>
                </div>

                <div id="journal-insights-list">
                    <!-- Popolato dinamicamente come righe .apple-cell coerenti -->
                </div>
            </div>

            <div class="section-header-apple">
                <span>Storico Trade Eseguiti</span>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <span class="mono" style="font-size: 11px; color: var(--apple-blue);" id="history-avg-label">Trade Medio: $0.00</span>
                    <span class="mono" style="font-size: 11px; color: var(--text-secondary);" id="closed-count-label">0 eseguiti</span>
                </div>
            </div>

            <div class="table-responsive-container mobile-hide-table">
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
            <div id="history-cards-list" class="mobile-card-list mono"></div>
        </div>

        <!-- ====================================================================
             TAB 4: GUIDA OPERATIVA & MANUALE DESK
             ==================================================================== -->
        <div id="view-guide" class="hidden">
            <div class="section-header-apple">
                <span>Guida Operativa &amp; Significato Indicatori</span>
                <span class="mono" style="font-size: 10px; color: var(--text-tertiary);">MANUALE PRATICO</span>
            </div>
        
        <div style="display: flex; flex-direction: column; gap: 14px;">
            
            <!-- Card 1: Monitoraggio Singole Posizioni -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">1. Come Leggere una Posizione Aperta</strong>
                    <span class="badge mono" style="background: var(--blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">TRADE LIVE</span>
                </div>
                <div style="font-size: 12px; color: var(--text-muted); line-height: 1.5; margin-bottom: 10px;">
                    Ogni riga di trade contiene le informazioni essenziali per monitorare il rischio al centesimo con protezioni calibrate sull'ATR:
                </div>
                <div style="background: var(--surface-elevated); padding: 10px; border-radius: 6px; border: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px; font-size: 11px;">
                    <div><strong>• Sizing Dinamico &amp; Bayesiano:</strong> Base 10% dell'equity scalata dinamicamente dal contesto Bayesiano (<code>1.25x</code> Boost, <code>1.0x</code> Standard, <code>0.5x</code> Cautious, <code>0.0x</code> Shadow Mode).</div>
                    <div><strong>• Ratchet Trailing Stop Dinamico su base ATR (<code>1.4x ATR</code>, range <code>0.90%-2.20%</code>):</strong>
                        <br>&nbsp;&nbsp;1. <code>TIGHT (-0.40x SL)</code> al raggiungimento di <code>+0.75x SL</code>: taglia il rischio iniziale impedendo ritracciamenti precoci in perdita piena.
                        <br>&nbsp;&nbsp;2. <code>BE SAFE (&ge; +0.25%, 0.25x SL)</code> a <code>+1.15x SL</code>: rischio azzerato e fee round-trip coperte.
                        <br>&nbsp;&nbsp;3. <code>LOCK MID (+0.80x SL)</code> a <code>+1.80x SL</code>: garantisce profitto intermedio protetto.
                        <br>&nbsp;&nbsp;4. <code>LOCK MAX (+1.40x SL)</code> a <code>+2.40x SL</code>: blinda il rendimento in corsa verso il TP <code>3.0x SL</code> (R:R 1:3).
                    </div>
                    <div><strong>• Kill-Zones Istituzionali:</strong> Europa (08:00 - 12:00 CET) e USA (14:30 - 21:30 CET) a massima liquidità. Fascia notturna (00:00 - 07:00 CET) a iper-selettività (volume minimo 1.40x per bloccare fakeout).</div>
                    <div><strong>• CVD Flow Shield (Cumulative Volume Delta):</strong> Misura gli ordini a mercato aggressivi. Rifiuta categoricamente acquisti se i venditori scaricano a mercato e rifiuta short se i compratori assorbono liquidità.</div>
                </div>
            </div>

            <!-- Card 2: Trading Compass & Metriche Quant -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">2. Metriche di Rischio &amp; Indice di Confluenza (Pre-Trade)</strong>
                    <span class="badge mono" style="background: var(--green); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">STATISTICA OPERATIVA</span>
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px; font-size: 11px; line-height: 1.45;">
                    <div><strong>• Health &amp; Alignment Score (0-100):</strong> Misura la salute dei <em>trade già aperti a mercato</em> (convergenza di win rate, profit factor, posizioni a break-even e PnL fluttuante). A mercato flat rimane giustamente sul benchmark neutro di 50.</div>
                    <div><strong>• Indice di Confluenza Pre-Trade (0-100):</strong> Monitora in tempo reale quanto il mercato è vicino ad attivare un nuovo ordine di trading anche se non ci sono posizioni aperte. Si compone di 4 pilastri da 25 punti: <strong>Macro Bias (4H+1H)</strong>, <strong>Ciclica Hurst/FLD</strong>, <strong>Momentum RSI</strong> e <strong>Order Book OBI</strong>. Sopra 75 = trigger imminente; 55-74 = fase di maturazione/accumulo; sotto 55 = stand-by rigido.</div>
                    <div><strong>• Expected Value (EV):</strong> Il valore matematico atteso per ogni trade. Se positivo (es. <code>+$45</code>), ogni operazione genera mediamente 45 dollari di profitto nel tempo.</div>
                    <div><strong>• R:R Reale vs Target:</strong> Rapporto tra vincita media e perdita media. Con Take Profit calibrato a <code>3.0x</code> dello Stop Loss dinamico ATR (range SL <code>0.90%-2.20%</code>), il rapporto target resta costantemente <strong>1:3.0</strong>.</div>
                    <div><strong>• Profit Factor:</strong> Rapporto tra tutti i profitti lordi e tutte le perdite lorde. Valori sopra 1.5 indicano un sistema statistico profittevole.</div>
                    <div><strong>• Posizioni in Gain &amp; Break-Even:</strong> Indica quanti dei contratti aperti sono già in attivo e quanti hanno il rischio totalmente azzerato.</div>
                </div>
            </div>

            <!-- Card 3: Regola Aurea Macro BTC Shield, Squeeze Funding & Alpha vs BTC -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">3. Gestione del Rischio, Registro Operazioni &amp; Cap Capitale 70%</strong>
                    <span class="badge mono" style="background: var(--amber); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">GESTIONE RISCHIO</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Il sistema combina trend strutturale, cicli di Hurst/Migliorino, Order Flow CVD e la nuova architettura di Trade Journaling e Cap Dinamico:<br>
                    <strong>• Esposizione Flessibile Fino al 70% del Capitale:</strong> Rimosso il vecchio vincolo rigido dei 3 trade. Se il mercato offre opportunità simultanee con rating A+, il bot apre posizioni modulando la size base del 10% con il moltiplicatore Bayesiano, fino a un tetto massimo di esposizione pari al 70% dell'equity totale (garantendo sempre un buffer liquido intoccabile del 30%).<br>
                    <strong>• Registro Esecuzioni &amp; Storico Dettagliato:</strong> Ogni posizione aperta registra motore, contesto (<code>context_key</code>) e parametri quantitativi di ingresso. Alla chiusura vengono calcolate MFE, MAE, Capture Efficiency ed Edge Ratio.<br>
                    <strong>• Integrazione Fondamentale Sentinella:</strong> La Sentinella analizza in tempo reale le disclosure istituzionali (Capitol Hill PTR) e le breaking news aziendali/downgrade. Gli asset con news flow negativo vengono automaticamente esclusi dai LONG; gli asset con catalyst positivi ricevono un Boost di priorità.<br>
                    <strong>• Scudo Macro SPY/BTC &amp; VIX Volatility Shield:</strong> Monitora BTC 4H/1H per le crypto e SPY con l'indice di volatilità VIX per Wall Street. Se il VIX è in ascesa (+2% o superiore a 24 punti) o in fase di shock, il regime azionario passa categoricamente a BEARISH vietando tassativamente qualsiasi acquisto LONG e proteggendo il capitale. Include il filtro di stabilizzazione per i primi 15 minuti di apertura a Wall Street (15:30-15:45 CET) e il Ratchet Trailing Stop ATR a 4 scalini (<code>+0.75x SL</code> &rarr; Tight, <code>+1.15x SL</code> &rarr; Break-Even Safe <code>&ge; +0.25%</code>, <code>+1.80x SL</code> &rarr; Lock Mid, <code>+2.40x SL</code> &rarr; Lock Max).
                </div>
            </div>

            <!-- Card 4: Patrimonio Bybit UTA & Composizione Demo -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">4. Patrimonio Bybit UTA &amp; Composizione Demo</strong>
                    <span class="badge mono" style="background: var(--blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">BYBIT UTA</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    <strong>• Total Equity:</strong> Somma a prezzi di mercato correnti tutti gli asset del conto (1 BTC spot, 1 ETH spot, 50,000 USDC e USDT disponibili).<br>
                    <strong>• Margine Libero USDT:</strong> Liquidità cash non impegnata in posizioni aperte, pronta per nuovi ordini derivati.<br>
                    <strong>• Accreditamento Profitti:</strong> I guadagni delle posizioni chiuse incrementano direttamente il saldo USDT disponibile.<br>
                    <strong>• Storico Trade:</strong> Riporta la colonna <strong>Investito ($)</strong> (~$15,000, 10% equity), <strong>PnL Netto</strong> e <strong>Resa %</strong> con <strong>Trade Medio</strong>.
                </div>
            </div>

            <!-- Card 5: Broker Separati & Grafici Indipendenti (Crypto vs Wall Street) -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">5. Broker Separati &amp; Grafici Indipendenti</strong>
                    <span class="badge mono" style="background: var(--apple-blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">MULTI-ASSET</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Ogni mercato opera su orari e grafici dedicati con identità cromatiche distinte:<br>
                    <strong>• Bybit Crypto (Blu Elettrico):</strong> Opera 24/7 (weekend compreso) sui futures liquidi (BTC, ETH, SOL, LINK, AVAX, XRP). Metriche sotto il grafico: Volume, PnL Chiuso, Win Rate e Trade Medio.<br>
                    <strong>• Alpaca Wall St (Oro / Ambra):</strong> Opera dal lunedì al venerdì (15:30 - 22:00 CET) sulle azioni USA (NYSE/NASDAQ). Metriche dedicate: Valore Titoli, Buying Power Cash, Titoli Aperti e Stato Mercato.<br>
                    <strong>• Consolidato (Viola):</strong> Panoramica globale combinata di entrambi i broker ($263k+).<br>
                    <strong>• Timeframe (3S, 1M, 1H, 1D, 1W, 1MO):</strong> Dal micro-tick in tempo reale fino all'orizzonte mensile.<br>
                    <strong>• Zoom su iPhone:</strong> Trascina per scorrere nel tempo, clicca <code>RESET ZOOM</code> per ripristinare.
                </div>
            </div>

            <!-- Card 6: Mini-Sparklines & Target R:R Progress -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">6. Mini-Sparklines &amp; Barra Progresso R:R 1:3</strong>
                    <span class="badge mono" style="background: var(--blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">REAL-TIME</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Sotto ogni posizione aperta è presente un box tecnico grafico ad alta densità:<br>
                    <strong>• Mini-Sparkline (15m):</strong> Mostra il trend a 15 minuti del sottostante con il punto live del prezzo corrente.<br>
                    <strong>• Livelli Prezzo TP &amp; SL Dinamici:</strong> Riporta il valore esatto in dollari di Take Profit (<code>3.0x SL ATR</code>) e Stop Loss (<code>1.4x ATR</code>, range <code>0.90%-2.20%</code>).<br>
                    <strong>• Barra di Progresso:</strong> Indica visivamente la percentuale di completamento verso il profitto netto target e la distanza rimanente.
                </div>
            </div>

            <!-- Card 7: Notifiche Push Telegram Smart -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">7. Notifiche Telegram &amp; Report Serale 22:00</strong>
                    <span class="badge mono" style="background: var(--green); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">ALERT 24/7</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Il bot comunica su Telegram esclusivamente nei momenti chiave di transizione del rischio:<br>
                    <strong>• Inversione Macro BTC 4H:</strong> Notifica quando il trend generale passa da Bullish a Bearish.<br>
                    <strong>• Break-Even Safe (<code>+1.15x SL</code>):</strong> Avviso quando lo stop viene alzato sopra l'ingresso (<code>&ge; +0.25%</code> netto a copertura delle fee).<br>
                    <strong>• Trailing Profit Lock (<code>+2.40x SL</code>):</strong> Avviso quando viene blindato il profitto finale (<code>+1.40x SL</code>) in corsa verso il Target 3R.<br>
                    <strong>• Chiusura TP / SL Dinamico:</strong> Riepilogo immediato con dollari incassati e PnL percentuale basato su <code>1.4x ATR</code>.<br>
                    <strong>• Report Giornaliero (22:00 CET) &amp; Audit Domenicale (20:00 CET):</strong> Un bilancio serale alle 22:00 CET e il self-audit statistico domenicale alle 20:00 CET (richiamabile anche con <code>/learning</code>).
                </div>
            </div>

            <!-- Card 8: Scheda Tattica Operativa, Livelli Interattivi & Diagnostica Ciclica -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">8. Analisi Ciclica &amp; Livelli Operativi</strong>
                    <span class="badge mono" style="background: var(--apple-blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">ANALISI TECNICA</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Toccando qualsiasi asset della watchlist o trade aperto si apre il pannello operativo tattico:<br>
                    <strong>• Livelli Operativi (Cosa fare ADESSO):</strong> Un box evidente che sintetizza senza ambiguità l'azione da compiere (<em>COMPRA / ACCUMULO</em>, <em>SHORT / HEDGE</em>, <em>PREPARA LIQUIDITÀ</em>, <em>STAND-BY</em>) indicando il Target di Take Profit suggerito da Fibonacci, lo Stop Loss di difesa e le barre stimate prima della prossima finestra di inversione ciclica.<br>
                    <strong>• Filtro Livelli a Pillole Interattive:</strong> Puoi isolare le curve con un tocco: <em>Tutti i Livelli</em>, <em>Prezzo + Monte Carlo</em> (intervallo di probabilità stocastico a cono P05-P95), <em>Hurst FLD</em> (linea di demarcazione T/2) oppure <em>Battleplan 4 Tempi</em> (sinusoide di Giuseppe Migliorino).<br>
                    <strong>• Hurst FLD (Future Line of Demarcation):</strong> Traslazione a mezzo periodo T/2: il superamento al rialzo della FLD conferma la nascita del nuovo ciclo con target sul massimo; la rottura al ribasso proietta verso il pavimento ciclico.<br>
                    <strong>• Battleplan e Vincolo di Migliorino:</strong> Mostra in quale dei 4 tempi (quarti) si trova il ciclo corrente (~32 barre per il mensile T+2). Se il minimo di partenza viene violato, scatta il vincolo ribassista obbligatorio secondo le leggi cicliche.<br>
                    <strong>• Grafici Apple Stocks a Colore Adattivo:</strong> Il grafico principale in Home adotta una scala cromatica dinamica ad alta leggibilità: diventa verde brillante (#30D158) quando il periodo è in guadagno e rosso corallo (#FF453A) in calo, con curve continue Catmull-Rom prive di assi ingombranti.
                </div>
            </div>

            <!-- Card 9: Motore Multi-Strategia & Regime Router -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">9. Motore Multi-Strategia &amp; Regime Router</strong>
                    <span class="badge mono" style="background: var(--apple-blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">PILLAR 1</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Il Regime Router seleziona dinamicamente quali motori possono operare in base ad ADX 1H, ATR%, Funding Rate, Spread e VIX:<br>
                    <strong>• Trend Pullback 4H/1D (<code>TREND_PULLBACK_4H</code>):</strong> Opera nei trend strutturali con ordini <em>Maker Limit</em> vicino alla EMA20 1H o alla FLD di Hurst, allineato alla direzione 4H.<br>
                    <strong>• Liquidity Sweep Mean Reversion (<code>LIQUIDITY_SWEEP_MR</code>):</strong> Attivo in range o squeeze (<code>ADX &lt; 18</code> o Funding estremo): esegue fade contrarian <em>Maker Limit</em> su spike con wick &ge; 0.45 confermati da CVD, OBI o estremi di Funding.<br>
                    <strong>• Intraday Momentum (<code>INTRADAY_MOMENTUM</code>):</strong> Breakout intraday a 15m con filtro anti-chop (<code>ADX &ge; 16</code>) e scudi VIX, CVD, Volume Notturno, Ciclo e OBI.
                </div>
            </div>

            <!-- Card 10: Causal Shadow Ledger -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">10. Causal Shadow Ledger (Segnali Scartati)</strong>
                    <span class="badge mono" style="background: var(--apple-purple); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">PILLAR 2</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Ogni segnale bloccato da un filtro di rischio o da un contesto in <em>Shadow Mode</em> non viene dimenticato:<br>
                    <strong>• Registrazione Immutabile:</strong> Viene salvato in <code>signal_shadows</code> con motivo dello scarto, prezzo del segnale, SL% e TP%.<br>
                    <strong>• Valutazione Causale su Barre Future Chiuse:</strong> Dopo la maturazione (<code>&ge; 90 minuti</code>), il motore simula il percorso reale esclusivamente su candele future chiuse, controllando lo Stop Loss prima del Take Profit sulle barre ambigue e sottraendo le commissioni round-trip.<br>
                    <strong>• Missed Alpha vs Capitale Salvato:</strong> Misura con precisione se i filtri stanno proteggendo il capitale (<code>Virtual Avg R &le; 0</code>) o scartando opportunita profittevoli (<code>Missed Alpha</code>).
                </div>
            </div>

            <!-- Card 11: Analisi Percorso MFE / MAE & Exit Frontier Adattiva -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">11. Analisi Percorso MFE / MAE &amp; Exit Frontier</strong>
                    <span class="badge mono" style="background: var(--green); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">PILLAR 3</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Ogni trade chiuso viene ricostruito barra per barra per valutarne la qualita di esecuzione:<br>
                    <strong>• MFE (Maximum Favorable Excursion):</strong> Picco massimo di profitto potenziale toccato durante la vita del trade.<br>
                    <strong>• MAE (Maximum Adverse Excursion):</strong> Massimo drawdown intraday subito prima dell'uscita.<br>
                    <strong>• Edge Ratio &amp; Capture Efficiency:</strong> L'<code>Edge Ratio</code> (<code>MFE / |MAE|</code>) valuta l'asimmetria dell'ingresso; la <code>Capture Efficiency</code> (<code>PnL / MFE</code>) misura quanto profitto potenziale e stato effettivamente incassato.<br>
                    <strong>• Exit Frontier Adattiva con Gate Anti-Overfitting:</strong> I parametri ATR Ratchet vengono aggiornati solo se esistono almeno <code>N &ge; 15</code> trade valutati e il Lower Confidence Bound (<code>LCB</code>) migliora di almeno <code>+0.05R</code> al netto delle fee.
                </div>
            </div>

            <!-- Card 12: Allocazione Bayesiana & Shadow Mode -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">12. Allocazione Bayesiana &amp; Auto-Riabilitazione Shadow</strong>
                    <span class="badge mono" style="background: var(--amber); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">PILLAR 4</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    Il dimensionamento delle posizioni si adatta al rendimento statistico di ogni contesto (<code>Broker | Simbolo | Motore | Lato | Volatilita | Sessione</code>):<br>
                    <strong>• Shrinkage Normal-Gamma &amp; Half-Life 35g:</strong> I dati recenti pesano di piu dei vecchi grazie al decadimento esponenziale (<code>half-life 35 giorni</code>), con backoff gerarchico se i campioni specifici sono pochi.<br>
                    <strong>• 4 Regimi Operativi:</strong> <code>BOOST 1.25x</code> (<code>N_eff &ge; 15</code>, <code>LCB &ge; +0.10R</code>), <code>NORMAL 1.00x</code>, <code>CAUTIOUS 0.50x</code> (<code>N_eff &ge; 10</code>, edge debole) e <code>SHADOW 0.00x</code> (blocco reale quando <code>LCB &le; -0.25R</code> e media <code>&le; -0.15R</code>).<br>
                    <strong>• Auto-Ripristino (<code>SHADOW RECOVERED</code>):</strong> Anche a size <code>0.00x</code>, i segnali shadow continuano a essere simulati: quando i virtual outcomes riportano l'aspettativa in recupero, il contesto viene automaticamente riabilitato.
                </div>
            </div>

            <!-- Card 13: Self-Audit Settimanale & Monitoraggio Drift Quant -->
            <div class="acc-cell" style="padding: 14px; text-align: left;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <strong style="color: var(--text-main); font-size: 13px;">13. Self-Audit Settimanale &amp; Monitoraggio Drift Quant</strong>
                    <span class="badge mono" style="background: var(--blue); color: #fff; font-size: 9px; padding: 2px 6px; border-radius: 3px;">PILLAR 5</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.45;">
                    La supervisione quantitativa rimane completamente trasparente e verificabile nel tab <strong>Storico</strong> e su Telegram:<br>
                    <strong>• Report Domenicale Automatico (20:00 CET):</strong> Ogni domenica alle 20:00 CET il motore esegue l'audit completo (<code>WEEKLY_AUDIT</code>), persistendolo nel database e inviando il riepilogo esecutivo su Telegram.<br>
                    <strong>• Comando <code>/learning</code> su Telegram:</strong> Permette di consultare in qualsiasi momento statistiche nette, MFE/MAE, Shadow Ledger, bucket bayesiani e stato dell'Exit Frontier.<br>
                    <strong>• Quant Drift Monitor (MetaGate):</strong> Verifica l'attivazione, lo stato <code>deployable</code>, il numero di eventi e il base rate del modello secondario MetaGate configurato.
                </div>
            </div>

        </div>
        </div>

        <!-- ====================================================================
             GHOST DOM BINDER FOR SCRIPT COMPATIBILITY (PRESERVES IDS AND EVENTS)
             ==================================================================== -->
        <div class="ghost-dom-binder">
            <div id="card-tf-3s"></div><div id="delta-3s-val"></div><div id="delta-3s-pct"></div>
            <div id="card-tf-1m"></div><div id="delta-1m-val"></div><div id="delta-1m-pct"></div>
            <div id="card-tf-1h"></div><div id="delta-1h-val"></div><div id="delta-1h-pct"></div>
            <div id="card-tf-1d"></div><div id="delta-1d-val"></div><div id="delta-1d-pct"></div>
            <div id="card-tf-1w"></div><div id="delta-1w-val"></div><div id="delta-1w-pct"></div>
            <div id="card-tf-1M"></div><div id="delta-1M-val"></div><div id="delta-1M-pct"></div>
        </div>

    </main>

    <!-- ========================================================================
         MODAL POPUP ANALISI TRADE AVANZATA
         ======================================================================== -->
    <!-- MODAL POPUP ANALISI TRADE AVANZATA -->
    <div class="modal-overlay" id="trade-modal" onclick="closeTradeModal(event)">
        <div class="modal-card mono" onclick="event.stopPropagation()">
            <div class="sheet-grabber"></div>
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
                <!-- SCHEDA TATTICA OPERATIVA (COSA FARE ORA) -->
                <div id="tactical-box" class="tactical-decision-box">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px;">
                        <div>
                            <div style="font-size: 9px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-secondary); font-weight: 700;">Livelli Operativi</div>
                            <div id="tactical-verdict" style="font-size: 14px; font-weight: 800; color: var(--apple-green); margin-top: 1px;">CALCOLO IN CORSO...</div>
                        </div>
                        <span id="tactical-badge" class="badge mono" style="padding: 3px 8px; font-size: 10px; border-radius: 6px; font-weight: 700; background: rgba(48,209,88,0.2); color: var(--apple-green);">ANALISI</span>
                    </div>
                    <div id="tactical-reason" style="font-size: 11px; line-height: 1.4; color: var(--text-main); margin-top: 3px;">
                        Diagnostica integrata tra FLD di Hurst, Battleplan a 4 tempi e Monte Carlo.
                    </div>
                    <div id="tactical-strategy" style="font-size: 11px; color: var(--text-secondary); margin-top: 4px; font-weight: 500;">
                        In attesa dei dati di mercato...
                    </div>
                    <div class="tactical-grid-3 mono">
                        <div>
                            <div style="font-size: 8px; color: var(--text-tertiary);">TARGET TAKE PROFIT</div>
                            <strong id="tactical-tp" style="font-size: 11px; color: var(--apple-green);">$0.00</strong>
                        </div>
                        <div>
                            <div style="font-size: 8px; color: var(--text-tertiary);">STOP LOSS DI DIFESA</div>
                            <strong id="tactical-sl" style="font-size: 11px; color: var(--apple-red);">$0.00</strong>
                        </div>
                        <div>
                            <div style="font-size: 8px; color: var(--text-tertiary);">FINESTRA INVERSIONE</div>
                            <strong id="tactical-reversal" style="font-size: 11px; color: var(--apple-blue);">~0 barre</strong>
                        </div>
                    </div>
                </div>

                <!-- SELETTORE LIVELLI GRAFICO & CONTROLLI TIMEFRAME -->
                <div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; flex-wrap: wrap; gap: 4px;">
                        <!-- Timeframe Selector nel Modal -->
                        <div style="display: flex; gap: 3px; align-items: center;">
                            <span style="font-size: 10px; font-weight: 700; color: var(--text-secondary); margin-right: 2px;">TIMEFRAME:</span>
                            <button class="tf-btn active" id="modal-tf-1d" onclick="switchModalTimeframe('1d')" style="padding: 2px 7px; font-size: 9px;">1D</button>
                            <button class="tf-btn" id="modal-tf-4h" onclick="switchModalTimeframe('4h')" style="padding: 2px 7px; font-size: 9px;">4H</button>
                            <button class="tf-btn" id="modal-tf-1h" onclick="switchModalTimeframe('1h')" style="padding: 2px 7px; font-size: 9px;">1H</button>
                        </div>
                        <div style="display: flex; gap: 6px; align-items: center;">
                            <span id="modal-tf-badge" class="badge mono" style="background: var(--surface-elevated); color: var(--text-muted); font-size: 9px; padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border);">1D • MACRO</span>
                            <span id="modal-mc-prob" class="badge mono" style="background: var(--green-bg); color: var(--green); font-size: 10px; padding: 2px 6px; border-radius: 4px;">Prob. Up: 50%</span>
                        </div>
                    </div>

                    <!-- PILLOLE FILTRO LIVELLI (INTERATTIVE) -->
                    <div class="layer-pills">
                        <button class="layer-btn active" id="layer-btn-all" onclick="setForecastLayer('all')">Tutti i Livelli</button>
                        <button class="layer-btn" id="layer-btn-mc" onclick="setForecastLayer('mc')">Prezzo + Monte Carlo</button>
                        <button class="layer-btn" id="layer-btn-hurst" onclick="setForecastLayer('hurst')">Hurst FLD</button>
                        <button class="layer-btn" id="layer-btn-battleplan" onclick="setForecastLayer('battleplan')">Battleplan 4 Tempi</button>
                    </div>

                    <div class="forecast-chart-container" style="height: 230px;">
                        <canvas id="forecastChart"></canvas>
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

    <!-- BOTTOM TABBAR IPHONE CON ICONE NATIVE -->

    <!-- ========================================================================
         APPLE FROSTED GLASS BOTTOM TABBAR
         ======================================================================== -->
    <nav class="tabbar">
        <button class="tab-item active" id="tab-btn-bybit" onclick="showTab('bybit')">
            <span class="dot"></span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
            <span>Bybit</span>
        </button>
        <button class="tab-item" id="tab-btn-alpaca" onclick="showTab('alpaca')">
            <span class="dot"></span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
            <span>Alpaca</span>
        </button>
        <button class="tab-item" id="tab-btn-history" onclick="showTab('history')">
            <span class="dot"></span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
            <span>Storico</span>
        </button>
        <button class="tab-item" id="tab-btn-guide" onclick="showTab('guide')">
            <span class="dot"></span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path></svg>
            <span>Guida</span>
        </button>
    </nav>

    <!-- APPLE DYNAMIC TOAST NOTIFICATION -->
    <div id="mobile-tooltip-toast" class="toast-tooltip-mobile">
        <div style="flex: 1;" id="mobile-tooltip-text">Spiegazione dell'indicatore</div>
        <button class="toast-tooltip-close" onclick="hideMobileToast()">&times;</button>
    </div>

    <!-- JAVASCRIPT CONTROLLERS -->
    <script>
        let chartInstance = null;
        let currentTimeframe = '3s';
        let currentInstance = 'bybit'; // 'bybit' | 'alpaca' | 'total'
        let chartMode = 'pct'; // 'pct' | 'usd' (default: Percentuale)
        let chartMetric = 'pnl'; // 'pnl' | 'wallet' (default: PnL Operativo)

        function setChartMetric(metric) {
            chartMetric = metric;
            document.getElementById('btn-view-wallet').classList.toggle('active', metric === 'wallet');
            document.getElementById('btn-view-pnl').classList.toggle('active', metric === 'pnl');
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }
            if (window.lastDashboardData) {
                renderUI(window.lastDashboardData);
            } else {
                fetchData();
            }
        }

        function setChartMode(mode) {
            chartMode = mode;
            document.getElementById('btn-mode-usd').classList.toggle('active', mode === 'usd');
            document.getElementById('btn-mode-pct').classList.toggle('active', mode === 'pct');
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }
            if (window.lastDashboardData) {
                renderUI(window.lastDashboardData);
            } else {
                fetchData();
            }
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
                    btn.classList.toggle('active', i === inst);
                    btn.classList.toggle('active-bybit', i === inst && inst === 'bybit');
                    btn.classList.toggle('active-alpaca', i === inst && inst === 'alpaca');
                    btn.classList.toggle('active-total', i === inst && inst === 'total');
                }
            });

            // Evidenzia visivamente anche la card corrispondente nei saldi hero
            const subBybit = document.getElementById('sub-acc-bybit');
            const subAlpaca = document.getElementById('sub-acc-alpaca');
            if (subBybit && subAlpaca) {
                subBybit.classList.toggle('active-acc', inst === 'bybit');
                subAlpaca.classList.toggle('active-acc', inst === 'alpaca');
            }

            const titleEl = document.getElementById('chart-instance-title');
            if (titleEl) {
                if (inst === 'bybit') {
                    titleEl.innerText = 'BYBIT FUTURES (CRYPTO 24/7)';
                    titleEl.style.color = 'var(--apple-blue)';
                } else if (inst === 'alpaca') {
                    titleEl.innerText = 'ALPACA (WALL STREET USA)';
                    titleEl.style.color = 'var(--apple-amber)';
                } else {
                    titleEl.innerText = 'PORTAFOGLIO CONSOLIDATO';
                    titleEl.style.color = '#BF5AF2';
                }
            }
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }
            if (window.lastDashboardData) {
                renderUI(window.lastDashboardData);
            } else {
                fetchData();
            }
        }

        // GESTIONE TEMA LIGHT / DARK CON LOCALSTORAGE
        function initTheme() {
            const savedTheme = localStorage.getItem('sentinel_theme') || 'dark';
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
            }

            fetchData();
        }

        function updateThemeButtonText(theme) {
            const btn = document.getElementById('theme-btn');
            if (btn) {
                btn.innerText = theme === 'light' ? 'DARK' : 'LIGHT';
            }
        }
        initTheme();

        function showTab(tabName) {
            ['bybit', 'alpaca', 'history', 'guide'].forEach(t => {
                const view = document.getElementById('view-' + t);
                const btn = document.getElementById('tab-btn-' + t);
                if (view) {
                    if (t === tabName) {
                        view.classList.remove('hidden');
                        if (btn) btn.classList.add('active');
                    } else {
                        view.classList.add('hidden');
                        if (btn) btn.classList.remove('active');
                    }
                }
            });

            // Nella tab 'history' e 'guide' lasciamo solo la vista specifica pulita senza grafico o card sovrastanti
            const heroCard = document.querySelector('.hero-equity-card');
            const chartCard = document.querySelector('.apple-chart-card');
            if (tabName === 'history' || tabName === 'guide') {
                if (heroCard) heroCard.classList.add('hidden');
                if (chartCard) chartCard.classList.add('hidden');
            } else {
                if (heroCard) heroCard.classList.remove('hidden');
                if (chartCard) chartCard.classList.remove('hidden');
            }

            // Evidenzia visivamente il conto attivo nei due box patrimonio
            const subBybit = document.getElementById('sub-acc-bybit');
            const subAlpaca = document.getElementById('sub-acc-alpaca');
            if (subBybit && subAlpaca) {
                subBybit.classList.toggle('active-acc', tabName === 'bybit');
                subAlpaca.classList.toggle('active-acc', tabName === 'alpaca');
            }

            // Separazione istanze: quando navigo su Bybit o Alpaca sincronizza il grafico corrispondente
            if (tabName === 'bybit') {
                setChartInstance('bybit');
            } else if (tabName === 'alpaca') {
                setChartInstance('alpaca');
            }
        }

        window.timeframeDataCache = {};

        function setTimeframe(tf) {
            currentTimeframe = tf;
            ['3s', '1m', '1h', '1d', '1w', '1M'].forEach(t => {
                const btn = document.getElementById('btn-tf-' + t);
                if (btn) btn.classList.toggle('active', t === tf);
                const card = document.getElementById('card-tf-' + t);
                if (card) card.classList.toggle('active', t === tf);
            });

            // REATTIVITÀ ISTANTANEA (0ms): se abbiamo già i dati di questo timeframe in cache, renderizza all'istante
            if (window.timeframeDataCache[tf]) {
                renderUI(window.timeframeDataCache[tf]);
            }
            // Sincronizza sempre in background per mantenere i dati freschi al tick
            fetchData();
        }

        function updateClock() {
            const now = new Date();
            document.getElementById('top-clock').innerText = now.toLocaleTimeString('it-IT');
        }
        setInterval(updateClock, 1000);
        updateClock();

        
        function escapeHtml(val) {
            if (val === null || val === undefined) return '';
            return String(val)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function getAssetAvatarHtml(symbol) {
            const sym = (symbol || '').toUpperCase().replace('USDT', '').replace('USD', '');
            let cls = 'avatar-generic';
            if (sym === 'BTC') cls = 'avatar-btc';
            else if (sym === 'ETH') cls = 'avatar-eth';
            else if (sym === 'SOL') cls = 'avatar-sol';
            else if (sym === 'XRP') cls = 'avatar-xrp';
            else if (sym === 'LINK') cls = 'avatar-link';
            else if (sym === 'AVAX') cls = 'avatar-avax';
            else if (['AAPL', 'NVDA', 'MSFT', 'TSLA', 'AMZN', 'META', 'GOOGL', 'AMD', 'SPY'].includes(sym)) cls = 'avatar-stock';
            
            const shortName = escapeHtml(sym.substring(0, 3));
            return `<div class="asset-avatar ${cls}">${shortName}</div>`;
        }

        function computeDynamicPositionRisk(pos, entry, isLong, pnlPct, marketLabel) {
            const atrPct = parseFloat(pos.atr_pct || 0);
            const rawSl = parseFloat(pos.stop_loss || 0);
            const rawTp = parseFloat(pos.take_profit || 0);
            const explicitSlPct = parseFloat(pos.sl_pct || 0);
            const explicitTpPct = parseFloat(pos.tp_pct || 0);

            let baseSlPct = null;
            if (explicitSlPct > 0) {
                baseSlPct = explicitSlPct;
            } else if (atrPct > 0) {
                baseSlPct = Math.max(0.90, Math.min(2.20, atrPct * 1.4));
            } else if (rawSl > 0 && entry > 0 && ((isLong && rawSl < entry) || (!isLong && rawSl > entry))) {
                baseSlPct = Math.abs((rawSl - entry) / entry) * 100;
            }

            let baseTpPct = null;
            if (explicitTpPct > 0) {
                baseTpPct = explicitTpPct;
            } else if (rawTp > 0 && entry > 0 && ((isLong && rawTp > entry) || (!isLong && rawTp < entry))) {
                baseTpPct = Math.abs((rawTp - entry) / entry) * 100;
            } else if (baseSlPct !== null) {
                baseTpPct = baseSlPct * 3.0;
            }

            const refSl = baseSlPct !== null ? baseSlPct : 1.40;
            const tightTrig = 0.75 * refSl;
            const tightLock = -(0.40 * refSl);
            const beTrig = 1.15 * refSl;
            const beLock = Math.max(0.25, 0.25 * refSl);
            const midTrig = 1.80 * refSl;
            const midLock = 0.80 * refSl;
            const maxTrig = 2.40 * refSl;
            const maxLock = 1.40 * refSl;

            const slBadgeLabel = baseSlPct !== null ? `SL -${baseSlPct.toFixed(2)}%` : 'SL 1.4x ATR';
            const slTipAtrNote = atrPct > 0 ? ` (ATR ${atrPct.toFixed(2)}%)` : ' (range 0.90%-2.20%)';
            let guardHtml = `<span class="trade-guard" data-tip-pos="right" data-tip="${escapeHtml(`Stop Loss Dinamico ATR ${marketLabel}: 1.4x ATR${slTipAtrNote} con Target 3.0x SL.`)}">${escapeHtml(slBadgeLabel)}</span>`;
            if (pnlPct >= maxTrig) {
                guardHtml = `<span class="trade-guard guard-lock" data-tip-pos="right" data-tip="${escapeHtml(`Trailing Profit Lock ATR: stop alzato a +${maxLock.toFixed(2)}% netto (scatta a +${maxTrig.toFixed(2)}%) verso TP 3R.`)}">LOCK +${maxLock.toFixed(2)}%</span>`;
            } else if (pnlPct >= midTrig) {
                guardHtml = `<span class="trade-guard guard-lock" data-tip-pos="right" data-tip="${escapeHtml(`Profit Lock Intermedio ATR: stop alzato a +${midLock.toFixed(2)}% netto per proteggere il rendimento.`)}">LOCK +${midLock.toFixed(2)}%</span>`;
            } else if (pnlPct >= beTrig) {
                guardHtml = `<span class="trade-guard guard-be" data-tip-pos="right" data-tip="${escapeHtml(`Break-Even Safe attivo: rischio azzerato e stop bloccato a +${beLock.toFixed(2)}% (>= +0.25% a totale copertura fee).`)}">BE SAFE +${beLock.toFixed(2)}%</span>`;
            } else if (pnlPct >= tightTrig) {
                guardHtml = `<span class="trade-guard guard-tight" data-tip-pos="right" data-tip="${escapeHtml(`Ratchet Step 1 ATR: rischio ridotto con stop stretto a ${tightLock.toFixed(2)}% al superamento di +${tightTrig.toFixed(2)}%.`)}">TIGHT ${tightLock.toFixed(2)}%</span>`;
            }

            const decimals = marketLabel === 'Wall Street' ? 2 : 4;
            const slPrice = rawSl > 0 ? rawSl : (baseSlPct !== null && entry > 0 ? (isLong ? entry * (1 - baseSlPct / 100) : entry * (1 + baseSlPct / 100)) : 0);
            const tpPrice = rawTp > 0 ? rawTp : (baseTpPct !== null && entry > 0 ? (isLong ? entry * (1 + baseTpPct / 100) : entry * (1 - baseTpPct / 100)) : 0);

            const slText = slPrice > 0
                ? `$${slPrice.toFixed(decimals)} (${baseSlPct !== null ? '-' + baseSlPct.toFixed(2) + '%' : 'ATR'})`
                : '1.4x ATR';
            const tpText = tpPrice > 0
                ? `$${tpPrice.toFixed(decimals)} (${baseTpPct !== null ? '+' + baseTpPct.toFixed(1) + '%' : '3R'})`
                : '3.0x SL (1:3)';

            const tpDenom = baseTpPct !== null && baseTpPct > 0 ? baseTpPct : (refSl * 3.0);
            const slDenom = refSl > 0 ? refSl : 1.40;
            const totalSpan = slDenom + tpDenom;
            const entryPos = (slDenom / totalSpan) * 100;
            const currentPos = Math.max(0, Math.min(100, ((pnlPct + slDenom) / totalSpan) * 100));
            const fillLeft = pnlPct >= 0 ? entryPos : currentPos;
            const fillWidth = Math.abs(currentPos - entryPos);
            const tpProgress = Math.max(0, Math.min(100, (pnlPct / tpDenom) * 100));
            const progressColor = pnlPct >= maxTrig ? 'var(--apple-amber)' : (pnlPct >= 0 ? 'var(--apple-green)' : 'var(--apple-red)');

            const toBarPos = (pct) => Math.max(0, Math.min(100, ((pct + slDenom) / totalSpan) * 100));
            const milestones = [
                { pos: toBarPos(tightTrig), label: 'TIGHT', trig: tightTrig, lock: tightLock, active: pnlPct >= tightTrig },
                { pos: toBarPos(beTrig), label: 'BE', trig: beTrig, lock: beLock, active: pnlPct >= beTrig },
                { pos: toBarPos(midTrig), label: 'LOCK1', trig: midTrig, lock: midLock, active: pnlPct >= midTrig },
                { pos: toBarPos(maxTrig), label: 'LOCK2', trig: maxTrig, lock: maxLock, active: pnlPct >= maxTrig }
            ];

            let ratchetHint = '';
            if (pnlPct < 0) {
                const usedRiskPct = Math.min(100, (Math.abs(pnlPct) / slDenom) * 100);
                const remToSl = Math.max(0, slDenom - Math.abs(pnlPct));
                ratchetHint = `Rischio: ${pnlPct.toFixed(2)}% / -${slDenom.toFixed(2)}% (${usedRiskPct.toFixed(0)}% usato · -${remToSl.toFixed(2)}% allo SL)`;
            } else if (pnlPct < tightTrig) {
                ratchetHint = `Prossimo SL: TIGHT ${tightLock.toFixed(2)}% a +${tightTrig.toFixed(2)}%`;
            } else if (pnlPct < beTrig) {
                ratchetHint = `SL stretto ${tightLock.toFixed(2)}% · Prossimo: BE +${beLock.toFixed(2)}% a +${beTrig.toFixed(2)}%`;
            } else if (pnlPct < midTrig) {
                ratchetHint = `SL in BE +${beLock.toFixed(2)}% · Prossimo: LOCK +${midLock.toFixed(2)}% a +${midTrig.toFixed(2)}%`;
            } else if (pnlPct < maxTrig) {
                ratchetHint = `SL bloccato +${midLock.toFixed(2)}% · Prossimo: MAX +${maxLock.toFixed(2)}% a +${maxTrig.toFixed(2)}%`;
            } else {
                ratchetHint = `MAX LOCK attivo: SL +${maxLock.toFixed(2)}% verso TP +${tpDenom.toFixed(1)}%`;
            }

            const currentR = slDenom > 0 ? (pnlPct / slDenom) : 0;
            const currentRText = `${currentR >= 0 ? '+' : ''}${currentR.toFixed(2)}R`;
            const rawOpenTs = pos.opened_at || pos.created_at || pos.timestamp || pos.entry_time || '';
            let openTimeText = '';
            if (rawOpenTs) {
                const d = new Date(typeof rawOpenTs === 'number' && rawOpenTs < 1e12 ? rawOpenTs * 1000 : rawOpenTs);
                if (!isNaN(d.getTime())) {
                    const hhmm = d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
                    const diffH = Math.max(0, (Date.now() - d.getTime()) / 3600000);
                    const dur = diffH < 1 ? `${Math.round(diffH * 60)}m` : `${diffH.toFixed(1)}h`;
                    openTimeText = `${hhmm} (${dur})`;
                }
            }

            return { guardHtml, slText, tpText, tpProgress, progressColor, entryPos, fillLeft, fillWidth, milestones, ratchetHint, currentR, currentRText, openTimeText };
        }

        function renderPositionRiskBarHtml(riskInfo) {
            const ticksHtml = (riskInfo.milestones || []).map(m => {
                const lockStr = m.lock >= 0 ? `+${m.lock.toFixed(2)}%` : `${m.lock.toFixed(2)}%`;
                const tip = `${m.label}: sposta SL a ${lockStr} quando PnL raggiunge +${m.trig.toFixed(2)}%`;
                const bg = m.active ? 'var(--apple-amber)' : 'rgba(255,255,255,0.45)';
                return `<span data-tip="${escapeHtml(tip)}" style="position:absolute; left:${m.pos.toFixed(1)}%; top:-2px; width:2px; height:9px; background:${bg}; border-radius:1px; transform:translateX(-50%); cursor:help; z-index:2;"></span>`;
            }).join('');

            const rColor = riskInfo.currentR >= 0 ? 'var(--apple-green)' : 'var(--apple-red)';
            const centerMeta = riskInfo.openTimeText
                ? `<b style="color:${rColor};">${escapeHtml(riskInfo.currentRText)}</b> · ${escapeHtml(riskInfo.openTimeText)}`
                : `<b style="color:${rColor};">${escapeHtml(riskInfo.currentRText)}</b>`;

            return `
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-top: 8px; font-size: 10px; color: var(--text-tertiary);">
                    <span>SL: <b style="color: var(--apple-red);">${escapeHtml(riskInfo.slText)}</b></span>
                    <span data-tip="Multiplo di rischio attuale (R) e orario di apertura">${centerMeta}</span>
                    <span>TP: <b style="color: var(--apple-green);">${escapeHtml(riskInfo.tpText)}</b></span>
                </div>
                <div class="trade-target-progress-bar" style="position:relative; height: 5px; border-radius: 2.5px; background: rgba(255,255,255,0.08); margin-top: 5px; overflow: visible;">
                    <span data-tip="Entry (0%)" style="position:absolute; left:${riskInfo.entryPos.toFixed(1)}%; top:-2px; width:2px; height:9px; background:rgba(255,255,255,0.85); border-radius:1px; transform:translateX(-50%); z-index:2;"></span>
                    ${ticksHtml}
                    <div class="trade-target-fill" style="position:absolute; left:${riskInfo.fillLeft.toFixed(1)}%; width:${riskInfo.fillWidth.toFixed(1)}%; height:100%; border-radius:2.5px; background:${riskInfo.progressColor}; transition: width 0.3s ease, left 0.3s ease;"></div>
                </div>
                <div style="margin-top: 5px; font-size: 10px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                    ${escapeHtml(riskInfo.ratchetHint)}
                </div>
            `;
        }

        
        // APPLE STOCKS INTERACTIVE SCRUBBING LISTENER
        function setupChartScrubbing() {
            const canvas = document.getElementById('perfChart');
            const badge = document.getElementById('chart-scrub-badge');
            const heroAmount = document.getElementById('total-equity');
            if (!canvas || !badge || canvas.getAttribute('data-scrub-init')) return;
            canvas.setAttribute('data-scrub-init', 'true');

            let originalHeroText = '';

            function handleMove(e) {
                if (!chartInstance || !chartInstance.data || !chartInstance.data.datasets[0]) return;
                const rect = canvas.getBoundingClientRect();
                const clientX = e.touches ? e.touches[0].clientX : e.clientX;
                const x = clientX - rect.left;
                if (x < 0 || x > rect.width) return;

                const points = chartInstance.getElementsAtEventForMode(e, 'index', { intersect: false }, true);
                if (points && points.length > 0) {
                    const idx = points[0].index;
                    const val = chartInstance.data.datasets[0].data[idx];
                    const label = chartInstance.data.labels[idx];
                    if (val !== undefined && val !== null) {
                        badge.style.display = 'block';
                        const sign = val >= 0 ? '+' : '';
                        const formatted = (chartMode === 'pct') ? `${sign}${val.toFixed(2)}%` : `$${val.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                        badge.innerText = `${label} • ${formatted}`;
                        
                        if (heroAmount && chartMetric === 'wallet' && chartMode === 'usd') {
                            if (!originalHeroText) originalHeroText = heroAmount.innerText;
                            heroAmount.innerText = `$${val.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                        }
                    }
                }
            }

            function handleEnd() {
                badge.style.display = 'none';
                if (heroAmount && originalHeroText) {
                    heroAmount.innerText = originalHeroText;
                    originalHeroText = '';
                }
            }

            canvas.addEventListener('mousemove', handleMove);
            canvas.addEventListener('mouseleave', handleEnd);
            canvas.addEventListener('touchmove', handleMove, { passive: true });
            canvas.addEventListener('touchend', handleEnd);
            canvas.addEventListener('touchcancel', handleEnd);
        }

        function initChart(snapshots) {
            try {
                if (typeof Chart === 'undefined') return;
                const canvas = document.getElementById('perfChart');
                if (!canvas) return;
                const ctx = canvas.getContext('2d');

                const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
                const gridColor = isDark ? 'rgba(255, 255, 255, 0.04)' : 'rgba(0, 0, 0, 0.04)';
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

                // Se chartMetric è 'pnl', plottiamo la curva del Net PnL specifica del broker selezionato
                if (chartMetric === 'pnl') {
                    if (currentInstance === 'alpaca') {
                        // Per Alpaca: variazione di PnL azionario rispetto alla baseline dell'orizzonte
                        if (chartMode === 'pct') {
                            equity = snapshots.map(s => parseFloat(((s.alpaca_equity - baseEq) / baseEq * 100).toFixed(3)));
                            labelName = 'Rendimento Azionario USA (%)';
                        } else {
                            equity = snapshots.map(s => parseFloat((s.alpaca_equity - baseEq).toFixed(2)));
                            labelName = 'PnL Operativo Wall Street ($)';
                        }
                        pnl = snapshots.map(s => 0);
                        pnlName = 'Benchmark Flat ($)';
                    } else if (currentInstance === 'bybit') {
                        // Per Bybit: Net Trading PnL (realizzato + non realizzato derivati)
                        if (chartMode === 'pct') {
                            equity = snapshots.map(s => parseFloat(((s.cumulative_realized_pnl + (s.unrealized_pnl || 0)) / baseEq * 100).toFixed(3)));
                            labelName = 'Trading PnL Bybit (%)';
                        } else {
                            equity = snapshots.map(s => parseFloat((s.cumulative_realized_pnl + (s.unrealized_pnl || 0)).toFixed(2)));
                            labelName = 'Trading PnL Bybit ($)';
                        }
                        pnl = snapshots.map(s => parseFloat(s.cumulative_realized_pnl.toFixed(2)));
                        pnlName = 'PnL Chiuso Bybit ($)';
                    } else {
                        // Consolidato
                        if (chartMode === 'pct') {
                            equity = snapshots.map(s => parseFloat(((s.total_equity - baseEq) / baseEq * 100).toFixed(3)));
                            labelName = 'Rendimento Consolidato (%)';
                        } else {
                            equity = snapshots.map(s => parseFloat((s.cumulative_realized_pnl + (s.unrealized_pnl || 0)).toFixed(2)));
                            labelName = 'Trading Net PnL Totale ($)';
                        }
                        pnl = snapshots.map(s => parseFloat(s.cumulative_realized_pnl.toFixed(2)));
                        pnlName = 'PnL Chiuso ($)';
                    }
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

                // PURE APPLE STOCKS DYNAMIC PALETTE
                // Calcola se il trend nel periodo visualizzato è positivo o negativo
                const validVals = equity.filter(v => typeof v === 'number' && !isNaN(v));
                const deltaTrend = (validVals.length >= 2) ? (validVals[validVals.length - 1] - validVals[0]) : 0;
                const isPositivePeriod = deltaTrend >= 0;

                // Verde Apple (#30D158) per periodi in utile, Rosso Apple (#FF453A) per periodi in flessione
                let mainRgb = isPositivePeriod ? '48, 209, 88' : '255, 69, 58';
                let lineColor = isPositivePeriod ? '#30D158' : '#FF453A';
                let smaColor = isDark ? 'rgba(255, 255, 255, 0.35)' : 'rgba(0, 0, 0, 0.35)';
                let pnlColor = isPositivePeriod ? 'rgba(48, 209, 88, 0.6)' : 'rgba(255, 69, 58, 0.6)';

                // Aggiorna il colore del LIVE HUD in base al broker selezionato
                const hudLiveEl = document.getElementById('hud-live-val');
                if (hudLiveEl) hudLiveEl.style.color = lineColor;

                const gradient = ctx.createLinearGradient(0, 0, 0, 240);
                if (isDark) {
                    gradient.addColorStop(0, `rgba(${mainRgb}, 0.22)`);
                    gradient.addColorStop(0.8, `rgba(${mainRgb}, 0.02)`);
                    gradient.addColorStop(1, `rgba(${mainRgb}, 0.00)`);
                } else {
                    gradient.addColorStop(0, `rgba(${mainRgb}, 0.16)`);
                    gradient.addColorStop(0.8, `rgba(${mainRgb}, 0.01)`);
                    gradient.addColorStop(1, `rgba(${mainRgb}, 0.00)`);
                }

                if (chartInstance) {
                    chartInstance.data.labels = labels;
                    chartInstance.data.datasets[0].data = equity;
                    chartInstance.data.datasets[0].label = labelName;
                    chartInstance.data.datasets[0].borderColor = lineColor;
                    chartInstance.data.datasets[0].pointHoverBackgroundColor = lineColor;
                    chartInstance.data.datasets[0].backgroundColor = gradient;
                    chartInstance.data.datasets[1].data = smaData;
                    chartInstance.data.datasets[1].borderColor = smaColor;
                    chartInstance.data.datasets[2].data = pnl;
                    chartInstance.data.datasets[2].label = pnlName;
                    chartInstance.data.datasets[2].borderColor = pnlColor;
                    chartInstance.options.scales.y.ticks.color = lineColor;
                    chartInstance.update('none');
                    return;
                }

                setTimeout(setupChartScrubbing, 50);
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
                                        enabled: false // Disabilitato pinch per permettere scroll naturale fluido su iOS
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
                                    font: { family: '-apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif', size: 10 }
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
                                display: true,
                                grid: { display: false },
                                ticks: { color: tickColor, font: { family: '-apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif', size: 9 }, maxTicksLimit: 5 }
                            },
                            y: {
                                position: 'right',
                                grid: { color: isDark ? 'rgba(255, 255, 255, 0.04)' : 'rgba(0, 0, 0, 0.04)' },
                                ticks: {
                                    color: tickColor,
                                    font: { family: '-apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif', size: 9 },
                                    callback: function(val) {
                                        if (chartMode === 'pct') {
                                            return (val >= 0 ? '+' : '') + val.toFixed(1) + '%';
                                        }
                                        return '$' + (val / 1000).toFixed(1) + 'k';
                                    }
                                }
                            },
                            y1: {
                                display: false,
                                ticks: {
                                    color: pnlColor,
                                    font: { family: '-apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif', size: 9 },
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
                const timeoutId = setTimeout(() => controller.abort(), 8000);
                const res = await fetch(`/api/dashboard?tf=${currentTimeframe}`, { cache: 'no-store', signal: controller.signal });
                clearTimeout(timeoutId);
                
                if (!res.ok) throw new Error('HTTP ' + res.status);
                const data = await res.json();
                window.lastDashboardData = data;
                window.timeframeDataCache[currentTimeframe] = data;
                renderUI(data);
                consecutiveErrors = 0;
                (document.querySelector('.nav-pulse-dot') || document.querySelector('.status-dot')).style.background = 'var(--green)';
            } catch (e) {
                console.error("Dashboard sync error:", e);
                consecutiveErrors++;
                (document.querySelector('.nav-pulse-dot') || document.querySelector('.status-dot')).style.background = 'var(--red)';
                // Se abbiamo dati in cache per questo timeframe o l'ultimo snapshot, renderizziamolo comunque per non lasciare il grafico vuoto
                if (window.timeframeDataCache[currentTimeframe]) {
                    renderUI(window.timeframeDataCache[currentTimeframe]);
                } else if (window.lastDashboardData) {
                    renderUI(window.lastDashboardData);
                }
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

            // Aggiorna Hero Delta Display (Apple Stocks style)
            const heroDeltaEl = document.getElementById('hero-delta-display');
            if (heroDeltaEl && variations['1d']) {
                const d1d = variations['1d'];
                const pctVal = typeof d1d.delta_equity_pct === 'number' ? d1d.delta_equity_pct : 0;
                const pSign = pctVal >= 0 ? '+' : '';
                heroDeltaEl.innerText = `${pSign}${pctVal.toFixed(2)}% oggi`;
                heroDeltaEl.className = pctVal >= 0 ? 'val-up' : 'val-down';
            }

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

                // Setup Readiness Radar UI
                const readiness = data.setup_readiness || {};
                const rScore = readiness.readiness_score || 50;
                const rScoreEl = document.getElementById('readiness-score-val');
                const rBadgeEl = document.getElementById('readiness-badge-el');
                const rBarEl = document.getElementById('readiness-bar-fill');
                const rDescEl = document.getElementById('readiness-desc-el');

                if (rScoreEl) rScoreEl.innerText = rScore;
                if (rBarEl) {
                    rBarEl.style.width = rScore + '%';
                    const barColor = rScore >= 75 ? 'var(--green)' : (rScore >= 55 ? 'var(--amber)' : 'var(--red)');
                    rBarEl.style.background = barColor;
                    if (rScoreEl) rScoreEl.style.color = barColor;
                }

                if (rBadgeEl) {
                    rBadgeEl.innerText = readiness.readiness_verdict || 'STAND-BY';
                    const cTheme = readiness.readiness_color || 'amber';
                    rBadgeEl.className = `badge mono badge-${cTheme}`;
                }

                if (rDescEl) {
                    rDescEl.innerHTML = `<strong>Movimento Atteso:</strong> ${escapeHtml(readiness.expected_movement || 'Monitoraggio in corso.')}`;
                }

                const bk = readiness.breakdown || {};
                const pMacro = document.getElementById('readiness-p-macro');
                if (pMacro && bk.macro) pMacro.innerText = `${bk.macro.score}/25`;
                const pCycle = document.getElementById('readiness-p-cycle');
                if (pCycle && bk.cycle) pCycle.innerText = `${bk.cycle.score}/25`;
                const pRsi = document.getElementById('readiness-p-rsi');
                if (pRsi && bk.rsi) pRsi.innerText = `${bk.rsi.score}/25`;
                const pBook = document.getElementById('readiness-p-book');
                if (pBook && bk.book) pBook.innerText = `${bk.book.score}/25`;

            } catch (errCompass) {
                console.error("Compass render error:", errCompass);
            }

            // 1b. Alpaca Trading Compass & Setup Readiness (SPY + VIX)
            try {
                const aComp = (data.alpaca && data.alpaca.compass) ? data.alpaca.compass : {};
                const aRead = (data.alpaca && data.alpaca.setup_readiness) ? data.alpaca.setup_readiness : {};
                const aScoreEl = document.getElementById('alpaca-compass-score-val');
                const aBadgeEl = document.getElementById('alpaca-compass-verdict-badge');
                const aDescEl = document.getElementById('alpaca-compass-verdict-desc');
                if (aScoreEl) aScoreEl.innerText = typeof aComp.health_score === 'number' ? aComp.health_score : 50;
                if (aBadgeEl) {
                    aBadgeEl.innerText = aComp.verdict || 'ALLINEATO';
                    const col = aComp.verdict_color || 'amber';
                    aBadgeEl.className = 'badge mono badge-' + col;
                    if (aScoreEl) aScoreEl.style.color = (col === 'green' ? 'var(--green)' : (col === 'red' ? 'var(--red)' : 'var(--amber)'));
                }
                if (aDescEl) aDescEl.innerText = aComp.verdict_desc || 'Parametri quantitativi Wall Street monitorati.';

                const aEvEl = document.getElementById('alpaca-diag-ev-val');
                if (aEvEl) {
                    const ev = aComp.expected_value_usd || 0;
                    aEvEl.innerText = `${ev >= 0 ? '+' : ''}$${ev.toFixed(2)}`;
                    aEvEl.style.color = ev >= 0 ? 'var(--green)' : 'var(--red)';
                }
                const aRrEl = document.getElementById('alpaca-diag-rr-val');
                if (aRrEl) aRrEl.innerText = `1:${(aComp.realized_rr || 0).toFixed(1)}`;
                const aWinEl = document.getElementById('alpaca-diag-win-val');
                if (aWinEl) aWinEl.innerText = `${aComp.open_itm_ratio || 0}%`;
                const aBeEl = document.getElementById('alpaca-diag-be-sub');
                if (aBeEl) aBeEl.innerText = `${aComp.protected_positions_count || 0} a Break-Even`;
                const aPfEl = document.getElementById('alpaca-diag-pf-val');
                if (aPfEl) aPfEl.innerText = (aComp.profit_factor || 0).toFixed(2);

                const arScore = aRead.readiness_score || 50;
                const arScoreEl = document.getElementById('alpaca-readiness-score-val');
                const arBadgeEl = document.getElementById('alpaca-readiness-verdict-badge');
                const arBarEl = document.getElementById('alpaca-readiness-progress-bar');
                const arDescEl = document.getElementById('alpaca-readiness-movement');
                if (arScoreEl) arScoreEl.innerText = arScore;
                if (arBarEl) {
                    arBarEl.style.width = arScore + '%';
                    const bCol = arScore >= 75 ? 'var(--green)' : (arScore >= 55 ? 'var(--amber)' : 'var(--red)');
                    arBarEl.style.background = bCol;
                    if (arScoreEl) arScoreEl.style.color = bCol;
                }
                if (arBadgeEl) {
                    arBadgeEl.innerText = aRead.readiness_verdict || 'STAND-BY';
                    arBadgeEl.className = `badge mono badge-${aRead.readiness_color || 'amber'}`;
                }
                if (arDescEl) arDescEl.innerHTML = `<strong>Movimento Atteso:</strong> ${escapeHtml(aRead.expected_movement || 'Monitoraggio SPY/VIX in corso.')}`;

                const abk = aRead.breakdown || {};
                const apMacro = document.getElementById('alpaca-bd-macro');
                if (apMacro && abk.macro) apMacro.innerText = `${abk.macro.score}/25`;
                const apCycle = document.getElementById('alpaca-bd-cycle');
                if (apCycle && abk.cycle) apCycle.innerText = `${abk.cycle.score}/25`;
                const apRsi = document.getElementById('alpaca-bd-rsi');
                if (apRsi && abk.rsi) apRsi.innerText = `${abk.rsi.score}/25`;
                const apBook = document.getElementById('alpaca-bd-book');
                if (apBook && abk.book) apBook.innerText = `${abk.book.score}/25`;
            } catch (errAlpacaCompass) {
                console.error("Alpaca compass render error:", errAlpacaCompass);
            }

            // 2. Acc Summary & Divisione Conti Distinti
            const bEq = bWallet.total_equity || 0;
            const aEq = parseFloat(aAcc.portfolio_value || 0);
            const totalEq = bEq + aEq;

            document.getElementById('total-equity').innerText = '$' + totalEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            const beEl = document.getElementById('bybit-equity'); if (beEl) beEl.innerText = '$' + bEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            
            const usdtCash = (bWallet.coins && bWallet.coins.USDT) ? bWallet.coins.USDT : (bWallet.available_balance || 0);
            const bcEl = document.getElementById('bybit-cash'); if (bcEl) bcEl.innerText = 'Disponibile: $' + usdtCash.toLocaleString('en-US', {maximumFractionDigits: 0}) + ' USDT';

            const aeEl = document.getElementById('alpaca-equity'); if (aeEl) aeEl.innerText = '$' + aEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            const abEl = document.getElementById('alpaca-bp'); if (abEl) abEl.innerText = 'BP: $' + parseFloat(aAcc.buying_power || 0).toLocaleString('en-US', {maximumFractionDigits: 0});

            // Popola i due conti separati nell'Hero Card in cima
            const heroBVal = document.getElementById('hero-bybit-amount');
            if (heroBVal) heroBVal.innerText = '$' + bEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            const heroBSub = document.getElementById('hero-bybit-sub');
            if (heroBSub) heroBSub.innerText = 'Disponibile: $' + usdtCash.toLocaleString('en-US', {maximumFractionDigits: 0}) + ' USDT';

            const heroAVal = document.getElementById('hero-alpaca-amount');
            if (heroAVal) heroAVal.innerText = '$' + aEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            const heroASub = document.getElementById('hero-alpaca-sub');
            if (heroASub) heroASub.innerText = 'BP: $' + parseFloat(aAcc.buying_power || 0).toLocaleString('en-US', {maximumFractionDigits: 0});

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

            // 4. Metrics & Chart (Dinamico e coerente con l'istanza di mercato visualizzata)
            const ql1 = document.getElementById('qlabel-1');
            const ql2 = document.getElementById('qlabel-2');
            const ql3 = document.getElementById('qlabel-3');
            const ql4 = document.getElementById('qlabel-4');
            const mvEl = document.getElementById('metric-volume');
            const rpEl = document.getElementById('metric-realized');
            const wrEl = document.getElementById('metric-winrate');
            const avgEl = document.getElementById('metric-avg-trade');

            let cumVol = 0;
            let cumPnl = 0;
            let wins = 0;
            bClosed.forEach(c => {
                const p = parseFloat(c.closedPnl || 0);
                cumPnl += p;
                cumVol += (parseFloat(c.cumExitValue || 0) + parseFloat(c.cumEntryValue || 0));
                if (p > 0) wins++;
            });
            const avgTrade = bClosed.length > 0 ? (cumPnl / bClosed.length) : 0;

            if (currentInstance === 'alpaca') {
                // Metriche specifiche per Wall Street USA (Alpaca)
                if (ql1) ql1.innerText = 'Val. Titoli';
                if (ql2) ql2.innerText = 'Buying Power';
                if (ql3) ql3.innerText = 'Posizioni';
                if (ql4) ql4.innerText = 'Market Status';

                const qc1 = document.getElementById('qcell-1');
                const qc2 = document.getElementById('qcell-2');
                const qc3 = document.getElementById('qcell-3');
                const qc4 = document.getElementById('qcell-4');
                if (qc1) qc1.setAttribute("data-tip", "Controvalore corrente di mercato delle azioni USA in portafoglio Alpaca");
                if (qc2) qc2.setAttribute("data-tip", "Capacita d'acquisto disponibile sul conto Alpaca per nuovi ordini");
                if (qc3) qc3.setAttribute("data-tip", "Numero totale di titoli azionari NYSE/NASDAQ attualmente aperti");
                if (qc4) qc4.setAttribute("data-tip", "Stato corrente della sessione regolare Wall Street (15:30 - 22:00 CET)");

                let alpacaMktVal = 0;
                aPositions.forEach(ap => { alpacaMktVal += parseFloat(ap.market_value || 0); });
                if (mvEl) mvEl.innerText = '$' + (alpacaMktVal / 1000).toFixed(1) + 'k';

                const bpVal = parseFloat(aAcc.buying_power || 0);
                if (rpEl) {
                    rpEl.innerText = '$' + (bpVal / 1000).toFixed(0) + 'k';
                    rpEl.className = 'val-neutral';
                }
                if (wrEl) wrEl.innerText = `${aPositions.length} titoli`;
                if (avgEl) {
                    avgEl.innerText = 'CHIUSA (W-END)';
                    avgEl.className = 'val-neutral';
                }
            } else if (currentInstance === 'total') {
                // Metriche per Portafoglio Consolidato
                if (ql1) ql1.innerText = 'Volume Crypto';
                if (ql2) ql2.innerText = 'PnL Chiuso';
                if (ql3) ql3.innerText = 'Win Rate';
                if (ql4) ql4.innerText = 'Trade Medio';

                const qc1 = document.getElementById('qcell-1');
                const qc2 = document.getElementById('qcell-2');
                const qc3 = document.getElementById('qcell-3');
                const qc4 = document.getElementById('qcell-4');
                if (qc1) qc1.setAttribute('data-tip', 'Volume nozionale cumulato scambiato dai trade');
                if (qc2) qc2.setAttribute('data-tip', 'Profit & Loss netto consolidato delle operazioni chiuse');
                if (qc3) qc3.setAttribute('data-tip', 'Percentuale di operazioni chiuse con profitto positivo');
                if (qc4) qc4.setAttribute('data-tip', 'Media matematica netta guadagnata o persa per singolo trade');

                if (mvEl) mvEl.innerText = '$' + (cumVol / 1000).toFixed(0) + 'k';
                if (rpEl) {
                    rpEl.innerText = `${cumPnl >= 0 ? '+' : ''}$${cumPnl.toFixed(2)}`;
                    rpEl.className = cumPnl >= 0 ? 'val-up' : 'val-down';
                }
                const wr = bClosed.length > 0 ? (wins / bClosed.length * 100).toFixed(0) : 0;
                if (wrEl) wrEl.innerText = `${wr}% (${wins}/${bClosed.length})`;
                if (avgEl) {
                    avgEl.innerText = `${avgTrade >= 0 ? '+' : ''}$${avgTrade.toFixed(2)}`;
                    avgEl.className = avgTrade >= 0 ? 'val-up' : 'val-down';
                }
            } else {
                // Default Bybit Crypto
                if (ql1) ql1.innerText = 'Volume';
                if (ql2) ql2.innerText = 'PnL Chiuso';
                if (ql3) ql3.innerText = 'Win Rate';
                if (ql4) ql4.innerText = 'Trade Medio';

                const qc1 = document.getElementById('qcell-1');
                const qc2 = document.getElementById('qcell-2');
                const qc3 = document.getElementById('qcell-3');
                const qc4 = document.getElementById('qcell-4');
                if (qc1) qc1.setAttribute('data-tip', 'Volume nozionale cumulato scambiato dai trade');
                if (qc2) qc2.setAttribute('data-tip', 'Profit & Loss netto consolidato delle operazioni chiuse');
                if (qc3) qc3.setAttribute('data-tip', 'Percentuale di operazioni chiuse con profitto positivo');
                if (qc4) qc4.setAttribute('data-tip', 'Media matematica netta guadagnata o persa per singolo trade');

                if (mvEl) mvEl.innerText = '$' + (cumVol / 1000).toFixed(0) + 'k';
                if (rpEl) {
                    rpEl.innerText = `${cumPnl >= 0 ? '+' : ''}$${cumPnl.toFixed(2)}`;
                    rpEl.className = cumPnl >= 0 ? 'val-up' : 'val-down';
                }
                const wr = bClosed.length > 0 ? (wins / bClosed.length * 100).toFixed(0) : 0;
                if (wrEl) wrEl.innerText = `${wr}% (${wins}/${bClosed.length})`;
                if (avgEl) {
                    avgEl.innerText = `${avgTrade >= 0 ? '+' : ''}$${avgTrade.toFixed(2)}`;
                    avgEl.className = avgTrade >= 0 ? 'val-up' : 'val-down';
                }
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
                listEl.innerHTML = '<div class="apple-group-card">' + bPositions.map((p, idx) => {

                    const isLong = p.side === 'BUY';
                    const sideClass = isLong ? 'trade-side-long' : 'trade-side-short';
                    const sideText = isLong ? 'LONG' : 'SHORT';
                    const unPnl = parseFloat(p.unrealized_pnl || 0);
                    const pctGain = typeof p.pnl_pct === 'number' ? p.pnl_pct : parseFloat(p.pnl_pct || 0);
                    const pSign = unPnl >= 0 ? '+' : '';
                    const pnlClass = unPnl >= 0 ? 'val-up' : 'val-down';

                    const entry = parseFloat(p.entry_price || 1);
                    const mark = parseFloat(p.mark_price || entry);
                    const riskInfo = computeDynamicPositionRisk(p, entry, isLong, pctGain, 'Bybit');

                    const safeSym = escapeHtml(p.symbol || '');
                    const safeSize = escapeHtml(p.size);
                    const avatar = getAssetAvatarHtml(p.symbol);
                    return `
                        <div class="wallet-item" data-sym="${safeSym}" data-side="${sideText}" data-entry="${entry}" data-mark="${mark}" onclick="openTradeModal(this.dataset.sym, this.dataset.side, Number(this.dataset.entry), Number(this.dataset.mark))" title="Tocca per visualizzare la diagnostica ciclica (Hurst/Migliorino), Elliott e Monte Carlo">
                            ${avatar}
                            <div class="wallet-item-content">
                                <div class="wallet-title-row">
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <span class="wallet-symbol">${safeSym}</span>
                                        <span class="${sideClass}" style="font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 4px;">${sideText}</span>
                                        ${riskInfo.guardHtml}
                                    </div>
                                    <div style="text-align: right;">
                                        <div class="trade-pnl ${pnlClass} wallet-val">${pSign}$${unPnl.toFixed(2)}</div>
                                        <div style="font-size: 11px; font-weight: 600;" class="${pnlClass}">${pSign}${pctGain.toFixed(2)}%</div>
                                    </div>
                                </div>
                                <div class="wallet-sub-row" style="margin-top: 4px;">
                                    <span>In $${entry.toFixed(4)} &rarr; Mark $${mark.toFixed(4)}</span>
                                    <span>Size: ${safeSize} ($${(parseFloat(p.position_value || 0)).toLocaleString('en-US', {maximumFractionDigits: 0})})</span>
                                </div>
                                <!-- Barra di Progresso Bidirezionale SL <-> Entry <-> Ratchet <-> TP -->
                                ${renderPositionRiskBarHtml(riskInfo)}
                            </div>
                        </div>
                    `;

}).join('') + '</div>';

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

            // 6. Alpaca Table & Mobile Cards
            const aBody = document.getElementById('alpaca-tbody');
            const aCards = document.getElementById('alpaca-cards-list');
            if (aPositions.length === 0) {
                const emptyMsg = `Nessun titolo aperto. Wall Street chiusa nel weekend.`;
                if (aBody) aBody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 20px 0; color: var(--text-dim);">${emptyMsg}</td></tr>`;
                if (aCards) aCards.innerHTML = `<div style="text-align: center; padding: 20px 0; color: var(--text-dim);">${emptyMsg}</div>`;
            } else {
                if (aBody) {
                    aBody.innerHTML = aPositions.map(ap => {
                        const u = parseFloat(ap.unrealized_pl || 0);
                        const uClass = u >= 0 ? 'val-up' : 'val-down';
                        const uSign = u >= 0 ? '+' : '';
                        const safeSym = escapeHtml(ap.symbol || '');
                        const entryVal = parseFloat(ap.avg_entry_price || 0);
                        const curVal = parseFloat(ap.current_price || 0);
                        return `
                            <tr>
                                <td style="font-weight: 700; color: var(--apple-amber); cursor: pointer;" data-sym="${safeSym}" data-side="LONG" data-entry="${entryVal}" data-mark="${curVal}" onclick="openTradeModal(this.dataset.sym, this.dataset.side, Number(this.dataset.entry), Number(this.dataset.mark))">${safeSym} ↗</td>
                                <td>${escapeHtml(ap.qty)}</td>
                                <td>$${entryVal.toFixed(2)}</td>
                                <td>$${curVal.toFixed(2)}</td>
                                <td>$${parseFloat(ap.market_value || 0).toFixed(2)}</td>
                                <td class="${uClass}">${uSign}$${u.toFixed(2)}</td>
                            </tr>
                        `;
                    }).join('');
                }
                if (aCards) {
                    aCards.innerHTML = '<div class="apple-group-card">' + aPositions.map(ap => {
                        const u = parseFloat(ap.unrealized_pl || 0);
                        const uClass = u >= 0 ? 'val-up' : 'val-down';
                        const uSign = u >= 0 ? '+' : '';
                        
                        const entry = parseFloat(ap.avg_entry_price || 0);
                        const current = parseFloat(ap.current_price || entry);
                        const marketVal = parseFloat(ap.market_value || 0);
                        const qty = parseFloat(ap.qty || 0);
                        const sideText = (String(ap.side || 'LONG').toUpperCase().includes('SHORT')) ? 'SHORT' : 'LONG';
                        const isLong = sideText === 'LONG';
                        
                        // Calcolo PnL Percentuale esatto
                        const pnlPct = parseFloat(ap.unrealized_plpc ? (ap.unrealized_plpc * 100) : (entry > 0 ? ((current - entry) / entry * 100) : 0));
                        
                        const riskInfo = computeDynamicPositionRisk(ap, entry, isLong, pnlPct, 'Wall Street');
                        const safeSym = escapeHtml(ap.symbol || '');
                        const avatar = getAssetAvatarHtml(ap.symbol);
                        return `
                            <div class="wallet-item" data-sym="${safeSym}" data-side="${sideText}" data-entry="${entry}" data-mark="${current}" onclick="openTradeModal(this.dataset.sym, this.dataset.side, Number(this.dataset.entry), Number(this.dataset.mark))" title="Tocca per visualizzare la diagnostica ciclica (Hurst/Migliorino), Elliott e Monte Carlo">
                                ${avatar}
                                <div class="wallet-item-content">
                                    <div class="wallet-title-row">
                                        <div style="display: flex; align-items: center; gap: 6px;">
                                            <span class="wallet-symbol">${safeSym}</span>
                                            <span class="badge mono" style="background: rgba(255, 159, 10, 0.15); color: var(--apple-amber); font-size: 9px; padding: 1px 5px; border-radius: 4px; font-weight: 700;">${sideText}</span>
                                            ${riskInfo.guardHtml}
                                        </div>
                                        <div style="text-align: right;">
                                            <div class="trade-pnl ${uClass} wallet-val">${uSign}$${u.toFixed(2)}</div>
                                            <div style="font-size: 11px; font-weight: 600;" class="${uClass}">${uSign}${pnlPct.toFixed(2)}%</div>
                                        </div>
                                    </div>
                                    <div class="wallet-sub-row" style="margin-top: 4px;">
                                        <span>In $${entry.toFixed(2)} &rarr; Mark $${current.toFixed(2)}</span>
                                        <span>Size: ${qty} az. ($${marketVal.toLocaleString('en-US', {maximumFractionDigits: 0})})</span>
                                    </div>
                                    <!-- Target Take Profit, Stop Loss & Barra Bidirezionale Ratchet -->
                                    ${renderPositionRiskBarHtml(riskInfo)}
                                </div>
                            </div>
                        `;

                    }).join('') + '</div>';
                }
            }

            // Previsioni caricate on-demand al tocco dell'asset

            // 7. History Table & Mobile Cards (Ordinamento Rigoroso: Più Recente in Alto, Bybit + Alpaca unificati)
            const aClosed = (data.alpaca && Array.isArray(data.alpaca.closed)) ? data.alpaca.closed : [];
            const combinedClosed = [
                ...bClosed.map(c => ({ ...c, broker: c.broker || 'BYBIT' })),
                ...aClosed.map(c => ({ ...c, broker: c.broker || 'ALPACA' }))
            ];
            const sortedClosed = combinedClosed.sort((a, b) => parseInt(b.updatedTime || 0) - parseInt(a.updatedTime || 0));
            document.getElementById('closed-count-label').innerText = `${sortedClosed.length} eseguiti`;
            const hBody = document.getElementById('history-tbody');
            const hCards = document.getElementById('history-cards-list');
            if (sortedClosed.length === 0) {
                const emptyHist = `Nessun trade chiuso recente.`;
                if (hBody) hBody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 20px 0; color: var(--text-dim);">${emptyHist}</td></tr>`;
                if (hCards) hCards.innerHTML = `<div style="text-align: center; padding: 20px 0; color: var(--text-dim);">${emptyHist}</div>`;
            } else {
                const rows = sortedClosed.slice(0, 30);
                if (hBody) {
                    hBody.innerHTML = rows.map(c => {
                        const pVal = parseFloat(c.closedPnl || 0);
                        const pClass = pVal >= 0 ? 'val-up' : 'val-down';
                        const pSign = pVal >= 0 ? '+' : '';
                        const timeStr = c.updatedTime ? new Date(parseInt(c.updatedTime)).toLocaleTimeString('it-IT') : '--:--';

                        const invested = parseFloat(c.cumEntryValue || 0) || (parseFloat(c.closedSize || 0) * parseFloat(c.avgEntryPrice || 0));
                        const investedStr = invested > 0 ? '$' + Math.round(invested).toLocaleString('en-US') : '--';

                        let pctStr = '--';
                        if (invested > 0) {
                            const pct = (pVal / invested) * 100;
                            pctStr = `${pSign}${pct.toFixed(2)}%`;
                        }

                        const safeSym = escapeHtml(c.symbol || '');
                        const safeSide = escapeHtml(c.side || '');
                        const sideUp = escapeHtml(String(c.side || '').toUpperCase());
                        const ep = parseFloat(c.avgEntryPrice || 0);
                        const xp = parseFloat(c.avgExitPrice || 0);
                        return `
                            <tr>
                                <td style="color: var(--text-muted); font-weight: 500;">${escapeHtml(timeStr)}</td>
                                <td style="font-weight: 700; color: var(--apple-blue); cursor: pointer;" data-sym="${safeSym}" data-side="${sideUp}" data-entry="${ep}" data-mark="${xp}" onclick="openTradeModal(this.dataset.sym, this.dataset.side, Number(this.dataset.entry), Number(this.dataset.mark))" title="Tocca per visualizzare la scheda previsionale">${safeSym} ↗</td>
                                <td>${safeSide}</td>
                                <td style="color: var(--text-main); font-weight: 600;">${escapeHtml(investedStr)}</td>
                                <td>$${ep.toFixed(3)} &rarr; $${xp.toFixed(3)}</td>
                                <td style="color: var(--text-dim);">$${(parseFloat(c.openFee || 0) + parseFloat(c.closeFee || 0)).toFixed(2)}</td>
                                <td class="${pClass}">${pSign}$${pVal.toFixed(2)}</td>
                                <td class="${pClass}">${escapeHtml(pctStr)}</td>
                            </tr>
                        `;
                    }).join('');
                }
                if (hCards) {
                    hCards.innerHTML = '<div class="apple-group-card">' + rows.map(c => {
                        const pVal = parseFloat(c.closedPnl || 0);
                        const pClass = pVal >= 0 ? 'val-up' : 'val-down';
                        const pSign = pVal >= 0 ? '+' : '';
                        const timeStr = c.updatedTime ? new Date(parseInt(c.updatedTime)).toLocaleTimeString('it-IT') : '--:--';

                        const invested = parseFloat(c.cumEntryValue || 0) || (parseFloat(c.closedSize || 0) * parseFloat(c.avgEntryPrice || 0));
                        const investedStr = invested > 0 ? '$' + Math.round(invested).toLocaleString('en-US') : '--';

                        let pctStr = '--';
                        if (invested > 0) {
                            const pct = (pVal / invested) * 100;
                            pctStr = `${pSign}${pct.toFixed(2)}%`;
                        }

                        const fee = (parseFloat(c.openFee || 0) + parseFloat(c.closeFee || 0)).toFixed(2);
                        const avatar = getAssetAvatarHtml(c.symbol);
                        const sideLow = String(c.side || '').toLowerCase();
                        const sideBadge = (sideLow === 'buy' || sideLow === 'long') ? 
                            '<span class="badge mono" style="font-size: 9px; padding: 1px 5px; background: var(--green-bg); color: var(--green); border-radius: 4px;">LONG</span>' : 
                            '<span class="badge mono" style="font-size: 9px; padding: 1px 5px; background: var(--red-bg); color: var(--red); border-radius: 4px;">SHORT</span>';
                        const brokerBadge = c.broker === 'ALPACA' ?
                            '<span class="badge mono" style="font-size: 9px; padding: 1px 5px; background: rgba(255, 159, 10, 0.14); color: #FF9F0A; border-radius: 4px;">ALPACA</span>' :
                            '<span class="badge mono" style="font-size: 9px; padding: 1px 5px; background: rgba(10, 132, 255, 0.14); color: var(--apple-blue); border-radius: 4px;">BYBIT</span>';
                        const safeSym = escapeHtml(c.symbol || '');
                        const sideUp = escapeHtml(String(c.side || '').toUpperCase());
                        const ep = parseFloat(c.avgEntryPrice || 0);
                        const xp = parseFloat(c.avgExitPrice || 0);

                        return `
                            <div class="wallet-item" data-sym="${safeSym}" data-side="${sideUp}" data-entry="${ep}" data-mark="${xp}" onclick="openTradeModal(this.dataset.sym, this.dataset.side, Number(this.dataset.entry), Number(this.dataset.mark))">
                                ${avatar}
                                <div class="wallet-item-content">
                                    <div class="wallet-title-row">
                                        <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                                            <span class="wallet-symbol">${safeSym}</span>
                                            ${sideBadge}
                                            ${brokerBadge}
                                            <span style="font-size: 11px; color: var(--text-secondary);">${escapeHtml(timeStr)}</span>
                                        </div>
                                        <div style="text-align: right;">
                                            <div class="${pClass} wallet-val">${pSign}$${pVal.toFixed(2)}</div>
                                            <div class="${pClass}" style="font-size: 11px; font-weight: 600;">${escapeHtml(pctStr)}</div>
                                        </div>
                                    </div>
                                    <div class="wallet-sub-row">
                                        <span>$${ep.toFixed(3)} &rarr; $${xp.toFixed(3)}</span>
                                        <span>Investito: <b>${escapeHtml(investedStr)}</b> • Fee: $${fee}</span>
                                    </div>
                                </div>
                            </div>
                        `;

                    }).join('') + '</div>';
                }
            }

            // 7. Render Motore di Apprendimento Strutturale & Journal Post-Mortem (XSS-safe)
            const jList = document.getElementById('journal-insights-list');
            const jBadge = document.getElementById('journal-stats-badge');
            const jWinrate = document.getElementById('journal-winrate-val');
            const jData = data.journal || {};
            const insights = jData.insights || [];
            const jStats = jData.stats || {};
            const lData = data.learning || {};
            const lCounts = lData.trade_counts || {};

            const effWinRate = (typeof lCounts.win_rate_pct === 'number' && (lCounts.total || 0) > 0)
                ? lCounts.win_rate_pct
                : (jStats.win_rate !== undefined ? Number(jStats.win_rate) : 0);
            if (jWinrate) {
                jWinrate.innerText = `${effWinRate.toFixed(1)}% Win`;
                jWinrate.style.color = effWinRate >= 50 ? 'var(--apple-green)' : 'var(--apple-amber)';
            }
            const totalCnt = lCounts.total || jStats.total_trades || 0;
            const winsCnt = lCounts.wins !== undefined ? lCounts.wins : (jStats.wins_count || 0);
            const lossesCnt = lCounts.losses !== undefined ? lCounts.losses : (jStats.losses_count || 0);
            if (jBadge && totalCnt > 0) {
                jBadge.innerText = `${winsCnt}V / ${lossesCnt}P • Cap: 70%`;
            }

            // 7a. Path Quality (MFE / MAE / Capture Efficiency / Edge Ratio) & Exit Frontier
            try {
                const avgMfe = Number(lData.avg_mfe_pct || 0);
                const avgMae = Number(lData.avg_mae_pct || 0);
                const avgCapPct = Number(lData.avg_capture_eff || 0) * 100;
                const avgEdge = Number(lData.avg_edge_ratio || 0);

                const mfeEl = document.getElementById('learning-avg-mfe');
                if (mfeEl) mfeEl.innerText = `+${Math.abs(avgMfe).toFixed(2)}%`;
                const maeEl = document.getElementById('learning-avg-mae');
                if (maeEl) maeEl.innerText = `${avgMae.toFixed(2)}%`;
                const capEl = document.getElementById('learning-capture-eff');
                if (capEl) capEl.innerText = `${avgCapPct.toFixed(1)}%`;
                const edgeEl = document.getElementById('learning-edge-ratio');
                if (edgeEl) {
                    edgeEl.innerText = `${avgEdge.toFixed(2)}x`;
                    edgeEl.style.color = avgEdge >= 1.5 ? 'var(--apple-green)' : (avgEdge > 0 ? 'var(--apple-amber)' : 'var(--text-primary)');
                }

                const ef = lData.exit_frontier || {};
                const efBadge = document.getElementById('learning-frontier-badge');
                const efDesc = document.getElementById('learning-frontier-desc');
                const adaptiveOn = Boolean(lData.adaptive_exit_active || ef.approved);
                const efN = Number(ef.n_samples || 0);
                if (efBadge) {
                    if (adaptiveOn) {
                        efBadge.innerText = 'FRONTIER ATTIVA';
                        efBadge.className = 'badge badge-green mono';
                    } else {
                        efBadge.innerText = `RACCOLTA (${efN}/15)`;
                        efBadge.className = 'badge badge-amber mono';
                    }
                }
                if (efDesc) {
                    if (adaptiveOn && ef.best_params) {
                        const bp = ef.best_params;
                        efDesc.innerHTML = `<span class="badge badge-green mono" style="margin-right: 6px;">ATR ADATTIVO</span> SL ${Number(bp.sl_atr || 1.4).toFixed(2)}x • BE ${Number(bp.be_trig_atr || 1.61).toFixed(2)}x • TP ${Number(bp.tp_atr || 4.2).toFixed(2)}x — ${escapeHtml(ef.reason || '')}`;
                    } else {
                        efDesc.innerText = ef.reason || `Raccolta campioni MFE/MAE (${efN}/15). Richiesto N >= 15 e LCB >= +0.05R netto fee.`;
                    }
                }
            } catch (ePath) {
                console.error('Learning path render error:', ePath);
            }

            // 7b. Causal Shadow Ledger
            try {
                const sh = lData.shadow_stats || {};
                const shTotal = Number(sh.total || 0);
                const shEval = Number(sh.evaluated || 0);
                const shPend = Number(sh.pending || 0);
                const shAvgR = Number(sh.avg_virtual_r || 0);
                const shWr = Number(sh.win_rate_pct || 0);
                const missedAlpha = Number(sh.missed_alpha_count || 0);
                const savedCap = Number(sh.saved_capital_count || 0);

                const shBadge = document.getElementById('learning-shadow-badge');
                if (shBadge) {
                    shBadge.innerText = `${shEval} VALUTATI • ${shPend} PENDING`;
                    shBadge.className = shEval > 0 ? 'badge badge-blue mono' : 'badge badge-neutral mono';
                }
                const shTotEl = document.getElementById('learning-shadow-total');
                if (shTotEl) shTotEl.innerText = `${shEval} / ${shTotal}`;
                const shREl = document.getElementById('learning-shadow-avg-r');
                if (shREl) {
                    shREl.innerText = `${shAvgR >= 0 ? '+' : ''}${shAvgR.toFixed(2)}R`;
                    shREl.style.color = shAvgR > 0.05 ? 'var(--apple-amber)' : (shAvgR < 0 ? 'var(--apple-green)' : 'var(--text-primary)');
                }
                const shWrEl = document.getElementById('learning-shadow-winrate');
                if (shWrEl) shWrEl.innerText = `${shWr.toFixed(1)}%`;

                const shVerdictEl = document.getElementById('learning-shadow-verdict');
                if (shVerdictEl) {
                    if (shEval === 0) {
                        shVerdictEl.innerHTML = '<span>Nessun segnale scartato ancora valutato sulle barre future chiuse.</span>';
                    } else {
                        const isAlphaMissed = shAvgR > 0.10 || missedAlpha > savedCap;
                        const tagCls = isAlphaMissed ? 'badge-amber' : 'badge-green';
                        const tagTxt = isAlphaMissed ? 'MISSED ALPHA' : 'CAPITALE SALVATO';
                        const descTxt = isAlphaMissed
                            ? `Opportunita positive scartate: ${missedAlpha} vs ${savedCap} evitate — possibile margine di calibrazione filtri.`
                            : `I filtri hanno evitato ${savedCap} trade perdenti rispetto a ${missedAlpha} segnali positivi.`;
                        shVerdictEl.innerHTML = `<span class="badge ${tagCls} mono">${tagTxt}</span><span>${escapeHtml(descTxt)}</span>`;
                    }
                }
            } catch (eShadow) {
                console.error('Shadow ledger render error:', eShadow);
            }

            // 7c. Allocazione Bayesiana Contestuale
            try {
                const buckets = Array.isArray(lData.context_buckets) ? lData.context_buckets : [];
                const bCountEl = document.getElementById('learning-buckets-count');
                const bListEl = document.getElementById('learning-context-buckets-list');
                if (bCountEl) bCountEl.innerText = `${buckets.length} CONTESTI`;
                if (bListEl) {
                    if (buckets.length === 0) {
                        bListEl.innerHTML = `<div class="learning-banner-row"><span>Nessun bucket contestuale consolidato: prior neutro 1.00x attivo.</span></div>`;
                    } else {
                        bListEl.innerHTML = buckets.slice(0, 8).map(b => {
                            const mode = String(b.mode || 'STANDARD').toUpperCase();
                            const scale = Number(b.scale !== undefined ? b.scale : 1.0);
                            const effN = Number(b.effective_n !== undefined ? b.effective_n : (b.n_eff || 0));
                            const realN = Number(b.real_n !== undefined ? b.real_n : (b.n_real || 0));
                            const shadowN = Number(b.shadow_n !== undefined ? b.shadow_n : (b.n_shadow || 0));
                            const meanR = Number(b.mean_r || 0);
                            const lcbR = Number(b.lcb_r || 0);

                            let modeBadgeCls = 'badge-blue';
                            let modeLabel = `NORMAL ${scale.toFixed(2)}x`;
                            if (mode === 'BOOSTED') {
                                modeBadgeCls = 'badge-green';
                                modeLabel = `BOOST ${scale.toFixed(2)}x`;
                            } else if (mode === 'CAUTIOUS') {
                                modeBadgeCls = 'badge-amber';
                                modeLabel = `CAUTIOUS ${scale.toFixed(2)}x`;
                            } else if (mode === 'SHADOW_BLOCKED') {
                                modeBadgeCls = 'badge-red';
                                modeLabel = `SHADOW 0.00x`;
                            } else if (mode === 'LEARNING_PRIOR') {
                                modeBadgeCls = 'badge-neutral';
                                modeLabel = `PRIOR ${scale.toFixed(2)}x`;
                            }

                            const recBadge = b.shadow_recovered
                                ? `<span class="badge badge-purple mono" data-tip="Contesto riabilitato automaticamente dai virtual outcomes positivi nello Shadow Ledger.">SHADOW RECOVERED</span>`
                                : '';
                            const backoffTag = Number(b.backoff_level || 0) > 0
                                ? `<span class="badge badge-neutral mono">L${Number(b.backoff_level)}</span>`
                                : '';
                            const meanCls = meanR >= 0 ? 'val-up' : 'val-down';

                            return `
                                <div class="learning-bucket-row" data-tip="${escapeHtml(`Bucket: ${b.context_key} | Matched: ${b.matched_key || b.context_key} | N_eff=${effN.toFixed(1)}, LCB=${lcbR >= 0 ? '+' : ''}${lcbR.toFixed(2)}R`)}">
                                    <div class="learning-bucket-main">
                                        <div class="learning-bucket-key mono">${escapeHtml(b.context_key || 'CONTESTO')}</div>
                                        <div class="learning-bucket-tags">
                                            <span class="badge ${modeBadgeCls} mono">${escapeHtml(modeLabel)}</span>
                                            ${recBadge}
                                            ${backoffTag}
                                        </div>
                                    </div>
                                    <div class="learning-bucket-stats mono">
                                        <div class="${meanCls}">${meanR >= 0 ? '+' : ''}${meanR.toFixed(2)}R <span style="color: var(--text-tertiary); font-weight: 500;">(LCB ${lcbR >= 0 ? '+' : ''}${lcbR.toFixed(2)}R)</span></div>
                                        <div>N_eff ${effN.toFixed(1)} &bull; R:${realN} / S:${shadowN}</div>
                                    </div>
                                </div>
                            `;
                        }).join('');
                    }
                }
            } catch (eBuckets) {
                console.error('Context buckets render error:', eBuckets);
            }

            // 7d. Breakdown Motori, MetaGate Drift & Weekly Audit
            try {
                const engMap = lData.engines_breakdown || {};
                const engListEl = document.getElementById('learning-engines-list');
                if (engListEl) {
                    const engKeys = Object.keys(engMap);
                    if (engKeys.length === 0) {
                        engListEl.innerHTML = '';
                    } else {
                        engListEl.innerHTML = engKeys.map(k => {
                            const st = engMap[k] || {};
                            const wr = Number(st.win_rate || 0);
                            const pf = Number(st.profit_factor_net || 0);
                            const pnlU = Number(st.net_pnl_usd || 0);
                            const expR = Number(st.expectancy_r || 0);
                            const pnlCls = pnlU >= 0 ? 'val-up' : 'val-down';
                            return `
                                <div class="learning-bucket-row">
                                    <div class="learning-bucket-main">
                                        <div class="learning-bucket-key mono">${escapeHtml(k)}</div>
                                        <div class="learning-section-sub mono">${Number(st.total || 0)} trade &bull; WR ${wr.toFixed(1)}% &bull; PF ${pf.toFixed(2)}</div>
                                    </div>
                                    <div class="learning-bucket-stats mono">
                                        <div class="${pnlCls}">${pnlU >= 0 ? '+' : ''}$${pnlU.toFixed(2)}</div>
                                        <div>Exp ${expR >= 0 ? '+' : ''}${expR.toFixed(2)}R</div>
                                    </div>
                                </div>
                            `;
                        }).join('');
                    }
                }

                const mg = lData.meta_gate_drift || {};
                const mgBadge = document.getElementById('learning-metagate-badge');
                const mgDesc = document.getElementById('learning-metagate-desc');
                if (mgBadge) {
                    if (mg.active && mg.deployable) {
                        mgBadge.innerText = 'METAGATE ATTIVO';
                        mgBadge.className = 'badge badge-green mono';
                    } else if (mg.active) {
                        mgBadge.innerText = 'METAGATE STANDBY';
                        mgBadge.className = 'badge badge-amber mono';
                    } else {
                        mgBadge.innerText = 'METAGATE OFF';
                        mgBadge.className = 'badge badge-neutral mono';
                    }
                }
                if (mgDesc) {
                    const baseRate = mg.base_rate !== undefined && mg.base_rate !== null ? ` • BaseRate ${(Number(mg.base_rate) * 100).toFixed(1)}%` : '';
                    mgDesc.innerText = `${mg.verdict || 'MetaGate non configurato'} (Eventi: ${Number(mg.n_events || 0)}${baseRate})`;
                }

                const audit = lData.latest_audit || null;
                const audStatus = document.getElementById('learning-audit-status');
                const audSummary = document.getElementById('learning-audit-summary');
                if (audStatus && audSummary) {
                    if (audit && audit.summary_text) {
                        const dtShort = String(audit.created_at || '').slice(0, 16).replace('T', ' ');
                        audStatus.innerText = dtShort || 'DISPONIBILE';
                        audStatus.className = 'badge badge-blue mono';
                        audSummary.innerText = String(audit.summary_text);
                    } else {
                        audStatus.innerText = 'IN ATTESA';
                        audStatus.className = 'badge badge-neutral mono';
                        audSummary.innerText = 'Prossimo self-audit settimanale programmato domenica alle 20:00 CET (oppure via /learning su Telegram).';
                    }
                }
            } catch (eAudit) {
                console.error('Audit/MetaGate render error:', eAudit);
            }

            // 7e. Ultime Esecuzioni Post-Mortem con MFE/MAE & Engine
            if (jList) {
                if (insights.length === 0) {
                    jList.innerHTML = `
                        <div class="apple-cell" style="padding: 12px 14px; color: var(--text-secondary); font-size: 11px;">
                            Ogni posizione chiusa registra i parametri di esecuzione, il percorso MFE/MAE e la motivazione tecnica di uscita.
                        </div>
                    `;
                } else {
                    jList.innerHTML = insights.slice(0, 6).map(ins => {
                        const pnlPctNum = parseFloat(ins.pnl_pct || 0);
                        const isWin = pnlPctNum >= 0;
                        const badgeColor = isWin ? 'var(--apple-green)' : 'var(--apple-red)';
                        const badgeBg = isWin ? 'rgba(48, 209, 88, 0.15)' : 'rgba(255, 69, 58, 0.15)';
                        const pSign = isWin ? '+' : '';
                        const tagLabel = isWin ? 'WIN' : 'PROTETTO';
                        const avatar = getAssetAvatarHtml(ins.symbol);
                        const safeSym = escapeHtml(ins.symbol || '');
                        const safeReason = escapeHtml(ins.close_reason || 'CHIUSO');
                        const safeEngine = escapeHtml(ins.engine || 'INTRADAY_MOMENTUM');
                        const safeNote = escapeHtml(ins.post_mortem_analysis || ins.learned_lesson || 'Diagnostica quantitativa registrata.');
                        const hasPath = ins.mfe_pct !== null && ins.mfe_pct !== undefined && ins.mae_pct !== null && ins.mae_pct !== undefined;
                        const pathLine = hasPath
                            ? `<div class="mono" style="font-size: 10px; color: var(--text-tertiary); margin-top: 3px;">MFE +${Math.abs(Number(ins.mfe_pct)).toFixed(2)}% &bull; MAE ${Number(ins.mae_pct).toFixed(2)}%${ins.capture_eff !== null && ins.capture_eff !== undefined ? ' &bull; Cap ' + (Number(ins.capture_eff) * 100).toFixed(0) + '%' : ''}</div>`
                            : '';

                        return `
                            <div class="apple-cell" style="padding: 11px 14px; align-items: flex-start; gap: 10px;">
                                <div style="display: flex; align-items: flex-start; gap: 8px; min-width: 0; flex: 1;">
                                    ${avatar}
                                    <div style="min-width: 0; flex: 1;">
                                        <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 2px;">
                                            <b style="color: var(--text-primary); font-size: 13px;">${safeSym}</b>
                                            <span class="badge mono" style="font-size: 8px; padding: 1px 5px; background: rgba(255,255,255,0.06); color: var(--text-secondary); border-radius: 4px;">${tagLabel}</span>
                                            <span class="badge mono" style="font-size: 9px; padding: 1px 5px; background: ${badgeBg}; color: ${badgeColor}; border-radius: 4px;">${safeReason}</span>
                                            <span class="badge badge-blue mono" style="font-size: 8px; padding: 1px 5px;">${safeEngine}</span>
                                        </div>
                                        <div style="color: var(--text-secondary); line-height: 1.35; font-size: 11px;">
                                            ${safeNote}
                                        </div>
                                        ${pathLine}
                                    </div>
                                </div>
                                <div style="text-align: right; white-space: nowrap;">
                                    <div class="mono" style="font-weight: 700; color: ${badgeColor}; font-size: 12px;">${pSign}${pnlPctNum.toFixed(2)}%</div>
                                    <div class="mono" style="font-size: 10px; color: var(--text-tertiary);">$${parseFloat(ins.pnl_usd || 0).toFixed(2)}</div>
                                </div>
                            </div>
                        `;
                    }).join('');
                }
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
            if (entry > 0 && mark > 0) {
                document.getElementById('modal-trade-price').innerText = `Entry: $${entry.toFixed(4)} | Mark: $${mark.toFixed(4)}`;
            } else {
                document.getElementById('modal-trade-price').innerText = `Analisi Quantitativa & Ciclica Live`;
            }

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

                // Sintesi tattica azionabile con verdetto chiaro
                const act = data.actionable || {};
                const tBox = document.getElementById('tactical-box');
                const tVerd = document.getElementById('tactical-verdict');
                const tBadge = document.getElementById('tactical-badge');
                const tReason = document.getElementById('tactical-reason');
                const tStrat = document.getElementById('tactical-strategy');
                const tTp = document.getElementById('tactical-tp');
                const tSl = document.getElementById('tactical-sl');
                const tRev = document.getElementById('tactical-reversal');

                if (tVerd && act.verdict) {
                    tVerd.innerText = act.verdict;
                    const col = act.color || 'green';
                    tVerd.style.color = (col === 'green' ? 'var(--apple-green)' : (col === 'red' ? 'var(--apple-red)' : 'var(--apple-amber)'));
                    if (tBox) {
                        tBox.className = 'tactical-decision-box ' + (col === 'red' ? 'short' : (col === 'amber' ? 'neutral' : ''));
                    }
                }
                if (tBadge && act.badge) {
                    tBadge.innerText = act.badge;
                    const col = act.color || 'green';
                    tBadge.style.color = (col === 'green' ? 'var(--apple-green)' : (col === 'red' ? 'var(--apple-red)' : 'var(--apple-amber)'));
                    tBadge.style.background = (col === 'green' ? 'rgba(48,209,88,0.15)' : (col === 'red' ? 'rgba(255,69,58,0.15)' : 'rgba(255,159,10,0.15)'));
                }
                if (tReason && act.reason) tReason.innerText = act.reason;
                if (tStrat && act.strategy) tStrat.innerText = act.strategy;
                if (tTp && act.target_tp) tTp.innerText = `$${Number(act.target_tp).toLocaleString('en-US', {maximumFractionDigits: 2})}`;
                if (tSl && act.target_sl) tSl.innerText = `$${Number(act.target_sl).toLocaleString('en-US', {maximumFractionDigits: 2})}`;
                if (tRev && act.bars_to_reversal) tRev.innerText = `~${act.bars_to_reversal} barre`;

                // Sintesi operativa classica per retrocompatibilità
                const adviceEl = document.getElementById('modal-advice-text');
                if (adviceEl) adviceEl.innerText = `${c.consiglio_pratico || ''} Setup: ${side === 'LONG' ? 'Rialzista' : 'Ribassista'} su ${symbol}.`;

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

        let currentForecastLayer = 'all';
        let cachedChartData = null;

        function setForecastLayer(layer) {
            currentForecastLayer = layer;
            ['all', 'mc', 'hurst', 'battleplan'].forEach(l => {
                const b = document.getElementById(`layer-btn-${l}`);
                if (b) b.classList.toggle('active', l === layer);
            });
            if (cachedChartData) {
                renderForecastChartWithLayer(cachedChartData, layer);
            }
        }

        function initForecastChart(chartData) {
            cachedChartData = chartData;
            renderForecastChartWithLayer(chartData, currentForecastLayer);
        }

        function renderForecastChartWithLayer(chartData, layer) {
            if (!chartData) return;
            const canvas = document.getElementById('forecastChart');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');

            if (forecastChartInstance) {
                forecastChartInstance.destroy();
                forecastChartInstance = null;
            }

            const hist = chartData.historical || chartData.historical_prices || [];
            const hurstFld = chartData.hurst_fld || chartData.hurst_fld_curve || [];
            const battleplan = chartData.battleplan_migliorino || chartData.battleplan_curve || [];
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

            // Configurazione visibilità dataset in base al layer selezionato
            const showHurst = (layer === 'all' || layer === 'hurst');
            const showBattleplan = (layer === 'all' || layer === 'battleplan');
            const showMc = (layer === 'all' || layer === 'mc');

            const datasets = [
                {
                    label: 'Prezzo',
                    data: histSeries,
                    borderColor: '#38bdf8',
                    borderWidth: 2.5,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    cubicInterpolationMode: 'monotone',
                    tension: 0.2
                }
            ];

            if (showHurst) {
                datasets.push({
                    label: 'Hurst FLD (Spartiacque)',
                    data: hurstSeries,
                    borderColor: '#f59e0b',
                    borderWidth: 2.0,
                    borderDash: [4, 3],
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    tension: 0.2
                });
            }

            if (showBattleplan) {
                datasets.push({
                    label: 'Battleplan 4 Tempi (Migliorino)',
                    data: battleplanSeries,
                    borderColor: '#06b6d4',
                    borderWidth: 1.8,
                    borderDash: [2, 2],
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    tension: 0.35
                });
            }

            if (showMc) {
                datasets.push(
                    {
                        label: 'Previsione Mediana P50',
                        data: p50Series,
                        borderColor: '#a855f7',
                        borderWidth: 2.2,
                        borderDash: [5, 4],
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        tension: 0.2
                    },
                    {
                        label: 'Banda Alta P95',
                        data: p95Series,
                        borderColor: 'rgba(48, 209, 88, 0.45)',
                        borderWidth: 1,
                        backgroundColor: 'transparent',
                        pointRadius: 0,
                        tension: 0.2
                    },
                    {
                        label: 'Banda Bassa P05',
                        data: p05Series,
                        borderColor: 'rgba(255, 69, 58, 0.45)',
                        borderWidth: 1,
                        backgroundColor: 'rgba(168, 85, 247, 0.08)',
                        fill: '-1',
                        pointRadius: 0,
                        tension: 0.2
                    }
                );
            }

            forecastChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: datasets
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
                            ticks: { maxTicksLimit: 7, font: { family: '-apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif', size: 9 }, color: '#94a3b8' },
                            grid: { display: false }
                        },
                        y: {
                            ticks: { font: { family: '-apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif', size: 9 }, color: '#94a3b8' },
                            grid: { color: 'rgba(148, 163, 184, 0.1)' }
                        }
                    }
                }
            });
        }

        fetchData();
        setInterval(fetchData, 5000);
    
        // GESTORE TOOLTIP TOAST FLUIDO PER MOBILE / IPHONE TOUCH & VIEWPORT EDGE SAFE DESKTOP
        let mobileToastTimer = null;
        function showMobileToast(text) {
            const toast = document.getElementById('mobile-tooltip-toast');
            const toastText = document.getElementById('mobile-tooltip-text');
            if (!toast || !toastText) return;
            toastText.textContent = text == null ? '' : String(text);
            toast.classList.add('show');
            if (mobileToastTimer) clearTimeout(mobileToastTimer);
            mobileToastTimer = setTimeout(() => {
                hideMobileToast();
            }, 6000);
        }

        function hideMobileToast() {
            const toast = document.getElementById('mobile-tooltip-toast');
            if (toast) toast.classList.remove('show');
            if (mobileToastTimer) clearTimeout(mobileToastTimer);
        }

        function adjustTooltipViewportPos(target) {
            if (!target || window.innerWidth <= 768) return;
            const rect = target.getBoundingClientRect();
            const origPos = target.getAttribute('data-tip-orig-pos') || target.getAttribute('data-tip-pos') || 'top';
            if (!target.hasAttribute('data-tip-orig-pos')) {
                target.setAttribute('data-tip-orig-pos', origPos);
            }

            if (origPos === 'right') {
                if ((window.innerWidth - rect.right) < 275) {
                    target.setAttribute('data-tip-pos', rect.left > 275 ? 'left' : (rect.top < 120 ? 'bottom-left' : 'top-left'));
                } else {
                    target.setAttribute('data-tip-pos', 'right');
                }
                return;
            }
            if (origPos === 'left') {
                if (rect.left < 275) {
                    target.setAttribute('data-tip-pos', (window.innerWidth - rect.right) > 275 ? 'right' : 'bottom-left');
                } else {
                    target.setAttribute('data-tip-pos', 'left');
                }
                return;
            }

            const useBottom = rect.top < 125 || origPos.startsWith('bottom');
            const nearLeft = rect.left < 145 || origPos.endsWith('-left');
            const nearRight = (window.innerWidth - rect.right) < 145 || origPos.endsWith('-right');
            let nextPos = useBottom ? 'bottom' : 'top';
            if (nearLeft && !nearRight) nextPos = useBottom ? 'bottom-left' : 'top-left';
            else if (nearRight && !nearLeft) nextPos = useBottom ? 'bottom-right' : 'top-right';
            target.setAttribute('data-tip-pos', nextPos);
        }

        document.addEventListener('DOMContentLoaded', () => {
            // Intercetta in capture phase i badge [data-tip] dentro row cliccabili e tutti i [data-tip] su mobile
            document.body.addEventListener('click', (e) => {
                const target = e.target.closest('[data-tip]');
                if (target && (window.innerWidth <= 768 || window.matchMedia('(hover: none)').matches)) {
                    const tipText = target.getAttribute('data-tip');
                    if (tipText) {
                        e.stopPropagation();
                        if (target.classList.contains('trade-guard')) {
                            e.preventDefault();
                        }
                        showMobileToast(tipText);
                    }
                }
            }, true);

            // Auto-adattamento bordi viewport su hover/focus desktop
            document.body.addEventListener('mouseover', (e) => {
                const target = e.target.closest('[data-tip]');
                if (target) adjustTooltipViewportPos(target);
            });
            document.body.addEventListener('focusin', (e) => {
                const target = e.target.closest('[data-tip]');
                if (target) adjustTooltipViewportPos(target);
            });
        });

    </script>

</body>
</html>
"""



async def handle_dashboard_page(request):
    """Serve la pagina HTML della dashboard."""
    return web.Response(
        text=DASHBOARD_HTML,
        content_type="text/html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

import asyncio
import time

_CACHE_STORE = {}
_LEARNING_CACHE: Dict[str, Any] = {}
_SHARED_LIVE_STATE = None
_SHARED_LIVE_TIME = 0.0
_CACHE_TTL = 3.5  # Cache TTL broker: 3.5 secondi per azzerare overhead di rete e rate limits


def _empty_learning_payload() -> Dict[str, Any]:
    """Schema di fallback sicuro per la sezione `learning` del payload dashboard."""
    return {
        "trade_counts": {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "profit_factor_net": 0.0,
            "expectancy_r": 0.0,
            "expectancy_usd": 0.0,
            "total_pnl_usd": 0.0,
            "total_fees_usd": 0.0,
        },
        "avg_mfe_pct": 0.0,
        "avg_mae_pct": 0.0,
        "avg_capture_eff": 0.0,
        "avg_edge_ratio": 0.0,
        "shadow_stats": {
            "total": 0,
            "evaluated": 0,
            "pending": 0,
            "avg_virtual_r": 0.0,
            "win_rate_pct": 0.0,
            "missed_alpha_count": 0,
            "saved_capital_count": 0,
        },
        "context_buckets": [],
        "exit_frontier": {
            "approved": False,
            "n_samples": 0,
            "baseline_expectancy_r": 0.0,
            "baseline_lcb_r": 0.0,
            "best_expectancy_r": 0.0,
            "best_lcb_r": 0.0,
            "best_params": {},
            "reason": "In attesa di campioni chiusi valutati.",
        },
        "adaptive_exit_active": False,
        "engines_breakdown": {},
        "meta_gate_drift": {
            "active": False,
            "deployable": False,
            "n_events": 0,
            "verdict": "MetaGate non configurato",
        },
        "latest_audit": None,
        "recent_shadows": [],
    }


def _build_learning_payload(db_path: Path, meta_gate_path: Optional[str] = None) -> Dict[str, Any]:
    """Aggrega e normalizza le metriche del Learning Engine con caching mtime+TTL per evitare latenze."""
    eff_db = Path(db_path)
    eff_mg = meta_gate_path if meta_gate_path is not None else (os.getenv("QUANT_META_GATE_PATH", "") or None)
    try:
        db_mtime_ns = eff_db.stat().st_mtime_ns if eff_db.exists() else 0
    except Exception:
        db_mtime_ns = 0

    cache_key = f"{eff_db}|{eff_mg or ''}"
    now_t = time.time()
    cached = _LEARNING_CACHE.get(cache_key)
    if (
        cached is not None
        and cached.get("mtime_ns") == db_mtime_ns
        and (now_t - cached.get("cached_at", 0.0)) < _CACHE_TTL
    ):
        return cached["data"]

    payload = _empty_learning_payload()
    try:
        raw_summary = learning_engine.get_learning_dashboard_summary(
            eff_db,
            meta_gate_path=eff_mg,
        ) or {}
    except Exception as e_le:
        print(f"[!] Dashboard: fallback learning_engine ({e_le})")
        return payload

    real_stats = raw_summary.get("real_stats") or {}
    payload["trade_counts"] = {
        "total": int(real_stats.get("total", 0) or 0),
        "wins": int(real_stats.get("wins", 0) or 0),
        "losses": int(real_stats.get("losses", 0) or 0),
        "win_rate_pct": float(real_stats.get("win_rate", 0.0) or 0.0),
        "profit_factor_net": float(real_stats.get("profit_factor_net", 0.0) or 0.0),
        "expectancy_r": float(real_stats.get("expectancy_r", 0.0) or 0.0),
        "expectancy_usd": float(real_stats.get("expectancy_usd", 0.0) or 0.0),
        "total_pnl_usd": float(real_stats.get("total_pnl_usd", 0.0) or 0.0),
        "total_fees_usd": float(real_stats.get("total_fees_usd", 0.0) or 0.0),
    }
    payload["avg_mfe_pct"] = float(real_stats.get("avg_mfe_pct", 0.0) or 0.0)
    payload["avg_mae_pct"] = float(real_stats.get("avg_mae_pct", 0.0) or 0.0)
    payload["avg_capture_eff"] = float(real_stats.get("avg_capture_eff", 0.0) or 0.0)
    payload["avg_edge_ratio"] = float(real_stats.get("avg_edge_ratio", 0.0) or 0.0)

    sh_raw = raw_summary.get("shadow_stats") or {}
    eval_sh = int(sh_raw.get("evaluated", 0) or 0)
    pend_sh = int(sh_raw.get("pending", 0) or 0)
    total_sh = int(sh_raw.get("total", eval_sh + pend_sh) or (eval_sh + pend_sh))

    missed_alpha_count = int(sh_raw.get("missed_alpha_count", 0) or 0)
    saved_capital_count = int(sh_raw.get("saved_capital_count", 0) or 0)
    shadow_pos_by_ctx: Dict[str, int] = {}
    real_neg_by_ctx: Dict[str, int] = {}
    recent_shadows = []

    if eff_db.exists():
        conn = None
        try:
            conn = sqlite3.connect(eff_db)
            conn.row_factory = sqlite3.Row
            tbl_check = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "signal_shadows" in tbl_check:
                agg_row = conn.execute(
                    """
                    SELECT
                        SUM(CASE WHEN status = 'EVALUATED' AND virtual_r > 0 THEN 1 ELSE 0 END) AS missed_alpha,
                        SUM(CASE WHEN status = 'EVALUATED' AND virtual_r <= 0 THEN 1 ELSE 0 END) AS saved_cap
                    FROM signal_shadows
                    """
                ).fetchone()
                if agg_row is not None:
                    missed_alpha_count = int(agg_row["missed_alpha"] or 0)
                    saved_capital_count = int(agg_row["saved_cap"] or 0)

                for srow in conn.execute(
                    """
                    SELECT UPPER(context_key) AS ck,
                           SUM(CASE WHEN virtual_r > 0 THEN 1 ELSE 0 END) AS pos_cnt
                    FROM signal_shadows
                    WHERE status = 'EVALUATED' AND context_key IS NOT NULL
                    GROUP BY UPPER(context_key)
                    """
                ).fetchall():
                    shadow_pos_by_ctx[str(srow["ck"])] = int(srow["pos_cnt"] or 0)

                for rec in conn.execute(
                    """
                    SELECT symbol, side, engine, reject_reason, status, virtual_r, virtual_pnl_pct, hit_outcome, created_at
                    FROM signal_shadows
                    ORDER BY id DESC
                    LIMIT 5
                    """
                ).fetchall():
                    recent_shadows.append(dict(rec))

            if "trade_journal" in tbl_check:
                for trow in conn.execute(
                    """
                    SELECT UPPER(context_key) AS ck,
                           SUM(CASE WHEN pnl_usd <= 0 THEN 1 ELSE 0 END) AS neg_cnt
                    FROM trade_journal
                    WHERE status = 'CLOSED' AND context_key IS NOT NULL
                    GROUP BY UPPER(context_key)
                    """
                ).fetchall():
                    real_neg_by_ctx[str(trow["ck"])] = int(trow["neg_cnt"] or 0)
        except Exception:
            pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    payload["shadow_stats"] = {
        "total": total_sh,
        "evaluated": eval_sh,
        "pending": pend_sh,
        "avg_virtual_r": float(sh_raw.get("shadow_expectancy_r", 0.0) or 0.0),
        "win_rate_pct": float(sh_raw.get("shadow_win_rate", 0.0) or 0.0),
        "missed_alpha_count": missed_alpha_count,
        "saved_capital_count": saved_capital_count,
    }

    buckets = []
    raw_allocs = raw_summary.get("context_allocations") or raw_summary.get("context_buckets") or []
    for a in raw_allocs:
        ck = str(a.get("context_key") or "")
        ck_u = ck.upper()
        mode = str(a.get("mode") or "STANDARD")
        real_n = int(a.get("n_real", a.get("real_n", 0)) or 0)
        shadow_n = int(a.get("n_shadow", a.get("shadow_n", 0)) or 0)
        eff_n = float(a.get("n_eff", a.get("effective_n", 0.0)) or 0.0)
        mean_r = float(a.get("mean_r", 0.0) or 0.0)
        lcb_r = float(a.get("lcb_r", 0.0) or 0.0)
        explicit_rec = a.get("shadow_recovered")
        if explicit_rec is not None:
            shadow_recovered = bool(explicit_rec)
        else:
            shadow_recovered = bool(
                shadow_n > 0
                and mode != "SHADOW_BLOCKED"
                and shadow_pos_by_ctx.get(ck_u, 0) > 0
                and (real_neg_by_ctx.get(ck_u, 0) > 0 or (real_n > 0 and mean_r > -0.15))
            )
        buckets.append({
            "context_key": ck,
            "matched_key": str(a.get("matched_key") or ck),
            "backoff_level": int(a.get("backoff_level", 0) or 0),
            "mode": mode,
            "scale": float(a.get("scale", 1.0) if a.get("scale") is not None else 1.0),
            "real_n": real_n,
            "shadow_n": shadow_n,
            "effective_n": round(eff_n, 2),
            "mean_r": round(mean_r, 4),
            "lcb_r": round(lcb_r, 4),
            "ucb_r": round(float(a.get("ucb_r", 0.0) or 0.0), 4),
            "shadow_recovered": shadow_recovered,
        })

    exit_frontier = raw_summary.get("exit_frontier") or payload["exit_frontier"]
    payload["context_buckets"] = buckets
    payload["exit_frontier"] = exit_frontier
    payload["adaptive_exit_active"] = bool(exit_frontier.get("approved", False))
    payload["engines_breakdown"] = raw_summary.get("engines_breakdown") or {}
    payload["meta_gate_drift"] = raw_summary.get("quant_drift") or raw_summary.get("meta_gate_drift") or payload["meta_gate_drift"]
    payload["latest_audit"] = raw_summary.get("latest_audit")
    payload["recent_shadows"] = recent_shadows

    try:
        new_mtime_ns = eff_db.stat().st_mtime_ns if eff_db.exists() else 0
    except Exception:
        new_mtime_ns = db_mtime_ns
    _LEARNING_CACHE[cache_key] = {
        "data": payload,
        "cached_at": now_t,
        "mtime_ns": new_mtime_ns,
    }
    return payload

def _fetch_shared_live_state_sync():
    """Interroga le API di Bybit e Alpaca memorizzando lo stato comune (wallet, posizioni, compass)."""
    global _bybit_service, _alpaca_service
    if not _bybit_service:
        _bybit_service = BybitExecutionService()
    if not _alpaca_service:
        try:
            _alpaca_service = AlpacaExecutionService()
        except Exception as e_alp:
            # Credenziali Alpaca assenti: la dashboard mostra solo Bybit invece di fallire
            print(f"[!] Dashboard: Alpaca disabilitato ({e_alp})")

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
        b_closed = sorted(raw_closed, key=lambda c: int(c.get("updatedTime", 0) or 0), reverse=True)
        # Sincronizza i trade chiusi con il Trade Journal per estrarre lezioni e statistiche
        try:
            _trade_journal_service.sync_historical_trades_from_broker(b_closed, broker="BYBIT")
        except Exception:
            pass
    except Exception:
        b_closed = []

    try:
        a_summary = _alpaca_service.get_account_summary()
    except Exception:
        a_summary = {}

    a_closed = []
    if _alpaca_service is not None:
        try:
            raw_a_closed = _alpaca_service.get_recent_closed_trades(limit_days=7) or []
            from datetime import datetime
            for ac in raw_a_closed:
                ts_ms = 0
                raw_t = ac.get("timestamp")
                if raw_t:
                    try:
                        ts_ms = int(datetime.fromisoformat(str(raw_t).replace("Z", "+00:00")).timestamp() * 1000)
                    except Exception:
                        ts_ms = 0
                qty = float(ac.get("qty", 0.0) or 0.0)
                ep = float(ac.get("entry_price", 0.0) or 0.0)
                a_closed.append({
                    "symbol": ac.get("symbol", ""),
                    "side": "Buy" if str(ac.get("side", "LONG")).upper() == "LONG" else "Sell",
                    "closedPnl": float(ac.get("pnl", 0.0) or 0.0),
                    "cumEntryValue": qty * ep,
                    "closedSize": qty,
                    "avgEntryPrice": ep,
                    "avgExitPrice": float(ac.get("exit_price", 0.0) or 0.0),
                    "openFee": 0.0,
                    "closeFee": 0.0,
                    "updatedTime": ts_ms,
                    "broker": "ALPACA",
                })
        except Exception:
            a_closed = []

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

    variations = perf_tracker.get_variations(tot_eq, cum_real, bybit_eq=b_eq, alpaca_eq=a_eq, current_unrealized_pnl=unreal_pnl)
    compass_metrics = trading_compass.compute_edge_metrics(b_closed, b_pos, tot_eq)
    setup_readiness = trading_compass.compute_setup_readiness(_bybit_service)
    alpaca_compass_metrics = trading_compass.compute_edge_metrics(a_closed, a_summary.get("positions", []), a_eq)
    alpaca_setup_readiness = trading_compass.compute_alpaca_setup_readiness()

    return {
        "b_wallet": b_wallet,
        "b_pos": b_pos,
        "b_closed": b_closed,
        "a_summary": a_summary,
        "a_closed": a_closed,
        "tot_eq": tot_eq,
        "b_eq": b_eq,
        "a_eq": a_eq,
        "cum_real": cum_real,
        "unreal_pnl": unreal_pnl,
        "variations": variations,
        "compass_metrics": compass_metrics,
        "setup_readiness": setup_readiness,
        "alpaca_compass_metrics": alpaca_compass_metrics,
        "alpaca_setup_readiness": alpaca_setup_readiness
    }

def _build_dashboard_payload_sync(tf: str):
    """Costruisce istantaneamente il payload combinando lo stato live condiviso con lo storico del timeframe richiesto."""
    global _SHARED_LIVE_STATE, _SHARED_LIVE_TIME
    now_t = time.time()

    # Se lo stato condiviso è scaduto o non esiste, rinfrescalo
    if _SHARED_LIVE_STATE is None or (now_t - _SHARED_LIVE_TIME) >= _CACHE_TTL:
        _SHARED_LIVE_STATE = _fetch_shared_live_state_sync()
        _SHARED_LIVE_TIME = now_t

    s = _SHARED_LIVE_STATE
    # Interroga solo la query SQLite locale per il timeframe specifico (<2ms)
    history = perf_tracker.get_timeframe_history(tf)

    journal_insights = []
    journal_stats = {}
    try:
        journal_insights = _trade_journal_service.get_recent_insights(limit=10)
        journal_stats = _trade_journal_service.get_learning_stats()
    except Exception:
        pass

    try:
        learning_summary = _build_learning_payload(_trade_journal_service.db_path)
    except Exception:
        learning_summary = _empty_learning_payload()

    return {
        "status": "online",
        "timestamp": datetime.now(ZoneInfo("Europe/Rome")).isoformat(),
        "timeframe": tf,
        "compass": s["compass_metrics"],
        "setup_readiness": s["setup_readiness"],
        "bybit": {
            "wallet": s["b_wallet"],
            "positions": s["b_pos"],
            "closed": s["b_closed"]
        },
        "alpaca": {
            "account": s["a_summary"].get("account", {}),
            "positions": s["a_summary"].get("positions", []),
            "closed": s.get("a_closed", []),
            "compass": s.get("alpaca_compass_metrics", {}),
            "setup_readiness": s.get("alpaca_setup_readiness", {})
        },
        "journal": {
            "insights": journal_insights,
            "stats": journal_stats
        },
        "learning": learning_summary,
        "perf_history": history,
        "variations": s["variations"]
    }

async def handle_dashboard_api(request):
    """Restituisce il payload JSON iper-reattivo in <5ms via thread pool asincrono e cache intelligente multi-timeframe."""
    global _CACHE_STORE
    tf = request.query.get("tf", "3s")
    now_t = time.time()

    # Se abbiamo già in cache esattamente questo timeframe < 3.5s fa, restituiscilo SUBITO
    if tf in _CACHE_STORE and (now_t - _CACHE_STORE[tf]["cached_at"]) < _CACHE_TTL:
        return web.json_response(_CACHE_STORE[tf]["data"])

    try:
        data = await asyncio.to_thread(_build_dashboard_payload_sync, tf)
        _CACHE_STORE[tf] = {
            "data": data,
            "cached_at": now_t
        }
        return web.json_response(data)
    except Exception as e:
        if tf in _CACHE_STORE:
            return web.json_response(_CACHE_STORE[tf]["data"])
        return web.json_response({"error": str(e), "status": "recovering"}, status=200)

async def handle_trade_forecast_api(request):
    """Restituisce l'analisi ciclica (Hurst/Migliorino), onde di Elliott e simulazione Monte Carlo per un asset."""
    symbol = request.query.get("symbol", "BTCUSDT")
    tf = request.query.get("tf", "1d")
    data = await asyncio.to_thread(get_deep_trade_forecast, symbol, tf)
    return web.json_response(data)

async def handle_trigger_briefing_api(request):
    """
    Endpoint protetto per triggerare briefing o watchdog remoto.
    Sicurezza Pre-Launch Check 02 & Check 07:
    - Rifiuta categoricamente qualsiasi token o secret passato via query string nell'URL.
    - Accetta solo l'header HTTP 'X-Trigger-Key' confrontato con timing-safe compare rispetto a TRIGGER_SECRET o BRIEFING_SECRET.
    """
    # Rifiuto categorico del secret in query param per prevenire leak nei log proxy o access log
    if "key" in request.query or "secret" in request.query:
        return web.json_response(
            {"error": "Forbidden: Passing secrets via query parameter is strictly prohibited. Use 'X-Trigger-Key' header."},
            status=403
        )
    
    expected_secret = os.getenv("TRIGGER_SECRET") or os.getenv("BRIEFING_SECRET")
    if not expected_secret:
        return web.json_response({"error": "Service Unavailable: TRIGGER_SECRET not configured on server."}, status=503)
        
    provided_key = request.headers.get("X-Trigger-Key", "")
    if not provided_key or not hmac.compare_digest(provided_key, expected_secret):
        return web.json_response({"error": "Unauthorized: Invalid or missing X-Trigger-Key header."}, status=401)
        
    slot = request.query.get("slot", "morning")
    callback = request.app.get("briefing_callback")
    if not callback:
        return web.json_response({"status": "acknowledged", "message": "No briefing callback registered, endpoint active.", "slot": slot})
        
    try:
        # Esegui il callback asincrono del briefing
        asyncio.create_task(callback(slot))
        return web.json_response({"status": "success", "message": f"Briefing trigger scheduled for slot '{slot}'."})
    except Exception as e:
        return web.json_response({"error": f"Failed to trigger briefing: {e}"}, status=500)

def create_web_app(bybit_svc=None, alpaca_svc=None, briefing_callback=None):
    global _bybit_service, _alpaca_service
    if bybit_svc:
        _bybit_service = bybit_svc
    if alpaca_svc:
        _alpaca_service = alpaca_svc

    app = web.Application()
    if briefing_callback:
        app["briefing_callback"] = briefing_callback
        
    app.router.add_get("/", handle_dashboard_page)
    app.router.add_get("/api/dashboard", handle_dashboard_api)
    app.router.add_get("/api/trade-forecast", handle_trade_forecast_api)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    app.router.add_get("/healthz", lambda r: web.Response(text="OK"))
    app.router.add_post("/api/trigger-briefing", handle_trigger_briefing_api)
    app.router.add_get("/api/trigger-briefing", handle_trigger_briefing_api)
    return app
