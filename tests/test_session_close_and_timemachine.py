"""Regression tests for the 2026-11-26 fixes:

1. NYSE session clock (New York time, early closes, US/EU DST mismatch) and forced flatten.
2. Late-session entry gate (no weak entries close to the forced flatten).
3. Time Machine gate without the resolved-win-rate bias, horizon capped at the flatten,
   same-rule historical replay on real paths, shadow evaluation bounded to the session.
"""
import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import market_calendar as mc
from services.strategy_engines_service import (
    ENGINE_ORB_BREAKOUT,
    engine_orb_breakout_15m,
    evaluate_timemachine_gate,
    late_session_entry_check,
    replay_signal_history,
)


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _random_walk(n, mu_bp, sigma_bp, seed, freq="15min", start="2026-01-01"):
    rng = np.random.default_rng(seed)
    ret = rng.normal(mu_bp / 1e4, sigma_bp / 1e4, n)
    close = 100.0 * np.exp(np.cumsum(ret))
    open_ = np.r_[100.0, close[:-1]]
    ext = np.abs(rng.normal(0.0, sigma_bp / 1e4 * 0.6, (n, 2)))
    high = np.maximum(open_, close) * (1.0 + ext[:, 0])
    low = np.minimum(open_, close) * (1.0 - ext[:, 1])
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": 1000.0}, index=idx)


def _ny_5m(day, closes, volumes=None, start="09:30"):
    idx = pd.date_range(f"{day} {start}", periods=len(closes), freq="5min", tz="America/New_York")
    opens = [closes[0]] + list(closes[:-1])
    return pd.DataFrame(
        {
            "Open": opens,
            "High": [max(o, c) + 0.05 for o, c in zip(opens, closes)],
            "Low": [min(o, c) - 0.05 for o, c in zip(opens, closes)],
            "Close": closes,
            "Volume": volumes if volumes is not None else [1000.0] * len(closes),
        },
        index=idx,
    )


class TestMarketCalendar(unittest.TestCase):
    def test_regular_day_minutes_to_close(self):
        # 2026-11-25 is EST (UTC-5): 20:00 UTC = 15:00 ET
        st = mc.session_status(_utc(2026, 11, 25, 20, 0))
        self.assertTrue(st["is_open"])
        self.assertAlmostEqual(st["minutes_to_close"], 60.0)
        self.assertFalse(mc.should_flatten_now(_utc(2026, 11, 25, 20, 0), lead_minutes=8))
        self.assertTrue(mc.should_flatten_now(_utc(2026, 11, 25, 20, 53), lead_minutes=8))

    def test_early_close_black_friday_2026(self):
        # 2026-11-27 closes at 13:00 ET = 18:00 UTC
        st = mc.session_status(_utc(2026, 11, 27, 17, 55))
        self.assertTrue(st["is_open"])
        self.assertEqual(st["early_close"], "day after Thanksgiving")
        self.assertAlmostEqual(st["minutes_to_close"], 5.0)
        self.assertTrue(mc.should_flatten_now(_utc(2026, 11, 27, 17, 55), lead_minutes=8))
        # The old 21:55 Rome rule (= 20:55 UTC) is three hours after this close
        self.assertFalse(mc.session_status(_utc(2026, 11, 27, 20, 55))["is_open"])

    def test_holiday_and_weekend_closed(self):
        self.assertFalse(mc.session_status(_utc(2026, 11, 26, 16, 0))["is_open"])  # Thanksgiving
        self.assertFalse(mc.session_status(_utc(2026, 11, 28, 16, 0))["is_open"])  # Saturday

    def test_us_eu_dst_mismatch_week(self):
        # 2026-03-16: New York already on EDT (UTC-4), Rome still on CET (UTC+1) -> 5h apart.
        # Close 16:00 EDT = 20:00 UTC; the old 21:55 Rome trigger = 20:55 UTC, i.e. after the close.
        self.assertFalse(mc.session_status(_utc(2026, 3, 16, 20, 55))["is_open"])
        self.assertTrue(mc.should_flatten_now(_utc(2026, 3, 16, 19, 55), lead_minutes=8))

    def test_broker_clock_overrides_calendar(self):
        clock = {"is_open": True, "next_close": "2026-11-25T13:00:00-05:00"}  # unscheduled early close
        st = mc.session_status(_utc(2026, 11, 25, 17, 55), clock)
        self.assertEqual(st["source"], "broker_clock")
        self.assertAlmostEqual(st["minutes_to_close"], 5.0)


