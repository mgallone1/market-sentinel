import re
import sys
import types

import pytest

try:
    import pybit.unified_trading  # noqa: F401
except Exception:  # pybit assente: stub minimo, i test usano una sessione finta
    pb = types.ModuleType("pybit"); ut = types.ModuleType("pybit.unified_trading")
    ut.HTTP = object
    sys.modules.setdefault("pybit", pb); sys.modules.setdefault("pybit.unified_trading", ut)

from services.bybit_execution_service import (
    BybitExecutionService, make_order_link_id, is_duplicate_link_id_response,
    classify_btc_bias, hysteresis_bias,
)


class FakeSession:
    def __init__(self, order_response=None):
        self.calls = []
        self.order_response = order_response or {"retCode": 0, "result": {"orderId": "1"}}

    def place_order(self, **kw):
        self.calls.append(kw)
        return self.order_response

    def set_leverage(self, **kw):
        return {}


def make_service(session, positions=None):
    svc = BybitExecutionService.__new__(BybitExecutionService)
    svc.session = session
    svc.get_realtime_tickers = lambda syms=None: {"BTCUSDT": {"last_price": 50000.0}}
    svc.get_open_positions = lambda syms=None: positions or []
    return svc


def test_order_link_id_deterministic_and_valid():
    a = make_order_link_id("1000PEPEUSDT", "L", 1_700_000_000)
    assert a == make_order_link_id("1000PEPEUSDT", "long", 1_700_000_000)
    assert a != make_order_link_id("1000PEPEUSDT", "S", 1_700_000_000)
    assert len(a) <= 36 and re.fullmatch(r"[A-Za-z0-9_-]+", a)


def test_place_order_passes_order_link_id():
    s = FakeSession()
    res = make_service(s).place_order("BTCUSDT", "Buy", 1000.0, order_link_id="msBTCUSDTL1")
    assert res["status"] == "success"
    assert s.calls[0]["orderLinkId"] == "msBTCUSDTL1"


def test_place_order_without_link_id_has_no_field():
    s = FakeSession()
    make_service(s).place_order("BTCUSDT", "Buy", 1000.0)
    assert "orderLinkId" not in s.calls[0]


@pytest.mark.parametrize("resp", [
    {"retCode": 10014, "retMsg": "x"},
    {"retCode": 110072, "retMsg": "OrderLinkedID is duplicate"},
])
def test_duplicate_link_id_flagged(resp):
    assert is_duplicate_link_id_response(resp)
    res = make_service(FakeSession(resp)).place_order("BTCUSDT", "Buy", 1000.0, order_link_id="a")
    assert res == {"error": "duplicate_order_link_id", "duplicate": True}


def test_close_on_flat_returns_error_without_order():
    s = FakeSession()
    res = make_service(s, positions=[]).close_position("BTCUSDT")
    assert "error" in res and s.calls == []


def test_close_uses_reduce_only():
    s = FakeSession()
    pos = [{"symbol": "BTCUSDT", "side": "BUY", "size": 0.1, "unrealized_pnl": 1.0}]
    res = make_service(s, positions=pos).close_position("BTCUSDT")
    assert res["status"] == "closed" and s.calls[0]["reduceOnly"] is True


def test_hysteresis():
    assert hysteresis_bias("BULLISH", "BULLISH") == "BULLISH"
    assert hysteresis_bias("BEARISH", "BEARISH") == "BEARISH"
    assert hysteresis_bias("BEARISH", "NEUTRAL") == "NEUTRAL"
    assert hysteresis_bias("BULLISH", "BEARISH") == "NEUTRAL"


def test_classify_btc_bias():
    up = [100 + i for i in range(80)]
    down = list(reversed(up))
    assert classify_btc_bias(up, up) == "BULLISH"
    assert classify_btc_bias(down, down) == "BEARISH"
    assert classify_btc_bias(down, up) == "NEUTRAL"
    # un flip su una sola candela 1h: current != previous -> NEUTRAL
    h = down[:-1] + [down[-1] + 1000]
    assert hysteresis_bias(classify_btc_bias(down, h), classify_btc_bias(down, down[:-1] + [down[-1]])) == "NEUTRAL"
