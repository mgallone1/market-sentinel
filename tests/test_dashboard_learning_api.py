import collections
import json
import re
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from services import dashboard_web_service as dws
from services.trade_journal_service import ROME_TZ, TradeJournalService


def _mock_live_state():
    return {
        "b_wallet": {"total_equity": 100000.0, "available_balance": 50000.0, "coins": {"USDT": 50000.0}},
        "b_pos": [],
        "b_closed": [],
        "a_summary": {"account": {"portfolio_value": 50000.0, "buying_power": 100000.0}, "positions": []},
        "a_closed": [],
        "tot_eq": 150000.0,
        "b_eq": 100000.0,
        "a_eq": 50000.0,
        "cum_real": 0.0,
        "unreal_pnl": 0.0,
        "variations": {
            "3s": {"delta_equity": 0.0, "delta_equity_pct": 0.0, "delta_trading_pnl": 0.0},
            "1d": {"delta_equity": 0.0, "delta_equity_pct": 0.0, "delta_trading_pnl": 0.0},
        },
        "compass_metrics": {"health_score": 50, "verdict": "HOLD", "verdict_color": "amber"},
        "setup_readiness": {"readiness_score": 50, "readiness_verdict": "WAIT", "readiness_color": "amber", "breakdown": {}},
        "alpaca_compass_metrics": {"health_score": 50, "verdict": "HOLD", "verdict_color": "amber"},
        "alpaca_setup_readiness": {"readiness_score": 50, "readiness_verdict": "WAIT", "readiness_color": "amber", "breakdown": {}},
    }


