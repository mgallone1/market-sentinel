"""Lab candidate strategies: exits, liquidation conditions, In Play selection, NYSE calendar rules."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import services.strategy_engines_service as se  # noqa: E402


def _bars(rows):
    """rows: list of (open, high, low, close)."""
    a = np.array(rows, float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


class TestActiveExit(unittest.TestCase):
    ATR = np.full(20, 1.0)

    def test_tp1_then_breakeven_stop(self):
        # long @100, SL 98 (R = 2): bar1 reaches 103 (+1.5R) -> 50% out; bar2 falls to 99.9 -> BE stop on the rest
        o, h, l, c = _bars([(100, 100, 100, 100), (100, 103.2, 99.5, 102), (102, 102, 99.9, 100)] + [(100, 100, 100, 100)] * 3)
        r = se.simulate_active_exit(o, h, l, c, 0, 1, 100.0, 98.0, self.ATR, 5, trail_atr=50.0)
        self.assertTrue(r["tp1_hit"])
        self.assertEqual([x["reason"] for x in r["legs"]], [se.EXIT_TP1_PARTIAL, se.EXIT_BREAKEVEN_STOP])
        self.assertAlmostEqual(r["legs"][0]["price"], 103.0)
        self.assertAlmostEqual(r["legs"][1]["price"], 100.0)
        self.assertAlmostEqual(r["ret"], 0.5 * 0.03)
        self.assertAlmostEqual(r["r_multiple"], 0.75)

    def test_breakeven_includes_round_trip_fees(self):
        o, h, l, c = _bars([(100, 100, 100, 100), (100, 103.2, 99.5, 102), (102, 102, 99.0, 99.5)] + [(99, 99, 99, 99)] * 2)
        r = se.simulate_active_exit(o, h, l, c, 0, 1, 100.0, 98.0, self.ATR, 4, trail_atr=50.0, fee_side=0.001)
        self.assertAlmostEqual(r["legs"][1]["price"], 100.0 * (1 + 2 * 0.001))
        # net: leg1 +3%, leg2 +0.2% (BE covers fees), minus fees 0.1% x (1 entry + 1 total exit)
        self.assertAlmostEqual(r["ret"], 0.5 * 0.03 + 0.5 * 0.002 - 0.001 * 2)

    def test_initial_stop_has_priority_inside_the_same_bar(self):
        o, h, l, c = _bars([(100, 100, 100, 100), (100, 104, 97, 101)] + [(101, 101, 101, 101)] * 3)
        r = se.simulate_active_exit(o, h, l, c, 0, 1, 100.0, 98.0, self.ATR, 4)
        self.assertEqual(r["exit_reason"], se.EXIT_STOP_LOSS)
        self.assertFalse(r["tp1_hit"])
        self.assertAlmostEqual(r["r_multiple"], -1.0)

    def test_trailing_atr_after_tp1(self):
        # TP1 at 103, then rally to 110 (trail = 110 - 1.5 = 108.5 from next bar), then drop to 107 -> trailing exit
        rows = [(100, 100, 100, 100), (100, 103.5, 100, 103), (103, 110, 103, 109.5), (109.5, 109.6, 107, 107.5)]
        o, h, l, c = _bars(rows + [(107, 107, 107, 107)] * 2)
        r = se.simulate_active_exit(o, h, l, c, 0, 1, 100.0, 98.0, self.ATR, 5, trail_atr=1.5)
        self.assertEqual(r["exit_reason"], se.EXIT_TRAILING_ATR)
        self.assertAlmostEqual(r["legs"][1]["price"], 108.5)
        self.assertAlmostEqual(r["ret"], 0.5 * 0.03 + 0.5 * 0.085)

    def test_time_stop_when_mfe_below_threshold(self):
        rows = [(100, 100, 100, 100)] + [(100, 100.4, 99.5, 100.1)] * 8
        o, h, l, c = _bars(rows)
        r = se.simulate_active_exit(o, h, l, c, 0, 1, 100.0, 98.0, self.ATR, 8, time_stop_bars=6, time_stop_r=0.5)
        self.assertEqual(r["exit_reason"], se.EXIT_TIME_STOP)
        self.assertEqual(r["bars_held"], 6)
        # MFE above the threshold: no time-stop, trade lives to the end
        rows2 = [(100, 100, 100, 100), (100, 101.2, 99.5, 100.1)] + [(100, 100.4, 99.5, 100.1)] * 7
        r2 = se.simulate_active_exit(*_bars(rows2), 0, 1, 100.0, 98.0, self.ATR, 8, time_stop_bars=6, time_stop_r=0.5)
        self.assertEqual(r2["exit_reason"], se.EXIT_EOD_FORCE_CLOSE)

    def test_short_side_and_vwap_target(self):
        # short @100, SL 102: TP1 at 97; runner exits at VWAP 95 when touched
        rows = [(100, 100, 100, 100), (100, 100.5, 96.8, 97), (97, 97.2, 94.5, 95)]
        o, h, l, c = _bars(rows + [(95, 95, 95, 95)] * 2)
        vwap = np.array([np.nan, 99.0, 95.0, 95.0, 95.0])
        r = se.simulate_active_exit(o, h, l, c, 0, -1, 100.0, 102.0, self.ATR, 4, vwap=vwap, trail_atr=50.0)
        self.assertEqual([x["reason"] for x in r["legs"]], [se.EXIT_TP1_PARTIAL, se.EXIT_VWAP_TARGET])
        self.assertAlmostEqual(r["ret"], 0.5 * 0.03 + 0.5 * 0.05)

    def test_fixed_bracket_ablation(self):
        rows = [(100, 100, 100, 100), (100, 103.2, 99.5, 102), (102, 104.5, 101, 104)]
        o, h, l, c = _bars(rows + [(104, 104, 104, 104)])
        r = se.simulate_active_exit(o, h, l, c, 0, 1, 100.0, 98.0, self.ATR, 3, fixed_tp_r=2.0)
        self.assertEqual(r["exit_reason"], se.EXIT_FIXED_TP)
        self.assertEqual(len(r["legs"]), 1)
        self.assertAlmostEqual(r["r_multiple"], 2.0)

    def test_gap_through_stop_fills_at_open(self):
        o, h, l, c = _bars([(100, 100, 100, 100), (96, 96.5, 95, 96)] + [(96, 96, 96, 96)] * 2)
        r = se.simulate_active_exit(o, h, l, c, 0, 1, 100.0, 98.0, self.ATR, 3)
        self.assertAlmostEqual(r["legs"][0]["price"], 96.0)
        self.assertAlmostEqual(r["r_multiple"], -2.0)


class TestPostLiquidation(unittest.TestCase):
    def _setup(self, spike_up=True, oi_z=-3.0, fpct=97.0, wick=0.6, vol_conf=50.0):
        n = 40
        o = np.full(n, 100.0); c = np.full(n, 100.0); h = np.full(n, 100.5); l = np.full(n, 99.5); v = np.full(n, 100.0)
        s, i = n - 2, n - 1
        if spike_up:
            o[s], c[s], h[s], l[s], v[s] = 100.0, 103.0, 103.5, 99.8, 400.0
            # confirmation: long upper wick, closes back under the pre-spike high (100.5)
            o[i], l[i] = 100.4, 100.0
            h[i] = 100.4 + wick * 3.0 / (1 - 0)  # range ~= h - l
            c[i] = 100.2
            h[i] = max(o[i], c[i]) + wick * (h[i] - l[i])
        else:
            o[s], c[s], h[s], l[s], v[s] = 100.0, 97.0, 100.2, 96.5, 400.0
            o[i], h[i], c[i] = 99.6, 100.0, 99.8
            l[i] = min(o[i], c[i]) - wick * 3.0
        v[i] = vol_conf
        return o, h, l, c, v, i, fpct, oi_z

    def test_short_setup_triggers_with_all_four_conditions(self):
        o, h, l, c, v, i, fp, z = self._setup()
        r = se.detect_post_liq_reversal(o, h, l, c, v, i, fp, z)
        self.assertTrue(r["triggered"], r)
        self.assertEqual(r["side"], "SHORT")
        atr = se.wilder_atr_array(h, l, c, 14)[i - 2]
        self.assertAlmostEqual(r["sl"], h[i - 1] + 0.25 * atr)
        self.assertGreater(r["sl"], r["entry"])

    def test_each_condition_can_reject(self):
        base = self._setup()
        self.assertEqual(se.detect_post_liq_reversal(*base[:6], 50.0, base[7])["reject_reason"], "FUNDING_NOT_EXTREME")
        self.assertEqual(se.detect_post_liq_reversal(*base[:6], base[6], -1.0)["reject_reason"], "OI_NOT_COLLAPSING")
        self.assertEqual(se.detect_post_liq_reversal(*base[:6], None, base[7])["reject_reason"], "NO_FUNDING_DATA")
        self.assertEqual(se.detect_post_liq_reversal(*base[:6], base[6], None)["reject_reason"], "NO_OI_DATA")
        lowfund = self._setup(fpct=3.0)  # shorts crowded but the spike is up -> wrong direction for a LONG
        self.assertEqual(se.detect_post_liq_reversal(*lowfund[:6], 3.0, -3.0)["reject_reason"], "SPIKE_WRONG_DIRECTION")
        heavy = self._setup(vol_conf=500.0)
        self.assertEqual(se.detect_post_liq_reversal(*heavy[:6], 97.0, -3.0)["reject_reason"], "NO_REABSORPTION")
        mirrored = se.detect_post_liq_reversal(*base[:6], 3.0, -3.0, params={"mirror": 1.0})
        self.assertTrue(mirrored["triggered"])
        self.assertEqual(mirrored["side"], "SHORT")

    def test_long_setup(self):
        o, h, l, c, v, i, _, _ = self._setup(spike_up=False)
        r = se.detect_post_liq_reversal(o, h, l, c, v, i, 2.0, -2.5)
        self.assertTrue(r["triggered"], r)
        self.assertEqual(r["side"], "LONG")
        self.assertLess(r["sl"], r["entry"])

    def test_no_spike_rejected(self):
        o, h, l, c, v, i, fp, z = self._setup()
        h2, l2 = h.copy(), l.copy()
        h2[i - 1], l2[i - 1] = 100.6, 99.6
        self.assertEqual(se.detect_post_liq_reversal(o, h2, l2, c, v, i, fp, z)["reject_reason"], "NO_SPIKE")

    def test_funding_percentile_point_in_time(self):
        idx = pd.date_range("2025-01-01", periods=120, freq="8h", tz="UTC")
        f = pd.Series(np.linspace(-1e-4, 1e-4, 120), index=idx)
        self.assertGreaterEqual(se.funding_percentile(f, idx[-1]), 95.0)
        f2 = f.copy()
        f2.iloc[-1] = 9.9  # a print in the future must not change the value at the previous timestamp
        self.assertEqual(se.funding_percentile(f, idx[-2]), se.funding_percentile(f2, idx[-2]))
        self.assertIsNone(se.funding_percentile(f.iloc[:5], idx[4]))
        self.assertIsNone(se.funding_percentile(None, idx[0]))

    def test_oi_zscore(self):
        rng = np.random.default_rng(0)
        oi = 1000 * np.cumprod(1 + rng.normal(0, 0.002, 300))
        oi[250] = oi[249] * 0.97  # -3% in one bar
        z = se.oi_change_zscore(oi, 250, 192)
        self.assertLess(z, -5)
        self.assertIsNone(se.oi_change_zscore(oi, 100, 192))  # not enough history
        oi_nan = oi.copy()
        oi_nan[250] = np.nan
        self.assertIsNone(se.oi_change_zscore(oi_nan, 250, 192))


class TestInPlay(unittest.TestCase):
    def _sessions(self, n_days=25, spike_day_vol=3.0, gap=0.02):
        days = pd.bdate_range("2026-09-14", periods=n_days + 3)
        days = [d for d in days if d.date().isoformat() not in ("2026-09-07",)][:n_days]
        frames = []
        prev_close = 100.0
        for k, d in enumerate(days):
            idx = pd.date_range(f"{d.date()} 09:30", periods=78, freq="5min", tz="America/New_York")
            last = k == len(days) - 1
            op = prev_close * (1 + (gap if last else 0.0))
            cl = np.full(78, op)
            vol = np.full(78, 1000.0)
            if last:
                vol[:3] = 1000.0 * spike_day_vol
                cl = op + np.linspace(0, 2, 78)
            frames.append(pd.DataFrame({"Open": cl, "High": cl + 0.1, "Low": cl - 0.1, "Close": cl, "Volume": vol}, index=idx))
            prev_close = float(cl[-1])
        df = pd.concat(frames)
        df.index = df.index.tz_convert("UTC")
        return df, days

    def test_rvol_same_window_and_no_lookahead(self):
        df, days = self._sessions()
        st = se.opening_window_stats(df)
        last = days[-1].date()
        self.assertAlmostEqual(se.rvol_opening(st, last, 20), 3.0)
        # changing volumes AFTER 09:45 or on later days does not change the value
        df2 = df.copy()
        ny = df2.index.tz_convert("America/New_York")
        df2.loc[(ny.date == last) & (ny.hour >= 10), "Volume"] = 1e9
        self.assertAlmostEqual(se.rvol_opening(se.opening_window_stats(df2), last, 20), 3.0)
        self.assertIsNone(se.rvol_opening(st, days[10].date(), 20))  # < 20 previous sessions

    def test_select_in_play_top2_and_empty_day(self):
        m = {"A": {"rvol": 3.0, "gap_pct": 2.0, "idio_z": 0.1}, "B": {"rvol": 5.0, "gap_pct": -0.2, "idio_z": -2.5},
             "C": {"rvol": 2.5, "gap_pct": 1.6, "idio_z": 0.0}, "D": {"rvol": 1.5, "gap_pct": 4.0, "idio_z": 3.0}}
        sel = se.select_in_play(m)
        self.assertEqual([x["symbol"] for x in sel], ["B", "A"])
        self.assertEqual(sel[0]["side"], "SHORT")  # residual qualifies, gap does not
        self.assertEqual(se.select_in_play({"X": {"rvol": 1.9, "gap_pct": 5.0, "idio_z": 4.0}}), [])

    def test_entry_respects_calendar_and_forced_close(self):
        df, days = self._sessions()
        ent = se.in_play_entry(df, days[-1].date(), "LONG")
        self.assertTrue(ent["triggered"])
        ny = df.index.tz_convert("America/New_York")
        self.assertGreaterEqual(ny[ent["pos"]] + pd.Timedelta(minutes=5), pd.Timestamp(f"{days[-1].date()} 09:50", tz="America/New_York"))
        self.assertEqual(ny[ent["end_pos"]] + pd.Timedelta(minutes=5), pd.Timestamp(f"{days[-1].date()} 15:50", tz="America/New_York"))

    def test_early_close_day_windows(self):
        idx = pd.date_range("2026-11-27 09:30", periods=42, freq="5min", tz="America/New_York")  # 13:00 close
        cl = np.r_[np.full(30, 100.0), np.linspace(100.2, 101, 12)]  # breakout only after 12:00
        df = pd.DataFrame({"Open": cl, "High": cl + 0.05, "Low": cl - 0.05, "Close": cl, "Volume": 1.0}, index=idx.tz_convert("UTC"))
        ent = se.in_play_entry(df, pd.Timestamp("2026-11-27").date(), "LONG")
        ny = df.index.tz_convert("America/New_York")
        if ent["triggered"]:
            self.assertLessEqual(ny[ent["pos"]] + pd.Timedelta(minutes=5), pd.Timestamp("2026-11-27 12:30", tz="America/New_York"))
            self.assertEqual(ny[ent["end_pos"]] + pd.Timedelta(minutes=5), pd.Timestamp("2026-11-27 12:50", tz="America/New_York"))
        late = df.copy()
        late["Close"] = late["High"] = late["Low"] = late["Open"] = 100.0
        late.loc[late.index[-4:], ["Close", "High"]] = 101.0  # breakout at 12:40+: too late (< 30 min to 13:00)
        self.assertFalse(se.in_play_entry(late, pd.Timestamp("2026-11-27").date(), "LONG")["triggered"])

    def test_holiday_has_no_session(self):
        self.assertEqual(se.in_play_entry(pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0]},
                                                       index=pd.DatetimeIndex(["2026-11-26 15:00"], tz="UTC")),
                                          pd.Timestamp("2026-11-26").date(), "LONG")["reject_reason"], "MARKET_CLOSED")


if __name__ == "__main__":
    unittest.main()
