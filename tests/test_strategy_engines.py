"""Unit tests for Wave 1 Core Foundations B: strategy engines, regime router & causal shadow evaluator."""
import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.strategy_engines_service import (
    ENGINE_INTRADAY_MOMENTUM,
    ENGINE_LIQUIDITY_SWEEP,
    ENGINE_ORB_BREAKOUT,
    ENGINE_TREND_PULLBACK,
    compute_adx,
    compute_spread_bps,
    engine_intraday_momentum,
    engine_liquidity_sweep_mr,
    engine_orb_breakout_15m,
    engine_trend_pullback_4h1d,
    evaluate_shadow_bars,
    evaluate_timemachine_gate,
    extract_normalized_features,
    prepare_closed_bars,
    regime_router,
    select_best_signal,
)


def _make_ohlcv(
    closes,
    spread_half=0.5,
    volumes=None,
    start="2026-01-01 00:00:00",
    freq="15min",
):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) + spread_half
    lows = np.minimum(opens, closes) - spread_half
    if volumes is None:
        volumes = np.full(n, 1000.0)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": np.asarray(volumes, dtype=float),
        },
        index=idx,
    )


def _make_chop_df(n=80, center=100.0, amplitude=0.6, freq="15min"):
    closes = np.array([center + (amplitude if i % 2 == 0 else -amplitude) for i in range(n)], dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = closes + 0.3
    lows = closes - 0.3
    idx = pd.date_range("2026-01-01 00:00:00", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": np.full(n, 1000.0),
        },
        index=idx,
    )


def _make_trending_pullback_1h():
    # Steady uptrend for 70 bars, then realistic pullback toward EMA20 while staying > EMA50,
    # cooling RSI into [42, 62] and ticking up on the final closed bar.
    up = np.linspace(100.0, 130.0, 70)
    pullback = np.array([129.0, 128.0, 127.0, 126.2, 125.5, 124.8, 124.3, 124.9])
    closes = np.concatenate([up, pullback])
    return _make_ohlcv(closes, spread_half=0.5, freq="1h")


def _make_trending_down_pullback_1h():
    down = np.linspace(130.0, 100.0, 70)
    bounce = np.array([101.0, 102.0, 103.0, 103.8, 104.5, 105.2, 105.7, 105.1])
    closes = np.concatenate([down, bounce])
    return _make_ohlcv(closes, spread_half=0.5, freq="1h")


