"""Telemetry v2 (orthogonal state variables): estimators, fallbacks, migration, decision invariance."""
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import telemetry_features as tv2


def _brownian_ohlc(n_bars, sigma_bar, mu_bar=0.0, sub=200, seed=0, p0=100.0):
    """OHLC of a (drifted) Brownian log-price sampled `sub` times per bar."""
    rng = np.random.default_rng(seed)
    inc = rng.normal(mu_bar / sub, sigma_bar / math.sqrt(sub), (n_bars, sub))
    lp = np.log(p0) + np.concatenate([[0.0], np.cumsum(inc.ravel())])
    o = np.exp(lp[0:-1:sub])
    c = np.exp(lp[sub::sub])
    seg = lp.reshape(-1)
    h = np.array([np.exp(seg[i * sub:(i + 1) * sub + 1].max()) for i in range(n_bars)])
    l = np.array([np.exp(seg[i * sub:(i + 1) * sub + 1].min()) for i in range(n_bars)])
    return o, h, l, c


def _bars_df(n, mu_bp=0.0, sig_bp=30.0, seed=0, freq="15min"):
    o, h, l, c = _brownian_ohlc(n, sig_bp / 1e4, mu_bp / 1e4, sub=20, seed=seed)
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    vol = np.random.default_rng(seed + 1).uniform(500, 1500, n)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": vol}, index=idx)


class TestRogersSatchell(unittest.TestCase):
    def test_unbiased_and_invariant_to_constant_drift(self):
        # 2000 sub-steps per bar: discrete sampling of H/L biases RS low by O(1/sqrt(sub)) (~3% here)
        sig, kw = 0.004, dict(sub=2000, seed=1)
        v0, _ = tv2.rogers_satchell_variance(*_brownian_ohlc(1500, sig, 0.0, **kw))
        # same shocks, strong drift (|mu| = 0.75 sigma per bar): RS must not move
        v1, _ = tv2.rogers_satchell_variance(*_brownian_ohlc(1500, sig, 0.75 * sig, **kw))
        v2, _ = tv2.rogers_satchell_variance(*_brownian_ohlc(1500, sig, -0.75 * sig, **kw))
        for v in (v0, v1, v2):
            self.assertAlmostEqual(v / sig ** 2, 1.0, delta=0.07)
        self.assertAlmostEqual(v1 / v0, 1.0, delta=0.03)
        self.assertAlmostEqual(v2 / v0, 1.0, delta=0.03)
        # Parkinson range estimator, for contrast, is inflated by the drift
        o, h, l, c = _brownian_ohlc(1500, sig, 0.75 * sig, **kw)
        o0, h0, l0, c0 = _brownian_ohlc(1500, sig, 0.0, **kw)
        park = lambda hh, ll: np.mean(np.log(hh / ll) ** 2) / (4 * math.log(2))  # noqa: E731
        self.assertGreater(park(h, l) / park(h0, l0), 1.1)

    def test_scale_invariance_exact(self):
        o, h, l, c = _brownian_ohlc(500, 0.003, seed=2)
        v, _ = tv2.rogers_satchell_variance(o, h, l, c)
        vs, _ = tv2.rogers_satchell_variance(o * 37.0, h * 37.0, l * 37.0, c * 37.0)
        self.assertAlmostEqual(v, vs, places=15)

    def test_flat_and_invalid_bars_fallback(self):
        flat = np.full(50, 100.0)
        self.assertEqual(tv2.rogers_satchell_variance(flat, flat, flat, flat), (None, 50))
        bad_h = np.array([100.0, 101.0]), np.array([99.0, 100.5]), np.array([98.0, 99.0]), np.array([100.5, 100.0])
        self.assertEqual(tv2.rogers_satchell_variance(*bad_h), (None, 0))  # H < max(O, C) everywhere
        self.assertEqual(tv2.rogers_satchell_variance([np.nan], [1.0], [1.0], [1.0]), (None, 0))

    def test_fokker_planck_rs_fields_and_close_to_close_fallback(self):
        from services.strategy_engines_service import evaluate_fokker_planck

        df = _bars_df(520, seed=3)
        now = df.index[-1] + timedelta(hours=1)
        res = evaluate_fokker_planck(df, "LONG", 1.2, 3.6, interval_minutes=15, now=now)
        for k in ("fp_s_rs", "fp_p_tp_rs", "fp_p_sl_rs", "fp_p_tp_rs_zero_drift", "fp_p_sl_rs_zero_drift"):
            self.assertIn(k, res)
        self.assertEqual(res["fp_rs_fallback"], 0)
        flat = df.copy()
        flat["High"] = flat[["Open", "Close"]].max(axis=1) - 1.0  # invalid OHLC everywhere
        res_fb = evaluate_fokker_planck(flat, "LONG", 1.2, 3.6, interval_minutes=15, now=now)
        self.assertEqual(res_fb["fp_rs_fallback"], 1)
        self.assertAlmostEqual(res_fb["fp_s_rs"] * 1e4, res_fb["sigma_bp_bar"], places=2)


