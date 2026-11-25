"""w5l4.4 the derived sets. A split's sets are derived on read, from the row, the NYSE calendar and the journal:

- `split.embargo_window(split)`: the `embargo_sessions` NYSE sessions right before the cutoff session, a tuple, oldest
  first; the cutoff is not in it, and a holiday or weekend is not a session, so it is not counted.
- `split.partition(split, days)`: a `Split` over the journal's sessions `days`, each distinct day once and in date
  order whatever order `days` came in, and `days` itself left as it was given: `train_val_sessions` before the
  window's first session, `embargoed_sessions` from the window's first session up to the cutoff, `test_sessions` on
  or after the cutoff (no end, 2028 included), and `embargo_window` the window. Each day is in exactly one of the
  three sets; the window's sessions are in neither train/val nor test.
- `split.derive(conn, split_id)`: `partition` of the stored split over the sessions the journal's `analysis` rows
  hold, so what the journal says today decides the sets.

The splits are registered on an in-memory journal at 2026-10-30 22:00 UTC. The dates are real NYSE sessions:
Thanksgiving 2026-11-26, Christmas 2026-12-25 and New Year's Day 2027-01-01 are closed, Columbus Day 2026-10-12 open.
The NYSE calendar is pinned to 2020–2030, whatever the day the check runs.
"""

from datetime import UTC, date, datetime
from functools import cache

import exchange_calendars as xcals
import pytest

from tradingresearch import journal, sessions, split

NOW = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)
DEC1, DEC29 = date(2026, 12, 1), date(2026, 12, 29)  # two cutoffs; 12-29 is the chapter's


@cache
def calendar_2020_to_2030() -> xcals.ExchangeCalendar:
    return xcals.get_calendar("XNYS", start="2020-01-01", end="2030-12-31")


@pytest.fixture(autouse=True)
def pinned_calendar(monkeypatch):
    """sessions.xnys() spans 20 years back and one ahead of today; this check's dates run to 2028."""
    monkeypatch.setattr(sessions, "xnys", calendar_2020_to_2030)


def d(text: str) -> date:
    return date.fromisoformat(text if len(text) == 10 else f"2026-{text}")


def dates(text: str) -> tuple[date, ...]:
    return tuple(map(d, text.split()))


WINDOWS = {  # (cutoff, embargo): the NYSE sessions right before the cutoff, counted back by hand
    (DEC1, 22): dates("10-29 10-30 11-02 11-03 11-04 11-05 11-06 11-09 11-10 11-11 11-12 11-13 11-16 11-17 11-18 "
                      "11-19 11-20 11-23 11-24 11-25 11-27 11-30"),
    (DEC29, 22): dates("11-25 11-27 11-30 12-01 12-02 12-03 12-04 12-07 12-08 12-09 12-10 12-11 12-14 12-15 12-16 "
                       "12-17 12-18 12-21 12-22 12-23 12-24 12-28"),
    (DEC1, 27): dates("10-22 10-23 10-26 10-27 10-28 10-29 10-30 11-02 11-03 11-04 11-05 11-06 11-09 11-10 11-11 "
                      "11-12 11-13 11-16 11-17 11-18 11-19 11-20 11-23 11-24 11-25 11-27 11-30"),
    (DEC1, 40): dates("10-05 10-06 10-07 10-08 10-09 10-12 10-13 10-14 10-15 10-16 10-19 10-20 10-21 10-22 10-23 "
                      "10-26 10-27 10-28 10-29 10-30 11-02 11-03 11-04 11-05 11-06 11-09 11-10 11-11 11-12 11-13 "
                      "11-16 11-17 11-18 11-19 11-20 11-23 11-24 11-25 11-27 11-30"),
    # cutoffs whose calendar day before is not a session: a Sunday, Thanksgiving, and New Year's Day after a weekend
    (d("11-30"), 22): dates("10-28 10-29 10-30 11-02 11-03 11-04 11-05 11-06 11-09 11-10 11-11 11-12 11-13 11-16 "
                            "11-17 11-18 11-19 11-20 11-23 11-24 11-25 11-27"),
    (d("11-27"), 22): dates("10-27 10-28 10-29 10-30 11-02 11-03 11-04 11-05 11-06 11-09 11-10 11-11 11-12 11-13 "
                            "11-16 11-17 11-18 11-19 11-20 11-23 11-24 11-25"),
    (d("2027-01-04"), 22): dates("12-01 12-02 12-03 12-04 12-07 12-08 12-09 12-10 12-11 12-14 12-15 12-16 12-17 12-18 "
                                 "12-21 12-22 12-23 12-24 12-28 12-29 12-30 12-31"),
}
SETS = ("train_val_sessions", "embargoed_sessions", "test_sessions")


def registered(cutoff: date, embargo: int) -> split.TrainingSplit:
    conn = journal.connect(":memory:")
    try:
        return split.register(conn, cutoff, embargo, split.gate_prereg(NOW), NOW)
    finally:
        conn.close()