class TestSharedUtilities(unittest.TestCase):
    def test_compute_adx_short_series_returns_fallback_20(self):
        df = _make_ohlcv([100.0 + i * 0.5 for i in range(15)])
        adx = compute_adx(df["High"], df["Low"], df["Close"], period=14)
        self.assertEqual(len(adx), 15)
        self.assertFalse(adx.isna().any())
        self.assertAlmostEqual(float(adx.iloc[-1]), 20.0, places=4)

    def test_compute_adx_distinguishes_trend_vs_chop(self):
        df_trend = _make_ohlcv(np.linspace(100.0, 150.0, 80), spread_half=0.35)
        adx_trend = compute_adx(df_trend["High"], df_trend["Low"], df_trend["Close"], period=14)
        self.assertFalse(adx_trend.isna().any())
        self.assertGreater(float(adx_trend.iloc[-1]), 25.0)

        df_chop = _make_chop_df(n=80)
        adx_chop = compute_adx(df_chop["High"], df_chop["Low"], df_chop["Close"], period=14)
        self.assertFalse(adx_chop.isna().any())
        self.assertLess(float(adx_chop.iloc[-1]), 16.0)

    def test_compute_spread_bps_valid_and_invalid(self):
        self.assertAlmostEqual(compute_spread_bps(100.0, 100.1), 9.995, places=3)
        self.assertEqual(compute_spread_bps(0.0, 100.0), 0.0)
        self.assertEqual(compute_spread_bps(101.0, 100.0), 0.0)
        self.assertEqual(compute_spread_bps(float("nan"), 100.0), 0.0)
        self.assertEqual(compute_spread_bps(100.0, float("inf")), 0.0)

    def test_extract_normalized_features_keys_and_no_lookahead(self):
        df = _make_ohlcv(np.linspace(100.0, 120.0, 80), spread_half=0.4, freq="1h")
        feats = extract_normalized_features(
            df,
            cvd_info={"ratio": 1.25},
            obi_info={"imbalance": 0.18},
            funding_rate=0.004,
            vix_val=17.5,
            spread_bps=4.2,
            macro_bias="BULLISH",
        )
        expected_keys = {
            "last_price",
            "rsi",
            "atr_pct",
            "adx",
            "dist_ema20_atr",
            "dist_ema50_atr",
            "dist_fld_atr",
            "vol_ratio",
            "cvd_ratio",
            "obi_imbalance",
            "funding_rate",
            "vix_val",
            "spread_bps",
            "tempo_battleplan",
            "macro_bias",
        }
        self.assertEqual(set(feats.keys()), expected_keys)
        self.assertAlmostEqual(feats["last_price"], 120.0, places=4)
        self.assertEqual(feats["macro_bias"], "BULLISH")
        self.assertEqual(feats["vix_val"], 17.5)
        for k, v in feats.items():
            if isinstance(v, float):
                self.assertTrue(math.isfinite(v), f"{k} not finite: {v}")

        # Verify causal invariance: appending future bars and stripping forming bar at cutoff leaves past features intact
        df_ext = pd.concat([df, _make_ohlcv([500.0], start="2026-01-04 08:00:00", freq="1h")])
        cutoff_now = df.index[-1] + timedelta(minutes=60)
        stripped = prepare_closed_bars(df_ext, interval_minutes=60, now=cutoff_now)
        self.assertEqual(len(stripped), len(df))


class TestRegimeRouter(unittest.TestCase):
    def test_regime_router_branches(self):
        r_trend = regime_router("BULLISH", adx_1h=28.0, atr_pct=1.1, funding_rate=0.005)
        self.assertEqual(r_trend["regime"], "TREND_STRONG")
        self.assertEqual(r_trend["allowed_engines"], [ENGINE_TREND_PULLBACK, ENGINE_INTRADAY_MOMENTUM])
        self.assertIsInstance(r_trend["prefer_limit"], bool)

        r_chop = regime_router("BULLISH", adx_1h=14.0, atr_pct=0.8, funding_rate=0.005)
        self.assertEqual(r_chop["regime"], "RANGE_OR_SQUEEZE")
        self.assertEqual(r_chop["allowed_engines"], [ENGINE_LIQUIDITY_SWEEP])
        self.assertTrue(r_chop["prefer_limit"])

        r_squeeze = regime_router("BULLISH", adx_1h=30.0, atr_pct=1.2, funding_rate=0.030)
        self.assertEqual(r_squeeze["regime"], "RANGE_OR_SQUEEZE")
        self.assertEqual(r_squeeze["allowed_engines"], [ENGINE_LIQUIDITY_SWEEP])
        self.assertTrue(r_squeeze["prefer_limit"])

        r_trans = regime_router("NEUTRAL", adx_1h=21.0, atr_pct=0.9, funding_rate=0.002)
        self.assertEqual(r_trans["regime"], "TRANSITION_NEUTRAL")
        self.assertEqual(
            r_trans["allowed_engines"],
            [ENGINE_TREND_PULLBACK, ENGINE_LIQUIDITY_SWEEP, ENGINE_INTRADAY_MOMENTUM],
        )