class TestAutoFlattenJob(unittest.TestCase):
    def _run(self, now_utc):
        import telegram_bot

        alp = MagicMock()
        alp.get_account_summary.return_value = {
            "positions": [
                {"symbol": "NVDA", "asset_class": "us_equity"},
                {"symbol": "BTCUSD", "asset_class": "crypto"},
            ]
        }
        app = MagicMock()
        with patch.object(telegram_bot, "alpaca_service", alp), patch.object(
            telegram_bot, "get_target_chat_ids", return_value=[]
        ):
            asyncio.run(telegram_bot.auto_flatten_overnight_job(app, now=now_utc, clock={"is_open": False}))
        return alp

    def test_flattens_equities_before_early_close_only(self):
        alp = self._run(_utc(2026, 11, 27, 17, 54))  # 12:54 ET, close 13:00
        alp.close_position.assert_called_once_with("NVDA")

    def test_does_nothing_far_from_close(self):
        alp = self._run(_utc(2026, 11, 25, 17, 54))  # 12:54 ET on a regular 16:00 day
        alp.close_position.assert_not_called()
        alp.get_account_summary.assert_not_called()

    def test_scheduler_uses_new_york_clock(self):
        import inspect
        import telegram_bot

        src = inspect.getsource(telegram_bot)
        self.assertIn('hour="12,15", minute="50-59", timezone="America/New_York"', src)
        self.assertNotIn("CronTrigger(hour=21, minute=55", src)


class TestLateSessionGate(unittest.TestCase):
    GOOD_TM = {"replays": 1200, "p_tp_first": 0.40, "expected_r": 0.12}

    def test_no_limit_without_session(self):
        self.assertTrue(late_session_entry_check(None, 10.0, None)["allowed"])

    def test_normal_zone(self):
        res = late_session_entry_check(120.0, 60.0, {"replays": 0})
        self.assertTrue(res["allowed"])
        self.assertEqual(res["zone"], "NORMAL")

    def test_no_entry_in_last_30_minutes_even_if_strong(self):
        res = late_session_entry_check(25.0, 99.0, self.GOOD_TM)
        self.assertFalse(res["allowed"])
        self.assertEqual(res["reason"], "LATE_SESSION_NO_TIME")

    def test_late_zone_requires_strong_evidence(self):
        self.assertTrue(late_session_entry_check(60.0, 80.0, self.GOOD_TM)["allowed"])
        self.assertEqual(late_session_entry_check(60.0, 70.0, self.GOOD_TM)["reason"], "LATE_SESSION_WEAK_SETUP")
        self.assertEqual(late_session_entry_check(60.0, 80.0, {"replays": 0})["reason"], "LATE_SESSION_NO_EVIDENCE")
        self.assertEqual(
            late_session_entry_check(60.0, 80.0, {**self.GOOD_TM, "p_tp_first": 0.05})["reason"],
            "LATE_SESSION_TP_UNREACHABLE",
        )
        self.assertEqual(
            late_session_entry_check(60.0, 80.0, {**self.GOOD_TM, "expected_r": -0.1})["reason"],
            "LATE_SESSION_NEG_EXPECTANCY",
        )


