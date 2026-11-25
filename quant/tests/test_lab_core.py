"""Test offline del core del laboratorio (paper)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from quant.core import COST_PRESETS
from quant.lab.base import Decision, Expected, Instrument, Target
from quant.lab.broker import PaperBroker
from quant.lab.marketdata import SyntheticMarketData
from quant.lab.review import scorecard, weekly_review
from quant.lab.runner import LabRunner, cron_matches, is_due
from quant.lab.storage import SQLiteStorage

PERP = Instrument("BYBIT:BTCUSDT", "bybit", "BTCUSDT", COST_PRESETS["bybit_perp"])
ETH = Instrument("BYBIT:ETHUSDT", "bybit", "ETHUSDT", COST_PRESETS["bybit_perp"])
EQ = Instrument("YAHOO:SPY", "yahoo", "SPY", COST_PRESETS["alpaca_equity"])
NOW = datetime(2024, 3, 1, 0, 5, tzinfo=timezone.utc)


class Dummy:
    version = "1"
    schedule = "5 0 * * *"
    capital = 10_000.0

    def __init__(self, name="dummy", weights=None, expected=None, fail=False):
        self.name, self.weights, self.expected, self.fail = name, weights or {PERP: 0.5}, expected, fail

    def decide(self, now_utc, data):
        if self.fail:
            raise RuntimeError("boom")
        return Decision(self.name, self.version, now_utc.isoformat(),
                        [Target(i, w, "test") for i, w in self.weights.items()], note="dummy")


@pytest.fixture
def env(tmp_path):
    st = SQLiteStorage(str(tmp_path / "lab.db"))
    data = SyntheticMarketData(seed=1)
    return st, data, PaperBroker(st, data)


def test_rebalance_reaches_target_and_books_costs(env):
    st, data, br = env
    s = Dummy()
    d = s.decide(NOW, data)
    fills = br.rebalance(s, d, NOW)
    assert len(fills) == 1 and fills[0]["fee"] > 0 and fills[0]["slippage"] > 0
    mark = br.mark(s, NOW)
    assert abs(mark["gross_exposure"] - 0.5) < 0.01
    assert mark["equity"] < s.capital  # costi
    assert br.rebalance(s, d, NOW) == []  # nessun nuovo trade
    px = data.last_price("bybit", "BTCUSDT", NOW)
    assert fills[0]["price"] > px  # acquisto: slippage avverso


def test_no_trade_band(env):
    st, data, br = env
    s = Dummy()
    br.rebalance(s, s.decide(NOW, data), NOW)
    s.weights = {PERP: 0.51}
    assert br.rebalance(s, s.decide(NOW, data), NOW) == []


def test_no_leverage_scaling(env):
    st, data, br = env
    s = Dummy(weights={PERP: 1.0, ETH: 1.0})
    fills = br.rebalance(s, s.decide(NOW, data), NOW)
    assert all("scaled" in f["reason"] for f in fills)
    assert br.mark(s, NOW)["gross_exposure"] <= 1.01


def test_funding_sign(env):
    st, data, br = env
    short, long_ = Dummy("s", {PERP: -0.5}), Dummy("l", {PERP: 0.5})
    for s in (short, long_):
        br.rebalance(s, s.decide(NOW, data), NOW)
    later = pd.Timestamp(NOW) + pd.Timedelta(days=1)
    fs, fl = br.accrue(short, later, NOW), br.accrue(long_, later, NOW)
    assert len(fs) == 3 and sum(f["fee"] for f in fs) < 0   # short incassa funding positivo
    assert sum(f["fee"] for f in fl) > 0
    assert st.cash("s", "1") > st.cash("l", "1") - 1e-9


def test_equity_short_borrow_and_long_free(env):
    st, data, br = env
    s = Dummy("e", {EQ: -0.5})
    br.rebalance(s, s.decide(NOW, data), NOW)
    out = br.accrue(s, pd.Timestamp(NOW) + pd.Timedelta(days=30), NOW)
    assert len(out) == 1 and out[0]["reason"].startswith("FINANCING") and out[0]["fee"] > 0
    st2 = Dummy("e2", {EQ: 0.5})
    br.rebalance(st2, st2.decide(NOW, data), NOW)
    assert br.accrue(st2, pd.Timestamp(NOW) + pd.Timedelta(days=30), NOW) == []


def test_decision_idempotent(env):
    st, data, _ = env
    d = Dummy().decide(NOW, data)
    assert st.log_decision(d) == st.log_decision(d)
    assert len(st.query("decisions", "dummy")) == 1


def test_runner_isolates_failure_and_schedule(env):
    st, data, br = env
    good, bad = Dummy("good"), Dummy("bad", fail=True)
    r = LabRunner([bad, good], st, data, br)
    res = r.run_due(NOW)
    assert [x["ok"] for x in res] == [False, True]
    assert "ERROR" in st.query("decisions", "bad")[0]["note"]
    assert st.last_run("good", "1") and st.last_run("bad", "1") is None
    assert [x["strategy"] for x in r.run_due(NOW + pd.Timedelta(hours=1))] == ["bad"]  # good non scaduta
    assert len(r.run_once("good", NOW + pd.Timedelta(hours=2))) == 1


def test_cron():
    t = datetime(2024, 3, 4, 0, 5, tzinfo=timezone.utc)  # lunedi'
    assert cron_matches("5 0 * * *", t) and cron_matches("*/5 0-3 * * 1", t) and cron_matches("5,10 0 4 3 *", t)
    assert not cron_matches("6 0 * * *", t) and not cron_matches("5 0 * * 0", t) and not cron_matches("5 0 * 4 *", t)
    assert cron_matches("5 0 * * 7", datetime(2024, 3, 3, 0, 5, tzinfo=timezone.utc))
    assert is_due("5 0 * * *", "2024-03-03T00:05:00Z", t) and not is_due("5 0 * * *", t, t + pd.Timedelta(hours=5))
    assert is_due("5 0 * * *", None, t)


def _run_days(st, data, br, s, days):
    r = LabRunner([s], st, data, br)
    t = pd.Timestamp("2024-03-01 00:05", tz="UTC")
    for i in range(days):
        s.weights = {PERP: 0.5 if i % 2 == 0 else -0.5}
        r.run_due((t + pd.Timedelta(days=i)).to_pydatetime())


def test_review_flags_and_scorecard(env):
    st, data, br = env
    exp = Expected(sharpe=3.0, mean_period_return=0.05, std_period_return=0.01, period="day", source_report="x")
    short = Dummy("short", expected=exp)
    _run_days(st, data, br, short, 4)
    txt = weekly_review(st, [short], pd.Timestamp("2024-03-05 00:10", tz="UTC"))
    assert "TOO_EARLY" in txt
    assert st.query("reviews", "short")[0]["flag"] == "TOO_EARLY"
    long = Dummy("long", expected=exp)
    _run_days(st, data, br, long, 14)
    weekly_review(st, [long], pd.Timestamp("2024-03-16 00:10", tz="UTC"))
    assert st.query("reviews", "long")[0]["flag"] == "UNDERPERFORMING"  # attesa irrealistica 5%/giorno
    ok = Dummy("ok", expected=Expected(0, -1.0, 0.5, "day", "x"))
    _run_days(st, data, br, ok, 14)
    weekly_review(st, [ok], pd.Timestamp("2024-03-16 00:10", tz="UTC"))
    assert st.query("reviews", "ok")[0]["flag"] == "OK"
    sc = scorecard(st, [short, long])
    assert "short" in sc and "long" in sc and len(sc) > 20
