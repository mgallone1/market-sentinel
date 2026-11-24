import time
import numpy as np
import pandas as pd

from quant.core import AssetSpec, crypto_perp, equity
from quant.backtest import (ExitRules, LEGACY_BOT_RULES, run_backtest, simulate_trade, trade_costs,
                            triple_barrier_labels, fractional_kelly, breakeven_probability, vol_target_fraction)


def mk(o, h, l, c, start="2024-01-01", freq="1h", **extra):
    idx = pd.date_range(start, periods=len(o), freq=freq, tz="UTC", name="ts")
    df = pd.DataFrame(dict(open=o, high=h, low=l, close=c, volume=1.0), index=idx).astype(float)
    for k, v in extra.items():
        df[k] = v
    return df


def arr(df):
    return [df[k].to_numpy(float) for k in ("open", "high", "low", "close")]


def walk(n, sigma, sub=30, seed=0, geometric=False, p0=1000.0):
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, sigma, (n, sub)) / np.sqrt(sub)
    if geometric:
        path = p0 * np.exp(np.cumsum(steps.ravel())).reshape(n, sub)
    else:
        path = p0 + np.cumsum(steps.ravel()).reshape(n, sub)
    prev = np.r_[p0, path[:-1, -1]]
    o = prev
    full = np.concatenate([prev[:, None], path], axis=1)
    return mk(o, full.max(1), full.min(1), path[:, -1])


R_PCT = ExitRules(sl_atr=None, tp_atr=None, sl_pct=0.01, tp_pct=0.02, max_hold_bars=5)


def test_sl_and_tp_same_bar_is_stop():
    df = mk([100, 100, 100], [100, 103, 100], [100, 97, 100], [100, 100, 100])
    o, h, l, c = arr(df)
    assert simulate_trade(o, h, l, c, 1, 1, 100, 99, 102, R_PCT)[1:] == (99.0, "SL")
    assert simulate_trade(o, h, l, c, 1, -1, 100, 101, 98, R_PCT)[1:] == (101.0, "SL")


def test_gap_through_stop_fills_at_open():
    df = mk([100, 100, 95], [100, 100.5, 96], [100, 99.5, 94], [100, 100, 95])
    o, h, l, c = arr(df)
    i, px, r = simulate_trade(o, h, l, c, 0, 1, 100, 99, 102, R_PCT)
    assert (i, px, r) == (2, 95.0, "SL_GAP")
    df = mk([100, 100, 105], [100, 100.5, 106], [100, 99.5, 104], [100, 100, 105])
    o, h, l, c = arr(df)
    assert simulate_trade(o, h, l, c, 0, 1, 100, 99, 102, R_PCT) == (2, 105.0, "TP_GAP")


def test_ratchet_never_loosens_and_moves_stop():
    rules = ExitRules(sl_atr=None, tp_atr=None, sl_pct=0.02, tp_pct=None, max_hold_bars=10,
                      ratchets=((1.0, 0.5), (0.5, -0.9)))
    # close a 102 (1R) -> stop 101; poi close 100.5 non deve allentare; poi low 100.9 -> SL a 101
    df = mk([100, 100, 101.6, 101.3, 100.5], [100, 102.2, 101.8, 101.5, 101], [100, 99.9, 101.5, 100.9, 100.9],
            [100, 102, 101.2, 101.3, 100.6])
    o, h, l, c = arr(df)
    i, px, r = simulate_trade(o, h, l, c, 1, 1, 100, 98, np.inf, rules)
    assert (r, px) == ("SL", 101.0) and i == 3


def test_time_stop_exact():
    n = 20
    df = mk([100] * n, [100.2] * n, [99.8] * n, [100] * n)
    o, h, l, c = arr(df)
    rules = ExitRules(sl_atr=None, tp_atr=None, sl_pct=0.05, tp_pct=0.05, max_hold_bars=7)
    i, px, r = simulate_trade(o, h, l, c, 3, 1, 100, 95, 105, rules)
    assert (i, r) == (9, "TIME")
    i, px, r = simulate_trade(o, h, l, c, 15, 1, 100, 95, 105, rules)
    assert (i, r) == (19, "EOD_DATA")


