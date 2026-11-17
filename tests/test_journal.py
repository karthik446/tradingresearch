import sqlite3

import pytest

from factories import analysis, event, thesis
from tradingresearch import journal
from tradingresearch.records import Analysis


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def test_analysis_round_trips_through_the_journal(conn):
    a = analysis()
    journal.add_analysis(conn, a, sources=[])
    assert journal.get(conn, Analysis, a.analysis_id) == a


@pytest.mark.parametrize("sql", ["UPDATE analysis SET ticker = 'MSFT'", "DELETE FROM analysis"])
def test_update_and_delete_abort(conn, sql):
    journal.add_analysis(conn, analysis(), sources=[])
    with pytest.raises(sqlite3.IntegrityError, match="analysis is append-only"):
        conn.execute(sql)


def test_insert_or_replace_aborts(conn):
    a = analysis()
    journal.add_analysis(conn, a, sources=[])
    with pytest.raises(sqlite3.IntegrityError, match="analysis is append-only"):
        conn.execute(
            "INSERT OR REPLACE INTO analysis (analysis_id, ticker, session, arm, body, record_sha256, created_at) "
            "VALUES (?, 'AAPL', '2026-11-13', 'main', '{}', 'x', 'now')",
            (a.analysis_id,),
        )


def test_without_recursive_triggers_replace_is_silent():
    """The trap: the same statement on a connection that skipped the pragma replaces the row."""
    c = journal.connect(":memory:")
    a = analysis()
    journal.add_analysis(c, a, sources=[])
    c.execute("PRAGMA recursive_triggers = OFF")
    c.execute(
        "INSERT OR REPLACE INTO analysis (analysis_id, ticker, session, arm, body, record_sha256, created_at) "
        "VALUES (?, 'AAPL', '2026-11-13', 'main', '{}', 'x', 'now')",
        (a.analysis_id,),
    )
    assert c.execute("SELECT body FROM analysis").fetchone()[0] == "{}"


def test_second_live_thesis_aborts(conn):
    a = analysis()
    journal.add_analysis(conn, a, sources=[])
    first = thesis(a.analysis_id)
    journal.add(conn, first, event(first.thesis_id, "PROPOSED"))
    with pytest.raises(sqlite3.IntegrityError, match="one live thesis"):
        journal.add(conn, thesis(a.analysis_id))


def test_new_thesis_allowed_after_terminal_event(conn):
    a = analysis()
    journal.add_analysis(conn, a, sources=[])
    first = thesis(a.analysis_id)
    journal.add(conn, first, event(first.thesis_id, "PROPOSED"))
    journal.add(conn, event(first.thesis_id, "EXPIRED", reason="window_missed"))
    journal.add(conn, thesis(a.analysis_id))  # no error


def test_teacher_theses_are_exempt(conn):
    a = analysis(arm="teacher", terms_class="trainable")
    journal.add_analysis(conn, a, sources=[])
    for _ in range(2):
        t = thesis(a.analysis_id, arm="teacher", terms_class="trainable")
        journal.add(conn, t, event(t.thesis_id, "PROPOSED"))
    assert conn.execute("SELECT count(*) FROM thesis").fetchone()[0] == 2