class TestTrendPullbackEngine(unittest.TestCase):
    def test_trend_pullback_4h_long_fires_with_limit_price(self):
        df_4h = _make_ohlcv(np.linspace(90.0, 130.0, 65), spread_half=0.8, freq="4h")
        df_1h = _make_trending_pullback_1h()
        cycle = {"vincolo_migliorino": "LIBERO", "tempo_battleplan": "2° Tempo su 4", "hurst_fld_value": 127.0}

        sig = engine_trend_pullback_4h1d(df_4h, df_1h, macro_bias="BULLISH", cycle_data=cycle, funding_rate=0.01)
        self.assertIsNotNone(sig)
        self.assertTrue(sig["triggered"])
        self.assertEqual(sig["side"], "LONG")
        self.assertEqual(sig["engine"], ENGINE_TREND_PULLBACK)
        self.assertEqual(sig["order_type"], "Limit")
        last_1h = float(df_1h["Close"].iloc[-1])
        self.assertLessEqual(sig["limit_price"], last_1h)
        self.assertGreaterEqual(sig["sl_pct"], 1.00)
        self.assertLessEqual(sig["sl_pct"], 2.40)
        self.assertAlmostEqual(sig["tp_pct"], round(sig["sl_pct"] * 3.0, 2), places=2)

    def test_trend_pullback_4h_short_and_cycle_block(self):
        df_4h_down = _make_ohlcv(np.linspace(140.0, 100.0, 65), spread_half=0.8, freq="4h")
        df_1h_down = _make_trending_down_pullback_1h()
        cycle_short = {"vincolo_migliorino": "LIBERO", "tempo_battleplan": "3° Tempo su 4", "hurst_fld_value": 103.0}

        sig = engine_trend_pullback_4h1d(df_4h_down, df_1h_down, macro_bias="BEARISH", cycle_data=cycle_short, funding_rate=-0.01)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["side"], "SHORT")
        self.assertEqual(sig["order_type"], "Limit")
        self.assertGreaterEqual(sig["limit_price"], float(df_1h_down["Close"].iloc[-1]))

        # Blocked when 1° Tempo forbids SHORT
        blocked = engine_trend_pullback_4h1d(
            df_4h_down,
            df_1h_down,
            macro_bias="BEARISH",
            cycle_data={"vincolo_migliorino": "LIBERO", "tempo_battleplan": "1° Tempo su 4", "hurst_fld_value": 103.0},
            funding_rate=-0.01,
        )
        self.assertIsNone(blocked)

        # LONG blocked by RIBASSISTA constraint
        df_4h_up = _make_ohlcv(np.linspace(90.0, 130.0, 65), spread_half=0.8, freq="4h")
        df_1h_up = _make_trending_pullback_1h()
        blocked_long = engine_trend_pullback_4h1d(
            df_4h_up,
            df_1h_up,
            macro_bias="BULLISH",
            cycle_data={"vincolo_migliorino": "⚠️ VINCOLO RIBASSISTA ATTIVO", "tempo_battleplan": "2° Tempo su 4", "hurst_fld_value": 127.0},
            funding_rate=0.0,
        )
        self.assertIsNone(blocked_long)


