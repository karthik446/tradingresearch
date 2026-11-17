"""`tr split` (SPIKE §1.1 `TrainingSplit`, TRAINING-SPIKE §7.2 row 4): register refusals and idempotence, and the
derived sets on a hand-checked NYSE window that holds Thanksgiving. No model call."""

from datetime import UTC, date, datetime, timedelta

import pytest

from factories import analysis, snapshot
from tradingresearch import journal, sessions, split
from tradingresearch.cli import main

NOW = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)  # after the 2026-10-30 close: last completed session is 10-30
CUTOFF = date(2026, 12, 1)  # a Tuesday
# The 20 NYSE sessions before 2026-12-01, counted back by hand: 11-30, 11-27, 11-25, 11-24, 11-23, 11-20 .. 11-16,
# 11-13 .. 11-09 (11-11 Veterans Day is open), 11-06 .. 11-02. Thanksgiving 11-26 is closed, so the window starts on
# 11-02, not 11-03.
WINDOW_FIRST, WINDOW_LAST = date(2026, 11, 2), date(2026, 11, 30)


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


# ---------- register ----------

def test_register_stores_the_split_once_and_reads_it_back(conn):
    s = split.register(conn, CUTOFF, 20, prereg(), NOW)
    assert s.split_id.startswith("sp_") and len(s.split_id) == 19
    assert (s.cutoff_session, s.embargo_sessions, s.prereg.primary_metric) == (CUTOFF, 20, "claims_valid")
    assert s.registered_at == NOW and s.registered_at.tzinfo == sessions.NY  # New York time, the session's date
    assert journal.get(conn, split.TrainingSplit, s.split_id) == s


def test_the_same_parameters_later_write_nothing_and_return_the_stored_split(conn):
    first = split.register(conn, CUTOFF, 20, prereg(), NOW)
    later = NOW + timedelta(days=3)
    again = split.register(conn, CUTOFF, 20, split.gate_prereg(later), later)
    assert again == first and rows(conn) == 1


def test_different_parameters_are_a_new_row_and_the_latest_governs(conn):
    first = split.register(conn, CUTOFF, 20, prereg(), NOW)
    second = split.register(conn, CUTOFF, 25, prereg(), NOW)
    third = split.register(conn, CUTOFF, 20, prereg("a different hypothesis"), NOW)
    assert len({first.split_id, second.split_id, third.split_id}) == 3 and rows(conn) == 3
    assert split.governing(conn) == third and split.governing(conn, first.split_id) == first
    with pytest.raises(split.Refused, match="no training split sp_missing"):
        split.governing(conn, "sp_missing")


@pytest.mark.parametrize(("cutoff", "embargo", "now", "why"), [
    (CUTOFF, 19, NOW, "embargo 19 < 20"),
    (date(2026, 11, 28), 20, NOW, "2026-11-28 is not an NYSE session"),
    (date(2026, 10, 30), 20, NOW, "not after the last completed session \\(2026-10-30\\)"),
    (date(2026, 10, 29), 20, NOW, "not after the last completed session"),
    (date(2026, 11, 2), 20, datetime(2026, 11, 2, 15, 0, tzinfo=UTC), "not before the cutoff session opens"),
])
def test_register_refuses_a_short_embargo_and_a_cutoff_that_is_not_still_ahead(conn, cutoff, embargo, now, why):
    with pytest.raises(split.Refused, match=why):
        split.register(conn, cutoff, embargo, split.gate_prereg(now), now)
    assert rows(conn) == 0


def test_an_evening_registration_for_the_next_session_is_allowed(conn):
    evening = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)  # 2026-11-02 21:00 New York; UTC already says 11-03
    s = split.register(conn, date(2026, 11, 3), 20, split.gate_prereg(evening), evening)
    assert s.registered_at.date() == date(2026, 11, 2)


def test_a_prereg_registered_after_the_cutoff_opened_is_refused(conn):
    late = split.gate_prereg(datetime(2026, 12, 1, 15, 0, tzinfo=UTC))
    with pytest.raises(split.Refused, match="prereg registered_at .* is not before the cutoff session opens"):
        split.register(conn, CUTOFF, 20, late, NOW)


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


# ---------- derive ----------

