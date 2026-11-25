import datetime as dt
import pytest
from services import risk_limits as rl

UTC = dt.timezone.utc
# Tue 2026-11-24 15:00 UTC = 10:00 ET (inside the equity window)
NOW = dt.datetime(2026, 11, 24, 15, 0, tzinfo=UTC)


@pytest.fixture
def st(tmp_path):
    return rl.RiskState(str(tmp_path / "risk.json"))


@pytest.fixture
def cfg(tmp_path):
    return rl.RiskConfig()


def chk(cfg, st, broker="BYBIT", equity=100000, pos=(), entry=100.0, stop=99.0, tp=102.0, qty=500, now=NOW, **kw):
    return rl.check_entry(cfg, st, broker, equity, list(pos), entry, stop, tp, qty, now, **kw)


def test_allow_basic(cfg, st):
    assert chk(cfg, st) == (True, "")


def test_disabled_allows_everything(st):
    c = rl.RiskConfig(enabled=False)
    assert chk(c, st, stop=None)[0] is True


def test_require_stop(cfg, st):
    ok, why = chk(cfg, st, stop=None)
    assert not ok and why.startswith("NO_STOP")
    assert chk(rl.RiskConfig(require_stop=False), st, stop=None)[0]


def test_per_trade_loss_boundary_refuses_not_shrinks(cfg, st):
    # loss = 1.0 * qty ; limit 0.75% of 100k = 750
    assert chk(cfg, st, qty=750)[0]
    ok, why = chk(cfg, st, qty=751)
    assert not ok and why.startswith("TRADE_RISK")


def test_notional_mode(cfg, st):
    # notional 75000 @100 = 750 units -> loss 750 allowed; 75100 blocked
    assert chk(cfg, st, qty=75000, is_notional=True)[0]
    assert not chk(cfg, st, qty=75100, is_notional=True)[0]


def test_reward_risk(cfg, st):
    assert chk(cfg, st, tp=101.5)[0]
    ok, why = chk(cfg, st, tp=101.49)
    assert not ok and why.startswith("REWARD_RISK")


def test_open_risk_cap(cfg, st):
    # new risk 700; existing 2300 (stop known) -> 3000 = 3% allowed; +1 blocked
    pos = [{"entry_price": 100, "size": 2300, "stop_loss": 99}]
    assert chk(cfg, st, pos=pos, qty=700)[0]
    ok, why = chk(cfg, st, pos=pos, qty=701)
    assert not ok and why.startswith("OPEN_RISK")


def test_open_risk_fallback_stop(cfg):
    # no stop info -> notional * 1.2%
    assert rl.open_risk_usd(cfg, [{"entry_price": 100, "size": 1000}]) == pytest.approx(1200)


def test_daily_loss_limit(cfg, st):
    st.rec("BYBIT", NOW, 100000)
    assert chk(cfg, st, equity=98001)[0]
    ok, why = chk(cfg, st, equity=98000)
    assert not ok and why.startswith("DAILY_LOSS")


def test_daily_loss_realized(cfg, st):
    st.rec("BYBIT", NOW, 100000)
    rl.record_close(cfg, st, "BYBIT", -2000, NOW)
    assert chk(cfg, st, equity=100000)[1].startswith("DAILY_LOSS")


def test_trades_per_day_per_broker(st):
    # Il limite giornaliero e' opzionale (default 0 = illimitato, commit 34e99c7): qui lo si attiva esplicitamente.
    c = rl.RiskConfig(max_trades_per_day=6)
    for _ in range(6):
        rl.record_open(c, st, "BYBIT", 100000, NOW)
    assert chk(c, st)[1].startswith("TRADES_PER_DAY")
    assert chk(c, st, broker="ALPACA")[0]  # other broker unaffected


def test_default_has_no_daily_trade_cap(cfg, st):
    for _ in range(20):
        rl.record_open(cfg, st, "BYBIT", 100000, NOW)
    assert chk(cfg, st)[0]


def test_max_concurrent_trades(cfg, st):
    # 6 posizioni aperte (rischio aperto trascurabile) -> la settima entrata e' bloccata
    pos = [dict(symbol=f"S{i}", side="BUY", entry_price=100.0, size=0.01, stop_loss=99.9) for i in range(6)]
    ok, why = chk(cfg, st, pos=pos)
    assert not ok and why.startswith("MAX_CONCURRENT_TRADES")
    assert chk(cfg, st, pos=pos[:5])[0]