def failed(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}".splitlines()[0].removesuffix(": ")


def window(cutoff: date, embargo: int) -> tuple:
    record = registered(cutoff, embargo)
    try:
        return split.embargo_window(record)
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"split.embargo_window(cutoff {cutoff}, embargo {embargo}) raised {failed(exc)}; "
                             f"expected the {embargo} NYSE sessions before the cutoff") from None


def parts(cutoff: date, embargo: int, days: list[date]) -> split.Split:
    record = registered(cutoff, embargo)
    try:
        got = split.partition(record, days)
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"split.partition(cutoff {cutoff}, embargo {embargo}, {shown(days)}) raised "
                             f"{failed(exc)}") from None
    assert isinstance(got, split.Split), f"split.partition returned {type(got).__name__}; expected a split.Split"
    for name in (*SETS, "embargo_window"):
        assert isinstance(getattr(got, name), tuple), (
            f"split.partition(cutoff {cutoff}, embargo {embargo}) gave {name} as a {type(getattr(got, name)).__name__}; "
            f"a Split holds each set as a tuple of dates, oldest first")
    return got


def shown(days) -> str:
    return "(" + ", ".join(map(str, days)) + ")" if days else "()"


@pytest.mark.parametrize(("cutoff", "embargo"), WINDOWS, ids=lambda v: str(v))
def test_the_window_is_the_embargo_s_nyse_sessions_right_before_the_cutoff(cutoff, embargo):
    got = window(cutoff, embargo)
    want = WINDOWS[(cutoff, embargo)]
    assert isinstance(got, tuple), f"embargo_window(cutoff {cutoff}, embargo {embargo}) returned a " \
                                   f"{type(got).__name__}; expected a tuple of dates"
    assert got == want, (
        f"embargo_window(cutoff {cutoff}, embargo {embargo}) is {len(got)} days from {got[0] if got else '-'} to "
        f"{got[-1] if got else '-'}; expected the {embargo} NYSE sessions before the cutoff, oldest first: {want[0]} "
        f"to {want[-1]} (Thanksgiving 11-26, Christmas 12-25 and New Year's Day 2027-01-01 are closed, so they are not "
        "counted)")


JOURNAL_A = dates("12-02 10-28 11-30 2027-03-01 10-29 12-01 10-27 11-27 10-28 11-25 10-30")  # out of order, 10-28 twice
JOURNAL_B = dates("11-24 11-25 11-27 12-24 12-28 12-29 12-30 2027-01-04")
JOURNALS = {
    "journal A, cutoff 12-01": (DEC1, 22, JOURNAL_A, (dates("10-27 10-28"), dates("10-29 10-30 11-25 11-27 11-30"),
                                                      dates("12-01 12-02 2027-03-01"))),
    "journal B, cutoff 12-29": (DEC29, 22, JOURNAL_B, (dates("11-24"), dates("11-25 11-27 12-24 12-28"),
                                                       dates("12-29 12-30 2027-01-04"))),
}


@pytest.mark.parametrize("which", JOURNALS)
def test_each_journal_session_is_in_one_set_in_date_order(which):
    cutoff, embargo, days, want = JOURNALS[which]
    given = list(days)
    got = parts(cutoff, embargo, given)
    assert given == list(days), (
        f"partition({which}) changed the list it was given to {shown(given)}; expected it as given, {shown(days)}: "
        "partition reads the journal's days and leaves them as they were")
    for name, expected in zip(SETS, want):
        assert getattr(got, name) == expected, (
            f"partition({which}, embargo {embargo}) {name} = {shown(getattr(got, name))}; expected {shown(expected)}: "
            f"window {WINDOWS[(cutoff, embargo)][0]} to {WINDOWS[(cutoff, embargo)][-1]}, journal days as given "
            f"{shown(days)}, each distinct day once, oldest first")
    assert got.embargo_window == WINDOWS[(cutoff, embargo)], (
        f"partition({which}).embargo_window = {shown(got.embargo_window)}; expected embargo_window(split)")
    leaked = set(got.embargo_window) & (set(got.train_val_sessions) | set(got.test_sessions))
    assert not leaked, f"partition({which}) put window sessions {shown(sorted(leaked))} in train/val or test"