class TestLiquiditySweepEngine(unittest.TestCase):
    def test_liquidity_sweep_mr_long_fires_with_cvd_confirmation(self):
        # 25 ranging bars with swing low around 99.6, then sweep bar low=98.4 reclaiming close=100.3
        closes = [100.2 + (0.3 if i % 2 == 0 else -0.3) for i in range(25)]
        df = _make_ohlcv(closes, spread_half=0.3, freq="15min")
        sweep_idx = df.index[-1] + timedelta(minutes=15)
        sweep_bar = pd.DataFrame(
            {"Open": [100.1], "High": [100.5], "Low": [98.4], "Close": [100.3], "Volume": [2500.0]},
            index=[sweep_idx],
        )
        df = pd.concat([df, sweep_bar])

        sig = engine_liquidity_sweep_mr(
            df,
            cvd_info={"ratio": 1.35, "bias": "BULLISH"},
            obi_info={"imbalance": 0.05},
            funding_rate=0.0,
            macro_bias="NEUTRAL",
        )
        self.assertIsNotNone(sig)
        self.assertTrue(sig["triggered"])
        self.assertEqual(sig["side"], "LONG")
        self.assertEqual(sig["engine"], ENGINE_LIQUIDITY_SWEEP)
        self.assertEqual(sig["order_type"], "Limit")
        self.assertGreaterEqual(sig["sl_pct"], 0.75)
        self.assertLessEqual(sig["sl_pct"], 1.60)
        self.assertAlmostEqual(sig["tp_pct"], round(sig["sl_pct"] * 3.0, 2), places=2)

        # Without any microstructure extreme -> returns None
        no_confirm = engine_liquidity_sweep_mr(
            df,
            cvd_info={"ratio": 1.0, "bias": "NEUTRAL"},
            obi_info={"imbalance": 0.0},
            funding_rate=0.0,
            macro_bias="NEUTRAL",
        )
        self.assertIsNone(no_confirm)

    def test_liquidity_sweep_mr_short_symmetric(self):
        closes = [100.0 + (0.3 if i % 2 == 0 else -0.3) for i in range(25)]
        df = _make_ohlcv(closes, spread_half=0.3, freq="15min")
        sweep_idx = df.index[-1] + timedelta(minutes=15)
        sweep_bar = pd.DataFrame(
            {"Open": [100.1], "High": [101.8], "Low": [99.8], "Close": [100.0], "Volume": [2500.0]},
            index=[sweep_idx],
        )
        df = pd.concat([df, sweep_bar])

        sig = engine_liquidity_sweep_mr(
            df,
            cvd_info={"ratio": 0.85, "bias": "BEARISH"},
            obi_info={"imbalance": -0.30},
            funding_rate=0.03,
            macro_bias="NEUTRAL",
        )
        self.assertIsNotNone(sig)
        self.assertEqual(sig["side"], "SHORT")
        self.assertEqual(sig["order_type"], "Limit")


