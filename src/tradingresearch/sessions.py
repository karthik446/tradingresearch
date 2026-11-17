"""NYSE sessions from exchange_calendars (XNYS): holidays and early closes, offline."""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

NY = ZoneInfo("America/New_York")


@cache
def xnys() -> xcals.ExchangeCalendar:
    return xcals.get_calendar("XNYS")


def is_session(day: date) -> bool:
    return xnys().is_session(pd.Timestamp(day))


def open_close(day: date) -> tuple[datetime, datetime]:
    """The session's open and close in UTC. An early close (13:00 New York) shows up here."""
    cal = xnys()
    ts = pd.Timestamp(day)
    return cal.session_open(ts).to_pydatetime(), cal.session_close(ts).to_pydatetime()


def last_completed(now: datetime | None = None) -> date:
    """The latest session whose close is at least 15 minutes before `now` (SIP is free from then on)."""
    now = now or datetime.now(UTC)
    cal = xnys()
    day = cal.minute_to_past_session(pd.Timestamp(now) - pd.Timedelta(minutes=15))
    return day.date()


def previous(day: date) -> date:
    return xnys().previous_session(pd.Timestamp(day)).date()


def between(start: date, end: date) -> list[date]:
    return [ts.date() for ts in xnys().sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))]


def recent(count: int, end: date | None = None) -> list[date]:
    """The last `count` sessions up to and including `end` (default: the last completed one)."""
    end = end or last_completed()
    window = xnys().sessions_window(pd.Timestamp(end), -count)
    return [ts.date() for ts in window]
