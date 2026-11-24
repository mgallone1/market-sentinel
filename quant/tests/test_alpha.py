import numpy as np
import pandas as pd

from quant.core import crypto_perp
from quant.backtest import ExitRules, LEGACY_BOT_RULES, run_backtest, triple_barrier_labels
from quant.backtest.carry import run_carry
from quant.data.synthetic import generate_bars
from quant.strategies import STRATEGIES, get_strategy
from quant.strategies.xs_momentum import xs_state

SPEC = crypto_perp("TESTUSDT")


def mk(o, h, l, c, start="2024-01-01", freq="1h"):
    idx = pd.date_range(start, periods=len(o), freq=freq, tz="UTC", name="ts")
    return pd.DataFrame(dict(open=o, high=h, low=l, close=c, volume=1.0), index=idx).astype(float)


def sig_every(bars, k=7, side=1):
    s = pd.DataFrame({"side": 0}, index=bars.index)
    s.iloc[100::k, 0] = side
    return s


# ---------------- maker execution ----------------
RULES = ExitRules(sl_atr=1.5, tp_atr=1.5, max_hold_bars=6)


def test_maker_martingale_zero_gross_and_cheaper():
    bars = generate_bars(30000, "1h", seed=3, with_funding=False)
    sg = sig_every(bars, 5, 1)
    sg.iloc[102::10, 0] = -1
    mk_ = run_backtest(bars, sg, SPEC, RULES, "1h", entry_mode="maker", size_frac=0.1)
    tk = run_backtest(bars, sg, SPEC, RULES, "1h", entry_mode="taker", size_frac=0.1)
    t = mk_.trades
    assert len(t) > 500
    g = t["gross_pnl"] / t["notional"]
    se = g.std() / np.sqrt(len(g))
    assert abs(g.mean()) < 3.5 * se, (g.mean(), se)
    assert (t["costs"] / t["notional"]).mean() < (tk.trades["costs"] / tk.trades["notional"]).mean()
    fr = mk_.metrics["maker_fill_rate"]
    assert 0 < fr < 1 and abs(fr - len(t) / mk_.metrics["maker_orders"]) < 0.02 or fr < 1
    assert tk.metrics["maker_fill_rate"] == 1.0


def test_maker_touch_does_not_fill_but_trade_through_does():
    n = 30
    o = np.full(n, 100.0)
    c = np.full(n, 100.0)
    h = np.full(n, 100.5)
    l = np.full(n, 99.5)
    l[11] = 99.0   # signal bar 10: limit = 100; low 99 < 100*(1-1e-4) -> fill on 11
    bars = mk(o, h, l, c)
    sg = pd.DataFrame({"side": 0}, index=bars.index)
    sg.iloc[10, 0] = 1
    rules = ExitRules(sl_atr=None, tp_atr=None, sl_pct=0.05, tp_pct=0.05, max_hold_bars=3)
    r = run_backtest(bars, sg, SPEC, rules, "1h", entry_mode="maker")
    assert len(r.trades) == 1 and r.trades.iloc[0]["entry_price"] == 100.0
    assert r.trades.iloc[0]["entry_ts"] == bars.index[11]
    # touch only: low == limit exactly (and within through_bps) -> no fill
    l2 = np.full(n, 99.5)
    l2[11] = 100.0
    l2[12] = 99.995  # < 100 but not through by 1 bp
    r2 = run_backtest(mk(o, h, l2, c), sg, SPEC, rules, "1h", entry_mode="maker")
    assert len(r2.trades) == 0 and r2.metrics["maker_fill_rate"] == 0.0
    # deeper in the wait window (bar 12 within max_wait=2) fills, bar 13 not
    l3 = np.full(n, 100.0)
    l3[13] = 90.0
    r3 = run_backtest(mk(o, h, l3, c), sg, SPEC, rules, "1h", entry_mode="maker")
    assert len(r3.trades) == 0
    r4 = run_backtest(mk(o, h, l3, c), sg, SPEC, rules, "1h", entry_mode="maker", max_wait_bars=3)
    assert len(r4.trades) == 1


def test_maker_short_and_no_entry_slippage():
    n = 30
    o = c = np.full(n, 100.0)
    h = np.full(n, 100.0)
    l = np.full(n, 100.0)
    h[11] = 101.0
    bars = mk(o, h, l, c)
    sg = pd.DataFrame({"side": 0}, index=bars.index)
    sg.iloc[10, 0] = -1
    rules = ExitRules(sl_atr=None, tp_atr=None, sl_pct=0.05, tp_pct=0.05, max_hold_bars=3)
    r = run_backtest(bars, sg, SPEC, rules, "1h", entry_mode="maker", size_frac=0.1)
    t = r.trades.iloc[0]
    cm = SPEC.costs
    assert t["entry_price"] == 100.0 and t["side"] == -1
    expect_fee = (cm.maker_fee + cm.taker_fee) * t["notional"]
    assert abs(t["fees"] - expect_fee) < 1e-9
    assert abs(t["slippage"] - cm.slippage_bps / 1e4 * t["notional"]) < 1e-9   # solo uscita