class TestBayesShrinkage(unittest.TestCase):
    def test_weight_formula_and_limits(self):
        nu, s, nby = 3e-4, 35e-4, 35040.0
        nb, w = tv2.bayes_shrunk_drift(nu, s, 500, nby, sr0=0.4)
        self.assertAlmostEqual(w, 0.16 * 500 / (0.16 * 500 + nby), places=12)
        self.assertAlmostEqual(nb, w * nu, places=15)
        self.assertLess(abs(nb), abs(nu))
        _, w_big = tv2.bayes_shrunk_drift(nu, s, 10 ** 12, nby)
        self.assertGreater(w_big, 0.999)  # n -> inf: no shrinkage
        _, w_small = tv2.bayes_shrunk_drift(nu, s, 1, nby)
        self.assertLess(w_small, 1e-4)  # n -> 0: full shrinkage
        nb0, w0 = tv2.bayes_shrunk_drift(nu, s, 500, nby, sr0=0.0)
        self.assertEqual((nb0, w0), (0.0, 0.0))
        self.assertEqual(tv2.bayes_shrunk_drift(nu, 0.0, 500, nby), (None, None))
        self.assertEqual(tv2.bayes_shrunk_drift(float("nan"), s, 500, nby), (None, None))
        # weight monotone in n and independent of s (scale-free prior)
        ws = [tv2.bayes_shrunk_drift(nu, s, n, nby)[1] for n in (10, 100, 1000, 10000)]
        self.assertEqual(ws, sorted(ws))
        self.assertAlmostEqual(tv2.bayes_shrunk_drift(nu, 10 * s, 500, nby)[1], w, places=12)

    def test_bars_per_year(self):
        self.assertAlmostEqual(tv2.bars_per_year(15, "crypto"), 35040.0)
        self.assertAlmostEqual(tv2.bars_per_year(5, "equity"), 252 * 78)
        self.assertIsNone(tv2.bars_per_year(None))

    def test_bayes_fields_removes_drift_inflation(self):
        from services.strategy_engines_service import evaluate_fokker_planck

        df = _bars_df(520, mu_bp=3.0, seed=4)
        res = evaluate_fokker_planck(df, "LONG", 1.2, 3.6, interval_minutes=15, now=df.index[-1] + timedelta(hours=1))
        for k in ("fp_nu_bayes", "fp_p_tp_bayes", "fp_p_sl_bayes", "fp_ev_r_bayes"):
            self.assertIn(k, res)
        # with ~500 bars of 15m the prior dominates: Bayes P(TP) ~ zero-drift P(TP)
        self.assertAlmostEqual(res["fp_p_tp_bayes"], res["fp_p_tp0"], delta=0.003)


