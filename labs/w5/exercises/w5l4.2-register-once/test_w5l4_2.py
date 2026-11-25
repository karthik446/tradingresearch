"""w5l4.2 register once. split.split_id_for(cutoff, embargo, prereg) is "sp_" + the first 16 hex of
hashing.digest({"cutoff_session": the ISO date, "embargo_sessions": the number, "prereg": the Prereg as JSON without
registered_at}), so the same split asked for later has the same id, and every other parameter, each of the Prereg's
other fields included, gives a new one. split.register looks that id up first and returns the stored split, writing
nothing; otherwise it stores a TrainingSplit whose registered_at is `now` in New York time (sessions.NY), to the
microsecond and with New York's offset on that date, and returns it. A different cutoff, embargo or Prereg is a new row.

The journal is in memory; the dates are real NYSE sessions. The refusals, and the split asked for again once its
cutoff has opened, are w5l4.3's, so every split here is one register stores.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from tradingresearch import journal, sessions, split

NOW = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)  # after the 2026-10-30 close
CUTOFF = date(2026, 12, 1)
IDS = {(CUTOFF, 22): "sp_45eda73898d532af", (date(2026, 12, 29), 22): "sp_511d03d559bae169"}
STEM = "the student arm is no worse than the base arm on claims_valid"  # two hypotheses that share it differ
# (now, registered_at expected): New York is -04:00 until 2026-11-01 and -05:00 after; seconds and microseconds stay
CLOCKS = [(NOW, "2026-10-30T18:00:00-04:00"), (datetime(2026, 11, 20, 22, 0, tzinfo=UTC), "2026-11-20T17:00:00-05:00"),
          (NOW + timedelta(seconds=17, microseconds=123), "2026-10-30T18:00:17.000123-04:00")]


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def rows(conn) -> int:
    return conn.execute("SELECT count(*) FROM training_split").fetchone()[0]


def ids(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT split_id FROM training_split ORDER BY rowid")]


@pytest.mark.parametrize(("cutoff", "embargo"), list(IDS))
def test_the_id_is_the_digest_of_the_cutoff_the_embargo_and_the_prereg(cutoff, embargo):
    want = IDS[cutoff, embargo]
    try:
        got = split.split_id_for(cutoff, embargo, split.gate_prereg(NOW))
    except NotImplementedError as exc:  # asserted after the try, so the FAIL shows this line and not the stub's raise
        got = exc
    assert not isinstance(got, NotImplementedError), (
        f"split.split_id_for({cutoff}, {embargo}, the gate prereg) raised {got!r}; expected {want!r}")
    assert got == want, (
        f"split_id_for({cutoff}, {embargo}, the gate prereg registered {NOW}) is {got!r}; expected {want!r}, from "
        f'{{"cutoff_session": "{cutoff}", "embargo_sessions": {embargo}, "prereg": the gate prereg\'s seven other '
        "fields}")


def test_the_same_split_asked_for_later_has_the_same_id_and_any_other_parameter_a_new_one():
    first = split.split_id_for(CUTOFF, 22, split.gate_prereg(NOW))
    later = split.split_id_for(CUTOFF, 22, split.gate_prereg(NOW + timedelta(days=3)))
    assert later == first, (
        f"the gate prereg registered 3 days later gives {later!r}, not {first!r}: registered_at says when, not which "
        "split, and the same split must have one id")
    gate = split.gate_prereg(NOW)
    others = {"cutoff 2026-12-02": split.split_id_for(date(2026, 12, 2), 22, gate),
              "embargo 25": split.split_id_for(CUTOFF, 25, gate),
              "a hypothesis": split.split_id_for(CUTOFF, 22, split.gate_prereg(NOW, "student no worse"))}
    for field, value in (("primary_metric", "claims_cited"), ("pass_rule", "NoWorseThan(claims_valid) >= -0.10"),
                         ("margin", 0.2), ("n_planned", 41), ("guard_metric", None)):
        others[f"prereg {field} {value!r}"] = split.split_id_for(CUTOFF, 22, gate.model_copy(update={field: value}))
    same = [what for what, got in others.items() if got == first]
    assert not same, (f"{', '.join(same)} gives the same id as cutoff {CUTOFF}, embargo 22 with the gate prereg: "
                      f"{first}; every parameter but registered_at is part of the split, so each changes the id")
    long = {split.split_id_for(CUTOFF, 22, split.gate_prereg(NOW, f"{STEM} {end}")) for end in ("today", "later")}
    assert len(long) == 2, (f"two hypotheses that share their first {len(STEM) + 1} characters and differ after them "
                            f"give one id, {long.pop()}: the whole hypothesis is in the digest, never a prefix")


@pytest.mark.parametrize(("now", "want"), CLOCKS)
def test_register_stores_the_split_in_new_york_time_and_returns_it(conn, now, want):
    prereg = split.gate_prereg(now - timedelta(days=1))  # pre-registered the day before the split
    got = split.register(conn, CUTOFF, 22, prereg, now)
    assert (got.split_id, got.cutoff_session, got.embargo_sessions) == (IDS[CUTOFF, 22], CUTOFF, 22), (
        f"register returned ({got.split_id}, {got.cutoff_session}, {got.embargo_sessions})")
    # the instant and New York's offset at it, not the tzinfo object: a row read back has a fixed -04:00 tzinfo
    assert got.registered_at == now and got.registered_at.isoformat() == want, (
        f"registered_at is {got.registered_at.isoformat()} in {got.registered_at.tzinfo}; expected now, "
        f"{now.isoformat()}, in America/New_York: {want}, the same instant to the microsecond, on the date and with "
        f"the offset New York has then (the prereg was registered {prereg.registered_at.isoformat()})")
    assert ids(conn) == [got.split_id], f"the journal holds {ids(conn)} after one register; expected [{got.split_id}]"
    assert journal.get(conn, split.TrainingSplit, got.split_id) == got, "the stored row is not the split returned"


@pytest.mark.parametrize("later", [timedelta(hours=1), timedelta(days=3)])
def test_the_same_split_later_writes_nothing_and_returns_the_stored_one(conn, later):
    first = split.register(conn, CUTOFF, 22, split.gate_prereg(NOW), NOW)
    when = NOW + later
    try:
        again = split.register(conn, CUTOFF, 22, split.gate_prereg(when), when)
    except Exception as exc:
        raise AssertionError(f"registering {first.split_id} again at {when} raised {type(exc).__name__}: "
                             f"{str(exc).splitlines()[0]}; the stored split is returned first") from None
    assert again == first and rows(conn) == 1, (
        f"registering again at {when} returned registered_at {again.registered_at.isoformat()} with {rows(conn)} "
        f"rows; expected the stored split, registered {first.registered_at.isoformat()}, and 1 row")


def test_other_parameters_are_new_rows_and_each_id_returns_its_own_split(conn):
    first = split.register(conn, CUTOFF, 22, split.gate_prereg(NOW), NOW)
    second = split.register(conn, CUTOFF, 25, split.gate_prereg(NOW), NOW)
    third = split.register(conn, date(2026, 12, 29), 22, split.gate_prereg(NOW), NOW)
    assert ids(conn) == [first.split_id, second.split_id, third.split_id] and len(set(ids(conn))) == 3, (
        f"three splits (embargo 22, embargo 25, cutoff 2026-12-29) left {ids(conn)}")
    again = split.register(conn, CUTOFF, 22, split.gate_prereg(NOW), NOW + timedelta(hours=1))
    assert again == first and rows(conn) == 3, (
        f"the first split asked for again returned {again.split_id} (embargo {again.embargo_sessions}) with "
        f"{rows(conn)} rows; expected {first.split_id} and 3 rows")


@pytest.mark.parametrize(("field", "value"), [("hypothesis", "a later, different hypothesis"), ("margin", 0.2)])
def test_a_different_prereg_under_the_same_cutoff_and_embargo_is_a_new_split(conn, field, value):
    first = split.register(conn, CUTOFF, 22, split.gate_prereg(NOW), NOW)
    when = NOW + timedelta(hours=1)
    other = split.register(conn, CUTOFF, 22, split.gate_prereg(when).model_copy(update={field: value}), when)
    assert other.split_id != first.split_id and ids(conn) == [first.split_id, other.split_id], (
        f"a second Prereg ({field} {value!r}) under cutoff {CUTOFF}, embargo 22 returned {other.split_id} with "
        f"{rows(conn)} row(s); expected a new split and 2 rows: a different Prereg is a different split, so the lookup "
        "is by the id, not by the cutoff and the embargo")
