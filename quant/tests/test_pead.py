import numpy as np
import pandas as pd

from quant.research import pead

DAYS = pd.bdate_range("2024-01-01", "2024-06-28")  # nessuna festivita: usiamo anche un indice con buco


def ts(s):
    return pd.Timestamp(s, tz="America/New_York")


def test_premarket_same_day_open():
    i = pead.reaction_day_index(ts("2024-03-05 07:00"), DAYS)
    assert DAYS[i] == pd.Timestamp("2024-03-05")


def test_after_close_next_day_and_unknown_time():
    assert DAYS[pead.reaction_day_index(ts("2024-03-05 16:05"), DAYS)] == pd.Timestamp("2024-03-06")
    assert DAYS[pead.reaction_day_index(ts("2024-03-05 00:00"), DAYS)] == pd.Timestamp("2024-03-06")


def test_weekend_and_holiday():
    # venerdi dopo la chiusura -> lunedi
    assert DAYS[pead.reaction_day_index(ts("2024-03-08 17:00"), DAYS)] == pd.Timestamp("2024-03-11")
    # sabato pre-market -> lunedi
    assert DAYS[pead.reaction_day_index(ts("2024-03-09 07:00"), DAYS)] == pd.Timestamp("2024-03-11")
    # festivo (2024-03-29 Good Friday assente dall'indice)
    d = DAYS.delete(DAYS.get_loc(pd.Timestamp("2024-03-29")))
    assert d[pead.reaction_day_index(ts("2024-03-28 17:00"), d)] == pd.Timestamp("2024-04-01")
    assert d[pead.reaction_day_index(ts("2024-03-29 07:00"), d)] == pd.Timestamp("2024-04-01")


def test_entry_never_before_announcement_and_skips_day1():
    for t in ["2024-03-05 07:00", "2024-03-05 16:30", "2024-03-08 20:00", "2024-03-09 09:00"]:
        a = ts(t)
        i_in, i_out = pead.entry_exit_index(a, DAYS)
        r = pead.reaction_day_index(a, DAYS)
        assert i_in == r + 1 and i_out == r + 20
        # l'open d'entrata (09:30 ET) e' strettamente dopo l'annuncio
        assert pd.Timestamp(DAYS[i_in]).tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30) > a
        assert i_out - i_in == 19  # open g2 -> close g21 = 20 sedute


def test_none_when_window_exceeds_data():
    assert pead.entry_exit_index(ts("2024-06-20 17:00"), DAYS) is None


def test_market_adjustment_arithmetic():
    adj, raw = pead.net_event_return(0.10, 0.04, 1)
    assert np.isclose(adj, 0.06 - 0.001) and np.isclose(raw, 0.10 - 0.001)
    adj, raw = pead.net_event_return(-0.10, -0.04, -1)
    borrow = 0.01 * 20 / 252
    assert np.isclose(adj, 0.06 - 0.001 - borrow) and np.isclose(raw, 0.10 - 0.001 - borrow)


def test_window_returns_uses_open_entry_close_exit():
    idx = pd.bdate_range("2024-01-01", periods=30)
    st = pd.DataFrame({"open": np.arange(100, 130.0), "close": np.arange(101, 131.0)}, index=idx)
    sp = pd.DataFrame({"open": 100.0, "close": 100.0}, index=idx)
    rs, rm = pead.window_returns(st, sp, 2, 21, idx)
    assert np.isclose(rs, 122 / 102 - 1) and rm == 0


def test_surprise_and_sides():
    assert np.isclose(pead.surprise_pct(1.1, 1.0), 0.1) and np.isclose(pead.surprise_pct(-0.5, -1.0), 0.5)
    assert np.isnan(pead.surprise_pct(1, 0))
    assert pead.side_of(0.06) == 1 and pead.side_of(-0.06) == -1 and pead.side_of(0.05) == 0
    assert pead.side_of(-0.2, long_only=True) == 0


def test_random_control_reproducible():
    idx = pd.bdate_range("2023-01-02", periods=300)
    rng = np.random.default_rng(0)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.01, 300))
    px = pd.DataFrame({"open": c, "close": c}, index=idx)
    spy = px.copy() * 1.0
    spy["close"] = spy["close"] * np.linspace(1, 1.2, 300)
    ev = pd.DataFrame({"ticker": ["X", "X", "X"], "side": [1, -1, 1]})
    a = pead.random_control(ev, {"X": px}, spy, idx, n_rep=5)
    b = pead.random_control(ev, {"X": px}, spy, idx, n_rep=5)
    c2 = pead.random_control(ev, {"X": px}, spy, idx, n_rep=5, seed=1)
    assert a.shape == (3, 5) and np.allclose(a, b) and not np.allclose(a, c2)