def test_labels_equal_backtest_maker():
    bars = generate_bars(6000, "1h", seed=5, with_funding=True)
    sg = sig_every(bars, 9, 1)
    sg.iloc[104::18, 0] = -1
    kw = dict(entry_mode="maker", offset_bps=3.0, max_wait_bars=2)
    r = run_backtest(bars, sg, SPEC, LEGACY_BOT_RULES, "1h", allow_overlap=True, size_frac=0.1, **kw)
    lab = triple_barrier_labels(bars, sg["side"], LEGACY_BOT_RULES, SPEC, "1h", **kw)
    t = r.trades.sort_values("entry_ts")
    assert len(lab) == len(t) > 50
    assert np.allclose(lab["ret_net"].to_numpy(), t["ret_net"].to_numpy(), atol=1e-12)
    assert (lab["t1"].to_numpy() == t["exit_ts"].to_numpy()).all()


# ---------------- carry ----------------
def carry_bars(n=24 * 40, rate=0.0003, spot_shift=None, perp_shift=None):
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC", name="ts")
    px = np.full(n, 100.0)
    perp = pd.DataFrame(dict(open=px.copy(), high=px + 0, low=px + 0, close=px.copy(), volume=1.0), index=idx)
    spot = perp.drop(columns=[]).copy()
    f = np.full(n, np.nan)
    f[np.arange(n) % 8 == 0] = rate
    perp["funding_rate"] = f
    return perp, spot


def test_carry_constant_funding_equals_funding_minus_fees():
    perp, spot = carry_bars(rate=0.0003)      # 0.0003*1095 = 32.8% APR
    r = run_carry(perp, spot, "1h")
    assert len(r.trades) == 1
    t = r.trades.iloc[0]
    notional = 0.5 * 100_000
    n_fund = int(perp["funding_rate"].iloc[t.name * 0 + perp.index.get_loc(t["enter_ts"]) + 1:].notna().sum())
    assert abs(t["funding"] - n_fund * 0.0003 * notional) < 1e-6
    assert abs(t["basis_pnl"]) < 1e-9
    assert abs(t["net"] - (t["funding"] - t["fees"] - t["slippage"])) < 1e-9
    assert abs(r.equity.iloc[-1] - 100_000 - t["net"]) < 1e-6
    cp, cs = 0.00055, 0.001
    assert abs(t["fees"] - 2 * notional * (cp + cs)) < 1e-6
    assert r.metrics["funding_share"] > 0.99 and r.metrics["time_in_market"] > 0.7


def test_carry_below_threshold_no_trades():
    perp, spot = carry_bars(rate=0.00005)     # 5.5% APR < 10%
    r = run_carry(perp, spot, "1h")
    assert len(r.trades) == 0 and (r.equity == 100_000).all()


def test_carry_basis_sign():
    perp, spot = carry_bars(rate=0.0003)
    n = len(perp)
    # perp si apprezza vs spot dopo ingresso -> short perp perde: basis_pnl < 0
    p2 = perp.copy()
    for c in ("open", "high", "low", "close"):
        p2.iloc[200:, p2.columns.get_loc(c)] = 105.0
    r = run_carry(p2, spot, "1h")
    assert r.trades["basis_pnl"].sum() < 0
    # perp si deprezza (basis si restringe) -> short perp guadagna
    p3 = perp.copy()
    for c in ("open", "high", "low", "close"):
        p3.iloc[200:, p3.columns.get_loc(c)] = 95.0
    r3 = run_carry(p3, spot, "1h")
    assert r3.trades["basis_pnl"].sum() > 0
    # movimento comune: delta-neutral
    r0 = run_carry(p2, p2.drop(columns="funding_rate"), "1h")
    assert abs(r0.trades["basis_pnl"].sum()) < 1e-6


def test_carry_reverse_only_when_allowed():
    perp, spot = carry_bars(rate=-0.0003)
    assert len(run_carry(perp, spot, "1h").trades) == 0
    r = run_carry(perp, spot, "1h", allow_reverse=True)
    assert len(r.trades) == 1 and r.trades.iloc[0]["funding"] > 0


# ---------------- xs momentum ----------------
def universe(n=1500, m=8, drifts=None, seed=0):
    u = {}
    for j in range(m):
        d = (drifts or {}).get(j, 0.0)
        b = generate_bars(n, "1h", seed=seed + j, mu=d, sigma=0.006, with_funding=False)
        u[f"S{j}USDT"] = b
    return u


def test_xs_momentum_causal_prefix():
    u = universe(1200, 6)
    fn = get_strategy("xs_momentum", k=2)
    full = {s: fn(b, crypto_perp(s), "1h", {"universe": u}) for s, b in u.items()}
    cut = 900
    up = {s: b.iloc[:cut] for s, b in u.items()}
    for s, b in up.items():
        part = fn(b, crypto_perp(s), "1h", {"universe": up})
        assert (part.to_numpy() == full[s].iloc[:cut].to_numpy()).all()
    assert "xs_momentum" in STRATEGIES


def test_xs_momentum_neutral_and_picks_planted():
    u = universe(3000, 8, drifts={3: 0.0015}, seed=10)
    st, is_reb = xs_state(u, "1h", k=2)
    rb = st[is_reb].iloc[10:]
    assert ((rb == 1).sum(axis=1) == (rb == -1).sum(axis=1)).all()
    assert ((rb == 1).sum(axis=1) == 2).all()
    frac_top = (rb["S3USDT"] == 1).mean()
    assert frac_top > 0.6 and frac_top > (rb["S0USDT"] == 1).mean()
    lo, _ = xs_state(u, "1h", k=2, allow_short=False)
    assert (lo.min().min() >= 0)


def test_xs_momentum_needs_2k_symbols():
    u = universe(600, 3)
    st, _ = xs_state(u, "1h", k=2)
    assert (st == 0).all().all()
