"""w5l4.3 a cutoff still ahead. split.register raises split.Refused, writing nothing, in this order:
  1. before the lookup, an embargo under MIN_EMBARGO: `embargo 21 < 22 sessions (entry window 2 + longest hold 20)`;
  then, for a split not already stored:
  2. a cutoff that is not an NYSE session: `cutoff 2026-11-26 is not an NYSE session`;
  3. a cutoff on or before sessions.last_completed(now): `cutoff 2026-10-30 is not after the last completed session
     (2026-10-30): a split is registered before its test period starts`;
  4. now, then the Prereg's registered_at, at or after the cutoff session's open (sessions.open_close):
     `now 2026-11-02T14:30:00+00:00 is not before the cutoff session opens (2026-11-02T14:30:00+00:00)`, and the same
     with `prereg registered_at` in place of `now`. Times print with isoformat().
A split already stored is returned as stored even once its cutoff has opened.

The journal is in memory; the dates are real NYSE sessions, Thanksgiving 2026-11-26 closed and 11-27 open, Good Friday
2027-03-26 closed though no federal holiday, and Veterans Day 2026-11-11 open though a federal holiday.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from tradingresearch import journal, split

NOW = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)  # after the 2026-10-30 close: the last completed session is 10-30
CUTOFF = date(2026, 12, 1)
OPEN_1102 = datetime(2026, 11, 2, 14, 30, tzinfo=UTC)  # 09:30 New York
LATE = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)  # 10:00 New York on the cutoff
WHY = "entry window 2 + longest hold 20"


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def rows(conn) -> int:
    return conn.execute("SELECT count(*) FROM training_split").fetchone()[0]


def refusal(conn, cutoff: date, embargo: int, now: datetime, prereg_at: datetime | None = None) -> str:
    """register's Refused message; a FAIL when it stored, raised something else, or wrote a row."""
    asked = f"register(cutoff {cutoff}, embargo {embargo}, now {now.isoformat()}" + (
        f", prereg registered {prereg_at.isoformat()})" if prereg_at else ")")
    try:
        got = split.register(conn, cutoff, embargo, split.gate_prereg(prereg_at or now), now)
    except split.Refused as exc:
        message = str(exc)
    except Exception as exc:
        raise AssertionError(f"{asked} raised {type(exc).__name__}: {str(exc).splitlines()[0]}; expected "
                             "split.Refused, before a TrainingSplit is built") from None
    else:
        raise AssertionError(f"{asked} stored {got.split_id}; expected split.Refused")
    assert rows(conn) == 0, f"{asked} was refused ({message}) but wrote {rows(conn)} row(s)"
    return message


def stored(conn, cutoff: date, now: datetime) -> split.TrainingSplit:
    try:
        return split.register(conn, cutoff, 22, split.gate_prereg(now), now)
    except Exception as exc:
        raise AssertionError(f"register(cutoff {cutoff}, embargo 22, now {now.isoformat()}) raised "
                             f"{type(exc).__name__}: {str(exc).splitlines()[0]}; that cutoff is still ahead") from None


@pytest.mark.parametrize("embargo", [21, 20])
def test_an_embargo_under_the_floor_is_refused_with_its_reason(conn, embargo):
    got = refusal(conn, CUTOFF, embargo, NOW)
    assert got == f"embargo {embargo} < 22 sessions ({WHY})", got


# Thanksgiving, a Saturday, Good Friday
@pytest.mark.parametrize("cutoff", [date(2026, 11, 26), date(2026, 11, 28), date(2027, 3, 26)])
def test_a_cutoff_that_is_not_an_nyse_session_is_refused(conn, cutoff):
    got = refusal(conn, cutoff, 22, NOW)
    assert got == f"cutoff {cutoff} is not an NYSE session", f"{got}  ({cutoff:%A}, the exchange is closed)"


@pytest.mark.parametrize("cutoff", [date(2026, 10, 30), date(2026, 10, 29)])
def test_a_cutoff_not_after_the_last_completed_session_is_refused(conn, cutoff):
    got = refusal(conn, cutoff, 22, NOW)
    want = (f"cutoff {cutoff} is not after the last completed session (2026-10-30): a split is registered before its "
            "test period starts")
    assert got == want, f"{got}  (at {NOW}, 2026-10-30 closed 2 hours ago)"


@pytest.mark.parametrize(("now", "prereg_at", "what", "at"), [
    (OPEN_1102, None, "now", "2026-11-02T14:30:00+00:00"),
    (OPEN_1102 + timedelta(hours=1), None, "now", "2026-11-02T15:30:00+00:00"),
    (NOW, LATE, "prereg registered_at", "2026-12-01T10:00:00-05:00"),
    (LATE, LATE, "now", "2026-12-01T15:00:00+00:00"),
], ids=["now-at-the-open", "now-after-the-open", "prereg-late", "both-late"])
def test_now_and_then_the_prereg_must_come_before_the_cutoff_session_opens(conn, now, prereg_at, what, at):
    cutoff = now.date() if prereg_at is None else CUTOFF
    opens = "2026-11-02T14:30:00+00:00" if cutoff == date(2026, 11, 2) else "2026-12-01T14:30:00+00:00"
    got = refusal(conn, cutoff, 22, now, prereg_at)
    assert got == f"{what} {at} is not before the cutoff session opens ({opens})", got


@pytest.mark.parametrize(("cutoff", "embargo", "now", "want"), [
    (date(2026, 11, 28), 21, NOW, "embargo 21 < 22"),
    (date(2026, 10, 25), 22, NOW, "cutoff 2026-10-25 is not an NYSE session"),
    (date(2026, 10, 29), 22, NOW, "cutoff 2026-10-29 is not after the last completed session"),
], ids=["embargo-before-the-calendar", "calendar-before-the-clock", "last-completed-before-the-open"])
def test_the_first_reason_in_order_is_the_one_given(conn, cutoff, embargo, now, want):
    got = refusal(conn, cutoff, embargo, now)
    assert got.startswith(want), f"cutoff {cutoff}, embargo {embargo} fails more than one rule; got {got!r}, the " \
                                 f"first in order is {want!r}"


@pytest.mark.parametrize(("cutoff", "now"), [
    (date(2026, 11, 27), NOW),  # the day after Thanksgiving is open
    (CUTOFF, datetime(2026, 11, 30, 22, 0, tzinfo=UTC)),  # the evening the session before the cutoff closed
    (date(2026, 11, 3), datetime(2026, 11, 3, 2, 0, tzinfo=UTC)),  # 21:00 New York, UTC already says 11-03
    (date(2026, 11, 11), NOW),  # Veterans Day, a federal holiday: the exchange is open
], ids=["after-thanksgiving", "the-evening-before-the-cutoff", "an-evening-utc-calls-the-next-day", "veterans-day"])
def test_a_cutoff_still_ahead_is_stored(conn, cutoff, now):
    assert stored(conn, cutoff, now).cutoff_session == cutoff and rows(conn) == 1


def test_a_stored_split_is_returned_even_once_its_cutoff_has_opened(conn):
    first = stored(conn, CUTOFF, NOW)
    try:
        again = split.register(conn, CUTOFF, 22, split.gate_prereg(NOW), LATE)
    except split.Refused as exc:
        raise AssertionError(f"asking for {first.split_id} again at {LATE.isoformat()} was refused: {exc}; the "
                             "lookup comes before the cutoff checks, so a stored split is returned as stored") from None
    assert again == first and rows(conn) == 1