class TestIntradayMomentumEngine(unittest.TestCase):
    @staticmethod
    def _make_breakout_long_df():
        # Realistic uptrend establishing high ADX & EMA20 > EMA50, healthy pullback/consolidation, then breakout
        base = np.linspace(95.0, 116.5, 52) + np.sin(np.arange(52) * 0.8) * 1.1
        pullback = np.array([115.2, 113.8, 113.0, 112.9, 113.4, 113.9, 114.2, 114.1])
        consol = np.array([114.3, 114.2, 114.4, 114.3])
        breakout = np.array([115.1])
        closes = np.concatenate([base, pullback, consol, breakout])
        vols = np.concatenate([np.full(len(closes) - 1, 1000.0), [2200.0]])
        return _make_ohlcv(closes, spread_half=0.35, volumes=vols, freq="15min")

    def test_chop_low_adx_rejects_with_low_adx_chop(self):
        df_chop = _make_chop_df(n=70, center=100.0, amplitude=0.4)
        res = engine_intraday_momentum(
            df_chop,
            macro_bias="BULLISH",
            cycle_data={"tempo_battleplan": "1° Tempo", "hurst_fld_value": 99.0},
            cvd_info={"ratio": 1.3, "bias": "BULLISH"},
            obi_info={"imbalance": 0.2, "bias": "BALANCED"},
            funding_rate=0.0,
            vol_ratio=1.5,
            is_overnight=False,
            adx_min=16.0,
        )
        self.assertFalse(res["triggered"])
        self.assertEqual(res["engine"], ENGINE_INTRADAY_MOMENTUM)
        self.assertEqual(res["reject_reason"], "LOW_ADX_CHOP")
        self.assertIn("adx", res["features"])
        self.assertLess(res["features"]["adx"], 16.0)

    def test_intraday_momentum_triggers_and_shields_populate_shadow_reasons(self):
        df_bo = self._make_breakout_long_df()
        cycle_ok = {"tempo_battleplan": "1° Tempo su 4", "vincolo_migliorino": "LIBERO", "hurst_fld_value": 117.0}

        ok = engine_intraday_momentum(
            df_bo,
            macro_bias="BULLISH",
            cycle_data=cycle_ok,
            cvd_info={"ratio": 1.35, "bias": "BULLISH"},
            obi_info={"imbalance": 0.15, "bias": "BALANCED"},
            funding_rate=0.005,
            vol_ratio=1.8,
            is_overnight=False,
        )
        self.assertTrue(ok["triggered"])
        self.assertEqual(ok["side"], "LONG")
        self.assertEqual(ok["order_type"], "Market")
        self.assertIsNone(ok["limit_price"])
        self.assertEqual(ok["reject_reason"], "")
        self.assertGreater(ok["score"], 0.0)

        # VIX Shield
        vix_blk = engine_intraday_momentum(
            df_bo, "BULLISH", cycle_ok, {"ratio": 1.35}, {"imbalance": 0.1}, 0.005, 1.8, False,
            is_equities=True, vix_unfavorable=True,
        )
        self.assertFalse(vix_blk["triggered"])
        self.assertEqual(vix_blk["side"], "LONG")
        self.assertEqual(vix_blk["reject_reason"], "VIX_SHIELD")

        # Overnight volume shield
        vol_blk = engine_intraday_momentum(
            df_bo, "BULLISH", cycle_ok, {"ratio": 1.35}, {"imbalance": 0.1}, 0.005, 1.4, True,
        )
        self.assertFalse(vol_blk["triggered"])
        self.assertEqual(vol_blk["reject_reason"], "LOW_VOLUME_OVERNIGHT")

        # CVD Shield
        cvd_blk = engine_intraday_momentum(
            df_bo, "BULLISH", cycle_ok, {"ratio": 0.65, "bias": "BEARISH"}, {"imbalance": 0.1}, 0.005, 1.8, False,
        )
        self.assertFalse(cvd_blk["triggered"])
        self.assertEqual(cvd_blk["reject_reason"], "CVD_SHIELD")

        # Funding Squeeze Shield
        fund_blk = engine_intraday_momentum(
            df_bo, "BULLISH", cycle_ok, {"ratio": 1.35}, {"imbalance": 0.1}, 0.045, 1.8, False,
        )
        self.assertFalse(fund_blk["triggered"])
        self.assertEqual(fund_blk["reject_reason"], "FUNDING_SQUEEZE")

        # OBI Wall Shield
        obi_blk = engine_intraday_momentum(
            df_bo, "BULLISH", cycle_ok, {"ratio": 1.35}, {"imbalance": -0.50, "bias": "SELL_WALL"}, 0.005, 1.8, False,
        )
        self.assertFalse(obi_blk["triggered"])
        self.assertEqual(obi_blk["reject_reason"], "OBI_WALL")

        # Strict AND cycle conflict under NEUTRAL macro bias when price <= FLD
        cyc_blk = engine_intraday_momentum(
            df_bo,
            "NEUTRAL",
            {"tempo_battleplan": "1° Tempo su 4", "vincolo_migliorino": "LIBERO", "hurst_fld_value": 125.0},
            {"ratio": 1.35},
            {"imbalance": 0.1},
            0.005,
            1.8,
            False,
        )
        self.assertFalse(cyc_blk["triggered"])
        self.assertEqual(cyc_blk["reject_reason"], "CYCLE_CONFLICT")


