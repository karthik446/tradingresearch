"""`tr grade` (SPIKE §7.1, §7.2, §7.4): shadows from the real fill, settled by `settle`; one Grade per closed thesis;
P2-P4 from checks.py; the P1 post-trade summary. Synthetic tickers and bars, hand-computed numbers, no model."""

from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import pytest

from factories import analysis, claim, event, snapshot, thesis
from tradingresearch import grade, journal, reconcile_run
from tradingresearch.analyze import snapshot_rows
from tradingresearch.cli import main
from tradingresearch.records import (RULES_VERSION, Congestion, EntryRule, Event, Grade, OutcomeGrade, Shadow,
                                     SourceRef)
from tradingresearch.sessions import NY

D0, D1, D2, D3 = date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19)
NOW = datetime(2026, 11, 19, 22, 0, tzinfo=UTC)
DAILY = {  # o, h, l, c: the thesis (long stop 101, stop 98, target 106) fills on D1 and hits its target on D2
    D1: [100.2, 101.6, 100.0, 101.3],
    D2: [101.5, 106.5, 101.0, 106.2],
    D3: [106.0, 107.5, 105.0, 107.2],
}
MINUTES = {D1: [("09:30", 100.2, 100.6, 100.0, 100.5), ("10:00", 100.5, 101.4, 100.4, 101.2)]}


def ny(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), NY).astimezone(UTC)