def test_no_lookahead_entry_at_next_open():
    spec = crypto_perp("X")
    df = walk(300, 0.3, seed=1)
    sig = pd.DataFrame({"side": 0}, index=df.index)
    sig.iloc[100, 0] = 1
    rules = ExitRules(max_hold_bars=10)
    r1 = run_backtest(df, sig, spec, rules, "1h")
    df2 = df.copy()
    df2.iloc[102:] *= 1.5
    r2 = run_backtest(df2, sig, spec, rules, "1h")
    assert r1.trades.entry_price[0] == df.open.iloc[101]
    assert r1.trades.entry_ts[0] == df.index[101]
    assert r2.trades.entry_price[0] == df2.open.iloc[101] == df.open.iloc[101]
    df3 = df.copy()
    df3.iloc[101:] *= 1.5   # cambiare t+1 cambia l'entry, non quello a t
    assert run_backtest(df3, sig, spec, rules, "1h").trades.entry_price[0] == df3.open.iloc[101]


def test_zero_edge_random_walk_costs_only():
    df = walk(100_000, 0.15, sub=30, seed=3)
    rng = np.random.default_rng(4)
    sig = pd.DataFrame({"side": np.where(rng.random(len(df)) < 0.1, rng.choice([-1, 1], len(df)), 0)}, index=df.index)
    spec = crypto_perp("X")
    res = run_backtest(df, sig, spec, ExitRules(), "1h")
    r = res.trades.ret_net
    sl_share = (res.trades.reason == "SL").mean()
    rt = 2 * spec.costs.one_way_frac(False) + sl_share * spec.costs.stop_slippage_bps / 1e4
    se = r.std() / np.sqrt(len(r))
    assert len(r) > 2000
    assert abs(r.mean() + rt) < 3 * se, (r.mean(), rt, se)


def test_funding_sign_long_pays_positive():
    spec = crypto_perp("X")
    n = 10
    f = [np.nan] * n
    f[4] = 0.001
    df = mk([100] * n, [100] * n, [100] * n, [100] * n, funding_rate=f)
    ts = df.index
    cl = trade_costs(spec, 1, 100, 100, 1.0, ts[1], ts[8], df)
    cs = trade_costs(spec, -1, 100, 100, 1.0, ts[1], ts[8], df)
    assert np.isclose(cl["funding"], 0.1) and np.isclose(cs["funding"], -0.1)
    assert trade_costs(spec, 1, 100, 100, 1.0, ts[4], ts[8], df)["funding"] == 0.0  # strettamente dopo l'entry
    assert np.isclose(cl["total"], cl["fees"] + cl["slippage"] + cl["funding"])


def test_labels_equal_isolated_backtest():
    spec = crypto_perp("X")
    df = walk(2000, 0.3, seed=5)
    rules = ExitRules(max_hold_bars=20)
    side = pd.Series(0, index=df.index)
    side.iloc[::97] = 1
    side.iloc[50::131] = -1
    lab = triple_barrier_labels(df, side, rules, spec, "1h")
    assert len(lab) > 10
    for ts, row in lab.iloc[:12].iterrows():
        sg = pd.DataFrame({"side": 0}, index=df.index)
        sg.loc[ts, "side"] = row.side
        tr = run_backtest(df, sg, spec, rules, "1h", size_frac=0.10).trades.iloc[0]
        assert np.isclose(tr.ret_net, row.ret_net, atol=1e-12)
        assert tr.exit_ts == row.t1 and tr.reason == row.exit_reason and np.isclose(tr.R, row.R)
    assert set(lab.label) <= {0, 1}