class TestSelectorAndShadowEvaluator(unittest.TestCase):
    def test_select_best_signal(self):
        cands = [
            None,
            {"triggered": False, "side": "LONG", "score": 99.0, "engine": "X"},
            {"triggered": True, "side": "LONG", "score": 72.5, "engine": ENGINE_INTRADAY_MOMENTUM},
            {"triggered": True, "side": "LONG", "score": 86.0, "engine": ENGINE_TREND_PULLBACK},
        ]
        best = select_best_signal(cands)
        self.assertIsNotNone(best)
        self.assertEqual(best["engine"], ENGINE_TREND_PULLBACK)
        self.assertEqual(best["score"], 86.0)
        self.assertIsNone(select_best_signal([None, {"triggered": False, "side": "LONG", "score": 90.0}]))

    def test_evaluate_shadow_bars_ambiguous_bar_sl_wins_over_tp_and_fees_deducted(self):
        # Signal LONG @ 100.0, SL=1.0% (99.0), TP=3.0% (103.0)
        # Bar 1 covers [98.5, 104.0] -> BOTH SL and TP lie inside Low..High; SL MUST trigger first!
        future = pd.DataFrame(
            {
                "Open": [100.0, 102.0],
                "High": [104.0, 105.0],
                "Low": [98.5, 101.0],
                "Close": [103.5, 104.5],
                "Volume": [1000.0, 1000.0],
            },
            index=pd.date_range("2026-01-01 01:00", periods=2, freq="15min", tz="UTC"),
        )
        res = evaluate_shadow_bars("LONG", 100.0, sl_pct=1.0, tp_pct=3.0, future_ohlcv_df=future, fee_rt_pct=0.12)
        self.assertEqual(res["status"], "EVALUATED")
        self.assertEqual(res["hit_outcome"], "SL")
        self.assertEqual(res["bars_held"], 1)
        self.assertAlmostEqual(res["virtual_pnl_pct"], -1.12, places=4)
        self.assertAlmostEqual(res["virtual_r"], -1.12, places=3)
        self.assertAlmostEqual(res["mfe_pct"], 4.0, places=4)
        self.assertAlmostEqual(res["mae_pct"], -1.5, places=4)

        # Short ambiguous bar: SL=101.0, TP=97.0 both inside [96.5, 101.5]
        future_short = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [101.5],
                "Low": [96.5],
                "Close": [97.0],
                "Volume": [1000.0],
            },
            index=pd.date_range("2026-01-01 01:00", periods=1, freq="15min", tz="UTC"),
        )
        res_s = evaluate_shadow_bars("SHORT", 100.0, sl_pct=1.0, tp_pct=3.0, future_ohlcv_df=future_short, fee_rt_pct=0.12)
        self.assertEqual(res_s["hit_outcome"], "SL")
        self.assertAlmostEqual(res_s["virtual_pnl_pct"], -1.12, places=4)

    def test_evaluate_shadow_bars_tp_time_exit_and_insufficient(self):
        # Clean TP on bar 2
        future_tp = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [101.5, 103.5, 90.0],
                "Low": [99.6, 100.5, 89.0],
                "Close": [101.0, 103.2, 89.5],
                "Volume": [1000.0, 1000.0, 1000.0],
            },
            index=pd.date_range("2026-01-01 01:00", periods=3, freq="15min", tz="UTC"),
        )
        res_tp = evaluate_shadow_bars("LONG", 100.0, sl_pct=1.0, tp_pct=3.0, future_ohlcv_df=future_tp, fee_rt_pct=0.12)
        self.assertEqual(res_tp["status"], "EVALUATED")
        self.assertEqual(res_tp["hit_outcome"], "TP")
        self.assertEqual(res_tp["bars_held"], 2)
        self.assertAlmostEqual(res_tp["virtual_pnl_pct"], 2.88, places=4)
        self.assertAlmostEqual(res_tp["virtual_r"], 2.88, places=3)

        # Insufficient (< 6 bars without SL/TP)
        future_short_horizon = _make_ohlcv([100.2, 100.4, 100.3], spread_half=0.2, freq="15min")
        res_ins = evaluate_shadow_bars("LONG", 100.0, sl_pct=1.5, tp_pct=4.5, future_ohlcv_df=future_short_horizon, fee_rt_pct=0.12)
        self.assertEqual(res_ins["status"], "INSUFFICIENT")
        self.assertEqual(res_ins["bars_held"], 3)

        # TIME_EXIT after >= 6 closed bars without SL/TP
        future_time = _make_ohlcv([100.2, 100.5, 100.4, 100.8, 100.6, 101.0], spread_half=0.2, freq="15min")
        res_te = evaluate_shadow_bars("LONG", 100.0, sl_pct=1.5, tp_pct=4.5, future_ohlcv_df=future_time, fee_rt_pct=0.12)
        self.assertEqual(res_te["status"], "EVALUATED")
        self.assertEqual(res_te["hit_outcome"], "TIME_EXIT")
        self.assertEqual(res_te["bars_held"], 6)
        self.assertAlmostEqual(res_te["virtual_pnl_pct"], 1.0 - 0.12, places=4)

    def test_forming_bar_excluded_prevents_lookahead(self):
        # Choppy baseline bars followed by an unclosed forming breakout spike bar at 00:00 (not closed until 00:15)
        df_base = _make_chop_df(n=60, center=100.0, amplitude=0.3, freq="15min")
        forming_ts = df_base.index[-1] + timedelta(minutes=15)
        forming_spike = pd.DataFrame(
            {"Open": [100.0], "High": [115.0], "Low": [100.0], "Close": [114.0], "Volume": [9000.0]},
            index=[forming_ts],
        )
        df_with_forming = pd.concat([df_base, forming_spike])
        # At forming_ts + 5min, the spike bar is still forming -> must be dropped before evaluation
        now_mid_bar = forming_ts + timedelta(minutes=5)
        res = engine_intraday_momentum(
            df_with_forming,
            macro_bias="BULLISH",
            cycle_data={"tempo_battleplan": "1° Tempo su 4", "hurst_fld_value": 95.0},
            cvd_info={"ratio": 1.4},
            obi_info={"imbalance": 0.2},
            funding_rate=0.0,
            vol_ratio=2.0,
            is_overnight=False,
            interval_minutes=15,
            now=now_mid_bar,
        )
        self.assertFalse(res["triggered"])
        self.assertLess(res["features"]["last_price"], 101.0)