class TestTimeMachineRevision(unittest.TestCase):
    def test_driftless_market_is_not_vetoed_for_asymmetric_plan(self):
        # Regression for the resolved-win-rate bias: SL 1.2% / TP 3.6% on a driftless walk was
        # blocked ~97% of the time by the old gate.
        passed = [
            evaluate_timemachine_gate(_random_walk(520, 0.0, 35.0, s), "LONG", 1.2, 3.6, fee_rt_pct=0.12)["passed"]
            for s in range(30)
        ]
        self.assertGreaterEqual(np.mean(passed), 0.75)

    def test_significant_adverse_drift_is_vetoed_both_sides(self):
        long_blk = [
            evaluate_timemachine_gate(_random_walk(520, -4.0, 35.0, s), "LONG", 1.2, 3.6)["passed"] for s in range(20)
        ]
        short_blk = [
            evaluate_timemachine_gate(_random_walk(520, 4.0, 35.0, s), "SHORT", 1.2, 3.6)["passed"] for s in range(20)
        ]
        self.assertLessEqual(np.mean(long_blk), 0.2)
        self.assertLessEqual(np.mean(short_blk), 0.2)

    def test_expected_r_counts_open_paths_and_reports_gross(self):
        res = evaluate_timemachine_gate(_random_walk(520, 0.0, 35.0, 3), "LONG", 1.2, 3.6, fee_rt_pct=0.12)
        self.assertAlmostEqual(res["expected_r_gross"] - res["expected_r"], 0.12 / 1.2, places=2)
        self.assertAlmostEqual(res["p_tp_first"] + res["p_sl_first"] + res["p_neither"], 1.0, places=3)

    def test_horizon_capped_at_flatten(self):
        res = evaluate_timemachine_gate(
            _random_walk(400, 0.0, 12.0, 1, freq="5min"), "LONG", 0.8, 2.0, horizon_bars=36, max_horizon_bars=6
        )
        self.assertEqual(res["horizon_bars"], 6)
        res_long = evaluate_timemachine_gate(_random_walk(400, 0.0, 12.0, 1, freq="5min"), "LONG", 0.8, 2.0, horizon_bars=36)
        self.assertLess(res["p_tp_first"], res_long["p_tp_first"] + 1e-9)

    def test_session_gaps_excluded_from_pool(self):
        df = pd.concat(
            [
                _random_walk(78, 0.0, 10.0, 1, freq="5min", start="2026-11-23 14:30"),
                _random_walk(78, 0.0, 10.0, 2, freq="5min", start="2026-11-24 14:30"),
            ]
        )
        res = evaluate_timemachine_gate(df, "LONG", 0.8, 2.0, interval_minutes=5, now=_utc(2026, 11, 25))
        self.assertEqual(res["gaps_skipped"], 1)


class TestSameRuleReplay(unittest.TestCase):
    def test_orb_replay_is_session_bound(self):
        # Day 1: OR 100.0-100.25, breakout at 09:45 with volume, then drift up but no TP
        day1 = [100.0, 100.1, 100.2, 100.6] + [100.6 + 0.01 * i for i in range(74)]
        vol1 = [1000.0, 1000.0, 1000.0, 2000.0] + [1000.0] * 74
        # Day 2: gap up far above the TP: must not be credited to day 1's trade
        day2 = [120.0] * 10
        df = pd.concat([_ny_5m("2026-11-23", day1, vol1), _ny_5m("2026-11-24", day2)])
        res = replay_signal_history(
            df, ENGINE_ORB_BREAKOUT, "LONG", sl_pct=0.8, tp_pct=2.0, fee_rt_pct=0.05,
            max_bars=200, interval_minutes=5, session_bound=True, now=_utc(2026, 11, 25),
        )
        self.assertEqual(res["n"], 1)
        self.assertEqual(res["tp_rate"], 0.0)
        self.assertLess(res["mean_r"], 2.0 / 0.8)

    def test_unknown_engine_has_no_replay(self):
        res = replay_signal_history(_random_walk(100, 0, 10, 1), "TREND_PULLBACK_4H", "LONG", 1.0, 2.0)
        self.assertEqual(res["n"], 0)
        self.assertEqual(res.get("note"), "NO_REPLAY_RULE")


class TestOrbSessionWindow(unittest.TestCase):
    def test_early_close_window_ends_30_minutes_before_13(self):
        # 2026-11-27 closes at 13:00 ET: a breakout bar completing at 12:45 is outside the window
        closes = [100.0, 100.1, 100.2] + [100.2] * 32 + [101.0]
        vols = [1000.0] * 35 + [3000.0]
        df = _ny_5m("2026-11-27", closes, vols)  # last bar 12:25 + 5 = 12:30
        now = df.index[-1] + timedelta(minutes=6)
        res = engine_orb_breakout_15m(df, "BULLISH", cycle_data={"tempo_battleplan": "1° TEMPO"}, interval_minutes=5, now=now)
        self.assertNotEqual(res["reject_reason"], "OUTSIDE_ORB_WINDOW")
        df_late = _ny_5m("2026-11-27", closes + [101.1], vols + [3000.0])  # completes 12:35
        res_late = engine_orb_breakout_15m(
            df_late, "BULLISH", cycle_data={"tempo_battleplan": "1° TEMPO"}, interval_minutes=5,
            now=df_late.index[-1] + timedelta(minutes=6),
        )
        self.assertEqual(res_late["reject_reason"], "OUTSIDE_ORB_WINDOW")

    def test_missing_opening_bars_rejected(self):
        df = _ny_5m("2026-11-25", [100.0, 100.1, 100.2, 100.3, 101.0, 101.2], start="09:35")
        res = engine_orb_breakout_15m(df, "BULLISH", interval_minutes=5, now=df.index[-1] + timedelta(minutes=6))
        self.assertEqual(res["reject_reason"], "OR_INCOMPLETE")


