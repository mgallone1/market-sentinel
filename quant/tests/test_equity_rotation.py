import numpy as np
import pandas as pd

from quant.portfolio.equity_rotation import (cash_daily, month_ends, rotation_weights, run, tom_flags, tom_weights)


def cal(start="2020-01-01", end="2020-06-30", drop=()):
    i = pd.bdate_range(start, end)
    return i.drop(pd.to_datetime(list(drop)))


def test_tom_window_with_holiday():
    # 2020-04-10 Good Friday assente; 2020-03-31 martedi' = ultimo giorno
    idx = cal(drop=["2020-04-10"])
    f = tom_flags(idx)
    on = list(f[f].index.strftime("%Y-%m-%d"))
    # marzo: penultimo 03-30, ultimo 03-31; aprile: 04-01, 04-02 (close del 3o giorno 04-03 = uscita)
    assert {"2020-03-30", "2020-03-31", "2020-04-01", "2020-04-02"} <= set(on)
    assert "2020-04-03" not in on and "2020-03-27" not in on
    # aprile: ultimo giorno 04-30, penultimo 04-29
    assert {"2020-04-29", "2020-04-30", "2020-05-01", "2020-05-04"} <= set(on)  # 05-01 e' venerdi', 05-04 lunedi'
    assert "2020-05-05" not in on


def test_tom_uses_actual_calendar_month_end_holiday():
    idx = cal("2020-06-01", "2020-07-31", drop=["2020-07-03"])  # 06-30 martedi', festivo 3 luglio
    f = tom_flags(idx)
    assert f["2020-06-29"] and f["2020-06-30"] and f["2020-07-01"] and f["2020-07-02"]
    assert not f["2020-07-06"]  # 3o giorno di luglio = 07-06: li' si e' gia' flat (peso 0 deciso al suo close)


def test_tom_hold_and_cost_on_turnover():
    idx = cal("2020-01-01", "2020-03-31")
    px = pd.DataFrame({"A": 100.0 * np.cumprod(np.full(len(idx), 1.001))}, index=idx)
    cash = pd.Series(0.0, index=idx)
    w = tom_weights(px, ["A"])
    res, net, gross = run(px, w, cash, 2.0)
    entries = (w["A"].diff().fillna(w["A"]).abs()).sum()
    assert abs(res.turnover.sum() - entries) < 1e-12  # un'unita' per ogni ingresso/uscita
    assert abs((gross - net).sum() - entries * 2e-4) < 1e-12


def test_cash_on_uninvested_share():
    idx = cal("2020-01-01", "2020-02-28")
    px = pd.DataFrame({"A": np.full(len(idx), 100.0)}, index=idx)
    cash = pd.Series(0.0004, index=idx)
    _, net, _ = run(px, pd.DataFrame({"A": 0.0}, index=idx), cash, 2.0)
    assert abs(net.iloc[5] - 0.0004) < 1e-15


def synth_monthly(seed=0, n=900):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n)
    r = rng.normal(0.0003, 0.01, (n, 5))
    return pd.DataFrame(100 * np.cumprod(1 + r, axis=0), index=idx, columns=list("ABCDE"))


def test_rank_prefix_no_lookahead():
    p = synth_monthly()
    cash = pd.Series(0.00005, index=p.index)
    W, _ = rotation_weights(p, cash, 3)
    cut = month_ends(p.index)[30]
    pre, _ = rotation_weights(p.loc[:cut], cash.loc[:cut], 3)
    pd.testing.assert_frame_equal(W.loc[:cut].iloc[:-1], pre.iloc[:-1])
    assert (W.loc[cut] == pre.loc[cut]).all()


def test_abs_filter_and_top_n_and_history():
    idx = pd.bdate_range("2015-01-01", periods=700)
    t = np.arange(len(idx))
    px = pd.DataFrame({"UP": 100 * 1.001 ** t, "DN": 100 * 0.9995 ** t, "UP2": 100 * 1.0005 ** t}, index=idx)
    px.loc[:idx[300], "UP2"] = np.nan  # storia corta: ammesso solo dopo 13 mesi
    cash = pd.Series(0.00008, index=idx)   # ~2% annuo: DN sotto, UP2 sopra
    W, elig = rotation_weights(px, cash, 2)
    last = W.iloc[-1]
    assert last["UP"] == 0.5 and last["UP2"] == 0.5 and last["DN"] == 0.0  # filtro assoluto: DN escluso
    first_ok = W.index[elig["UP2"].values.argmax()]
    assert first_ok > idx[300] + pd.DateOffset(months=12)
    assert W.loc[:first_ok].iloc[:-1]["UP2"].eq(0).all()
    # con T-bill altissimo tutti gli slot vanno in cash
    W2, _ = rotation_weights(px, pd.Series(0.01, index=idx), 2)
    assert W2.iloc[-1].sum() == 0.0