class TestOrbBreakoutAndTimeMachine(unittest.TestCase):
    def _make_ny_5m_session(self, close_prices, volumes=None, end_hour=10, end_minute=0):
        idx = pd.date_range(
            "2026-10-19 09:30",
            periods=len(close_prices),
            freq="5min",
            tz="America/New_York",
        )
        vols = volumes if volumes is not None else [1000.0] * len(close_prices)
        opens = [close_prices[0]] + list(close_prices[:-1])
        highs = [max(o, c) + 0.35 for o, c in zip(opens, close_prices)]
        lows = [min(o, c) - 0.35 for o, c in zip(opens, close_prices)]
        return pd.DataFrame(
            {"Open": opens, "High": highs, "Low": lows, "Close": close_prices, "Volume": vols},
            index=idx,
        )

    def test_regime_router_includes_orb_only_for_equities(self):
        r_crypto = regime_router("BULLISH", adx_1h=28.0, atr_pct=1.1, is_equities=False)
        self.assertNotIn(ENGINE_ORB_BREAKOUT, r_crypto["allowed_engines"])
        r_eq = regime_router("BULLISH", adx_1h=28.0, atr_pct=1.1, is_equities=True)
        self.assertIn(ENGINE_ORB_BREAKOUT, r_eq["allowed_engines"])

    def test_orb_breakout_triggers_long_and_blocks_vix_and_low_vol(self):
        # 3 OR bars (09:30, 09:35, 09:40) around 100.0 (OR high ~100.85), followed by consolidation then breakout
        closes = [100.0, 100.2, 100.1, 100.3, 100.4, 101.3]
        vols = [1000.0, 1000.0, 1000.0, 900.0, 950.0, 1800.0]
        df_5m = self._make_ny_5m_session(closes, volumes=vols)
        now_after = df_5m.index[-1] + timedelta(minutes=6)

        res = engine_orb_breakout_15m(
            df_5m,
            macro_bias="BULLISH",
            cycle_data={"tempo_battleplan": "1° Tempo su 4", "hurst_fld_value": 99.0},
            vix_unfavorable=False,
            interval_minutes=5,
            now=now_after,
        )
        self.assertTrue(res["triggered"])
        self.assertEqual(res["side"], "LONG")
        self.assertEqual(res["engine"], ENGINE_ORB_BREAKOUT)
        self.assertGreaterEqual(res["score"], 62.0)

        vix_blk = engine_orb_breakout_15m(
            df_5m, macro_bias="BULLISH", vix_unfavorable=True, interval_minutes=5, now=now_after
        )
        self.assertFalse(vix_blk["triggered"])
        self.assertEqual(vix_blk["reject_reason"], "VIX_SHIELD")

        vols_low = [1000.0, 1000.0, 1000.0, 900.0, 950.0, 400.0]
        df_low = self._make_ny_5m_session(closes, volumes=vols_low)
        vol_blk = engine_orb_breakout_15m(
            df_low, macro_bias="BULLISH", vix_unfavorable=False, interval_minutes=5, now=now_after
        )
        self.assertFalse(vol_blk["triggered"])
        self.assertEqual(vol_blk["reject_reason"], "LOW_VOLUME")

    def test_timemachine_gate_passes_favorable_blocks_unfavorable_and_insufficient(self):
        # Favorable bullish drift -> LONG passes
        bull_closes = [100.0 * (1.0035 ** i) for i in range(60)]
        df_bull = _make_ohlcv(bull_closes, spread_half=0.25, freq="15min")
        ok = evaluate_timemachine_gate(df_bull, side="LONG", sl_pct=1.0, tp_pct=2.0, n_replays=400, interval_minutes=15)
        self.assertTrue(ok["passed"])
        self.assertGreater(ok["expected_r"], 0.0)

        # Strong bearish drift -> LONG blocked by Time Machine
        bear_closes = [100.0 * (0.994 ** i) for i in range(60)]
        df_bear = _make_ohlcv(bear_closes, spread_half=0.25, freq="15min")
        blk = evaluate_timemachine_gate(df_bear, side="LONG", sl_pct=1.0, tp_pct=2.0, n_replays=400, interval_minutes=15)
        self.assertFalse(blk["passed"])
        self.assertIn(blk["reason"], ("TIMEMACHINE_NEG_EXPECTANCY", "TIMEMACHINE_LOW_WIN_PROB"))

        # Short history -> graceful pass
        df_short = _make_ohlcv([100.0, 100.5, 101.0], spread_half=0.2, freq="15min")
        ins = evaluate_timemachine_gate(df_short, side="LONG", sl_pct=1.0, tp_pct=2.0, interval_minutes=15)
        self.assertTrue(ins["passed"])
        self.assertEqual(ins["reason"], "INSUFFICIENT_HISTORY")

    def test_intraday_momentum_blocks_overextended_chase(self):
        # Strong late ramp so RSI > 68 and price is stretched > 2.2 ATR above EMA20
        closes = [100.0 + (i * 0.2 if i < 24 else (i - 23) * 3.5) for i in range(32)]
        df = _make_ohlcv(closes, spread_half=0.3, freq="15min")
        res = engine_intraday_momentum(
            df,
            macro_bias="BULLISH",
            cycle_data={"tempo_battleplan": "1° TEMPO", "vincolo_migliorino": "LIBERO", "hurst_fld_value": 90.0},
            cvd_info={"bias": "BULLISH", "ratio": 1.3},
            obi_info={"bias": "BALANCED", "imbalance": 0.1},
            funding_rate=0.0,
            vol_ratio=1.5,
            is_overnight=False,
            adx_min=10.0,
            interval_minutes=15,
        )
        self.assertFalse(res["triggered"])
        self.assertEqual(res["reject_reason"], "OVEREXTENDED_CHASE")
        self.assertEqual(res["side"], "LONG")


if __name__ == "__main__":
    unittest.main(verbosity=2)