def test_the_embargo_window_is_the_20_sessions_before_the_cutoff_skipping_thanksgiving(conn):
    window = split.embargo_window(split.register(conn, CUTOFF, 20, prereg(), NOW))
    assert (len(window), window[0], window[-1]) == (20, WINDOW_FIRST, WINDOW_LAST)
    assert date(2026, 11, 26) not in window and date(2026, 11, 11) in window


def test_derive_puts_each_journal_session_in_one_set_and_the_embargo_in_neither(conn):
    s = split.register(conn, CUTOFF, 20, prereg(), NOW)
    days = [date(2026, 10, 29), date(2026, 10, 30), WINDOW_FIRST, date(2026, 11, 27), WINDOW_LAST, CUTOFF,
            date(2026, 12, 2)]
    analysed(conn, *days, date(2026, 10, 30))  # a second analysis on one session counts once
    parts = split.derive(conn, s.split_id)
    assert parts.train_val_sessions == (date(2026, 10, 29), date(2026, 10, 30))
    assert parts.embargoed_sessions == (WINDOW_FIRST, date(2026, 11, 27), WINDOW_LAST)
    assert parts.test_sessions == (CUTOFF, date(2026, 12, 2))
    assert set(parts.train_val_sessions).isdisjoint(parts.test_sessions)
    assert not set(parts.embargo_window) & (set(parts.train_val_sessions) | set(parts.test_sessions))
    assert split.partition(s, days) == parts  # the reader adds nothing: the row, the calendar, the sessions


def test_a_longer_embargo_moves_train_sessions_into_the_embargo(conn):
    s = split.register(conn, CUTOFF, 25, prereg(), NOW)
    parts = split.partition(s, [date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 30)])
    assert parts.embargo_window[0] == date(2026, 10, 26)  # 5 more sessions back: 10-30, 29, 28, 27, 26
    assert (parts.train_val_sessions, parts.embargoed_sessions) == ((), (date(2026, 10, 26), date(2026, 10, 27),
                                                                         date(2026, 10, 30)))


def test_render_states_counts_the_embargo_and_the_rule(conn):
    split.register(conn, CUTOFF, 20, prereg("student no worse than teacher"), NOW)
    analysed(conn, date(2026, 10, 30), CUTOFF)
    s = split.governing(conn)  # as stored: the JSON round trip keeps the offset, not the zone name
    lines = split.render(s, split.derive(conn, s.split_id), 1)
    assert lines[0] == (f"split {s.split_id}: cutoff 2026-12-01, embargo 20 sessions, "
                        "registered 2026-10-30T18:00-04:00 (New York)")
    assert "hypothesis: student no worse than teacher" in lines[1] and "n_planned 40" in lines[1]
    assert lines[2:6] == ["  embargo window: 2026-11-02 to 2026-11-30 (20 NYSE sessions, in neither set)",
                          "  train/val: 1 sessions: 2026-10-30", "  embargoed: 0 sessions: none",
                          "  test (on or after the cutoff): 1 sessions: 2026-12-01"]


# ---------- CLI ----------

def test_cli_register_is_idempotent_and_show_reads_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    cutoff = sessions.xnys().sessions_window(sessions.last_completed(), 5)[-1].date()  # 4 sessions ahead
    with pytest.raises(SystemExit, match="no training split registered yet"):
        main(["split", "show"])
    main(["split", "register", "--cutoff", cutoff.isoformat(), "--embargo", "20", "--note", "dev"])
    assert capsys.readouterr().out.startswith("stored: sp_")
    main(["split", "register", "--cutoff", cutoff.isoformat(), "--embargo", "20", "--note", "dev"])
    assert capsys.readouterr().out.startswith("already registered, nothing written: sp_")
    with pytest.raises(SystemExit, match="embargo 5 < 20"):
        main(["split", "register", "--cutoff", cutoff.isoformat(), "--embargo", "5"])
    with pytest.raises(SystemExit, match="is not YYYY-MM-DD"):
        main(["split", "register", "--cutoff", "soon", "--embargo", "20"])
    main(["split", "show"])
    out = capsys.readouterr().out
    assert f"cutoff {cutoff}" in out and "1 split(s) registered" in out
    assert rows(journal.connect(tmp_path / "journal.db")) == 1