def test_legacy_rules_driftless_walk():
    df = walk(20000, 0.007, sub=20, seed=7, geometric=True)
    rng = np.random.default_rng(8)
    sig = pd.DataFrame({"side": np.where(rng.random(len(df)) < 0.05, rng.choice([-1, 1], len(df)), 0)}, index=df.index)
    res = run_backtest(df, sig, crypto_perp("X"), LEGACY_BOT_RULES, "1h")
    tr = res.trades
    tp_rate = tr.reason.isin(["TP", "TP_GAP"]).mean()
    print(tr.reason.value_counts(normalize=True).to_dict(), tr.ret_net.mean())
    assert len(tr) > 300
    assert tp_rate < 0.06, tp_rate
    assert tr.ret_net.mean() < 0


def test_equity_rth_flatten_eod():
    # 2 giorni, 7 barre/giorno 1h dalle 14:30 UTC (9:30 ET inverno)
    days = []
    for d in ("2024-01-08", "2024-01-09"):
        days.append(pd.date_range(f"{d} 14:30", periods=7, freq="1h", tz="UTC"))
    idx = days[0].append(days[1])
    n = len(idx)
    px = 100 + np.arange(n) * 0.01
    df = pd.DataFrame(dict(open=px, high=px + 0.05, low=px - 0.05, close=px + 0.005, volume=1.0), index=idx)
    df.index.name = "ts"
    spec = equity("AAPL")
    sig = pd.DataFrame({"side": 0}, index=idx)
    sig.iloc[1, 0] = 1
    rules = ExitRules(sl_atr=None, tp_atr=None, sl_pct=0.05, tp_pct=0.05, max_hold_bars=100, flatten_eod=True)
    tr = run_backtest(df, sig, spec, rules, "1h").trades.iloc[0]
    assert tr.reason == "EOD_SESSION" and tr.exit_ts == idx[6]
    # segnale fuori sessione ignorato
    idx2 = idx.append(pd.DatetimeIndex([idx[-1] + pd.Timedelta(hours=3)]))
    df2 = pd.concat([df, df.iloc[[-1]].set_axis(idx2[-1:])])
    df2.index.name = "ts"
    sg2 = pd.DataFrame({"side": 0}, index=idx2)
    sg2.iloc[-2, 0] = 1
    assert len(run_backtest(df2, sg2, spec, rules, "1h").trades) == 0


def test_sizing_helpers():
    assert fractional_kelly(0.4, 1.0) == 0.0
    assert np.isclose(fractional_kelly(0.6, 1.0, lam=0.5), 0.1)
    assert fractional_kelly(0.99, 10, lam=1.0, cap=0.25) == 0.25
    assert np.isclose(breakeven_probability(2.0, 1.0, 0.1), 1.1 / 3.0)
    assert vol_target_fraction(0.8) == 0.25 and vol_target_fraction(0.1) == 1.0


def test_speed_labels_20k():
    spec = crypto_perp("X")
    df = walk(20000, 0.3, seed=9)
    t0 = time.time()
    lab = triple_barrier_labels(df, 1, ExitRules(max_hold_bars=48, sl_atr=6, tp_atr=12), spec, "1h")
    assert len(lab) > 19000 and time.time() - t0 < 15


def test_legacy_rules_gross_pnl_zero_on_martingale():
    """Teorema di arresto opzionale: nessuna regola di uscita crea edge lordo su una martingala.
    Usa il generatore con estremi da ponte browniano (fill allo stop esatto per un percorso continuo)."""
    from quant.backtest import LEGACY_BOT_RULES
    from quant.data.synthetic import generate_bars
    spec = crypto_perp("X")
    g = []
    for seed in range(4):
        b = generate_bars(n=20000, interval="1h", seed=seed, sigma=0.007, with_funding=False)
        rng = np.random.default_rng(50 + seed)
        sig = pd.DataFrame({"side": rng.choice([-1, 1], len(b))}, index=b.index)
        t = run_backtest(b, sig, spec, LEGACY_BOT_RULES, "1h").trades
        g.append((t.gross_pnl / t.notional).values)
    g = np.concatenate(g)
    se = g.std() / np.sqrt(len(g))
    assert abs(g.mean()) < 3.5 * se, (g.mean(), se)
