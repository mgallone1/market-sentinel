"""NYSE session calendar in New York time (holidays, 1:00 p.m. early closes, DST-safe).

Every intraday rule for US equities (open-bell filter, late-entry gate, forced flatten)
must be expressed on the New York clock, never on the Rome clock: the two are 6 hours
apart most of the year but only 5 hours apart for ~3 weeks (US and EU change DST on
different Sundays), and on early-close days the session ends at 13:00 ET.

Sources: https://www.nyse.com/markets/hours-calendars (same list as day_trader/trader-alerts).
When the broker clock (Alpaca `GET /v2/clock`) is available, its `next_close` is
authoritative and overrides the static table (covers unscheduled closures).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")

NYSE_HOLIDAYS: Dict[str, str] = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King, Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King, Jr. Day",
    "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth National Independence Day (observed)",
    "2027-07-05": "Independence Day (observed)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day",
    "2027-12-24": "Christmas Day (observed)",
}

NYSE_EARLY_CLOSE: Dict[str, str] = {  # 1:00 p.m. ET
    "2026-11-27": "day after Thanksgiving",
    "2026-12-24": "Christmas Eve",
    "2027-11-26": "day after Thanksgiving",
}

CALENDAR_YEARS = (2026, 2027)
REGULAR_OPEN = _dt.time(9, 30)
REGULAR_CLOSE = _dt.time(16, 0)
EARLY_CLOSE = _dt.time(13, 0)


def now_ny(now: Any = None) -> _dt.datetime:
    """Return an aware New York datetime. Naive inputs are interpreted as UTC."""
    if now is None:
        return _dt.datetime.now(NY_TZ)
    if isinstance(now, str):
        now = _dt.datetime.fromisoformat(now.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    return now.astimezone(NY_TZ)


def session_bounds(day: _dt.date) -> Optional[Tuple[_dt.datetime, _dt.datetime]]:
    """(open, close) as aware New York datetimes, or None if the exchange is closed all day."""
    if day.weekday() >= 5 or day.isoformat() in NYSE_HOLIDAYS:
        return None
    close_t = EARLY_CLOSE if day.isoformat() in NYSE_EARLY_CLOSE else REGULAR_CLOSE
    return (
        _dt.datetime.combine(day, REGULAR_OPEN, tzinfo=NY_TZ),
        _dt.datetime.combine(day, close_t, tzinfo=NY_TZ),
    )


def _parse_broker_close(clock: Optional[Dict[str, Any]]) -> Optional[_dt.datetime]:
    if not isinstance(clock, dict) or not clock.get("is_open"):
        return None
    raw = clock.get("next_close")
    if not raw:
        return None
    try:
        return _dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(NY_TZ)
    except (TypeError, ValueError):
        return None


def session_status(now: Any = None, clock: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Current regular-session status on the New York clock.

    Keys: is_open, open_ny, close_ny, minutes_since_open, minutes_to_close, early_close,
    calendar_known, source ("broker_clock" or "calendar").
    """
    t = now_ny(now)
    bounds = session_bounds(t.date())
    status: Dict[str, Any] = {
        "now_ny": t.isoformat(timespec="minutes"),
        "is_open": False,
        "open_ny": None,
        "close_ny": None,
        "minutes_since_open": None,
        "minutes_to_close": None,
        "early_close": NYSE_EARLY_CLOSE.get(t.date().isoformat()),
        "calendar_known": t.year in CALENDAR_YEARS,
        "source": "calendar",
    }
    open_dt: Optional[_dt.datetime] = bounds[0] if bounds else None
    close_dt: Optional[_dt.datetime] = bounds[1] if bounds else None

    broker_close = _parse_broker_close(clock)
    if broker_close is not None and broker_close.date() == t.date():
        close_dt = broker_close
        if open_dt is None:
            open_dt = _dt.datetime.combine(t.date(), REGULAR_OPEN, tzinfo=NY_TZ)
        status["source"] = "broker_clock"

    if open_dt is None or close_dt is None:
        return status

    status["open_ny"] = open_dt.isoformat(timespec="minutes")
    status["close_ny"] = close_dt.isoformat(timespec="minutes")
    if open_dt <= t < close_dt:
        status["is_open"] = True
        status["minutes_since_open"] = round((t - open_dt).total_seconds() / 60.0, 2)
        status["minutes_to_close"] = round((close_dt - t).total_seconds() / 60.0, 2)
    return status


def minutes_to_close(now: Any = None, clock: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Minutes until today's regular close, or None when the session is not open."""
    return session_status(now, clock).get("minutes_to_close")


def should_flatten_now(
    now: Any = None,
    clock: Optional[Dict[str, Any]] = None,
    lead_minutes: float = 5.0,
) -> bool:
    """True inside the last `lead_minutes` of the regular session (incl. 13:00 early closes)."""
    mtc = minutes_to_close(now, clock)
    return mtc is not None and mtc <= float(lead_minutes)
