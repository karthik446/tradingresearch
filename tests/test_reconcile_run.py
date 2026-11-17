"""The reconcile runner (SPIKE §6 intro, §6.8): journal in, synthetic bars through `settle`, events and TeacherOutcome
out; a second run appends nothing."""

import json
from datetime import UTC, date, datetime, time
from pathlib import Path

import pandas as pd
import pytest

from factories import analysis, event, thesis
from tradingresearch import journal, reconcile_run
from tradingresearch.cli import main
from tradingresearch.commands.reconcile import completed_session
from tradingresearch.records import RULES_VERSION, EntryRule, Event, Shadow, SourceRef, TeacherOutcome
from tradingresearch.sessions import NY

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "reconcile_run" / "bars.json").read_text())
D1, D2 = date(2026, 11, 17), date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 22, 0, tzinfo=UTC)


def ny(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), NY).astimezone(UTC)


class FixtureBars:
    """A BarSource over the synthetic fixtures; `revised` replaces one daily bar, as a late tape correction would."""

    feed = "sip"

    def __init__(self, revised: dict[tuple[str, str], list[float]] | None = None):
        self.revised = revised or {}

    def daily(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        rows = []
        for day, *ohlc in FIXTURES[ticker]["daily"]:
            o, h, low, c = self.revised.get((ticker, day), ohlc)
            if start <= date.fromisoformat(day) <= end:
                rows.append({"session": date.fromisoformat(day), "o": o, "h": h, "l": low, "c": c, "v": 1000, "n": 10,
                             "vw": c})
        return pd.DataFrame(rows, columns=["session", "o", "h", "l", "c", "v", "n", "vw"])

    def corporate_action_days(self, ticker: str, start: date, end: date) -> set[date]:
        days = {date.fromisoformat(d) for d in FIXTURES[ticker].get("corporate_actions", ())}
        return {d for d in days if start <= d <= end}

    def minutes(self, ticker: str, session: date) -> pd.DataFrame | None:
        rows = FIXTURES[ticker]["minutes"].get(session.isoformat())
        if rows is None:
            return None
        return pd.DataFrame([{"t": ny(session, r[0]), "o": r[1], "h": r[2], "l": r[3], "c": r[4]} for r in rows])


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def seed(conn, ticker: str, arm: str = "champion", rules_version: str = RULES_VERSION):
    """One PROPOSED thesis with its `written` event, as `tr thesis` stores it."""
    a = analysis(ticker=ticker)
    journal.add_analysis(conn, a, sources=[])
    t = thesis(
        a.analysis_id, ticker=ticker, arm=arm, rules_version=rules_version, stop=98.0, target=106.0,
        invalidation_price=99.0, hold_sessions=3,
        entry=EntryRule(kind="stop", price=101.0, window_start=ny(D1, "09:30"), window_end=ny(D1, "16:00")),
    )
    journal.add(conn, t, event(t.thesis_id, "PROPOSED").model_copy(update={"rules_version": rules_version}))
    return t


def states(conn, subject_id: str) -> list[tuple]:
    return [(e.state, e.reason, e.price) for e in journal.events_for(conn, subject_id)]


def outcomes(conn) -> list[TeacherOutcome]:
    return [TeacherOutcome.model_validate_json(b) for (b,) in conn.execute("SELECT body FROM teacher_outcome")]


def test_settles_open_then_closed_and_stamps_the_bars_source(conn):
    """§6.8 PROPOSED → OPEN → CLOSED over two runs; each appended event cites a stored raw-bars SourceRef."""
    t = seed(conn, "SYNA")
    first = reconcile_run.run(conn, FixtureBars(), D1, now=NOW)
    assert states(conn, t.thesis_id)[1:] == [("OPEN", "entry_fill", 101.0)]
    reconcile_run.run(conn, FixtureBars(), D2, now=NOW)
    assert states(conn, t.thesis_id)[1:] == [("OPEN", "entry_fill", 101.0), ("CLOSED", "target", 106.0)]
    events = journal.events_for(conn, t.thesis_id)[1:]
    assert all(e.recorded_at == NOW and e.rules_version == RULES_VERSION for e in events)
    source = journal.get(conn, SourceRef, events[1].bars_source_id)
    assert (source.kind, source.feed) == ("bars_daily", "sip")
    assert "adjustment=raw" in source.uri and "end=2026-11-18" in source.uri
    assert events[0].bars_source_id != events[1].bars_source_id  # the day-2 run cites the longer bar set
    assert reconcile_run.render(first)[0] == f"SYNA short PROPOSED→OPEN entry_fill 101  ({t.thesis_id}, champion)"
    assert outcomes(conn) == []  # a champion thesis gets no TeacherOutcome


def test_second_run_for_the_same_session_appends_nothing(conn):
    """§6 intro: idempotent; once CLOSED the subject is no longer read at all."""
    seed(conn, "SYNA")
    reconcile_run.run(conn, FixtureBars(), D2, now=NOW)
    before = conn.execute("SELECT count(*) FROM event").fetchone()[0]
    again = reconcile_run.run(conn, FixtureBars(), D2, now=NOW)
    assert conn.execute("SELECT count(*) FROM event").fetchone()[0] == before
    assert again.settled == ()
    assert reconcile_run.render(again) == ["nothing to settle"]


def test_open_subject_rerun_is_unchanged(conn):
    t = seed(conn, "SYNA")
    reconcile_run.run(conn, FixtureBars(), D1, now=NOW)
    again = reconcile_run.run(conn, FixtureBars(), D1, now=NOW)
    assert again.settled[0].events == () and again.settled[0].notes == ()
    assert len(states(conn, t.thesis_id)) == 2
    assert reconcile_run.render(again)[0] == f"SYNA short OPEN unchanged  ({t.thesis_id}, champion)"


def test_dry_run_writes_nothing(conn):
    t = seed(conn, "SYNA")
    report = reconcile_run.run(conn, FixtureBars(), D2, dry_run=True, now=NOW)
    assert [(e.state, e.reason) for e in report.settled[0].events] == [("OPEN", "entry_fill"), ("CLOSED", "target")]
    assert len(states(conn, t.thesis_id)) == 1
    assert conn.execute("SELECT count(*) FROM source_ref").fetchone()[0] == 0
    assert reconcile_run.render(report)[-1].endswith("2 events, 0 teacher outcomes (dry run: nothing written)")


def test_teacher_thesis_closed_writes_one_teacher_outcome_with_the_grade(conn):
    """SPIKE §1.1 TeacherOutcome: CLOSED → outcome set, P2-P4 from `grade.code_checks`, no score id."""
    t = seed(conn, "SYNA", arm="teacher")
    report = reconcile_run.run(conn, FixtureBars(), D2, now=NOW)
    [o] = outcomes(conn)
    assert (o.thesis_id, o.final_state, o.outcome_score_id) == (t.thesis_id, "CLOSED", None)
    assert o.code_checks == {"p2_evidence_valid": False,  # the factory thesis cites cl_0, not one of its claims
                             "p3_invalidation_testable": True, "p4_levels_coherent": True}
    assert o.outcome.r_gross == pytest.approx((106.0 - 101.0) / 3.0)
    assert o.settled_at == journal.events_for(conn, t.thesis_id)[-1].at
    assert report.settled[0].teacher_outcome == o
    reconcile_run.run(conn, FixtureBars(), D2, now=NOW)
    assert len(outcomes(conn)) == 1


def test_teacher_thesis_expired_writes_an_outcome_without_a_grade(conn):
    t = seed(conn, "SYNB", arm="teacher")
    report = reconcile_run.run(conn, FixtureBars(), D1, now=NOW)
    assert states(conn, t.thesis_id)[1:] == [("EXPIRED", "window_missed", None)]
    [o] = outcomes(conn)
    assert (o.final_state, o.outcome) == ("EXPIRED", None)
    assert "  teacher_outcome EXPIRED" in reconcile_run.render(report)


def test_corporate_action_flag_cancels(conn):
    """§6.1: a split ex-date inside the holding period → CANCELLED corporate_action."""
    t = seed(conn, "SYND")
    reconcile_run.run(conn, FixtureBars(), D1, now=NOW)
    assert states(conn, t.thesis_id)[1:] == [("CANCELLED", "corporate_action", None)]


def test_revised_bars_give_a_data_revision_note_and_keep_the_events(conn):
    """§6 intro: a re-fetch that differs from the cited bars is a note in the run output; no event is touched."""
    t = seed(conn, "SYNA")
    reconcile_run.run(conn, FixtureBars(), D1, now=NOW)
    revised = FixtureBars({("SYNA", "2026-11-17"): [100.2, 101.7, 100.0, 101.3]})
    report = reconcile_run.run(conn, revised, D1, now=NOW)
    [note] = report.settled[0].notes
    assert note.startswith("data_revision: re-fetched SYNA bars 2026-11-17..2026-11-17 differ from src_")
    assert len(states(conn, t.thesis_id)) == 2


def test_waiting_subject_fetches_nothing_and_says_when(conn):
    t = seed(conn, "SYNA")

    class NoBars(FixtureBars):
        def daily(self, *args):
            raise AssertionError("no fetch before the entry window")

    report = reconcile_run.run(conn, NoBars(), date(2026, 11, 16), now=NOW)
    assert report.settled[0].notes == ("waiting: the entry window opens on 2026-11-17",)
    assert len(states(conn, t.thesis_id)) == 1


def test_other_rules_version_is_skipped(conn):
    t = seed(conn, "SYNA", rules_version="rules-0")
    report = reconcile_run.run(conn, FixtureBars(), D2, now=NOW)
    assert report.settled[0].notes == (f"skipped: written under rules-0, this engine is {RULES_VERSION}",)
    assert len(states(conn, t.thesis_id)) == 1


def test_open_shadows_are_listed_not_settled(conn):
    t = seed(conn, "SYNA")
    journal.add(conn, Shadow(shadow_id="sh_1", thesis_id=t.thesis_id, direction="long", entry_price=101.0,
                             entry_at=NOW, stop=98.0, target=106.0, hold_sessions=3, rule_version="shadow-1"),
                Event(event_id="ev_sh", subject_id="sh_1", state="OPEN", at=NOW, recorded_at=NOW, price=101.0,
                      reason="entry_fill", bars_source_id=None, rules_version=RULES_VERSION))
    report = reconcile_run.run(conn, FixtureBars(), D1, now=NOW)
    assert report.shadows == ("sh_1",)
    assert "skipped 1 shadow(s): settle does not support shadow subjects yet" in reconcile_run.render(report)


def test_a_session_before_close_plus_15_minutes_is_refused():
    before = datetime(2026, 11, 16, 21, 10, tzinfo=UTC)  # 16:10 New York
    with pytest.raises(SystemExit, match="2026-11-16 is not complete yet"):
        completed_session("2026-11-16", before)
    assert completed_session(None, before) == date(2026, 11, 13)
    assert completed_session("2026-11-16", datetime(2026, 11, 16, 21, 16, tzinfo=UTC)) == date(2026, 11, 16)


def test_command_with_nothing_open_prints_nothing_to_settle(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "absent.env"))
    main(["reconcile", "--dry-run"])
    assert capsys.readouterr().out == "nothing to settle\n"