def test_cooldown_then_release(cfg, st):
    for _ in range(4):
        rl.record_close(cfg, st, "BYBIT", -1, NOW)
    ok, why = chk(cfg, st)
    assert not ok and why.startswith("COOLDOWN")
    assert not chk(cfg, st, now=NOW + dt.timedelta(minutes=239))[0]
    assert chk(cfg, st, now=NOW + dt.timedelta(minutes=241))[0]


def test_win_resets_streak(cfg, st):
    for _ in range(3):
        rl.record_close(cfg, st, "BYBIT", -1, NOW)
    rl.record_close(cfg, st, "BYBIT", 5, NOW)
    rl.record_close(cfg, st, "BYBIT", -1, NOW)
    assert chk(cfg, st)[0]


def test_alpaca_window_and_holiday(cfg, st):
    def at(h, m, day=24):
        return dt.datetime(2026, 11, day, h, m, tzinfo=UTC)
    # 14:44 UTC = 09:44 ET (EST) blocked; 14:45 allowed; 20:30 = 15:30 allowed; 20:31 blocked
    assert chk(cfg, st, broker="ALPACA", now=at(14, 44))[1].startswith("SESSION")
    assert chk(cfg, st, broker="ALPACA", now=at(14, 45))[0]
    assert chk(cfg, st, broker="ALPACA", now=at(20, 30))[0]
    assert chk(cfg, st, broker="ALPACA", now=at(20, 31))[1].startswith("SESSION")
    assert "holiday" in chk(cfg, st, broker="ALPACA", now=at(16, 0, 26))[1]   # Thanksgiving
    assert "weekend" in chk(cfg, st, broker="ALPACA", now=at(16, 0, 28))[1]
    # crypto is not subject to the equity window
    assert chk(cfg, st, broker="BYBIT", now=at(3, 0, 28))[0]


def test_dst_window(cfg, st):
    # July: 13:45 UTC = 09:45 EDT
    assert chk(cfg, st, broker="ALPACA", now=dt.datetime(2026, 7, 14, 13, 45, tzinfo=UTC))[0]
    assert not chk(cfg, st, broker="ALPACA", now=dt.datetime(2026, 7, 14, 13, 44, tzinfo=UTC))[0]


def test_persistence_and_rollover(cfg, tmp_path):
    path = str(tmp_path / "s.json")
    s1 = rl.RiskState(path)
    s1.rec("BYBIT", NOW, 50000)
    rl.record_open(cfg, s1, "BYBIT", None, NOW)
    for _ in range(4):
        rl.record_close(cfg, s1, "BYBIT", -10, NOW)
    s2 = rl.RiskState(path)  # "restart"
    r = s2.rec("BYBIT", NOW)
    assert r["start_equity"] == 50000 and r["trades_opened"] == 1
    assert r["realized_pnl"] == -40 and r["pause_until"]
    nxt = NOW + dt.timedelta(days=1)
    r2 = s2.rec("BYBIT", nxt, 51000)
    assert r2["start_equity"] == 51000 and r2["trades_opened"] == 0 and r2["realized_pnl"] == 0
    assert r2["consecutive_losses"] == 4 and r2["pause_until"] == r["pause_until"]  # streak carried
    assert not (tmp_path / "s.json.tmp").exists()


def test_corrupt_state_file(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{nope")
    assert rl.RiskState(str(p)).rec("BYBIT", NOW, 1)["trades_opened"] == 0


def test_notification_dedupe(st):
    assert st.should_notify("BYBIT", "DAILY_LOSS", NOW)
    assert not st.should_notify("BYBIT", "DAILY_LOSS", NOW)
    assert st.should_notify("BYBIT", "COOLDOWN", NOW)
    assert st.should_notify("ALPACA", "DAILY_LOSS", NOW)
    assert st.should_notify("BYBIT", "DAILY_LOSS", NOW + dt.timedelta(days=1))
    assert rl.reason_key("DAILY_LOSS: -2.1% <= -2%") == "DAILY_LOSS"


def test_exits_not_gated():
    # Exits never call check_entry; the module exposes only entry gating and
    # record_close, which records pnl and never refuses.
    assert not hasattr(rl, "check_exit")


def test_env_config(monkeypatch):
    monkeypatch.setenv("RISK_ENABLED", "false")
    monkeypatch.setenv("RISK_MAX_TRADES_PER_DAY", "3")
    c = rl.RiskConfig.from_env()
    assert not c.enabled and c.max_trades_per_day == 3 and c.max_daily_loss_pct == 2.0


def test_bot_exit_sites_not_gated():
    import re
    src = open("telegram_bot.py", encoding="utf-8").read()
    for m in re.finditer(r"close_position\(", src):
        window = src[max(0, m.start() - 200):m.start()]
        assert "_risk_gate" not in window
