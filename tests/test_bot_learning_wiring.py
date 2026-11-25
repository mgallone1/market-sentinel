import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import telegram_bot
from services.learning_engine_service import compute_atr_ratchet_levels


class TestBotLearningWiring(unittest.TestCase):
    def test_concurrent_cap_uses_risk_config(self):
        self.assertGreaterEqual(telegram_bot._RISK_CFG.max_concurrent_trades, 6)

    def test_log_shadow_rejection_calls_journal(self):
        with patch.object(telegram_bot.trade_journal_svc, "record_shadow_signal", return_value=42) as mock_rec:
            telegram_bot._log_shadow_rejection(
                broker="BYBIT",
                symbol="BTCUSDT",
                side="LONG",
                engine="TREND_PULLBACK",
                macro_bias="BULLISH",
                atr_pct=1.4,
                rome_hour=15,
                reject_reason="CHOP_ADX_LOW",
                signal_price=95000.0,
                sl_pct=1.5,
                tp_pct=3.0,
                features={"adx": 14.0},
            )
            mock_rec.assert_called_once()
            kwargs = mock_rec.call_args.kwargs
            self.assertEqual(kwargs["broker"], "BYBIT")
            self.assertEqual(kwargs["symbol"], "BTCUSDT")
            self.assertEqual(kwargs["reject_reason"], "CHOP_ADX_LOW")
            self.assertIn("BYBIT|LONG|", kwargs["context_key"])
            self.assertIn("TREND_PULLBACK", kwargs["context_key"])

    def test_apply_context_allocation_blocks_and_scales(self):
        with patch.object(
            telegram_bot.learning_engine,
            "compute_context_allocation",
            return_value={"mode": "SHADOW", "scale": 0.0},
        ):
            allowed, notional, alloc = telegram_bot._apply_context_allocation("CTX", 100.0, 500.0, 15.0)
            self.assertFalse(allowed)
            self.assertEqual(notional, 0.0)
            self.assertEqual(alloc["mode"], "SHADOW")

        with patch.object(
            telegram_bot.learning_engine,
            "compute_context_allocation",
            return_value={"mode": "BOOSTED", "scale": 1.25},
        ):
            allowed, notional, alloc = telegram_bot._apply_context_allocation("CTX", 100.0, 500.0, 15.0, gate_scale=1.0)
            self.assertTrue(allowed)
            self.assertAlmostEqual(notional, 125.0)

    def test_dynamic_atr_ratchet_be_floor_and_no_phantom_alert_on_error(self):
        levels = compute_atr_ratchet_levels(side="LONG", entry_price=100.0, atr_pct=0.5)
        self.assertGreaterEqual(levels["be_lock_pct"], 0.25)

        stage_map = {}
        notifications = []
        mock_update_sl = MagicMock(return_value={"error": "exchange_rejected"})
        mock_close = MagicMock(return_value={"error": "close_rejected"})

        closed = telegram_bot._apply_dynamic_ratchet_and_exits(
            broker="ALPACA",
            symbol="AAPL",
            side_norm="LONG",
            entry_price=200.0,
            current_price=205.0,
            current_sl=195.0,
            pnl_pct=2.5,
            unrealized_usd=25.0,
            notional_usd=1000.0,
            atr_pct=1.0,
            macro_bias="BULLISH",
            stage_map=stage_map,
            update_sl_fn=mock_update_sl,
            close_fn=mock_close,
            bar_minutes=60,
            adaptive_params={},
            notification_events=notifications,
        )
        self.assertFalse(closed)
        self.assertEqual(notifications, [])
        self.assertEqual(stage_map.get("AAPL"), "INITIAL")

    def test_execution_services_support_limit_and_market_orders(self):
        import inspect
        from services.alpaca_execution_service import AlpacaExecutionService
        from services.bybit_execution_service import BybitExecutionService

        alpaca_sig = inspect.signature(AlpacaExecutionService.place_bracket_order)
        self.assertIn("order_type", alpaca_sig.parameters)
        self.assertIn("limit_price", alpaca_sig.parameters)

        bybit_sig = inspect.signature(BybitExecutionService.place_order)
        self.assertIn("order_type", bybit_sig.parameters)
        self.assertIn("limit_price", bybit_sig.parameters)
        self.assertIn("post_only", bybit_sig.parameters)

    def test_timemachine_precheck_logs_shadow_rejection_when_blocked(self):
        import pandas as pd
        idx = pd.date_range("2026-01-01 00:00", periods=50, freq="15min", tz="UTC")
        closes = [100.0 * (0.993 ** i) for i in range(50)]
        df_bear = pd.DataFrame(
            {
                "Open": closes,
                "High": [c + 0.2 for c in closes],
                "Low": [c - 0.2 for c in closes],
                "Close": closes,
                "Volume": [1000.0] * 50,
            },
            index=idx,
        )
        with patch.object(telegram_bot.trade_journal_svc, "record_shadow_signal", return_value=77) as mock_rec:
            ok, res = telegram_bot._timemachine_precheck_or_reject(
                broker="BYBIT",
                symbol="BTCUSDT",
                df_bars=df_bear,
                side="LONG",
                engine="INTRADAY_MOMENTUM",
                macro_bias="NEUTRAL",
                atr_pct=1.0,
                rome_hour=15,
                signal_price=75.0,
                sl_pct=1.0,
                tp_pct=2.5,
                features={"rsi": 50.0},
                context_key="BYBIT|LONG|NEUTRAL|MED|EU|INTRADAY_MOMENTUM",
                fee_rt_pct=0.12,
                interval_minutes=15,
            )
            self.assertFalse(ok)
            self.assertIn(res["reason"], ("TIMEMACHINE_NEG_EXPECTANCY", "TIMEMACHINE_LOW_WIN_PROB"))
            mock_rec.assert_called_once()


if __name__ == "__main__":
    unittest.main()