class TestShadowSessionTruncation(unittest.TestCase):
    def test_alpaca_shadow_marked_at_flatten(self):
        from services.learning_engine_service import _truncate_to_equity_session

        idx = pd.date_range("2026-11-27 14:30", "2026-11-30 21:00", freq="5min", tz="UTC")
        df = pd.DataFrame({"High": 1.0, "Low": 1.0, "Close": 1.0}, index=idx)
        out, still_open = _truncate_to_equity_session(df, _utc(2026, 11, 27, 15, 0), now=_utc(2026, 12, 1))
        self.assertFalse(still_open)
        # last bar must complete by 12:52 ET (13:00 early close - 8 min) = 17:52 UTC
        self.assertLessEqual(out.index[-1] + pd.Timedelta(minutes=5), pd.Timestamp("2026-11-27 17:52", tz="UTC"))
        _, still_open2 = _truncate_to_equity_session(df, _utc(2026, 11, 27, 15, 0), now=_utc(2026, 11, 27, 16, 0))
        self.assertTrue(still_open2)


class TestAlpacaLateSessionWiring(unittest.TestCase):
    def _run(self, minutes_to_close):
        import telegram_bot

        df_1h = _random_walk(200, 0.0, 30.0, 5, freq="60min")
        sig = {
            "triggered": True, "side": "LONG", "engine": "INTRADAY_MOMENTUM", "reject_reason": "",
            "order_type": "Market", "limit_price": None, "sl_pct": 1.2, "tp_pct": 3.6, "score": 70.0,
            "features": {"rsi": 60.0},
        }
        alp = MagicMock()
        alp.place_bracket_order.return_value = {"id": "x1"}
        route = {"allowed_engines": ["INTRADAY_MOMENTUM"], "prefer_limit": False}
        with patch.object(telegram_bot, "alpaca_service", alp), \
             patch.object(telegram_bot, "regime_router", return_value=route), \
             patch.object(telegram_bot, "engine_intraday_momentum", return_value=sig), \
             patch.object(telegram_bot.sentinel_svc, "get_asset_fundamental_sentiment", return_value={"sentiment": "NEUTRAL"}), \
             patch.object(telegram_bot, "_apply_context_allocation", return_value=(True, 5000.0, {"mode": "STANDARD", "scale": 1.0})), \
             patch.object(telegram_bot, "_risk_gate", return_value=True), \
             patch.object(telegram_bot, "_risk_opened"), \
             patch.object(telegram_bot.trade_journal_svc, "record_entry") as rec_entry, \
             patch.object(telegram_bot.trade_journal_svc, "record_shadow_signal", return_value=1) as rec_shadow:
            spent = telegram_bot._evaluate_and_trade_alpaca_candidate(
                sym="NVDA", df_sym_1h=df_1h, eq_bias="BULLISH", vix_val=15.0, vix_delta_pct=0.0, spy_24h_ch=0.0,
                equity_alpaca=100000.0, base_notional=5000.0, available_budget=50000.0, positions=[],
                adaptive_params=None, notification_events=[], df_sym_5m=None, minutes_to_close=minutes_to_close,
            )
        return spent, alp, rec_entry, rec_shadow

    def test_no_order_in_last_30_minutes(self):
        spent, alp, rec_entry, rec_shadow = self._run(20.0)
        self.assertEqual(spent, 0.0)
        alp.place_bracket_order.assert_not_called()
        reasons = [c.kwargs.get("reject_reason") for c in rec_shadow.call_args_list]
        self.assertIn("LATE_SESSION_NO_TIME", reasons)
        feats = rec_shadow.call_args_list[-1].kwargs["features"]
        self.assertEqual(feats["minutes_to_close"], 20.0)
        self.assertIn("ruleset_version", feats)

    def test_weak_setup_blocked_in_late_zone(self):
        spent, alp, _, rec_shadow = self._run(60.0)  # score 70 < 75
        self.assertEqual(spent, 0.0)
        reasons = [c.kwargs.get("reject_reason") for c in rec_shadow.call_args_list]
        self.assertIn("LATE_SESSION_WEAK_SETUP", reasons)

    def test_order_sent_mid_session_with_telemetry(self):
        spent, alp, rec_entry, _ = self._run(240.0)
        self.assertGreater(spent, 0.0)
        alp.place_bracket_order.assert_called_once()
        ctx = rec_entry.call_args.kwargs["context"]
        for key in ("ruleset_version", "tm_expected_r", "tm_drift_z", "hist_n", "minutes_to_close", "late_zone",
                    "fp_p_tp", "fp_p_tp0", "pe", "pe_se"):
            self.assertIn(key, ctx)
        self.assertEqual(ctx["late_zone"], "NORMAL")