class TestIdiosyncratic(unittest.TestCase):
    def _make(self, beta=1.4, n=200, seed=5):
        rng = np.random.default_rng(seed)
        idx = pd.date_range("2026-10-01 13:30", periods=n, freq="1h", tz="UTC")
        rm = rng.normal(0, 0.004, n)
        rs = beta * rm + rng.normal(0.0002, 0.003, n)
        return pd.Series(100 * np.exp(np.cumsum(rs)), idx), pd.Series(500 * np.exp(np.cumsum(rm)), idx)

    def test_residual_orthogonal_to_spy_and_beta_recovered(self):
        stock, spy = self._make()
        d = tv2.idio_decomposition(stock, spy, window=140)
        self.assertAlmostEqual(d["spy_beta"], 1.4, delta=0.25)
        j = pd.concat([stock, spy], axis=1, join="inner")
        r = np.log(j).diff().dropna().tail(140).to_numpy()
        eps = r[:, 0] - d["spy_beta"] * r[:, 1]
        self.assertAlmostEqual(float(np.cov(eps, r[:, 1], ddof=1)[0, 1]), 0.0, places=12)
        self.assertAlmostEqual(d["idio_ret_window"], float(eps.sum()), places=12)
        self.assertAlmostEqual(d["idio_z_drift"], float(eps.mean() / (eps.std(ddof=1) / math.sqrt(len(eps)))), places=9)

    def test_misaligned_timestamps_are_inner_joined(self):
        stock, spy = self._make()
        d_full = tv2.idio_decomposition(stock, spy)
        d_holes = tv2.idio_decomposition(stock.drop(stock.index[::7]), spy)
        self.assertIsNotNone(d_holes["spy_beta"])
        self.assertAlmostEqual(d_holes["spy_beta"], d_full["spy_beta"], delta=0.3)
        self.assertIsNone(tv2.idio_decomposition(stock.iloc[:10], spy)["spy_beta"])  # too short

    def test_cross_sectional_rank(self):
        vals = {"NVDA": 0.05, "AAPL": -0.01, "MSFT": 0.0, "TSLA": 0.02, "AMZN": -0.03,
                "META": 0.01, "GOOGL": 0.03, "AMD": None}
        self.assertEqual(tv2.cross_sectional_rank(vals, "NVDA"), 1.0)
        self.assertEqual(tv2.cross_sectional_rank(vals, "AMZN"), 0.0)
        self.assertAlmostEqual(tv2.cross_sectional_rank(vals, "MSFT"), 2 / 6)
        self.assertIsNone(tv2.cross_sectional_rank(vals, "AMD"))
        stock, spy = self._make()
        uni = tv2.idio_universe({"A": stock, "B": stock * 1.0001, "C": spy}, spy)
        for d in uni.values():
            self.assertTrue(d["idio_cs_rank"] is None or 0.0 <= d["idio_cs_rank"] <= 1.0)


class TestOfiBvc(unittest.TestCase):
    def test_range_sign_and_volume_weighting(self):
        df = _bars_df(300, seed=6)
        out = tv2.ofi_bvc(df)
        for k in ("ofi_bvc_short", "ofi_bvc_med"):
            self.assertIsNotNone(out[k])
            self.assertGreaterEqual(out[k], -1.0)
            self.assertLessEqual(out[k], 1.0)
        up = df.copy()
        up.iloc[-15:, up.columns.get_loc("Close")] = up["Open"].iloc[-15:] * 1.02  # strong buying bars
        self.assertGreater(tv2.ofi_bvc(up)["ofi_bvc_short"], 0.9)
        dn = df.copy()
        dn.iloc[-15:, dn.columns.get_loc("Close")] = dn["Open"].iloc[-15:] * 0.98
        self.assertLess(tv2.ofi_bvc(dn)["ofi_bvc_short"], -0.9)
        novol = df.drop(columns=["Volume"])
        self.assertIsNotNone(tv2.ofi_bvc(novol)["ofi_bvc_short"])

    def test_formula_matches_normal_cdf(self):
        from statistics import NormalDist

        df = _bars_df(120, seed=7)
        dp = df["Close"] - df["Open"]
        sig = dp.rolling(60, min_periods=20).std().shift(1)
        z = (dp / sig).iloc[-15:]
        ofi = np.array([2 * NormalDist().cdf(x) - 1 for x in z])
        w = df["Volume"].iloc[-15:].to_numpy()
        self.assertAlmostEqual(tv2.ofi_bvc(df)["ofi_bvc_short"], float(np.sum(ofi * w) / np.sum(w)), places=10)

    def test_bad_input_returns_none(self):
        self.assertEqual(tv2.ofi_bvc(pd.DataFrame({"x": [1, 2]})), {"ofi_bvc_short": None, "ofi_bvc_med": None})
        self.assertEqual(tv2.ofi_bvc(_bars_df(5)), {"ofi_bvc_short": None, "ofi_bvc_med": None})


