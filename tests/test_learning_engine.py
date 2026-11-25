import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from services.alpaca_execution_service import AlpacaExecutionService
from services.bybit_execution_service import BybitExecutionService, format_bybit_price, format_bybit_qty
from services.learning_engine_service import (
    backoff_context_keys,
    build_weekly_learning_report,
    compute_atr_ratchet_levels,
    compute_context_allocation,
    evaluate_trade_path_mfe_mae,
    get_learning_dashboard_summary,
    normalize_context_key,
    optimize_exit_frontier,
    run_evaluation_cycle,
)
from services.trade_journal_service import ROME_TZ, TradeJournalService


class TestLearningEngineWave1(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_sentinel.db"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_additive_db_migration_preserves_legacy_rows(self):
        # Crea schema legacy minimale senza le nuove colonne o tabelle
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE trade_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT UNIQUE NOT NULL,
                    broker TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    notional_usd REAL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    pnl_usd REAL DEFAULT 0.0,
                    pnl_pct REAL DEFAULT 0.0,
                    close_reason TEXT,
                    entry_context TEXT,
                    post_mortem_analysis TEXT,
                    learned_lesson TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO trade_journal (
                    trade_id, broker, symbol, side, status, entry_price, exit_price,
                    notional_usd, opened_at, closed_at, pnl_usd, pnl_pct, close_reason, entry_context
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "BYBIT_BTCUSDT_legacy_1",
                    "BYBIT",
                    "BTCUSDT",
                    "LONG",
                    "CLOSED",
                    80000.0,
                    81600.0,
                    2000.0,
                    "2026-10-01T10:00:00+02:00",
                    "2026-10-01T12:00:00+02:00",
                    40.0,
                    2.0,
                    "TAKE_PROFIT",
                    json.dumps({"atr_pct": 1.1}),
                ),
            )
            conn.commit()

        # Inizializza TradeJournalService: deve migrare in modo additivo senza perdere righe
        journal = TradeJournalService(self.db_path)
        self.assertIsNotNone(journal)

        with sqlite3.connect(self.db_path) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(trade_journal)").fetchall()}
            for expected_col in (
                "client_order_id",
                "engine",
                "context_key",
                "mfe_pct",
                "mae_pct",
                "capture_eff",
                "edge_ratio",
                "bars_held",
                "fees_usd",
                "exit_eval_json",
            ):
                self.assertIn(expected_col, cols)

            tables = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            self.assertIn("signal_shadows", tables)
            self.assertIn("learning_audit", tables)

            row = conn.execute(
                "SELECT trade_id, pnl_usd, engine FROM trade_journal WHERE trade_id = 'BYBIT_BTCUSDT_legacy_1'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], 40.0)
            self.assertEqual(row[2], "INTRADAY_MOMENTUM")

    def test_reconcile_closed_trades_and_deduplicate_untracked(self):
        journal = TradeJournalService(self.db_path)
        ck = normalize_context_key("BYBIT", "LONG", "BULL", 1.2, 15)
        opened_dt = datetime.now(ROME_TZ) - timedelta(minutes=30)
        trade_id = journal.record_entry(
            broker="BYBIT",
            symbol="SOLUSDT",
            side="LONG",
            entry_price=150.0,
            notional_usd=1500.0,
            context={"atr_pct": 1.2, "sl_pct": 1.68, "tp_pct": 5.04, "macro_bias": "BULL"},
            client_order_id="cli_sol_001",
            engine="INTRADAY_MOMENTUM",
            context_key=ck,
        )
        # Retrodata opened_at di 30 minuti per garantire closed_dt >= opened_dt
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE trade_journal SET opened_at = ? WHERE trade_id = ?",
                (opened_dt.isoformat(), trade_id),
            )
            conn.commit()

        # Bybit get_closed_pnl usa `side="Sell"` per chiusura di un LONG (+5.04% -> TAKE_PROFIT)
        closed_dt_ms = int((datetime.now(ROME_TZ) - timedelta(minutes=5)).timestamp() * 1000)
        reconciled = journal.reconcile_closed_trades_with_open_journal(
            "BYBIT",
            [
                {
                    "symbol": "SOLUSDT",
                    "side": "Sell",
                    "avgEntryPrice": 150.0,
                    "avgExitPrice": 157.56,
                    "closedPnl": 73.8,
                    "closeFee": 1.8,
                    "updatedTime": closed_dt_ms,
                }
            ],
        )
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0]["trade_id"], trade_id)
        self.assertEqual(reconciled[0]["close_reason"], "TAKE_PROFIT")
        self.assertEqual(journal.get_open_trade_ids(), [])

        # Verifica nessun duplicato orfano creato e contesto preservato
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM trade_journal WHERE symbol = 'SOLUSDT'").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "CLOSED")
            self.assertAlmostEqual(rows[0]["fees_usd"], 1.8, places=2)
            self.assertEqual(rows[0]["context_key"], ck)
            self.assertEqual(rows[0]["close_reason"], "TAKE_PROFIT")
            self.assertIn("BULL", rows[0]["post_mortem_analysis"])
            self.assertTrue(rows[0]["learned_lesson"])

        # Una seconda riconciliazione sullo stesso payload non deve ritoccare nulla
        reconciled_again = journal.reconcile_closed_trades_with_open_journal(
            "BYBIT",
            [
                {
                    "symbol": "SOLUSDT",
                    "side": "Sell",
                    "avgEntryPrice": 150.0,
                    "avgExitPrice": 156.0,
                    "closedPnl": 58.2,
                    "updatedTime": closed_dt_ms,
                }
            ],
        )
        self.assertEqual(reconciled_again, [])

        # Deduplica untracked entro 10 minuti su record_exit
        journal.record_exit("ALPACA", "NVDA", 120.0, -45.0, -1.5, "SL_HIT")
        journal.record_exit("ALPACA", "NVDA", 120.0, -45.0, -1.5, "SL_HIT")
        with sqlite3.connect(self.db_path) as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM trade_journal WHERE broker='ALPACA' AND symbol='NVDA'"
            ).fetchone()[0]
            self.assertEqual(cnt, 1)

        # Inserisce manualmente un legacy untracked duplicato nello stesso minuto e verifica cleanup
        with sqlite3.connect(self.db_path) as conn:
            ts = "2026-10-10T15:30:10+02:00"
            conn.execute(
                """
                INSERT INTO trade_journal (
                    trade_id, broker, symbol, side, status, entry_price, exit_price,
                    notional_usd, opened_at, closed_at, pnl_usd, pnl_pct, close_reason
                ) VALUES
                ('ALPACA_AAPL_enriched_1', 'ALPACA', 'AAPL', 'LONG', 'CLOSED', 200.0, 204.0, 2000.0, ?, ?, 40.0, 2.0, 'TP'),
                ('ALPACA_AAPL_untracked_999', 'ALPACA', 'AAPL', 'LONG', 'CLOSED', 204.0, 204.0, 0.0, ?, ?, 40.0, 0.0, 'TP'),
                ('ALPACA_AAPL_untracked_1000', 'ALPACA', 'AAPL', 'LONG', 'CLOSED', 204.0, 204.0, 0.0, ?, ?, 40.0, 0.0, 'TP')
                """,
                (ts, ts, ts, ts, ts, ts),
            )
            conn.commit()
        removed = journal.deduplicate_legacy_untracked()
        self.assertEqual(removed, 2)
        with sqlite3.connect(self.db_path) as conn:
            rem_ids = [
                r[0]
                for r in conn.execute("SELECT trade_id FROM trade_journal WHERE symbol='AAPL'").fetchall()
            ]
            self.assertEqual(rem_ids, ["ALPACA_AAPL_enriched_1"])

    def test_mfe_mae_and_exit_frontier_anti_overfitting_gate(self):
        # Costruisce serie 15m sintetica
        t0 = pd.Timestamp("2026-11-01T10:00:00Z")
        idx = pd.date_range(t0, periods=20, freq="15min")
        # Trade attivo da bar 0 a bar 5 (entry 100.0, max high 103.0 -> +3%, min low 99.2 -> -0.8%, exit close 101.2)
        highs = [100.5, 101.5, 103.0, 102.2, 101.8, 101.4] + [101.5 + 0.1 * i for i in range(14)]
        lows = [99.8, 99.2, 100.5, 100.8, 100.9, 100.7] + [101.0 for _ in range(14)]
        closes = [100.2, 100.9, 102.5, 101.6, 101.3, 101.2] + [101.3 + 0.1 * i for i in range(14)]
        df = pd.DataFrame({"high": highs, "low": lows, "close": closes}, index=idx)

        path_eval = evaluate_trade_path_mfe_mae(
            df,
            side="LONG",
            entry_price=100.0,
            opened_at_iso=idx[0].isoformat(),
            closed_at_iso=idx[5].isoformat(),
            exit_price=101.2,
            realized_pct=1.2,
        )
        self.assertIsNotNone(path_eval)
        self.assertAlmostEqual(path_eval["mfe_pct"], 3.0, places=2)
        self.assertAlmostEqual(path_eval["mae_pct"], -0.8, places=2)
        self.assertEqual(path_eval["bars_held"], 6)
        self.assertAlmostEqual(path_eval["edge_ratio"], 3.75, places=2)
        self.assertAlmostEqual(path_eval["capture_eff"], 0.4, places=2)
        self.assertIsNotNone(path_eval["post_exit_4b_pct"])
        self.assertIsNotNone(path_eval["post_exit_12b_pct"])

        # Gate Anti-Overfitting: N < 15 deve rifiutare sempre
        small_sample = [
            {
                "side": "LONG",
                "atr_pct": 1.0,
                "mfe_pct": 2.6,
                "mae_pct": -0.4,
                "pnl_pct": 0.3,
            }
            for _ in range(10)
        ]
        res_small = optimize_exit_frontier(small_sample, fee_rt_pct=0.12)
        self.assertFalse(res_small["approved"])
        self.assertEqual(res_small["n_samples"], 10)

        # N >= 20 con edge reale netto fee deve approvare un TP/SL migliore della baseline
        large_sample = [
            {
                "side": "LONG",
                "atr_pct": 1.0,
                "mfe_pct": 2.7 + (0.05 if i % 2 == 0 else 0.0),
                "mae_pct": -0.45 - (0.05 if i % 3 == 0 else 0.0),
                "pnl_pct": 0.25,
            }
            for i in range(20)
        ]
        res_large = optimize_exit_frontier(large_sample, fee_rt_pct=0.12)
        self.assertTrue(res_large["approved"])
        self.assertEqual(res_large["n_samples"], 20)
        self.assertGreater(res_large["best_lcb_r"], res_large["baseline_expectancy_r"] + 0.05)

    def test_compute_context_allocation_shadow_block_and_recovery(self):
        journal = TradeJournalService(self.db_path)
        ck = normalize_context_key("BYBIT", "SHORT", "BULL", 1.5, 16, "INTRADAY_MOMENTUM")

        # 18 trade reali negativi (-1.0R ciascuno, netti di SL 1.5%)
        base_dt = datetime.now(ROME_TZ) - timedelta(days=5)
        with sqlite3.connect(self.db_path) as conn:
            for i in range(18):
                ts = (base_dt + timedelta(hours=i)).isoformat()
                conn.execute(
                    """
                    INSERT INTO trade_journal (
                        trade_id, broker, symbol, side, status, entry_price, exit_price,
                        notional_usd, opened_at, closed_at, pnl_usd, pnl_pct, close_reason,
                        entry_context, engine, context_key, fees_usd
                    ) VALUES (?, 'BYBIT', 'ETHUSDT', 'SHORT', 'CLOSED', 3000.0, 3045.0,
                              1500.0, ?, ?, -22.5, -1.5, 'STOP_LOSS', ?, 'INTRADAY_MOMENTUM', ?, 1.8)
                    """,
                    (
                        f"BYBIT_ETHUSDT_loss_{i}",
                        ts,
                        ts,
                        json.dumps({"atr_pct": 1.5, "sl_pct": 1.5, "macro_bias": "BULL"}),
                        ck,
                    ),
                )
            conn.commit()

        blocked = compute_context_allocation(self.db_path, ck)
        self.assertEqual(blocked["mode"], "SHADOW_BLOCKED")
        self.assertEqual(blocked["scale"], 0.0)
        self.assertLessEqual(blocked["lcb_r"], -0.25)

        # Invecchiamo i vecchi trade oltre 2 half-life (70 giorni) e aggiungiamo 18 shadow signal vincenti recenti
        old_dt = (datetime.now(ROME_TZ) - timedelta(days=90)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE trade_journal SET opened_at = ?, closed_at = ?", (old_dt, old_dt))
            conn.commit()

        for i in range(18):
            sh_id = journal.record_shadow_signal(
                broker="BYBIT",
                symbol="ETHUSDT",
                side="SHORT",
                engine="INTRADAY_MOMENTUM",
                context_key=ck,
                reject_reason="SHADOW_BLOCKED",
                signal_price=3000.0,
                sl_pct=1.5,
                tp_pct=4.5,
                features={"idx": i},
            )
            # Evita cooldown 15m forzando shadow_id univoco solo per i test successivi se cooldown attivo
            if sh_id is None:
                with sqlite3.connect(self.db_path) as conn:
                    sh_id = f"SH_TEST_{i}"
                    conn.execute(
                        """
                        INSERT INTO signal_shadows (
                            shadow_id, broker, symbol, side, engine, context_key,
                            reject_reason, signal_price, sl_pct, tp_pct, features_json, created_at, status
                        ) VALUES (?, 'BYBIT', 'ETHUSDT', 'SHORT', 'INTRADAY_MOMENTUM', ?, 'SHADOW_BLOCKED',
                                  3000.0, 1.5, 4.5, '{}', ?, 'PENDING')
                        """,
                        (sh_id, ck, datetime.now(ROME_TZ).isoformat()),
                    )
                    conn.commit()
            journal.update_shadow_eval(
                shadow_id=sh_id,
                virtual_pnl_pct=3.0,
                virtual_r=2.0,
                mfe_pct=3.2,
                mae_pct=-0.3,
                hit_outcome="TP",
            )

        recovered = compute_context_allocation(self.db_path, ck)
        self.assertNotEqual(recovered["mode"], "SHADOW_BLOCKED")
        self.assertGreater(recovered["scale"], 0.0)
        self.assertEqual(recovered["mode"], "BOOSTED")
        self.assertEqual(recovered["scale"], 1.25)

    def test_atr_ratchet_levels_and_context_helpers(self):
        levels = compute_atr_ratchet_levels(atr_pct=1.5, side="LONG", entry_price=100.0)
        self.assertEqual(levels["sl_pct"], 2.1)
        self.assertEqual(levels["tp_pct"], 6.3)
        self.assertGreaterEqual(levels["be_lock_pct"], 0.25)
        self.assertGreater(levels["be_trigger_pct"], 1.0)
        self.assertLess(levels["sl_price"], 100.0)
        self.assertGreater(levels["tp_price"], 100.0)
        self.assertGreater(levels["max_sl"], levels["mid_sl"])
        self.assertGreater(levels["mid_sl"], levels["be_sl"])
        self.assertGreater(levels["be_sl"], levels["tight_sl"])

        ck = normalize_context_key("BYBIT", "LONG", "BEAR", 2.5, 15, "MEAN_REVERSION")
        self.assertEqual(ck, "BYBIT|LONG|BEAR|VOL_HIGH|US_PEAK|MEAN_REVERSION")
        self.assertEqual(
            backoff_context_keys(ck),
            [
                "BYBIT|LONG|BEAR|VOL_HIGH|US_PEAK|MEAN_REVERSION",
                "BYBIT|LONG|BEAR|MEAN_REVERSION",
                "BYBIT|LONG|BEAR",
            ],
        )

    def test_bybit_price_formatting_and_limit_orders(self):
        self.assertEqual(format_bybit_price(0.14123, 0.14123), "0.14123")
        self.assertEqual(format_bybit_price(0.9234, 0.9234), "0.9234")
        self.assertEqual(format_bybit_price(89500.50, 89500.50), "89500.5")
        self.assertEqual(format_bybit_qty(1500.0 / 0.14123, "DOGEUSDT"), "10621")

        # Mock BybitExecutionService Limit/PostOnly order su DOGEUSDT
        svc = BybitExecutionService.__new__(BybitExecutionService)
        svc.session = MagicMock()
        svc.get_realtime_tickers = MagicMock(return_value={"DOGEUSDT": {"last_price": 0.14123}})
        svc.session.place_order.return_value = {"retCode": 0, "result": {"orderId": "ord_doge_1"}}

        res = svc.place_order(
            symbol="DOGEUSDT",
            side="Buy",
            notional_usd=500.0,
            take_profit_pct=3.0,
            stop_loss_pct=1.0,
            order_type="Limit",
            limit_price=0.14100,
            post_only=True,
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["order_type"], "Limit")
        kwargs = svc.session.place_order.call_args.kwargs
        self.assertEqual(kwargs["orderType"], "Limit")
        self.assertEqual(kwargs["timeInForce"], "PostOnly")
        self.assertEqual(kwargs["price"], "0.14100")
        self.assertEqual(kwargs["takeProfit"], "0.14523")
        self.assertEqual(kwargs["stopLoss"], "0.13959")

        # Mock AlpacaExecutionService Limit bracket order
        alp = AlpacaExecutionService.__new__(AlpacaExecutionService)
        alp._api_request = MagicMock(return_value={"id": "alp_1", "status": "accepted"})
        alp.place_bracket_order(
            symbol="AAPL",
            qty=10,
            side="buy",
            take_profit_price=210.55,
            stop_loss_price=198.12,
            order_type="limit",
            limit_price=201.346,
        )
        sent_payload = alp._api_request.call_args.kwargs["payload"]
        self.assertEqual(sent_payload["type"], "limit")
        self.assertEqual(sent_payload["limit_price"], 201.35)

    def test_evaluation_cycle_dashboard_summary_and_weekly_report(self):
        journal = TradeJournalService(self.db_path)
        ck = normalize_context_key("BYBIT", "LONG", "NEUTRAL", 1.1, 10)
        opened = datetime.now(ROME_TZ) - timedelta(hours=3)
        closed = opened + timedelta(minutes=45)

        tid = journal.record_entry(
            broker="BYBIT",
            symbol="BTCUSDT",
            side="LONG",
            entry_price=80000.0,
            notional_usd=2000.0,
            context={"atr_pct": 1.1, "sl_pct": 1.54},
            context_key=ck,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE trade_journal SET opened_at = ? WHERE trade_id = ?",
                (opened.isoformat(), tid),
            )
            conn.commit()
        journal.record_exit("BYBIT", "BTCUSDT", 81200.0, 27.6, 1.38, "TAKE_PROFIT", fees_usd=2.4)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE trade_journal SET closed_at = ? WHERE trade_id = ?",
                (closed.isoformat(), tid),
            )
            conn.commit()

        sh_id = journal.record_shadow_signal(
            broker="BYBIT",
            symbol="BTCUSDT",
            side="LONG",
            engine="INTRADAY_MOMENTUM",
            context_key=ck,
            reject_reason="COOLDOWN",
            signal_price=80000.0,
            sl_pct=1.0,
            tp_pct=2.0,
            features={"rsi": 61},
        )
        sh_old = (datetime.now(ROME_TZ) - timedelta(hours=2)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE signal_shadows SET created_at = ? WHERE shadow_id = ?",
                (sh_old, sh_id),
            )
            conn.commit()

        def fake_fetcher(broker, symbol, start_iso, end_iso):
            t0 = pd.Timestamp(opened.astimezone(ROME_TZ)).tz_convert("UTC")
            idx = pd.date_range(t0, periods=15, freq="15min")
            return pd.DataFrame(
                {
                    "high": [80200 + 200 * i for i in range(15)],
                    "low": [79800 + 50 * i for i in range(15)],
                    "close": [80100 + 150 * i for i in range(15)],
                },
                index=idx,
            )

        cycle_res = run_evaluation_cycle(self.db_path, fake_fetcher)
        self.assertEqual(cycle_res["trades_evaluated"], 1)
        self.assertEqual(cycle_res["shadows_evaluated"], 1)

        summary, md = build_weekly_learning_report(self.db_path)
        self.assertEqual(summary["real_stats"]["total"], 1)
        self.assertEqual(summary["shadow_stats"]["evaluated"], 1)
        self.assertIn("WEEKLY LEARNING AUDIT", md)
        self.assertIsNotNone(journal.get_latest_audit("WEEKLY_AUDIT"))

        dash = get_learning_dashboard_summary(self.db_path)
        self.assertIn("INTRADAY_MOMENTUM", dash["engines_breakdown"])


if __name__ == "__main__":
    unittest.main()
