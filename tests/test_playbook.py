"""The playbook (SPIKE §8.1): rows per (horizon, setup_type) with hand-computed Wilson, mean and median numbers, the
thin flag, the as-of cutoff, arm separation, the computed facts and the empty state. No model call."""

import math
from datetime import UTC, date, datetime

import pytest
from gigai_core.score import ScoreRecord

from factories import T0, analysis, event, thesis
from tradingresearch import journal, playbook
from tradingresearch.cli import main
from tradingresearch.hashing import new_id
from tradingresearch.records import Grade, OutcomeGrade

Z = 1.959963984540054  # two-sided 95%
HOLD = {"day": 0, "short": 5, "swing": 10}


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 17, 0, tzinfo=UTC)  # 12:00 New York, same date


def add_thesis(conn, session: date, *, arm: str = "champion", horizon: str = "short", setup: str = "breakout_20d",
               r_net: float = 1.0, final: str = "GRADED", p1: str | None = None, closed: date | None = None,
               mfe: float = 1.0, mae: float = -0.5) -> str:
    """One main-analysis thesis on `session`, opened that day; `final` GRADED (closed on `closed`, default the same
    day), EXPIRED, CANCELLED, OPEN or PROPOSED. `p1` is a judge verdict: pass, fail or unknown."""
    a = analysis(session=session)
    journal.add_analysis(conn, a, sources=[])
    t = thesis(a.analysis_id, arm=arm, horizon=horizon, setup_type=setup, hold_sessions=HOLD[horizon])
    steps = {"GRADED": ["PROPOSED", "OPEN", "CLOSED"], "EXPIRED": ["PROPOSED", "EXPIRED"],
             "CANCELLED": ["PROPOSED", "CANCELLED"], "OPEN": ["PROPOSED", "OPEN"], "PROPOSED": ["PROPOSED"]}[final]
    days = {"PROPOSED": T0, "OPEN": at(session), "CLOSED": at(closed or session)}
    journal.add(conn, t, *(event(t.thesis_id, s).model_copy(update={"at": days.get(s, at(session))}) for s in steps))
    if final == "GRADED":
        o = OutcomeGrade(subject_id=t.thesis_id, entry_price=100.0, exit_price=100.0 + r_net, r_gross=r_net,
                         cost_bps=0.0, cost_r=0.0, r_net=r_net, mfe_r=mfe, mae_r=mae, exit_reason="target",
                         sessions_held=1)
        score = ScoreRecord(score_id=new_id("sc"), trace_id="trace_0", grader_id="outcome_r_net", grader_version="1",
                            kind="code", value=r_net, recorded_at=T0)
        journal.add_grade(conn, Grade(grade_id=new_id("gr"), thesis_id=t.thesis_id, outcome=o,
                                      outcome_score_id=score.score_id, process_score_id=None, code_checks={},
                                      shadow_id=new_id("sh")), score, event(t.thesis_id, "GRADED", reason="graded"))
        if p1 is not None:
            verdict, reason = ("pass", "ok") if p1 == "pass" else ("fail", "unknown: no data" if p1 == "unknown"
                                                                      else "invalidation not specific")
            journal.add_judge_verdict(conn, t.thesis_id, verdict, reason)
    return t.thesis_id


def wilson(k: int, n: int) -> tuple[float, float]:
    """(p + z²/2n ± z sqrt(p(1-p)/n + z²/4n²)) / (1 + z²/n)."""
    p = k / n
    centre, half = p + Z**2 / (2 * n), Z * math.sqrt(p * (1 - p) / n + Z**2 / (4 * n**2))
    return (centre - half) / (1 + Z**2 / n), (centre + half) / (1 + Z**2 / n)


