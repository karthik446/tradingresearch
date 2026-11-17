import sqlite3

import pytest
from gigai_core.score import ScoreRecord

from factories import T0, analysis, event, thesis
from tradingresearch import journal
from tradingresearch.records import Analysis, Grade, OutcomeGrade


def outcome(subject_id: str) -> OutcomeGrade:
    return OutcomeGrade(subject_id=subject_id, entry_price=101.0, exit_price=106.0, r_gross=5 / 3, cost_bps=10.0,
                        cost_r=0.0337, r_net=1.633, mfe_r=1.7, mae_r=-0.2, exit_reason="target", sessions_held=0)


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


@pytest.mark.parametrize("sql", ["UPDATE score SET value = 9", "DELETE FROM score"])
def test_score_rows_are_append_only(conn, sql):
    a = analysis()
    journal.add_analysis(conn, a, sources=[])
    t = thesis(a.analysis_id)
    journal.add(conn, t)
    score = ScoreRecord(score_id="sc_0", trace_id="trace_0", grader_id="outcome_r_net", grader_version="1",
                        kind="code", value=1.5, recorded_at=T0)
    journal.add_grade(conn, Grade(grade_id="gr_0", thesis_id=t.thesis_id, outcome=outcome(t.thesis_id),
                                  outcome_score_id="sc_0", process_score_id=None, code_checks={}, shadow_id="sh_0"),
                      score, event(t.thesis_id, "GRADED", reason="graded"))
    assert journal.scores_for(conn, t.thesis_id) == [score]
    with pytest.raises(sqlite3.IntegrityError, match="score is append-only"):
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