class Bars:
    """A BarSource over DAILY and MINUTES for any synthetic ticker; it counts the daily fetches."""

    feed = "sip"

    def __init__(self) -> None:
        self.fetched = 0

    def daily(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        self.fetched += 1
        rows = [{"session": d, "o": o, "h": h, "l": low, "c": c, "v": 1000, "n": 10, "vw": c}
                for d, (o, h, low, c) in DAILY.items() if start <= d <= end]
        return pd.DataFrame(rows, columns=["session", "o", "h", "l", "c", "v", "n", "vw"])

    def corporate_action_days(self, ticker: str, start: date, end: date) -> set[date]:
        return set()

    def minutes(self, ticker: str, session: date) -> pd.DataFrame | None:
        rows = MINUTES.get(session)
        if rows is None:
            return None
        return pd.DataFrame([{"t": ny(session, r[0]), "o": r[1], "h": r[2], "l": r[3], "c": r[4]} for r in rows])


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def seed(conn, ticker: str = "SYNG", sma_20: float | None = 99.0, arm: str = "champion"):
    """One PROPOSED long thesis from an analysis whose close is 100; sma_20 sets the shadow's direction."""
    values = {"close": 100.0, "atr_14": 2.0} | ({} if sma_20 is None else {"sma_20": sma_20})
    a = analysis(ticker=ticker, session=D0, snapshot=snapshot(ticker=ticker, session=D0, values=values),
                 terms_class="trainable" if arm == "teacher" else "restricted")
    journal.add_analysis(conn, a, sources=[])
    t = thesis(a.analysis_id, ticker=ticker, arm=arm, rules_version=RULES_VERSION, stop=98.0, target=106.0,
               invalidation_price=98.0, hold_sessions=2, terms_class=a.terms_class,
               entry=EntryRule(kind="stop", price=101.0, window_start=ny(D1, "09:30"), window_end=ny(D1, "16:00")))
    journal.add(conn, t, event(t.thesis_id, "PROPOSED").model_copy(update={"rules_version": RULES_VERSION}))
    return t


def settle(conn, bars: Bars, day: date) -> None:
    reconcile_run.run(conn, bars, day, now=NOW)


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def opened(price: float = 101.0) -> Event:
    return event("th_x", "OPEN", reason="entry_fill").model_copy(update={"price": price, "at": ny(D1, "10:00")})


# ---------- the shadow's numbers (§7.4) ----------

def test_the_shadow_takes_the_fill_and_its_stop_distance_with_direction_from_close_vs_sma_20():
    t = thesis("an_x", stop=98.0)
    long_ = grade.shadow_for(t, opened(), analysis(snapshot=snapshot(values={"close": 100.0, "sma_20": 99.0})))
    short = grade.shadow_for(t, opened(), analysis(snapshot=snapshot(values={"close": 100.0, "sma_20": 101.0})))
    assert isinstance(long_, Shadow) and isinstance(short, Shadow)
    assert (long_.direction, long_.entry_price, long_.stop, long_.target) == ("long", 101.0, 98.0, 107.0)
    assert (short.direction, short.entry_price, short.stop, short.target) == ("short", 101.0, 104.0, 95.0)
    assert long_.entry_at == ny(D1, "10:00") and long_.hold_sessions == t.hold_sessions
    assert long_.rule_version == RULES_VERSION and long_.shadow_id == short.shadow_id  # one shadow per thesis


def test_no_shadow_without_a_direction_or_a_stop_distance():
    t = thesis("an_x", stop=98.0)
    flat = analysis(snapshot=snapshot(values={"close": 100.0, "sma_20": 100.0}))
    assert grade.shadow_for(t, opened(), flat) == "no shadow: close 100 equals sma_20, so no direction"
    assert grade.shadow_for(t, opened(), analysis()) == "no shadow: the snapshot has no close or sma_20"
    up = analysis(snapshot=snapshot(values={"close": 100.0, "sma_20": 99.0}))
    assert grade.shadow_for(t, opened(98.0), up) == "no shadow: the fill 98 equals the stop"


# ---------- runs over the journal ----------

def test_a_proposed_thesis_waits_and_no_bars_are_read(conn):
    t = seed(conn)
    report = grade.run(conn, None, D1, now=NOW)
    assert [(it.thesis.thesis_id, it.waiting) for it in report.items] == [(t.thesis_id, "PROPOSED: not filled yet")]
    assert grade.render(report)[-1] == "grade 2026-11-17: 0 graded, 0 shadow(s) created, 1 waiting"


def test_the_long_shadow_opens_at_the_fill_and_the_grade_waits_until_it_closes(conn):
    t, bars = seed(conn), Bars()
    settle(conn, bars, D1)
    [it] = grade.run(conn, bars, D1, now=NOW).items
    s = it.shadow
    assert it.created and it.waiting == "OPEN: not closed yet" and (s.direction, s.stop, s.target) == ("long", 98, 107)
    assert [(e.state, e.reason, e.price, e.at) for e in journal.events_for(conn, s.shadow_id)] == [
        ("PROPOSED", "written", None, ny(D1, "10:00")), ("OPEN", "entry_fill", 101.0, ny(D1, "10:00"))]
    assert journal.get(conn, SourceRef, journal.events_for(conn, s.shadow_id)[1].bars_source_id).kind == "bars_daily"
    settle(conn, bars, D2)  # the thesis hits 106 on D2; the shadow's 107 is not reached until D3
    [it] = grade.run(conn, bars, D2, now=NOW).items
    assert not it.created and it.outcome is not None and it.grade is None
    assert it.waiting == f"shadow {s.shadow_id} OPEN: the grade waits for it to close"
    assert (count(conn, "shadow"), count(conn, "grade"), count(conn, "shadow_outcome")) == (1, 0, 0)


def test_both_closed_gives_one_grade_with_its_score_and_graded_event_and_a_rerun_adds_nothing(conn):
    t, bars = seed(conn), Bars()
    for day in (D1, D2):
        settle(conn, bars, day)
    report = grade.run(conn, bars, D3, now=NOW)
    [it] = report.items
    so, o = it.shadow_outcome, it.outcome
    assert (so.exit_reason, so.exit_price, so.r_gross, so.mae_r, so.sessions_held) == ("target", 107.0, 2.0,
                                                                                      pytest.approx(-0.2), 2)
    assert (o.exit_reason, o.exit_price, o.r_gross, o.sessions_held) == ("target", 106.0, pytest.approx(5 / 3), 1)
    assert o.r_net == pytest.approx(o.r_gross - o.cost_r)
    [g] = [Grade.model_validate_json(b) for (b,) in conn.execute("SELECT body FROM grade")]
    assert g == it.grade and (g.thesis_id, g.shadow_id, g.outcome, g.process_score_id) == (
        t.thesis_id, it.shadow.shadow_id, o, None)
    assert g.code_checks == {"p2_evidence_valid": False, "p3_invalidation_testable": True, "p4_levels_coherent": True}
    [score] = journal.scores_for(conn, t.thesis_id)
    assert (score.score_id, score.value, score.grader_id, score.kind) == (g.outcome_score_id, o.r_net, "outcome_r_net",
                                                                          "code")
    assert journal.shadow_outcome(conn, it.shadow.shadow_id) == so
    assert [(e.state, e.reason) for e in journal.events_for(conn, t.thesis_id)][-1] == ("GRADED", "graded")
    line = grade.render(report)[0]
    assert f"r_net {o.r_net:+.2f}" in line and f"r_net {so.r_net:+.2f}" in line and "P2 fail P3 ok P4 ok" in line
    assert grade.render(report)[-1] == "grade 2026-11-19: 1 graded, 1 shadow(s) created, 0 waiting"
    assert grade.run(conn, bars, D3, now=NOW).items == ()  # built once: the thesis is no longer ungraded
    assert (count(conn, "grade"), count(conn, "score"), count(conn, "shadow")) == (1, 1, 1)
    with pytest.raises(Exception, match="UNIQUE|append-only"):
        journal.add_grade(conn, *grade.build_grade(t, journal.get(conn, type(analysis()), t.analysis_id), o,
                                                   it.shadow, NOW))


def test_the_short_shadow_is_stopped_at_its_stop(conn):
    seed(conn, sma_20=101.0)
    bars = Bars()
    for day in (D1, D2):
        settle(conn, bars, day)
    [it] = grade.run(conn, bars, D2, now=NOW).items
    so = it.shadow_outcome
    assert (it.shadow.direction, so.exit_reason, so.exit_price, so.r_gross) == ("short", "stop", 104.0, -1.0)
    assert it.grade is not None and it.waiting is None


def test_a_dry_run_shows_the_grade_and_writes_nothing(conn):
    seed(conn)
    bars = Bars()
    for day in (D1, D2):
        settle(conn, bars, day)
    report = grade.run(conn, bars, D3, dry_run=True, now=NOW)
    assert report.items[0].grade is not None
    assert (count(conn, "shadow"), count(conn, "grade"), count(conn, "score")) == (0, 0, 0)
    lines = grade.render(report)
    assert "would grade" in lines[0] and lines[1].startswith("    would create shadow sh_")
    assert lines[-1] == ("grade 2026-11-19 (dry run): would grade 1, would create 1 shadow(s), 0 waiting; "
                         "nothing written")


def test_a_teacher_thesis_gets_no_shadow_and_no_grade(conn):
    seed(conn, "SYNH", arm="teacher")
    bars = Bars()
    for day in (D1, D2):
        settle(conn, bars, day)
    assert grade.run(conn, bars, D3, now=NOW).items == ()
    assert (count(conn, "shadow"), count(conn, "grade"), count(conn, "teacher_outcome")) == (0, 0, 1)


def test_no_sma_20_means_no_shadow_and_the_thesis_waits(conn):
    seed(conn, sma_20=None)
    bars = Bars()
    settle(conn, bars, D1)
    [it] = grade.run(conn, bars, D1, now=NOW).items
    assert it.waiting == "no shadow: the snapshot has no close or sma_20" and count(conn, "shadow") == 0


def test_tr_grade_dry_run_on_proposed_theses_reads_no_bars(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    conn = journal.connect(tmp_path / "journal.db")
    t = seed(conn)
    conn.close()
    main(["grade", "--session", "2026-11-16", "--dry-run"])  # a completed session; the fill window is later
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(f"SYNG   short {t.thesis_id} PROPOSED")
    assert out[0].endswith("waiting: PROPOSED: not filled yet")
    assert out[-1] == "grade 2026-11-16 (dry run): would grade 0, would create 0 shadow(s), 1 waiting; nothing written"


# ---------- the P1 judge's post-trade summary ----------

def test_post_trade_summary_reports_the_exit_trigger_volume_and_closes_against_cited_levels():
    snap = snapshot(ticker="SYNG", session=D0, values={"close": 100.0, "atr_14": 2.0, "sma_20": 99.0, "high_20": 104.0},
                    congestion=Congestion(low=98.0, high=104.0, sessions=6, range_atr=1.2))
    rows = {row.name: row for row in snapshot_rows(snap)[1]}
    aid = "an_post"
    high = claim(aid, claim_id="cl_high", value=104.0, source_ids=(rows["high_20"].source_id,))
    sma = claim(aid, claim_id="cl_sma", value=99.0, source_ids=(rows["sma_20"].source_id,))
    above = claim(aid, claim_id="cl_inf", tag="inference", value=None, unit=None, source_ids=(),
                  derived_from=("cl_sma",), steps="close 100 > sma_20 99")
    a = analysis(analysis_id=aid, ticker="SYNG", session=D0, snapshot=snap, claims=(high, sma, above))
    t = thesis(aid, ticker="SYNG", evidence=("cl_high", "cl_inf"), invalidation_price=98.0, stop=98.0)
    events = (opened(), Event.model_validate(opened().model_dump() | {
        "state": "CLOSED", "reason": "target", "price": 106.0, "at": ny(D2, "11:00")}))
    earlier = [D1 - timedelta(days=n) for n in range(20, 0, -1)]
    bars = pd.DataFrame([{"session": d, "c": 100.0, "v": 1000} for d in earlier] + [
        {"session": D1, "c": 101.3, "v": 2500}, {"session": D2, "c": 103.5, "v": 1500},
        {"session": D3, "c": 107.2, "v": 900}])
    outcome = OutcomeGrade(subject_id=t.thesis_id, entry_price=101.0, exit_price=106.0, r_gross=5 / 3, cost_bps=10.0,
                           cost_r=0.0337, r_net=1.633, mfe_r=1.83, mae_r=-0.2, exit_reason="target", sessions_held=1)
    assert grade.post_trade_summary(t, a, events, bars, outcome).splitlines() == [
        "exit: target at 106 on 2026-11-18, filled at 101 on 2026-11-17; r_net +1.63, MFE +1.83R, MAE -0.20R, "
        "1 session(s) held after the fill day",
        "trigger day 2026-11-17: rel_volume 2.50",
        "closes: 2026-11-17 101.3, 2026-11-18 103.5",
        "vs high_20 104: closed at or above it on 0 of 2 sessions",
        "vs sma_20 99: closed at or above it on 2 of 2 sessions",
        "vs invalidation 98: closed at or above it on 2 of 2 sessions",
        "congestion 98-104 (6 sessions): high held on 0 of 2 closes, low held on 2 of 2 (held = closed at or above "
        "it, the trade's side)",
    ]
    assert "rel_volume n/a (fewer than 20 sessions before it)" in grade.post_trade_summary(t, a, events, bars[5:],
                                                                                          outcome)