class TestVrp(unittest.TestCase):
    def test_vrp_spread_units(self):
        days = pd.bdate_range("2026-11-09", "2026-11-20")
        idx = pd.DatetimeIndex([pd.Timestamp(f"{d.date()} {h:02d}:30", tz="America/New_York")
                                for d in days for h in range(9, 16)]).tz_convert("UTC")
        rng = np.random.default_rng(8)
        c = 600 * np.exp(np.cumsum(rng.normal(0, 0.003, len(idx))))
        spy = pd.DataFrame({"Close": c}, index=idx)
        rv = tv2.realized_vol_5d_annualized(spy)
        self.assertIsNotNone(rv)
        self.assertTrue(0.01 < rv < 1.0)
        self.assertAlmostEqual(tv2.vrp_spread(20.0, spy), 0.20 - rv, places=12)
        self.assertIsNone(tv2.vrp_spread(None, spy))
        self.assertIsNone(tv2.vrp_spread(20.0, spy.iloc[:3]))


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


class TestBybitPublicState(unittest.TestCase):
    OI = {"retCode": 0, "result": {"list": [
        {"openInterest": str(v), "timestamp": str(1_700_000_000_000 - i * 3_600_000)}
        for i, v in enumerate([110.0, 100.0, 95.0, 90.0, 88.0])
    ]}}
    FR = {"retCode": 0, "result": {"list": [{"fundingRate": "0.0001", "fundingRateTimestamp": "1"}]}}

    def _get(self, url, params=None, timeout=None):
        assert timeout is not None and max(timeout) <= 2.0  # strict timeout always passed
        return _Resp(self.FR if "funding" in url else self.OI)

    def test_parsing(self):
        st = tv2.BybitPublicState(http_get=self._get, background=False)
        out = st.fetch("BTCUSDT")
        self.assertAlmostEqual(out["bybit_funding_rate"], 1e-4)
        self.assertAlmostEqual(out["bybit_oi_delta_1h"], 0.10)
        self.assertAlmostEqual(out["bybit_oi_delta_4h"], 110.0 / 88.0 - 1.0)

    def test_timeout_and_errors_fall_back_cleanly(self):
        import requests

        calls = []

        def boom(url, params=None, timeout=None):
            calls.append(url)
            raise requests.exceptions.Timeout("timeout")

        st = tv2.BybitPublicState(http_get=boom, background=False, cooldown=300)
        self.assertEqual(st.fetch("BTCUSDT"), tv2.BybitPublicState.EMPTY)
        n = len(calls)
        self.assertEqual(st.get("BTCUSDT"), tv2.BybitPublicState.EMPTY)  # circuit open: no new call
        self.assertEqual(len(calls), n)
        bad = tv2.BybitPublicState(http_get=lambda *a, **k: _Resp({"retCode": 10001}), background=False)
        self.assertEqual(bad.fetch("BTCUSDT"), tv2.BybitPublicState.EMPTY)
        forbidden = tv2.BybitPublicState(http_get=lambda *a, **k: _Resp({}, status=403), background=False)
        self.assertEqual(forbidden.fetch("BTCUSDT"), tv2.BybitPublicState.EMPTY)

    def test_get_never_blocks_and_uses_cache(self):
        def slow(url, params=None, timeout=None):
            time.sleep(1.0)
            return self._get(url, params, timeout)

        st = tv2.BybitPublicState(http_get=slow, ttl=90)
        t0 = time.monotonic()
        first = st.get("ETHUSDT")
        self.assertLess(time.monotonic() - t0, 0.2)  # returns immediately
        self.assertEqual(first, tv2.BybitPublicState.EMPTY)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and st.get("ETHUSDT")["bybit_funding_rate"] is None:
            time.sleep(0.05)
        self.assertAlmostEqual(st.get("ETHUSDT")["bybit_funding_rate"], 1e-4)

    def test_safe_telemetry_swallows_exceptions(self):
        def raiser(*a, **k):
            raise RuntimeError("x")

        self.assertEqual(tv2.safe_telemetry(raiser, 1), {})


