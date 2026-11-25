"""Test offline delle strategie del lab con MarketData sintetico."""
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from quant.lab.strategies import default_strategies
from quant.lab.strategies._util import is_last_trading_day_of_month
from quant.lab.strategies.brent_wti_grid import BrentWtiSpreadGrid, replay_grid
from quant.lab.strategies.crypto_breakout import CryptoBreakout4hMaker
from quant.lab.strategies.funding_carry import FundingCarry, carry_state
from quant.lab.strategies.tsmom_monthly import TsmomMonthly


def _ohlc(c, idx):
    c = np.asarray(c, float)
    return pd.DataFrame({"open": np.r_[c[0], c[:-1]], "high": c * 1.004, "low": c * 0.996, "close": c,
                         "volume": 1.0}, index=idx)


class FakeData:
    """Genera serie casuali deterministiche; restituisce solo barre con open <= now (il filtro 'chiuse' e' della strategia)."""
    def __init__(self, seed=0, funding_apr=None, drift=0.0003):
        self.seed, self.funding_apr, self.drift = seed, funding_apr, drift
        self.max_ts_seen = None

    def _walk(self, key, n, vol, p0):
        r = np.random.default_rng(abs(hash(key)) % 2**31 + self.seed)
        r = np.random.default_rng([self.seed, sum(map(ord, key))])
        return p0 * np.exp(np.cumsum(r.normal(self.drift, vol, n)))

    def bars(self, source, symbol, interval, lookback_days, now_utc):
        now = pd.Timestamp(now_utc)
        if interval == "1d":
            idx = pd.date_range("2022-01-03", "2027-01-01", freq="D", tz="UTC")
            if symbol not in ("BTC-USD", "ETH-USD"):
                idx = idx[idx.dayofweek < 5]
            c = self._walk(symbol, len(idx), 0.01, 60.0)
            if symbol == "BZ=F":
                c = c + 4
        else:
            idx = pd.date_range("2024-01-01", "2027-01-01", freq="4h", tz="UTC")
            c = self._walk(symbol, len(idx), 0.01, 100.0)
        df = _ohlc(c, idx)
        df = df[df.index <= now]
        self.max_ts_seen = df.index.max()
        return df.iloc[-int(lookback_days * (6 if interval == "4h" else 1.5)):] if interval != "1d" else df

    def last_price(self, source, symbol, now_utc):
        return float(self.bars(source, symbol, "1d", 5, now_utc)["close"].iloc[-1])

    def funding(self, symbol, lookback_days, now_utc):
        idx = pd.date_range("2025-01-01", "2027-01-01", freq="8h", tz="UTC")
        apr = self.funding_apr(idx) if callable(self.funding_apr) else np.full(len(idx), self.funding_apr or 0.0)
        s = pd.Series(np.asarray(apr) / (365 * 3), index=idx)
        return s[s.index <= pd.Timestamp(now_utc)]


def _valid(dec):
    ws = [t.weight for t in dec.targets]
    assert all(math.isfinite(w) for w in ws)
    assert sum(abs(w) for w in ws) <= 1.0 + 1e-9
    assert dec.note
    for t in dec.targets:
        assert t.reason and isinstance(t.features, dict)


