"""w3l3.3 refuse before the call: a thesis the judge may not take costs nothing and says why.

Two theses from tests/test_week3.py's FAKEA trade (tools/fakea.py `judging`): the teacher arm's, closed but never graded
(ADR-003: teacher theses are never judged), and a champion thesis that never entered (PROPOSED, no Grade, so no
post-trade summary to judge). The transport answers any request with the recorded reply, so a call would be a paid one.
The last check makes the journal's reads fail on purpose: a storage error is not a refusal.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

WHAT = {"teacher": "a teacher thesis (ADR-003: teacher theses are never judged)",
        "never_entered": "a thesis that never entered (no Grade, so no post-trade summary to judge)"}


@pytest.mark.parametrize(("arm", "why"), [("teacher", "teacher thesis"), ("never_entered", "no grade")])
def test_a_thesis_the_judge_may_not_take_is_refused_before_any_call(tmp_path, arm, why):
    from tradingresearch.evals import CannotGrade

    j = fakea.judging(tmp_path, arm=arm)
    assert isinstance(j.got, CannotGrade), (
        f"On {WHAT[arm]} p1_judge ended with {fakea.shown(j.got)}, after {len(j.sent)} request(s). A grader that "
        f"will not grade raises CannotGrade: the one error `tr grade --judge` keeps on a thesis before it goes on."
    )
    assert j.raised, (
        f"p1_judge returned {fakea.shown(j.got)} instead of raising it. A returned CannotGrade is a value: the "
        f"caller (`tr grade --judge`) never sees it as an error and reads it as the thesis's result."
    )
    assert why in str(j.got), (
        f"CannotGrade says {fakea.shown(j.got)!r}; it should say why, as label.labelable's refusal does "
        f"({why!r} is in its reason)."
    )
    files = fakea.run_files(j.data_dir)
    row, scores = fakea.stored(j.conn, j.thesis.thesis_id)
    assert not j.sent and not files, (
        f"On {WHAT[arm]} p1_judge sent {len(j.sent)} request(s) and left {len(files)} run file(s): the refusal comes "
        f"before any call, so a thesis the judge may not take costs nothing."
    )
    assert row is None and not scores, (
        f"The refusal left a verdict row ({None if row is None else row['verdict']!r}) and {len(scores)} p1_judge "
        f"ScoreRecord(s); a thesis that was not judged has no verdict."
    )


@pytest.mark.parametrize("arm", ["teacher", "never_entered"])
def test_the_refusal_keeps_its_own_words(tmp_path, arm):
    from tradingresearch import label

    j = fakea.judging(tmp_path, arm=arm)
    with pytest.raises(label.Refused) as refused:
        label.labelable(j.conn, j.thesis.thesis_id)
    assert str(refused.value) in str(j.got), (
        f"CannotGrade says {fakea.shown(j.got)!r}; label.labelable refused this thesis with "
        f"{fakea.masked(str(refused.value))!r}. The operator reads only the CannotGrade, so it carries the whole "
        f"refusal, not a summary or a part of it."
    )


def test_a_storage_error_is_not_a_refusal(tmp_path):
    j = fakea.judging(tmp_path, broken="get")
    assert isinstance(j.got, sqlite3.OperationalError) and j.raised, (
        f"With the journal's reads failing (an injected disk I/O error) p1_judge ended with {fakea.shown(j.got)}. "
        f"Only label.Refused is a refusal; a storage error says nothing about the thesis, and it should reach the "
        f"caller as it is, not as CannotGrade (which `tr grade --judge` reports as the thesis's outcome and goes on)."
    )
