import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from quant.core import AssetSpec, validate_bars
from quant.data import binance_vision as bv
from quant.data import bybit, cache
from quant.data import load_bars, yahoo
from quant.data.synthetic import generate_bars, generate_bars_with_signal
from quant.validation import spearman_ic


def _zip(text, name="x.csv"):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


HDR = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
ROWS = ["1704067200000,10,12,9,11,100,1704070799999,1,1,40,1,0", "1704070800000,11,13,10,12,200,1704074399999,1,1,90,1,0"]


@pytest.mark.parametrize("header", [True, False])
@pytest.mark.parametrize("micro", [False, True])
def test_parse_klines(header, micro):
    rows = [r.replace("1704067200000", "1704067200000000").replace("1704070800000", "1704070800000000")
            if micro else r for r in ROWS]
    df = bv.parse_klines(_zip((HDR if header else "") + "\n".join(rows) + "\n"))
    assert list(df.index) == [pd.Timestamp("2024-01-01 00:00", tz="UTC"), pd.Timestamp("2024-01-01 01:00", tz="UTC")]
    assert df["taker_buy_volume"].tolist() == [40.0, 90.0] and df["close"].dtype == "float64"
    validate_bars(df)


def test_funding_and_oi_attach():
    bars = pd.DataFrame({"close": 1.0}, index=pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC", name="ts"))
    f = bv.parse_funding(_zip("calc_time,funding_interval_hours,last_funding_rate\n1704096000123,8,0.0003\n"))
    out = bv.attach_funding(bars, f, "1h")
    assert out["funding_rate"].notna().sum() == 1
    assert out.loc[pd.Timestamp("2024-01-01 08:00", tz="UTC"), "funding_rate"] == 0.0003
    m = bv.parse_metrics(_zip("create_time,symbol,sum_open_interest\n2024-01-01 00:05:00,X,5\n2024-01-01 00:55:00,X,7\n"))
    o = bv.attach_oi(bars, m, "1h")["open_interest"]
    assert o.iloc[0] == 7 and o.iloc[1] == 7 and np.isnan(o.iloc[2])


def test_binance_get_bars_monthly_404_and_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    calls = []

    def fake(url, timeout=60.0):
        calls.append(url)
        if "2024-01" in url and "klines" in url:
            return _zip(HDR + "\n".join(ROWS) + "\n")
        return None

    monkeypatch.setattr(bv, "_fetch", fake)
    now = pd.Timestamp("2024-06-15", tz="UTC")
    df = bv.get_bars("BTCUSDT", "1h", "2024-01-01", "2024-02-28", now=now)
    assert len(df) == 2 and "funding_rate" in df
    bv.get_bars("BTCUSDT", "1h", "2024-01-01", "2024-02-28", now=now)
    assert sum("klines/BTCUSDT/1h/BTCUSDT-1h-2024-01" in c for c in calls) == 1  # mese chiuso dalla cache


def test_forming_bar_dropped():
    df = generate_bars(10, "1h", start="2024-01-01")
    now = df.index[-1] + pd.Timedelta(minutes=30)
    assert len(cache.drop_forming(df, "1h", now)) == 9


def test_bybit_mocked(monkeypatch):
    t0 = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    hour = 3600_000
    kl = [[str(t0 + i * hour), "10", "12", "9", "11", "5", "50"] for i in range(5)][::-1]

    def fake(path, params, timeout=20.0):
        if "kline" in path:
            lst = [r for r in kl if int(r[0]) <= params["end"]]
            return {"retCode": 0, "result": {"list": lst}}
        if "funding" in path:
            return {"retCode": 0, "result": {"list": [{"fundingRate": "0.0001", "fundingRateTimestamp": str(t0 + 2 * hour)}]}}
        return {"retCode": 0, "result": {"list": []}}

    monkeypatch.setattr(bybit, "_http_get_json", fake)
    s, e = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-01-01 04:00", tz="UTC")
    df = bybit.fetch_klines("BTCUSDT", "1h", s, e)
    assert len(df) == 5 and df.index.is_monotonic_increasing
    validate_bars(df)
    out = bybit._fetch_range("BTCUSDT", "1h", s, e, False)
    assert out["funding_rate"].notna().sum() == 1


def test_load_bars_bybit_fallback(monkeypatch):
    spec = AssetSpec("BTCUSDT", "crypto_perp", "bybit")
    syn = generate_bars(50)

    def boom(self, *a, **k):
        raise OSError("geo-blocked")

    monkeypatch.setattr(bybit.BybitProvider, "get_bars", boom)
    monkeypatch.setattr(bv, "get_bars", lambda *a, **k: syn)
    assert len(load_bars(spec, "1h", "2024-01-01", "2024-01-05")) == 50
    with pytest.raises(OSError):
        load_bars(spec, "1h", "2024-01-01", "2024-01-05", research_proxy=False)


def test_yahoo_normalize():
    idx = pd.date_range("2024-01-02 09:30", periods=4, freq="1h", tz="America/New_York")
    cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["SPY"]])
    raw = pd.DataFrame(np.tile([10.0, 12, 9, 11, 100], (4, 1)), index=idx, columns=cols)
    now = idx[-1].tz_convert("UTC") + pd.Timedelta(minutes=10)
    df = yahoo.normalize(raw, "1h", now)
    assert str(df.index.tz) == "UTC" and len(df) == 3
    validate_bars(df)


def test_synthetic_valid_and_deterministic():
    a, b = generate_bars(2000, seed=3), generate_bars(2000, seed=3)
    pd.testing.assert_frame_equal(a, b)
    validate_bars(a)
    assert (a["taker_buy_volume"].between(0, a["volume"])).all()
    assert a["funding_rate"].notna().sum() == 2000 // 8
    r = generate_bars(3000, regimes=[(0.99, 0.0005, 0.003), (0.98, -0.0005, 0.02)])
    validate_bars(r)


def test_planted_signal_ic():
    h = 12
    df = generate_bars_with_signal(40000, seed=1, ic=0.2, horizon=h)
    validate_bars(df)
    fwd = np.log(df["close"].shift(-h) / df["close"])
    assert abs(spearman_ic(df["planted_signal"], fwd) - 0.2) < 0.07