class TestJournalMigration(unittest.TestCase):
    def test_idempotent_migration_on_legacy_db_and_values_stored(self):
        from services.trade_journal_service import TradeJournalService

        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "legacy.db"
            with sqlite3.connect(db) as conn:  # pre-v2 schema with one existing row
                conn.execute("""CREATE TABLE trade_journal (id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id TEXT UNIQUE,
                    broker TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, entry_price REAL NOT NULL,
                    notional_usd REAL NOT NULL, opened_at TEXT NOT NULL, closed_at TEXT, exit_price REAL, pnl_usd REAL,
                    pnl_pct REAL, close_reason TEXT, entry_context TEXT, post_mortem_analysis TEXT, learned_lesson TEXT,
                    status TEXT DEFAULT 'OPEN')""")
                conn.execute("INSERT INTO trade_journal (trade_id, broker, symbol, side, entry_price, notional_usd, opened_at) "
                             "VALUES ('OLD_1', 'ALPACA', 'NVDA', 'LONG', 100.0, 1000.0, '2026-01-01T00:00:00')")
            j1 = TradeJournalService(db_path=db)
            TradeJournalService(db_path=db)  # second init: no error, no duplicate columns
            with sqlite3.connect(db) as conn:
                for table in ("trade_journal", "signal_shadows"):
                    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
                    for c in tv2.TELEMETRY_V2_COLUMNS:
                        self.assertEqual(cols.count(c), 1, (table, c))
                old = conn.execute("SELECT trade_id, spy_beta FROM trade_journal WHERE trade_id='OLD_1'").fetchone()
            self.assertEqual(old, ("OLD_1", None))

            ctx = {"spy_beta": 1.3, "idio_cs_rank": 0.75, "vrp_spread": float("nan"), "ofi_bvc_short": "0.4",
                   "fp_p_tp_bayes": 0.03, "macro_bias": "BULLISH"}
            tid = j1.record_entry("ALPACA", "NVDA", "LONG", 101.0, 1000.0, context=ctx)
            sid = j1.record_shadow_signal("BYBIT", "BTCUSDT", "LONG", "INTRADAY_MOMENTUM", "K", "VIX_SHIELD",
                                          90000.0, 1.2, 3.6, {"bybit_oi_delta_1h": 0.02, "fp_s_rs": 0.004})
            with sqlite3.connect(db) as conn:
                row = conn.execute("SELECT spy_beta, idio_cs_rank, vrp_spread, ofi_bvc_short, fp_p_tp_bayes, entry_context "
                                   "FROM trade_journal WHERE trade_id=?", (tid,)).fetchone()
                sh = conn.execute("SELECT bybit_oi_delta_1h, fp_s_rs, bybit_funding_rate FROM signal_shadows "
                                  "WHERE shadow_id=?", (sid,)).fetchone()
            self.assertEqual(row[:5], (1.3, 0.75, None, 0.4, 0.03))  # NaN -> NULL
            self.assertEqual(json.loads(row[5])["macro_bias"], "BULLISH")
            self.assertEqual(sh, (0.02, 0.004, None))