@pytest.mark.parametrize("strat,now", [
    (TsmomMonthly(), "2026-10-30 21:15"),
    (BrentWtiSpreadGrid(), "2026-06-10 20:45"),
    (FundingCarry(), "2026-06-10 00:10"),
    (CryptoBreakout4hMaker(), "2026-06-10 04:02"),
])
def test_valid_decisions(strat, now, monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_STATE_DIR", str(tmp_path))
    d = FakeData(funding_apr=0.2)
    dec = strat.decide(pd.Timestamp(now, tz="UTC"), d)
    _valid(dec)
    assert dec.strategy == strat.name and dec.version == "1.0"
    assert len(dec.targets) > 0


def test_registry_env(monkeypatch):
    assert len(default_strategies()) == 4
    monkeypatch.setenv("LAB_STRATEGIES", "funding_carry")
    assert [s.name for s in default_strategies()] == ["funding_carry"]


def test_no_future_data_prefix(monkeypatch, tmp_path):
    """Modificare i dati dopo `now` non cambia la decisione (le strategie vedono solo il passato chiuso)."""
    monkeypatch.setenv("LAB_STATE_DIR", str(tmp_path))
    now = pd.Timestamp("2026-06-10 20:45", tz="UTC")

    class Poisoned(FakeData):
        def bars(self, *a, **k):
            df = super().bars(*a, **k)
            fut = pd.DataFrame({c: [1e6] for c in df.columns}, index=[df.index[-1] + pd.Timedelta(hours=1)])
            return pd.concat([df, fut])

        def funding(self, symbol, lookback_days, now_utc):
            s = super().funding(symbol, lookback_days, now_utc)
            return pd.concat([s, pd.Series([5.0], index=[pd.Timestamp(now_utc) + pd.Timedelta(hours=1)])])

        def last_price(self, source, symbol, now_utc):
            return FakeData.last_price(self, source, symbol, now_utc)

    for strat in (BrentWtiSpreadGrid(), FundingCarry(), CryptoBreakout4hMaker()):
        a = strat.decide(now, FakeData(funding_apr=0.2))
        b = strat.decide(now, Poisoned(funding_apr=0.2))
        assert [t.weight for t in a.targets] == [t.weight for t in b.targets], strat.name


def test_grid_lag_one_day(monkeypatch, tmp_path):
    """Un segnale al giorno t cambia i target solo dal giorno t+1: la barra di oggi non e' mai visibile."""
    monkeypatch.setenv("LAB_STATE_DIR", str(tmp_path))
    idx = pd.bdate_range("2023-01-02", periods=300, tz="UTC")
    rng = np.random.default_rng(3)
    cl = pd.Series(70 + np.cumsum(rng.normal(0, .3, 300)), index=idx)
    spread = pd.Series(4 + rng.normal(0, .3, 300), index=idx)
    t = 250
    spread.iloc[t] = spread.iloc[t - 1] - 0.9           # shock: apre unita' long al giorno t
    bz = cl + spread

    class D:
        def bars(self, src, sym, itv, lb, now):
            x = bz if sym == "BZ=F" else cl
            return _ohlc(x.to_numpy(), x.index)[lambda df: df.index <= pd.Timestamp(now)]

        def last_price(self, src, sym, now):
            return 70.0 + (4 if sym == "BZ=F" else 0)

    s = BrentWtiSpreadGrid()
    day = lambda k: idx[k] + pd.Timedelta(hours=20, minutes=45)
    f = lambda k: s.decide(day(k), D()).targets[0].features
    f0, f1, f2 = f(t - 1), f(t), f(t + 1)
    key = lambda x: (x["units_long"], x["units_short"])
    l1, s1 = replay_grid(spread.iloc[:t].to_numpy())
    assert key(f1) == (len(l1), len(s1))
    assert f1["last_signal_date"] == str(idx[t - 1].date())   # al giorno t la barra di t non e' visibile
    assert f2["last_signal_date"] == str(idx[t].date())       # il segnale di t e' agito a t+1
    sl, ss = replay_grid(spread.iloc[:t + 1].to_numpy())
    assert key(f2) == (len(sl), len(ss))
    assert f0["last_signal_date"] == str(idx[t - 2].date())


def test_grid_replay_closes_at_step():
    s = np.r_[np.full(70, 4.0) + np.random.default_rng(0).normal(0, .2, 70), 3.0, 3.0, 5.0]
    longs, shorts = replay_grid(s)
    assert len(longs) <= 8 and len(shorts) <= 8


def test_carry_thresholds():
    idx = pd.date_range("2025-01-01", periods=60, freq="8h", tz="UTC")
    f = lambda apr: pd.Series(np.full(60, apr / 1095.0), index=idx)
    assert carry_state(f(0.12))[0] is True
    assert carry_state(f(0.09))[0] is False
    # isteresi: sale sopra 10% poi scende a 5% (tra 3 e 10) -> resta attivo; sotto 3% -> esce
    v = np.r_[np.full(20, 0.15), np.full(40, 0.05)] / 1095.0
    assert carry_state(pd.Series(v, index=idx))[0] is True
    v = np.r_[np.full(20, 0.15), np.full(40, 0.01)] / 1095.0
    assert carry_state(pd.Series(v, index=idx))[0] is False


def test_carry_weights_split():
    dec = FundingCarry().decide(pd.Timestamp("2026-06-10 08:10", tz="UTC"), FakeData(funding_apr=0.2))
    perp = [t.weight for t in dec.targets if t.instrument.key.startswith("BYBIT:")]
    spot = [t.weight for t in dec.targets if t.instrument.key.startswith("BYBIT_SPOT:")]
    assert perp == [-0.1] * 5 and spot == [0.1] * 5
    off = FundingCarry().decide(pd.Timestamp("2026-06-10 08:10", tz="UTC"), FakeData(funding_apr=0.01))
    assert all(t.weight == 0 for t in off.targets)


def test_tsmom_month_end_only():
    assert is_last_trading_day_of_month(date(2026, 10, 30))
    assert not is_last_trading_day_of_month(date(2026, 10, 29))
    assert not is_last_trading_day_of_month(date(2026, 10, 31))     # sabato
    assert is_last_trading_day_of_month(date(2026, 11, 30)) and not is_last_trading_day_of_month(date(2026, 11, 27))
    s, d = TsmomMonthly(), FakeData(drift=0.0006)
    hold = s.decide(pd.Timestamp("2026-10-27 21:15", tz="UTC"), d)
    hold2 = s.decide(pd.Timestamp("2026-10-29 21:15", tz="UTC"), d)
    reb = s.decide(pd.Timestamp("2026-10-30 21:15", tz="UTC"), d)
    assert hold.note.startswith("hold") and hold2.note.startswith("hold")
    assert [t.weight for t in hold.targets] == [t.weight for t in hold2.targets]
    assert reb.note.startswith("ribilancio")
    assert sum(t.weight for t in reb.targets) <= 1.0 + 1e-9 and min(t.weight for t in reb.targets) >= 0
