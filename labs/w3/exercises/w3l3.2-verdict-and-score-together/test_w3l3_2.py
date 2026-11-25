"""w3l3.2 the verdict and its ScoreRecord together: p1_judge returns the Score the reply earns and stores both in one
transaction.

The closed FAKEA trade, replayed with four replies (tools/fakea.py `answer`): `recorded`, the real one (pass);
`unknown` and `fail`, the same reasoning ending in the rubric's unknown or fail; `no_verdict`, the reasoning with no
verdict line. One check makes one journal write fail on purpose and looks at what the other one left.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

COST = fakea.load("judge_reply")["usage"]["cost"]


def held(row: dict | None, scores: list) -> str:
    verdict = "no verdict row" if row is None else f"verdict row {row['verdict']!r} (score_id {row['score_id']!r})"
    return fakea.masked(f"{verdict} and {len(scores)} p1_judge ScoreRecord(s)")


@pytest.fixture(scope="module")
def recorded(tmp_path_factory) -> fakea.Judging:
    return fakea.judging(tmp_path_factory.mktemp("w3l3_2_recorded"))


@pytest.fixture(scope="module")
def unknown(tmp_path_factory) -> fakea.Judging:
    return fakea.judging(tmp_path_factory.mktemp("w3l3_2_unknown"), replies=("unknown",))


@pytest.fixture(scope="module")
def no_verdict(tmp_path_factory) -> fakea.Judging:
    return fakea.judging(tmp_path_factory.mktemp("w3l3_2_no_verdict"), replies=("no_verdict",))


def test_a_pass_is_a_score_of_one_stored_with_its_score_record(recorded):
    from gigai_core.score import Score
    from tradingresearch import evals

    got = recorded.got
    _, reason = evals.p1_verdict(fakea.load("judge_reply")["choices"][0]["message"]["content"])
    assert isinstance(got, Score), (
        f"On the recorded reply (verdict pass) p1_judge ended with {fakea.shown(got)}; it returns the Score the "
        f"reply earns."
    )
    assert (got.value, got.answer, got.explanation) == (1.0, "pass", reason), (
        f"The Score has value {got.value}, answer {got.answer!r}, explanation {got.explanation[:60]!r}; for the "
        f"recorded pass it is value 1.0, answer 'pass' and the reason p1_verdict reads ({reason[:40]!r}...)"
    )
    assert got.judge is not None and got.judge.model == evals.JUDGE_MODEL and len(got.judge.calls) == 1, (
        f"The Score's judge note is {fakea.shown(got.judge)}: it names the judge model ({evals.JUDGE_MODEL}) and "
        f"holds the one call, so a score says which model gave it."
    )
    row, scores = fakea.stored(recorded.conn, recorded.thesis.thesis_id)
    assert row is not None and len(scores) == 1, (
        f"After the pass the journal holds {held(row, scores)}; it should hold one of each: the verdict that "
        f"`tr label` and the reports read, and the ScoreRecord of the call that made it."
    )
    record = scores[0]
    assert (row["verdict"], row["reason"]) == ("pass", reason), (
        f"The stored verdict is {row['verdict']!r} with reason {row['reason'][:60]!r}; the reply said pass, "
        f"{reason[:40]!r}..."
    )
    assert row["score_id"] == record.score_id, (
        f"The verdict row points at score_id {fakea.masked(str(row['score_id']))!r}; the ScoreRecord stored with it "
        f"is {fakea.masked(record.score_id)}. The verdict says which record it came from."
    )
    assert (record.kind, record.value, record.judge_model) == ("model", 1.0, evals.JUDGE_MODEL), (
        f"The ScoreRecord has kind {record.kind!r}, value {record.value}, judge_model {record.judge_model!r}; a "
        f"judge's pass is kind 'model', value 1.0, judge_model {evals.JUDGE_MODEL!r}"
    )
    sha = fakea.judge_prompt_sha256()
    says = (record.grader_version, got.judge.prompt_sha256[:12], (record.judge_prompt_sha256 or "None")[:12])
    assert says == (evals.P1Judge.version, sha[:12], sha[:12]), (
        "The ScoreRecord has grader_version {!r}; the Score's judge note gives prompt sha256 {}... and the "
        "ScoreRecord {}.... A score names the grader version (P1Judge's {!r}) and the judge's prompt "
        "({}...), so a change to either shows in the scores it gave.".format(*says, evals.P1Judge.version, sha[:12])
    )
    spans = fakea.model_spans(recorded.data_dir)
    pointed = [(record.trace_id, span) for span in record.judge_span_ids]
    assert pointed and sorted(pointed) == sorted(spans), (
        f"The ScoreRecord points at {fakea.masked(str(pointed))}; the run file's model spans are "
        f"{fakea.masked(str(spans))}. A judge's ScoreRecord points at the trace and spans of the call it scores."
    )


def test_unknown_is_stored_as_fail_with_value_zero(unknown):
    from gigai_core.score import Score

    got = unknown.got
    assert isinstance(got, Score), f"On a reply whose verdict is unknown, p1_judge ended with {fakea.shown(got)}"
    assert (got.value, got.answer) == (0.0, "fail") and got.explanation.startswith("unknown:"), (
        f"On a reply whose verdict is unknown the Score has value {got.value}, answer {got.answer!r}, explanation "
        f"{got.explanation[:30]!r}...; unknown is an abstain the rubric stores as fail: value 0.0, answer 'fail', the "
        f"reason starting 'unknown:' (as your p1_verdict reads it)."
    )
    row, scores = fakea.stored(unknown.conn, unknown.thesis.thesis_id)
    stored_ok = row is not None and row["verdict"] == "fail" and row["reason"].startswith("unknown:")
    assert stored_ok and len(scores) == 1 and scores[0].value == 0.0, (
        f"After an unknown the journal holds {held(row, scores)}"
        f"{'' if not scores else f', value {scores[0].value}'}; it should hold verdict 'fail' with an 'unknown:' "
        f"reason and one ScoreRecord of value 0.0."
    )


def test_a_reply_with_no_verdict_stores_nothing_and_keeps_its_run(no_verdict):
    from tradingresearch.evals import CannotGrade

    got = no_verdict.got
    assert isinstance(got, CannotGrade), (
        f"On a reply with no verdict p1_judge ended with {fakea.shown(got)}; such a reply cannot grade the thesis "
        f"(your p1_verdict says CannotGrade), and p1_judge passes that on."
    )
    assert no_verdict.raised, (
        f"p1_judge returned {fakea.shown(got)} instead of raising it. A returned CannotGrade is a value: the caller "
        f"(`tr grade --judge`) never sees it as an error and reads it as the thesis's result."
    )
    row, scores = fakea.stored(no_verdict.conn, no_verdict.thesis.thesis_id)
    assert row is None and not scores, (
        f"After a reply with no verdict the journal holds {held(row, scores)}: no verdict was given, so none is "
        f"stored; a stored fail would grade the thesis on a reply that never said."
    )
    files = fakea.run_files(no_verdict.data_dir)
    assert len(files) == 1 and abs(fakea.spent(files[0]) - COST) < 1e-6, (
        f"A reply with no verdict was still paid (${COST:.6f}); its run file must stay and say so. Run files: "
        f"{len(files)}."
    )


@pytest.mark.parametrize("broken", ["add_judge_verdict", "_insert_score"])
def test_a_failure_between_the_two_writes_leaves_neither(tmp_path, broken):
    j = fakea.judging(tmp_path, broken=broken)
    assert isinstance(j.got, sqlite3.OperationalError), (
        f"With journal.{broken} failing, p1_judge ended with {fakea.shown(j.got)}; the storage error should reach the "
        f"caller."
    )
    row, scores = fakea.stored(j.conn, j.thesis.thesis_id)
    assert row is None and not scores, (
        f"journal.{broken} failed (injected) and the journal still holds {held(row, scores)}. The verdict and the "
        f"ScoreRecord it points at land in one transaction: a failure between the two writes leaves neither."
    )


def test_the_score_record_keeps_the_reason(recorded):
    row, scores = fakea.stored(recorded.conn, recorded.thesis.thesis_id)
    assert row is not None and len(scores) == 1, f"After the pass the journal holds {held(row, scores)}"
    assert scores[0].explanation == recorded.got.explanation == row["reason"], (
        f"The ScoreRecord's explanation is {scores[0].explanation[:40]!r}; the Score and the verdict row give the "
        f"reason {row['reason'][:40]!r}.... The ScoreRecord is what a later audit reads: it keeps the judge's reason "
        f"for the score, the same as the verdict it backs."
    )


def test_a_fail_verdict_is_a_score_of_zero(tmp_path):
    from gigai_core.score import Score
    from tradingresearch import evals

    j = fakea.judging(tmp_path, replies=("fail",))
    _, reason = evals.p1_verdict(fakea.answer("fail").json()["choices"][0]["message"]["content"])
    got = j.got
    assert isinstance(got, Score), f"On a reply whose verdict is fail, p1_judge ended with {fakea.shown(got)}"
    row, scores = fakea.stored(j.conn, j.thesis.thesis_id)
    says = (got.value, got.answer, got.explanation, row and row["verdict"], [s.value for s in scores])
    assert says == (0.0, "fail", reason, "fail", [0.0]), (
        f"On a reply whose verdict is fail the Score has value {got.value}, answer {got.answer!r}, and the journal "
        f"holds {held(row, scores)}{'' if not scores else f', value {scores[0].value}'}. Only a pass earns 1.0: a "
        f"fail is value 0.0, answer 'fail', stored as verdict 'fail' with one ScoreRecord of value 0.0."
    )