@pytest.mark.parametrize(("cutoff", "day", "where"), [
    (DEC1, d("10-27"), "train_val_sessions"), (DEC1, d("10-28"), "train_val_sessions"),
    (DEC1, d("10-29"), "embargoed_sessions"), (DEC1, d("10-30"), "embargoed_sessions"),
    (DEC1, d("11-27"), "embargoed_sessions"), (DEC1, d("11-30"), "embargoed_sessions"),
    (DEC1, d("12-01"), "test_sessions"), (DEC1, d("12-02"), "test_sessions"),
    (DEC29, d("11-24"), "train_val_sessions"), (DEC29, d("11-25"), "embargoed_sessions"),
    (DEC29, d("12-28"), "embargoed_sessions"), (DEC29, d("12-29"), "test_sessions"),
    (DEC29, d("12-30"), "test_sessions"), (DEC29, d("2027-06-01"), "test_sessions"),
    (DEC29, d("2028-01-03"), "test_sessions"),
], ids=lambda v: str(v))
def test_around_the_window_s_first_session_and_the_cutoff(cutoff, day, where):
    got = parts(cutoff, 22, [day])
    found = [name for name in SETS if day in getattr(got, name)]
    first = WINDOWS[(cutoff, 22)][0]
    assert found == [where], (
        f"partition(cutoff {cutoff}, embargo 22, [{day}]) put {day} in {found or 'no set'}; expected {where} only: "
        f"the window's first session is {first} and the cutoff {cutoff}; before {first} is train/val, from {first} up "
        f"to the cutoff embargoed, on or after the cutoff test")


def test_a_longer_embargo_moves_train_sessions_into_the_embargo():
    days = list(dates("10-21 10-22 10-28 11-30 12-01"))
    short, long = parts(DEC1, 22, days), parts(DEC1, 27, days)
    assert (short.train_val_sessions, short.embargoed_sessions) == (dates("10-21 10-22 10-28"), dates("11-30")), (
        f"embargo 22 before cutoff {DEC1}: train/val {shown(short.train_val_sessions)}, embargoed "
        f"{shown(short.embargoed_sessions)}; the window starts 10-29")
    assert (long.train_val_sessions, long.embargoed_sessions, long.test_sessions) == (
        dates("10-21"), dates("10-22 10-28 11-30"), dates("12-01")), (
        f"embargo 27 before cutoff {DEC1}: train/val {shown(long.train_val_sessions)}, embargoed "
        f"{shown(long.embargoed_sessions)}, test {shown(long.test_sessions)}; 5 more sessions back (10-28, 27, 26, 23, "
        f"22) the window starts 10-22, so 10-22 and 10-28 move from train/val into the embargo")


@pytest.mark.parametrize(("days", "want"), [
    ([], ((), (), ())),
    (list(dates("10-01 10-02")), (dates("10-01 10-02"), (), ())),
    (list(dates("11-02 11-30")), ((), dates("11-02 11-30"), ())),
    (list(dates("12-31 12-01")), ((), (), dates("12-01 12-31"))),
], ids=["no-session", "all-train", "all-embargoed", "all-test"])
def test_a_set_with_no_session_is_empty(days, want):
    got = parts(DEC1, 22, days)
    assert tuple(getattr(got, name) for name in SETS) == want, (
        f"partition(cutoff {DEC1}, embargo 22, {shown(days)}) = train/val {shown(got.train_val_sessions)}, embargoed "
        f"{shown(got.embargoed_sessions)}, test {shown(got.test_sessions)}; expected {[shown(w) for w in want]}: a set "
        f"no journal day falls in is an empty tuple")
    assert got.embargo_window == WINDOWS[(DEC1, 22)], (
        f"partition(cutoff {DEC1}, embargo 22, {shown(days)}).embargo_window has {len(got.embargo_window)} sessions; "
        f"the window comes from the calendar, not the journal: 22 sessions, 10-29 to 11-30")


def test_derive_partitions_the_journal_s_sessions_for_a_stored_split():
    conn = journal.connect(":memory:")
    try:
        record = split.register(conn, DEC1, 22, split.gate_prereg(NOW), NOW)
        for n, (ticker, day) in enumerate([("AAPL", d("12-02")), ("AAPL", d("10-27")), ("MSFT", d("10-27")),
                                           ("AAPL", d("10-29")), ("AAPL", d("12-01"))]):
            conn.execute("INSERT INTO analysis (analysis_id, ticker, session, arm, body, record_sha256, created_at) "
                         "VALUES (?, ?, ?, 'main', '{}', '', ?)", (f"an_{n}", ticker, day.isoformat(), NOW.isoformat()))
        try:
            got = split.derive(conn, record.split_id)
        except Exception as exc:  # noqa: BLE001 - reported here
            raise AssertionError(f"split.derive(conn, {record.split_id}) raised {failed(exc)}") from None
    finally:
        conn.close()
    want = (dates("10-27"), dates("10-29"), dates("12-01 12-02"))
    assert tuple(getattr(got, name) for name in SETS) == want, (
        f"derive(conn, {record.split_id}) over a journal with analyses on 12-02, 10-27 (two tickers), 10-29 and 12-01 "
        f"= train/val {shown(got.train_val_sessions)}, embargoed {shown(got.embargoed_sessions)}, test "
        f"{shown(got.test_sessions)}; expected {[shown(w) for w in want]}: derive partitions the stored split over the "
        "sessions the journal holds analyses for, each once")
