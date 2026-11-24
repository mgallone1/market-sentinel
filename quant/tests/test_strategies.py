import numpy as np
import pandas as pd
import pytest

from quant.core import crypto_perp, equity
from quant.data import generate_bars
from quant.strategies import STRATEGIES, get_strategy
from quant.strategies.legacy import macro_bias, rome_overnight

REG = [(0.995, 0.0006, 0.004), (0.995, -0.0006, 0.004), (0.99, 0.0, 0.002)]


def _bars(interval="15m", n=6000, seed=1, regimes=REG):
    return generate_bars(n=n, interval=interval, seed=seed, regimes=regimes, start="2024-03-01")


def _ctx(b, name):
    return {"benchmark": b} if name.startswith("legacy") else {}


@pytest.mark.parametrize("interval", ["15m", "1h"])
@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_causality(name, interval):
    b = _bars(interval, n=3000)
    spec = crypto_perp("BTCUSDT", "binance")
    fn = STRATEGIES[name]
    full = fn(b, spec, interval, _ctx(b, name))
    assert set(np.unique(full)) <= {-1, 0, 1} and full.index.equals(b.index)
    for k in (700, 1234, 2001, 2500):
        sub = b.iloc[:k]
        part = fn(sub, spec, interval, _ctx(sub, name))
        pd.testing.assert_series_equal(part, full.iloc[:k], check_names=False)


def test_get_strategy_partial():
    b = _bars("1h", n=1500)
    s = get_strategy("donchian_breakout", n=20)(b, crypto_perp("X"), "1h", {})
    assert (s != 0).sum() > 0


def test_htf_no_unfinished_bar():
    b = _bars("15m", n=3000)
    spec = crypto_perp("BTCUSDT", "binance")
    # ultima barra 15m di un bucket 4h in zona dove il bias e' definito
    idx = b.index[(b.index.hour % 4 == 3) & (b.index.minute == 45)]
    last = idx[idx > b.index[1500]][0]
    pos = b.index.get_loc(last)
    base = macro_bias(b, b.index, "15m")
    b2 = b.copy()
    b2.loc[last, ["close", "high"]] = b.loc[last, "close"] * 0.5   # crollo sulla chiusura 4h
    alt = macro_bias(b2, b2.index, "15m")
    # barre intra-4h (strettamente prima della chiusura del bucket): invariate
    pd.testing.assert_series_equal(base.iloc[:pos], alt.iloc[:pos])
    # segnale legacy: invariato fino alla barra precedente
    s1 = STRATEGIES["legacy"](b, spec, "15m", {"benchmark": b})
    s2 = STRATEGIES["legacy"](b2, spec, "15m", {"benchmark": b2})
    pd.testing.assert_series_equal(s1.iloc[:pos], s2.iloc[:pos])
    # alla chiusura il bias puo' (deve, dato il crollo) cambiare
    assert base.iloc[pos] != alt.iloc[pos] or (base.iloc[pos + 1:pos + 17] != alt.iloc[pos + 1:pos + 17]).any()


def test_legacy_both_sides():
    spec = crypto_perp("BTCUSDT", "binance")
    tot_l = tot_s = 0
    for seed in range(4):
        b = _bars("15m", n=20000, seed=seed, regimes=[(0.999, 0.0012, 0.004), (0.999, -0.0012, 0.004)])
        s = STRATEGIES["legacy"](b, spec, "15m", {"benchmark": b})
        tot_l += int((s == 1).sum()); tot_s += int((s == -1).sum())
    assert tot_l > 0 and tot_s > 0


@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_long_only_equity(name):
    b = _bars("1h", n=3000, seed=3)
    spec = equity("SPY", allow_short=False)
    s = STRATEGIES[name](b, spec, "1h", _ctx(b, name))
    assert (s >= 0).all()


def test_overnight_threshold_dst():
    # 01:00 UTC inverno = 02:00 Roma (notte); luglio 01:00 UTC = 03:00 Roma; 06:00 UTC inverno = 07:00 Roma (giorno)
    w = pd.DatetimeIndex(["2024-01-15 05:00", "2024-01-15 06:00"], tz="UTC")
    assert rome_overnight(w, "15m").tolist() == [True, False]    # 06:15 Roma notte, 07:15 giorno
    s = pd.DatetimeIndex(["2024-07-15 04:00", "2024-07-15 05:00"], tz="UTC")
    assert rome_overnight(s, "15m").tolist() == [True, False]    # 06:15 Roma (CEST) notte, 07:15 giorno
    # a pari ora UTC (05:00) l'esito differisce tra inverno e estate
    assert rome_overnight(w[:1], "15m").iloc[0] and not rome_overnight(s[1:], "15m").iloc[0]


def test_cct_family_causal():
    from quant.core import crypto_perp
    from quant.data.synthetic import generate_bars
    from quant.strategies.cct import cct, flow_only, funding_contrarian, trend_only
    b = generate_bars(n=1500, interval="4h", seed=7)
    spec = crypto_perp("XUSDT", "bybit")
    for fn in (cct, trend_only, funding_contrarian, flow_only):
        full = fn(b, spec, "4h")
        for k in (600, 1000, 1499):
            assert fn(b.iloc[:k], spec, "4h").equals(full.iloc[:k]), fn.__name__