def test_a_thin_cell_shows_hand_computed_numbers_and_is_flagged(conn):
    add_thesis(conn, date(2026, 12, 1), r_net=1.0, p1="pass", mfe=1.0, mae=-0.5)
    add_thesis(conn, date(2026, 12, 2), r_net=-0.5, p1="fail", mfe=0.5, mae=-1.0)
    add_thesis(conn, date(2026, 12, 3), r_net=2.0, p1="unknown", mfe=3.0, mae=-0.2)
    lines = playbook.render(playbook.compute(conn, date(2026, 12, 3)))
    lo, hi = wilson(2, 3)  # 2 wins (r_net > 0) of 3
    assert lines[1:] == [
        "short breakout_20d: n 3 closed THIN",
        f"  win rate 2/3 = 66.7%, 95% CI [{lo:.1%}, {hi:.1%}] (Wilson)",
        "  mean r_net +0.83 R, 95% CI insufficient (3 sessions < 10)",  # (1.0 - 0.5 + 2.0) / 3 = 0.833
        "  real - shadow: no shadow outcome yet; P1 met 1/2 = 50.0%; 1 unknown excluded",
        "  median MFE +1.00 R, median MAE -0.50 R"]  # medians of (1.0, 0.5, 3.0) and (-0.5, -1.0, -0.2)


def test_ten_sessions_of_constant_r_give_an_exact_interval_and_no_thin_flag(conn):
    days = [date(2026, 12, d) for d in (1, 2, 3, 4, 7, 8, 9, 10, 11, 14)]
    for day in days:
        add_thesis(conn, day, horizon="swing", setup="range_fade", r_net=1.0)
    (row,) = playbook.compute(conn, days[-1]).rows
    assert (row.horizon, row.setup_type, row.n, row.thin) == ("swing", "range_fade", 10, False)
    assert (row.mean_r_ci.ci.lower, row.mean_r_ci.ci.upper) == (1.0, 1.0)  # every resample of ten 1.0s means 1.0


def test_rows_are_per_horizon_and_setup_and_never_pooled(conn):
    add_thesis(conn, date(2026, 12, 1), horizon="swing", setup="breakout_20d")
    add_thesis(conn, date(2026, 12, 1), horizon="day", setup="gap_continuation")
    add_thesis(conn, date(2026, 12, 2), horizon="day", setup="breakout_20d")
    rows = playbook.compute(conn, date(2026, 12, 2)).rows
    assert [(r.horizon, r.setup_type, r.n) for r in rows] == [
        ("day", "breakout_20d", 1), ("day", "gap_continuation", 1), ("swing", "breakout_20d", 1)]


def test_only_trades_closed_by_the_session_and_graded_count(conn):
    add_thesis(conn, date(2026, 12, 1), r_net=1.0)
    add_thesis(conn, date(2026, 12, 1), r_net=5.0, closed=date(2026, 12, 3))  # closes after the cutoff
    add_thesis(conn, date(2026, 12, 2), final="EXPIRED")
    add_thesis(conn, date(2026, 12, 2), horizon="swing", final="OPEN")
    (row,) = playbook.compute(conn, date(2026, 12, 2)).rows
    assert [t.r_net for t in row.trades] == [1.0]


def test_arms_are_separate_and_the_teacher_has_no_playbook(conn):
    add_thesis(conn, date(2026, 12, 1), r_net=1.0)
    add_thesis(conn, date(2026, 12, 1), arm="challenger", r_net=-1.0)
    assert [t.r_net for t in playbook.compute(conn, date(2026, 12, 1)).rows[0].trades] == [1.0]
    assert [t.r_net for t in playbook.compute(conn, date(2026, 12, 1), "challenger").rows[0].trades] == [-1.0]
    with pytest.raises(ValueError, match="teacher"):
        playbook.compute(conn, date(2026, 12, 1), "teacher")


def test_facts_are_computed_source_dicts(conn):
    add_thesis(conn, date(2026, 12, 1), r_net=1.0, p1="pass")
    (fact,) = playbook.as_facts(playbook.compute(conn, date(2026, 12, 1)))
    assert fact["kind"] == "computed" and fact["uri"] == playbook.SOURCE_URI
    assert (fact["horizon"], fact["setup_type"], fact["n"], fact["thin"], fact["win_rate"]) == (
        "short", "breakout_20d", 1, True, 1.0)
    assert (fact["mean_r_net"], fact["mean_r_net_ci"], fact["p1_met"], fact["p1_judged"]) == (1.0, None, 1, 1)


def test_an_empty_journal_prints_an_honest_empty_playbook(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    main(["learn", "--session", "2026-12-01"])
    assert capsys.readouterr().out.splitlines() == [
        "playbook: champion theses graded and closed by 2026-12-01, one row per (horizon, setup_type), never pooled; "
        "cells with n < 5 are thin (few trades overfit)",
        "  no graded champion theses closed by 2026-12-01 yet: nothing to learn from"]