class TestDecisionInvariance(unittest.TestCase):
    """Telemetry v2 must not change any operational decision: compare a run with working telemetry
    against a run where every telemetry builder raises or returns extreme values."""

    def _run_alpaca(self, minutes_to_close, score):
        import telegram_bot

        df_1h = _bars_df(200, seed=9, freq="60min")
        df_5m = _bars_df(400, mu_bp=5.0, seed=10, freq="5min")  # positive drift: TM lets the order through
        sig = {"triggered": True, "side": "LONG", "engine": "INTRADAY_MOMENTUM", "reject_reason": "",
               "order_type": "Market", "limit_price": None, "sl_pct": 1.2, "tp_pct": 3.6, "score": score,
               "features": {"rsi": 60.0}}
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
                adaptive_params=None, notification_events=[], df_sym_5m=df_5m, minutes_to_close=minutes_to_close,
                telemetry_cycle={"idio": {"NVDA": {"spy_beta": 1.2, "idio_ret_window": 0.01, "idio_z_drift": 0.5,
                                                   "idio_cs_rank": 0.6}}, "vrp_spread": 0.04},
            )
        orders = [c.args for c in alp.place_bracket_order.call_args_list]
        reasons = [c.kwargs.get("reject_reason") for c in rec_shadow.call_args_list]
        ctx = rec_entry.call_args.kwargs["context"] if rec_entry.called else {}
        return spent, orders, reasons, ctx

    def test_alpaca_decisions_identical_with_broken_telemetry(self):
        import services.strategy_engines_service as se

        def raiser(*a, **k):
            raise RuntimeError("telemetry down")

        for mtc, score in ((240.0, 70.0), (60.0, 70.0), (60.0, 90.0), (20.0, 99.0)):
            ok = self._run_alpaca(mtc, score)
            with patch.object(tv2, "ofi_bvc", raiser), patch.object(se, "_fp_telemetry_v2", raiser), \
                 patch.object(tv2, "rogers_satchell_variance", raiser):
                broken = self._run_alpaca(mtc, score)
            with patch.object(tv2, "ofi_bvc", lambda *a, **k: {"ofi_bvc_short": 1.0, "ofi_bvc_med": -1.0}):
                extreme = self._run_alpaca(mtc, score)
            self.assertEqual(ok[:3], broken[:3], (mtc, score))
            self.assertEqual(ok[:3], extreme[:3], (mtc, score))
        # telemetry actually reaches the journal when it works
        _, orders, _, ctx = self._run_alpaca(240.0, 70.0)
        self.assertTrue(orders)
        for k in ("spy_beta", "idio_cs_rank", "vrp_spread", "ofi_bvc_short", "fp_p_tp_bayes", "fp_p_tp_rs"):
            self.assertIn(k, ctx)

    def test_gates_and_ruleset_untouched(self):
        import services.strategy_engines_service as se

        self.assertEqual(se.STRATEGY_RULESET_VERSION, "2026-11-26.1")
        df = _bars_df(520, seed=11)
        now = df.index[-1] + timedelta(hours=1)
        tm = se.evaluate_timemachine_gate(df, "LONG", 1.2, 3.6, fee_rt_pct=0.12, now=now)
        with patch.object(se, "_fp_telemetry_v2", lambda *a, **k: {}):
            base_fp = se.evaluate_fokker_planck(df, "LONG", 1.2, 3.6, now=now)
        full_fp = se.evaluate_fokker_planck(df, "LONG", 1.2, 3.6, now=now)
        self.assertEqual({k: full_fp[k] for k in base_fp}, base_fp)  # pre-existing fields unchanged
        self.assertEqual(se.evaluate_timemachine_gate(df, "LONG", 1.2, 3.6, fee_rt_pct=0.12, now=now), tm)
        self.assertEqual(se.late_session_entry_check(60.0, 80.0, {"replays": 1, "p_tp_first": 0.3, "expected_r": 0.1}),
                         {"allowed": True, "zone": "LATE", "reason": ""})

    def test_bybit_collect_survives_telemetry_failure(self):
        import telegram_bot

        df = _bars_df(180, seed=12)

        class Boom:
            def get(self, *_a, **_k):
                raise RuntimeError("bybit down")

        def run():
            with patch.object(telegram_bot, "_fetch_bybit_closed_ohlcv", return_value=df), \
                 patch.object(telegram_bot.bybit_service, "get_cumulative_volume_delta", return_value=None), \
                 patch.object(telegram_bot.bybit_service, "get_orderbook_imbalance", return_value=None), \
                 patch.object(telegram_bot.trade_journal_svc, "record_shadow_signal", return_value=1):
                pack = telegram_bot._collect_bybit_signals(
                    b_sym="BTCUSDT", b_yf="BTC-USD", macro_bias="NEUTRAL", c_funding=0.0, spread_bps=1.0, rome_hour=12,
                )
            return None if not pack else (pack["signal"].get("side"), pack["signal"].get("engine"), pack["signal"].get("score"))

        with patch.object(telegram_bot, "_bybit_public_state", lambda: Boom()):
            broken = run()
        ok = run()
        self.assertEqual(ok, broken)


if __name__ == "__main__":
    unittest.main()