class TestDashboardLearningAPI(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_dashboard.db"
        self.journal = TradeJournalService(self.db_path)
        dws._CACHE_STORE.clear()
        dws._LEARNING_CACHE.clear()
        dws._SHARED_LIVE_STATE = None
        dws._SHARED_LIVE_TIME = 0.0

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_dashboard_payload_empty_db_returns_valid_learning_and_journal(self):
        with (
            patch.object(dws, "_fetch_shared_live_state_sync", return_value=_mock_live_state()),
            patch.object(dws.perf_tracker, "get_timeframe_history", return_value=[]),
            patch.object(dws, "_trade_journal_service", self.journal),
        ):
            payload = dws._build_dashboard_payload_sync("3s")

        self.assertEqual(payload["status"], "online")
        self.assertIn("journal", payload)
        self.assertIn("insights", payload["journal"])
        self.assertIn("stats", payload["journal"])

        self.assertIn("learning", payload)
        learning = payload["learning"]
        for key in (
            "trade_counts",
            "avg_mfe_pct",
            "avg_mae_pct",
            "avg_capture_eff",
            "avg_edge_ratio",
            "shadow_stats",
            "context_buckets",
            "exit_frontier",
            "adaptive_exit_active",
            "engines_breakdown",
            "meta_gate_drift",
            "latest_audit",
        ):
            self.assertIn(key, learning)

        self.assertEqual(learning["trade_counts"]["total"], 0)
        self.assertEqual(learning["shadow_stats"]["total"], 0)
        self.assertEqual(learning["shadow_stats"]["missed_alpha_count"], 0)
        self.assertFalse(learning["adaptive_exit_active"])
        self.assertIsInstance(learning["context_buckets"], list)
        self.assertEqual(learning["context_buckets"], [])

    def test_dashboard_payload_seeded_db_aggregates_all_learning_pillars(self):
        now_dt = datetime.now(ROME_TZ)
        ck_main = "BYBIT|BTCUSDT|TREND_PULLBACK_4H|LONG|NORMAL|EU"
        ck_mr = "BYBIT|ETHUSDT|LIQUIDITY_SWEEP_MR|SHORT|NORMAL|US"

        conn = sqlite3.connect(self.db_path)
        try:
            # Seed 2 closed trades with path metrics
            for i, (sym, eng, ck, pnl_usd, pnl_pct, mfe, mae, cap, edge) in enumerate(
                [
                    ("BTCUSDT", "TREND_PULLBACK_4H", ck_main, 240.0, 2.4, 3.0, -0.5, 0.80, 6.0),
                    ("ETHUSDT", "LIQUIDITY_SWEEP_MR", ck_mr, -110.0, -1.1, 0.4, -1.3, -2.75, 0.31),
                ],
                start=1,
            ):
                opened = (now_dt - timedelta(hours=3 + i)).isoformat()
                closed = (now_dt - timedelta(hours=1 + i)).isoformat()
                conn.execute(
                    """
                    INSERT INTO trade_journal (
                        trade_id, broker, symbol, side, entry_price, notional_usd,
                        opened_at, closed_at, exit_price, pnl_usd, pnl_pct,
                        close_reason, entry_context, post_mortem_analysis, learned_lesson,
                        status, engine, context_key, mfe_pct, mae_pct, capture_eff, edge_ratio, bars_held, fees_usd
                    ) VALUES (?, 'BYBIT', ?, 'LONG', 100.0, 10000.0, ?, ?, 102.0, ?, ?, 'TAKE_PROFIT', ?, 'Analisi', 'Lezione',
                              'CLOSED', ?, ?, ?, ?, ?, ?, 8, 12.0)
                    """,
                    (
                        f"T_{i}",
                        sym,
                        opened,
                        closed,
                        pnl_usd,
                        pnl_pct,
                        json.dumps({"sl_pct": 1.2, "engine": eng, "pnl_is_net": True}),
                        eng,
                        ck,
                        mfe,
                        mae,
                        cap,
                        edge,
                    ),
                )

            # Seed 2 evaluated shadows (1 missed alpha, 1 saved capital) + 1 pending
            conn.execute(
                """
                INSERT INTO signal_shadows (
                    shadow_id, broker, symbol, side, engine, context_key, reject_reason,
                    signal_price, sl_pct, tp_pct, created_at, evaluated_at, status,
                    virtual_pnl_pct, virtual_r, mfe_pct, mae_pct, hit_outcome
                ) VALUES (?, 'BYBIT', 'ETHUSDT', 'SHORT', 'LIQUIDITY_SWEEP_MR', ?, 'CVD_SHIELD',
                          2000.0, 1.2, 3.6, ?, ?, 'EVALUATED', 2.4, 2.0, 2.8, -0.3, 'TP')
                """,
                ("SH_1", ck_mr, (now_dt - timedelta(hours=4)).isoformat(), now_dt.isoformat()),
            )
            conn.execute(
                """
                INSERT INTO signal_shadows (
                    shadow_id, broker, symbol, side, engine, context_key, reject_reason,
                    signal_price, sl_pct, tp_pct, created_at, evaluated_at, status,
                    virtual_pnl_pct, virtual_r, mfe_pct, mae_pct, hit_outcome
                ) VALUES (?, 'BYBIT', 'SOLUSDT', 'LONG', 'INTRADAY_MOMENTUM', 'BYBIT|SOLUSDT|INTRADAY_MOMENTUM|LONG|HIGH|US',
                          'LOW_VOLUME', 150.0, 1.4, 4.2, ?, ?, 'EVALUATED', -1.5, -1.07, 0.2, -1.6, 'SL')
                """,
                ("SH_2", (now_dt - timedelta(hours=5)).isoformat(), now_dt.isoformat()),
            )
            conn.execute(
                """
                INSERT INTO signal_shadows (
                    shadow_id, broker, symbol, side, engine, context_key, reject_reason,
                    signal_price, sl_pct, tp_pct, created_at, status
                ) VALUES (?, 'BYBIT', 'BTCUSDT', 'LONG', 'TREND_PULLBACK_4H', ?, 'COOLDOWN',
                          90000.0, 1.4, 4.2, ?, 'PENDING')
                """,
                ("SH_3", ck_main, now_dt.isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

        self.journal.save_learning_audit(
            "WEEKLY_AUDIT",
            {"real_stats": {"total": 2}},
            "Audit settimanale test: 2 trade reali, 2 shadow valutati.",
        )

        with (
            patch.object(dws, "_fetch_shared_live_state_sync", return_value=_mock_live_state()),
            patch.object(dws.perf_tracker, "get_timeframe_history", return_value=[]),
            patch.object(dws, "_trade_journal_service", self.journal),
        ):
            payload = dws._build_dashboard_payload_sync("1h")

        learning = payload["learning"]
        self.assertEqual(learning["trade_counts"]["total"], 2)
        self.assertEqual(learning["trade_counts"]["wins"], 1)
        self.assertEqual(learning["trade_counts"]["losses"], 1)
        self.assertAlmostEqual(learning["trade_counts"]["max_drawdown_usd"], 110.0, places=2)
        self.assertAlmostEqual(learning["avg_mfe_pct"], 1.7, places=2)
        self.assertAlmostEqual(learning["avg_mae_pct"], -0.9, places=2)
        self.assertAlmostEqual(learning["avg_edge_ratio"], 3.155, places=2)

        sh = learning["shadow_stats"]
        self.assertEqual(sh["total"], 3)
        self.assertEqual(sh["evaluated"], 2)
        self.assertEqual(sh["pending"], 1)
        self.assertEqual(sh["missed_alpha_count"], 1)
        self.assertEqual(sh["saved_capital_count"], 1)
        self.assertAlmostEqual(sh["win_rate_pct"], 50.0, places=1)
        self.assertEqual(sh["reason_counts"].get("CVD_SHIELD"), 1)
        self.assertEqual(sh["timemachine_blocked_count"], 0)
        self.assertEqual(len(learning["recent_shadows"]), 3)

        buckets = learning["context_buckets"]
        self.assertGreaterEqual(len(buckets), 2)
        mr_bucket = next((b for b in buckets if b["context_key"] == ck_mr), None)
        self.assertIsNotNone(mr_bucket)
        self.assertIn("mode", mr_bucket)
        self.assertIn("scale", mr_bucket)
        self.assertIn("real_n", mr_bucket)
        self.assertIn("shadow_n", mr_bucket)
        self.assertIn("effective_n", mr_bucket)
        self.assertTrue(mr_bucket["shadow_recovered"])

        self.assertIn("TREND_PULLBACK_4H", learning["engines_breakdown"])
        self.assertIn("LIQUIDITY_SWEEP_MR", learning["engines_breakdown"])
        self.assertFalse(learning["adaptive_exit_active"])
        self.assertIsNotNone(learning["latest_audit"])
        self.assertIn("Audit settimanale test", learning["latest_audit"]["summary_text"])
        self.assertEqual(len(payload["journal"]["insights"]), 2)

    def test_dashboard_payload_learning_engine_exception_safe_fallback(self):
        with (
            patch.object(dws, "_fetch_shared_live_state_sync", return_value=_mock_live_state()),
            patch.object(dws.perf_tracker, "get_timeframe_history", return_value=[]),
            patch.object(dws, "_trade_journal_service", self.journal),
            patch.object(dws.learning_engine, "get_learning_dashboard_summary", side_effect=RuntimeError("db boom")),
        ):
            payload = dws._build_dashboard_payload_sync("3s")

        self.assertEqual(payload["status"], "online")
        self.assertIn("learning", payload)
        self.assertEqual(payload["learning"]["trade_counts"]["total"], 0)
        self.assertFalse(payload["learning"]["adaptive_exit_active"])

    def test_html_has_no_duplicate_ids_and_valid_js_syntax(self):
        html = dws.DASHBOARD_HTML
        ids = re.findall(r'\bid=["\']([^"\']+)["\']', html)
        dup_ids = {k: v for k, v in collections.Counter(ids).items() if v > 1}
        self.assertEqual(dup_ids, {}, f"Duplicate HTML IDs found: {dup_ids}")

        scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, flags=re.S)
        inline_scripts = [s for s in scripts if s.strip()]
        self.assertGreaterEqual(len(inline_scripts), 1)
        for idx, script_body in enumerate(inline_scripts):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=True) as tf:
                tf.write(script_body)
                tf.flush()
                res = subprocess.run(["node", "--check", tf.name], capture_output=True, text=True)
                self.assertEqual(
                    res.returncode,
                    0,
                    f"JS syntax error in inline script #{idx}: {res.stderr}",
                )

    def test_xss_escaping_and_tooltips_and_guide_updates(self):
        html = dws.DASHBOARD_HTML

        # XSS helper checks
        self.assertIn("function escapeHtml(", html)
        self.assertIn("function formatContextKeyPills(", html)
        self.assertIn("function renderExposureStrip(", html)
        self.assertIn("function toggleUnknownBuckets(", html)
        self.assertIn("overflow-wrap: anywhere;", html)
        self.assertIn("toastText.textContent =", html)
        self.assertNotIn("toastText.innerHTML =", html)
        self.assertIn("escapeHtml(ins.post_mortem_analysis || ins.learned_lesson", html)
        self.assertIn("formatContextKeyPills(b.context_key", html)
        self.assertIn("escapeHtml(label)", html)
        self.assertIn("escapeHtml(readiness.expected_movement", html)
        self.assertIn("escapeHtml(aRead.expected_movement", html)
        self.assertNotIn("openTradeModal('${p.symbol}'", html)
        self.assertNotIn("openTradeModal('${ap.symbol}'", html)
        self.assertNotIn("openTradeModal('${c.symbol}'", html)

        # Tooltip CSS & uniqueness checks
        self.assertIn("[data-tip]:hover::after", html)
        self.assertIn("z-index: 99999;", html)
        self.assertIn("overflow: visible;", html)
        tips = re.findall(r'data-tip=["\']([^"\']+)["\']', html)
        self.assertGreaterEqual(len(tips), 30)
        dup_tips = {k: v for k, v in collections.Counter(tips).items() if v > 1}
        self.assertEqual(dup_tips, {}, f"Duplicate data-tip attributes found: {dup_tips}")

        # No stale hardcoded -1.20% / +3.60% claims
        self.assertNotIn("perde l'1.20%", html)
        self.assertNotIn("SL -1.20%", html)
        self.assertNotIn("(+3.60%)", html)
        self.assertNotIn("(-1.20%)", html)

        # Self-Learning Guide Desk & History cards checks
        for expected_phrase in (
            "TREND_PULLBACK_4H",
            "LIQUIDITY_SWEEP_MR",
            "INTRADAY_MOMENTUM",
            "Causal Shadow Ledger",
            "MFE",
            "MAE",
            "Capture Efficiency",
            "Edge Ratio",
            "Exit Frontier",
            "1.25x",
            "0.5x",
            "0.0x",
            "SHADOW RECOVERED",
            "half-life 35",
            "20:00 CET",
            "/learning",
            "MetaGate",
        ):
            self.assertIn(expected_phrase, html)

        # Zero emojis in HTML/CSS/JS
        emojis = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", html)
        self.assertEqual(emojis, [], f"Unexpected emojis in UI chrome: {emojis}")


if __name__ == "__main__":
    unittest.main()