class TestFokkerPlanckFirstPassage(unittest.TestCase):
    A = -np.log(1 - 0.012)
    B = np.log(1.036)
    S2 = (35e-4) ** 2

    def test_infinite_horizon_matches_gamblers_ruin(self):
        from services.strategy_engines_service import first_passage_probabilities as fpp

        self.assertAlmostEqual(fpp(0.0, self.S2, self.A, self.B, 1e7)["p_tp"], self.A / (self.A + self.B), places=6)
        nu = 2e-4
        k = 2 * nu / self.S2
        exact = np.expm1(-k * self.A) / np.expm1(-k * (self.A + self.B))
        self.assertAlmostEqual(fpp(nu, self.S2, self.A, self.B, 1e7)["p_tp"], exact, places=6)

    def test_finite_horizon_matches_brownian_simulation_and_conserves_mass(self):
        from services.strategy_engines_service import first_passage_probabilities as fpp

        res = fpp(2e-4, self.S2, self.A, self.B, 24, survival_grid=400)
        rng = np.random.default_rng(7)
        sub = 100
        paths = np.cumsum(rng.normal(2e-4 / sub, 35e-4 / np.sqrt(sub), (20000, 24 * sub)), axis=1)
        hs = np.where((paths <= -self.A).any(1), (paths <= -self.A).argmax(1), 10**9)
        ht = np.where((paths >= self.B).any(1), (paths >= self.B).argmax(1), 10**9)
        self.assertAlmostEqual(res["p_tp"], float((ht < hs).mean()), delta=0.01)
        self.assertAlmostEqual(res["p_sl"], float((hs < ht).mean()), delta=0.015)
        mass = res["p_tp"] + res["p_sl"] + np.trapezoid(res["density"], res["y"])
        self.assertAlmostEqual(mass, 1.0, places=3)

    def test_short_is_mirror_of_long_and_peclet_noise_reported(self):
        from services.strategy_engines_service import evaluate_fokker_planck

        df = _random_walk(520, 3.0, 35.0, 11)
        now = df.index[-1] + timedelta(hours=1)
        inv = df.copy()
        inv[["Open", "Close"]] = 1e4 / df[["Open", "Close"]]
        inv["High"], inv["Low"] = 1e4 / df["Low"], 1e4 / df["High"]
        lng = evaluate_fokker_planck(df, "LONG", 1.0, 1.0, fee_rt_pct=0.0, now=now)
        sht = evaluate_fokker_planck(inv, "SHORT", 1.0, 1.0, fee_rt_pct=0.0, now=now)
        self.assertTrue(lng["fp_ok"] and sht["fp_ok"])
        # same drift magnitude seen from the mirrored side; b differs only by log(1.01) vs -log(0.99)
        self.assertAlmostEqual(lng["pe"], sht["pe"], delta=0.05)
        # Pe standard error = 2 b / (sigma sqrt(n)): the estimate is noisy by construction
        lr = np.diff(np.log(df["Close"].to_numpy()))
        expected_se = 2 * np.log(1.01) / (lr.std(ddof=1) * np.sqrt(len(lr)))
        self.assertAlmostEqual(lng["pe_se"], expected_se, delta=0.01)
        self.assertGreater(lng["fp_p_tp"], lng["fp_p_tp0"])  # positive drift helps the LONG target


if __name__ == "__main__":
    unittest.main()
