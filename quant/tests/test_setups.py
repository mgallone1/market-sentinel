import numpy as np
import pandas as pd
import pytest

from quant.core import equity
from quant.data import generate_bars
from quant.strategies import STRATEGIES
from quant.strategies.setups import wilder_rsi

SPEC = equity("TEST")
DAILY = ["breakout_20d_close_high", "bull_flag", "reclaim_20d_ma", "oversold", "oversold_bounce"]


def _daily(n=1500, seed=3):
    return generate_bars(n=n, interval="1h", seed=seed, start="2020-01-01",
                         regimes=[(0.97, 0.004, 0.03), (0.97, -0.004, 0.03)])


def _intraday(days, start="2024-03-04", step=5, vol_seed=0):
    """Barre 5m per sessioni RTH US/Eastern (9:30-16:00), indice UTC = apertura barra."""
    rng = np.random.default_rng(vol_seed)
    rows = []
    for d in pd.bdate_range(start, periods=days):
        t0 = pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30)
        for k in range(78):
            rows.append(t0 + pd.Timedelta(minutes=step * k))
    idx = pd.DatetimeIndex(rows).tz_convert("UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.0012, len(idx))))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0004, len(idx))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0004, len(idx))))
    return pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c,
                         "volume": rng.integers(1000, 5000, len(idx)).astype(float)}, index=pd.DatetimeIndex(idx, name="ts"))


@pytest.mark.parametrize("name", DAILY)
def test_daily_setups_causal_and_fire(name):
    b = _daily()
    full = STRATEGIES[name](b, SPEC, "1d", {})
    assert set(np.unique(full)) <= {0, 1} and full.index.equals(b.index)
    assert full.iloc[:29].sum() == 0 and full.sum() > 0
    for k in (300, 777, 1200):
        part = STRATEGIES[name](b.iloc[:k], SPEC, "1d", {})
        pd.testing.assert_series_equal(part, full.iloc[:k], check_names=False)


def test_rsi_matches_scan_reference():
    import importlib.util, pathlib
    p = pathlib.Path(__file__).parents[2] / "day_trader/trader-scanner/scan.py"
    spec = importlib.util.spec_from_file_location("scan_ref", p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    c = _daily(200)["close"]
    r = wilder_rsi(c)
    for k in (30, 100, 199):
        assert r.iloc[k] == pytest.approx(m.rsi(list(c.iloc[:k + 1])))


def test_orb_causal_once_per_session_after_range():
    b = _intraday(40)
    full = STRATEGIES["orb"](b, SPEC, "5m", {})
    et = b.index.tz_convert("America/New_York")
    assert full.sum() > 5
    fired = full[full == 1].index.tz_convert("America/New_York")
    assert pd.Series(fired.date).is_unique                       # una volta per sessione
    assert all(t.hour * 60 + t.minute >= 9 * 60 + 45 for t in fired)   # mai prima del completamento del range
    for k in (100, 1000, 2000, 3000):
        part = STRATEGIES["orb"](b.iloc[:k], SPEC, "5m", {})
        pd.testing.assert_series_equal(part, full.iloc[:k], check_names=False)
    # fire bar: close > max high del range e nessuna barra precedente (post-range) lo ha fatto
    for t in fired[:5]:
        day = b[et.date == t.date()]
        e = day.index.tz_convert("America/New_York")
        rng = day[(e.hour * 60 + e.minute) < 9 * 60 + 45]
        assert len(rng) == 3
        post = day[(e.hour * 60 + e.minute) >= 9 * 60 + 45]
        first = post.index[post["close"] > rng["high"].max()][0]
        assert first == t.tz_convert("UTC")


def test_orb_dst_sessions():
    # sessioni a cavallo del cambio ora US (10 marzo 2024) e di quello di novembre (3 nov): 9:30 ET = 13:30 o 14:30 UTC
    b = pd.concat([_intraday(3, "2024-03-07"), _intraday(3, "2024-10-31", vol_seed=1)])
    b = b[~b.index.duplicated()].sort_index()
    utc_open = {d: t.hour * 60 + t.minute for d, t in b.groupby(b.index.tz_convert("America/New_York").date).apply(lambda g: g.index[0]).items()}
    assert utc_open[pd.Timestamp("2024-03-08").date()] == 14 * 60 + 30      # EST
    assert utc_open[pd.Timestamp("2024-03-11").date()] == 13 * 60 + 30      # EDT
    assert utc_open[pd.Timestamp("2024-10-31").date()] == 13 * 60 + 30      # EDT
    assert utc_open[pd.Timestamp("2024-11-04").date()] == 14 * 60 + 30      # EST
    s = STRATEGIES["orb"](b, SPEC, "5m", {})
    e = s[s == 1].index.tz_convert("America/New_York")
    assert len(e) >= 3 and all(t.hour * 60 + t.minute >= 9 * 60 + 45 for t in e)


def test_orb_incomplete_range_and_extended_hours_ignored():
    b = _intraday(5)
    day0 = b.index.tz_convert("America/New_York").date == b.index.tz_convert("America/New_York").date[0]
    b2 = b[~(day0 & (np.arange(len(b)) == 1))]          # manca una barra del range: niente segnale quel giorno
    assert STRATEGIES["orb"](b2, SPEC, "5m", {}).iloc[:78].sum() == 0
    # barre premarket (9:00-9:30 ET) non fanno parte del range
    pre = b.iloc[:1].copy()
    pre.index = pre.index - pd.Timedelta(minutes=30)
    pre["high"] = 1e6
    s = STRATEGIES["orb"](pd.concat([pre, b]), SPEC, "5m", {})
    pd.testing.assert_series_equal(s.iloc[1:], STRATEGIES["orb"](b, SPEC, "5m", {}), check_names=False)
