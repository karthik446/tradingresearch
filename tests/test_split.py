"""`tr split` (SPIKE §1.1 `TrainingSplit`, TRAINING-SPIKE §7.2 row 4): register refusals and idempotence, the
derived sets on hand-checked NYSE windows that hold Thanksgiving and Christmas, and the embargo floor: the last
train/val session's latest swing exit lands before the cutoff. No model call."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError

from factories import analysis, snapshot
from tradingresearch import journal, records, sessions, split
from tradingresearch.cli import main

NOW = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)  # after the 2026-10-30 close: last completed session is 10-30
CUTOFF = date(2026, 12, 1)  # a Tuesday
# The 22 NYSE sessions before 2026-12-01, counted back by hand: 11-30, 11-27, 11-25, 11-24, 11-23, 11-20 .. 11-16,
# 11-13 .. 11-09 (11-11 Veterans Day is open), 11-06 .. 11-02 (20), 10-30, 10-29. Thanksgiving 11-26 is closed, so
# the window starts on 10-29, not 10-30.
WINDOW_FIRST, WINDOW_LAST = date(2026, 10, 29), date(2026, 11, 30)


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def prereg(note: str | None = None):
    return split.gate_prereg(NOW, note)


def rows(conn) -> int:
    return conn.execute("SELECT count(*) FROM training_split").fetchone()[0]


def analysed(conn, *days: date) -> None:
    for day in days:
        journal.add(conn, analysis(session=day, snapshot=snapshot(session=day)))


def latest_swing_exit(written: date) -> date:
    """The last session a thesis written after `written`'s close can read: entry on the last day of the 2-session
    swing window (thesis.windows), exit 20 sessions after the entry session (reconcile `exit_session`)."""
    cal = sessions.xnys()
    entry = cal.session_offset(pd.Timestamp(written), 2)
    return cal.session_offset(entry, 20).date()


# ---------- register ----------

def test_the_floor_is_the_swing_entry_window_plus_the_longest_hold_and_the_record_enforces_it():
    assert (records.SWING_ENTRY_SESSIONS, records.HOLD_RANGE["swing"][1], records.MIN_EMBARGO) == (2, 20, 22)
    assert split.MIN_EMBARGO is records.MIN_EMBARGO  # one constant: register and the record cannot drift
    fields = dict(split_id="sp_x", cutoff_session=CUTOFF, prereg=prereg(), registered_at=NOW)
    assert records.TrainingSplit(embargo_sessions=22, **fields).embargo_sessions == 22
    with pytest.raises(ValidationError, match="embargo_sessions must be >= 22 \\(entry window 2 \\+ longest hold 20\\)"):
        records.TrainingSplit(embargo_sessions=21, **fields)


def test_register_stores_the_split_once_and_reads_it_back(conn):
    s = split.register(conn, CUTOFF, 22, prereg(), NOW)
    assert s.split_id.startswith("sp_") and len(s.split_id) == 19
    assert (s.cutoff_session, s.embargo_sessions, s.prereg.primary_metric) == (CUTOFF, 22, "claims_valid")
    assert s.registered_at == NOW and s.registered_at.tzinfo == sessions.NY  # New York time, the session's date
    assert journal.get(conn, split.TrainingSplit, s.split_id) == s


def test_the_same_parameters_later_write_nothing_and_return_the_stored_split(conn):
    first = split.register(conn, CUTOFF, 22, prereg(), NOW)
    later = NOW + timedelta(days=3)
    again = split.register(conn, CUTOFF, 22, split.gate_prereg(later), later)
    assert again == first and rows(conn) == 1


def test_different_parameters_are_a_new_row_and_the_latest_governs(conn):
    first = split.register(conn, CUTOFF, 22, prereg(), NOW)
    second = split.register(conn, CUTOFF, 25, prereg(), NOW)
    third = split.register(conn, CUTOFF, 22, prereg("a different hypothesis"), NOW)
    assert len({first.split_id, second.split_id, third.split_id}) == 3 and rows(conn) == 3
    assert split.governing(conn) == third and split.governing(conn, first.split_id) == first
    with pytest.raises(split.Refused, match="no training split sp_missing"):
        split.governing(conn, "sp_missing")


@pytest.mark.parametrize(("cutoff", "embargo", "now", "why"), [
    (CUTOFF, 21, NOW, "embargo 21 < 22 sessions \\(entry window 2 \\+ longest hold 20\\)"),
    (CUTOFF, 20, NOW, "embargo 20 < 22"),
    (date(2026, 11, 28), 22, NOW, "2026-11-28 is not an NYSE session"),
    (date(2026, 10, 30), 22, NOW, "not after the last completed session \\(2026-10-30\\)"),
    (date(2026, 10, 29), 22, NOW, "not after the last completed session"),
    (date(2026, 11, 2), 22, datetime(2026, 11, 2, 15, 0, tzinfo=UTC), "not before the cutoff session opens"),
])
def test_register_refuses_a_short_embargo_and_a_cutoff_that_is_not_still_ahead(conn, cutoff, embargo, now, why):
    with pytest.raises(split.Refused, match=why):
        split.register(conn, cutoff, embargo, split.gate_prereg(now), now)
    assert rows(conn) == 0


def test_an_evening_registration_for_the_next_session_is_allowed(conn):
    evening = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)  # 2026-11-02 21:00 New York; UTC already says 11-03
    s = split.register(conn, date(2026, 11, 3), 22, split.gate_prereg(evening), evening)
    assert s.registered_at.date() == date(2026, 11, 2)


def test_a_prereg_registered_after_the_cutoff_opened_is_refused(conn):
    late = split.gate_prereg(datetime(2026, 12, 1, 15, 0, tzinfo=UTC))
    with pytest.raises(split.Refused, match="prereg registered_at .* is not before the cutoff session opens"):
        split.register(conn, CUTOFF, 22, late, NOW)


def test_prereg_json_replaces_the_gate_and_the_clock_sets_registered_at():
    p = split.prereg_from('{"primary_metric": "parse_ok", "pass_rule": "wilson_lb >= 0.95", "margin": 0.0, '
                          '"n_planned": 20}', "the student parses", NOW)
    assert (p.primary_metric, p.n_planned, p.hypothesis, p.registered_at) == ("parse_ok", 20, "the student parses",
                                                                             NOW)
    with pytest.raises(split.Refused, match="without registered_at"):
        split.prereg_from('{"registered_at": "2026-10-30T22:00:00Z"}', None, NOW)
    with pytest.raises(split.Refused, match="given twice"):
        split.prereg_from('{"primary_metric": "m", "pass_rule": "r", "margin": 0.1, "n_planned": 1, '
                          '"hypothesis": "h"}', "note", NOW)
    with pytest.raises(split.Refused, match="not a gigai-core Prereg"):
        split.prereg_from('{"primary_metric": "m"}', None, NOW)


# ---------- the embargo holds ----------

def test_the_last_train_session_s_longest_swing_exit_lands_before_the_cutoff(conn):
    # Cutoff 2026-12-29, counted back by hand: 12-28, 12-24 .. 12-21 (Christmas 12-25 closed), 12-18 .. 12-14,
    # 12-11 .. 12-07, 12-04 .. 12-01 (19), 11-30, 11-27, 11-25 (22). Last train/val session 11-24; entry by 11-27;
    # exit 20 sessions later on 12-28, the session before the cutoff.
    s = split.register(conn, date(2026, 12, 29), 22, prereg(), NOW)
    window = split.embargo_window(s)
    assert (window[0], window[-1]) == (date(2026, 11, 25), date(2026, 12, 28))
    last_train = split.partition(s, [date(2026, 11, 24), date(2026, 11, 25)]).train_val_sessions[-1]
    assert last_train == date(2026, 11, 24)
    assert latest_swing_exit(last_train) == date(2026, 12, 28) < s.cutoff_session
    # The old floor of 20 (W5R-r M2): window from 11-30, last train/val session 11-27, exit 12-30 = cutoff + 1.
    short = sessions.recent(20, sessions.previous(date(2026, 12, 29)))
    assert latest_swing_exit(sessions.previous(short[0])) == date(2026, 12, 30)


# ---------- derive ----------

def test_the_embargo_window_is_the_22_sessions_before_the_cutoff_skipping_thanksgiving(conn):
    window = split.embargo_window(split.register(conn, CUTOFF, 22, prereg(), NOW))
    assert (len(window), window[0], window[-1]) == (22, WINDOW_FIRST, WINDOW_LAST)
    assert date(2026, 11, 26) not in window and date(2026, 11, 11) in window


def test_derive_puts_each_journal_session_in_one_set_and_the_embargo_in_neither(conn):
    s = split.register(conn, CUTOFF, 22, prereg(), NOW)
    days = [date(2026, 10, 27), date(2026, 10, 28), WINDOW_FIRST, date(2026, 11, 27), WINDOW_LAST, CUTOFF,
            date(2026, 12, 2)]
    analysed(conn, *days, date(2026, 10, 28))  # a second analysis on one session counts once
    parts = split.derive(conn, s.split_id)
    assert parts.train_val_sessions == (date(2026, 10, 27), date(2026, 10, 28))
    assert parts.embargoed_sessions == (WINDOW_FIRST, date(2026, 11, 27), WINDOW_LAST)
    assert parts.test_sessions == (CUTOFF, date(2026, 12, 2))
    assert set(parts.train_val_sessions).isdisjoint(parts.test_sessions)
    assert not set(parts.embargo_window) & (set(parts.train_val_sessions) | set(parts.test_sessions))
    assert split.partition(s, days) == parts  # the reader adds nothing: the row, the calendar, the sessions


def test_a_longer_embargo_moves_train_sessions_into_the_embargo(conn):
    s = split.register(conn, CUTOFF, 27, prereg(), NOW)
    parts = split.partition(s, [date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 28)])
    assert parts.embargo_window[0] == date(2026, 10, 22)  # 5 more sessions back: 10-28, 27, 26, 23, 22
    assert parts.train_val_sessions == (date(2026, 10, 21),)
    assert parts.embargoed_sessions == (date(2026, 10, 22), date(2026, 10, 28))


def test_render_states_counts_the_embargo_and_the_rule(conn):
    split.register(conn, CUTOFF, 22, prereg("student no worse than teacher"), NOW)
    analysed(conn, date(2026, 10, 28), CUTOFF)
    s = split.governing(conn)  # as stored: the JSON round trip keeps the offset, not the zone name
    lines = split.render(s, split.derive(conn, s.split_id), 1)
    assert lines[0] == (f"split {s.split_id}: cutoff 2026-12-01, embargo 22 sessions, "
                        "registered 2026-10-30T18:00-04:00 (New York)")
    assert "hypothesis: student no worse than teacher" in lines[1] and "n_planned 40" in lines[1]
    assert lines[2:6] == ["  embargo window: 2026-10-29 to 2026-11-30 (22 NYSE sessions, in neither set)",
                          "  train/val: 1 sessions: 2026-10-28", "  embargoed: 0 sessions: none",
                          "  test (on or after the cutoff): 1 sessions: 2026-12-01"]


# ---------- CLI ----------

def test_cli_register_is_idempotent_and_show_reads_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    cutoff = sessions.xnys().sessions_window(sessions.last_completed(), 5)[-1].date()  # 4 sessions ahead
    with pytest.raises(SystemExit, match="no training split registered yet: .* --embargo 22"):
        main(["split", "show"])
    main(["split", "register", "--cutoff", cutoff.isoformat(), "--embargo", "22", "--note", "dev"])
    assert capsys.readouterr().out.startswith("stored: sp_")
    main(["split", "register", "--cutoff", cutoff.isoformat(), "--embargo", "22", "--note", "dev"])
    assert capsys.readouterr().out.startswith("already registered, nothing written: sp_")
    with pytest.raises(SystemExit, match="embargo 21 < 22"):
        main(["split", "register", "--cutoff", cutoff.isoformat(), "--embargo", "21"])
    with pytest.raises(SystemExit, match="is not YYYY-MM-DD"):
        main(["split", "register", "--cutoff", "soon", "--embargo", "22"])
    main(["split", "show"])
    out = capsys.readouterr().out
    assert f"cutoff {cutoff}" in out and "1 split(s) registered" in out
    assert rows(journal.connect(tmp_path / "journal.db")) == 1
