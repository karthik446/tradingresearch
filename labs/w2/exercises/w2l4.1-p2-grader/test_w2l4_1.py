"""w2l4.1 P2 as a grader: score a whole thesis run, 1 if every thesis in it passes p2_evidence_valid, else 0.

The sample is the author's recorded reply (tests/fixtures/thesis/AAPL_2026-11-16.*, the week-1 champion on AAPL): one
swing thesis, limit 343.41, evidence cl_9357533ae3784540 (a fact: level_hvn_2 at 343.41), cl_f8c267ead3c04d34 (an
inference) and cl_dfd3b95f6afc4f93 (a fact: regime_spy). Each case copies that thesis and says what it changed.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from gigai_core.graders.protocol import CannotGrade
from gigai_core.score import Score

from tradingresearch import evals, thesis as th
from tradingresearch.records import Analysis

FIXTURES = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "thesis"
ANALYSIS = Analysis.model_validate_json((FIXTURES / "AAPL_2026-11-16.analysis.json").read_text())
REPLY = json.loads((FIXTURES / "AAPL_2026-11-16.reply.json").read_text())
EXPECTED = th.item_for(ANALYSIS, ("day", "short", "swing"), "champion").expected
OPINION = "cl_ba1ecc8934034a7d"  # "The setup looks constructive but somewhat extended ...", tagged opinion
GRADER = "p2_evidence_valid"


def swing(**changes) -> dict:
    return {**REPLY["theses"][0], **changes}


def short(**changes) -> dict:
    """The same thesis as a short-horizon one (3 sessions), so a sample can hold two theses."""
    return swing(horizon="short", hold_sessions=3, **changes)


def with_opinion(item: dict) -> dict:
    return {**item, "evidence": [*item["evidence"], OPINION]}


def grade(*items, parse_status: str = "ok") -> object:
    sample = SimpleNamespace(parse_status=parse_status, output_parsed={"theses": list(items), "no_trade": []},
                             recorded_at=datetime(2026, 11, 17, 3, 46, tzinfo=UTC), trace_id="t")
    try:
        return evals.GRADERS[GRADER]().grade(sample, EXPECTED)
    except CannotGrade:
        raise
    except Exception as exc:  # show a crash as a result, so the message can say which sample caused it
        return f"{type(exc).__name__}: {exc}"


def shown(got: object) -> str:
    if isinstance(got, Score):
        return f"Score(value={got.value!r}, explanation={got.explanation!r})"
    return repr(got)


def test_p2_is_a_registered_code_grader():
    assert GRADER in evals.GRADERS, (
        f"No grader is registered under {GRADER!r}. An experiment config names its graders by id and "
        f"evals.graders() finds them in evals.GRADERS, which holds {', '.join(evals.GRADERS)}; a class reaches it "
        f"only through @grader"
    )
    cls = evals.GRADERS[GRADER]
    assert cls.id == GRADER, f"evals.GRADERS[{GRADER!r}] is {cls.__name__}, whose id is {cls.id!r}"
    assert cls.kind == "code", (
        f"{cls.__name__}.kind is {cls.kind!r}. kind says what decides the score: P2 is a rule in code, like parsed "
        f"and claims_valid beside it, not a model's judgement"
    )
    assert isinstance(cls.version, str) and cls.version, (
        f"{cls.__name__}.version is {cls.version!r} ({type(cls.version).__name__}). Every grader in the registry "
        f"carries its version as a non-empty string (Parsed has {evals.GRADERS['parsed'].version!r}): the eval "
        f"records store it beside each score, so scores from a changed rule are never compared with old ones"
    )


def test_the_real_reply_scores_one():
    got = grade(swing())
    assert isinstance(got, Score) and got.value == 1.0 and got.explanation is None, (
        f"The recorded AAPL reply has one swing thesis; its evidence is two facts whose numbers are in the thesis "
        f"prompt's source table (level_hvn_2 343.41 under source src_1cad32e483f64af9, regime_spy) and one "
        f"inference, so p2_evidence_valid passes it and the run scores Score(value=1.0, explanation=None); got "
        f"{shown(got)}"
    )


def test_one_broken_thesis_after_a_good_one_scores_zero():
    got = grade(swing(), with_opinion(short()))
    assert isinstance(got, Score) and got.value == 0.0 and got.explanation == "fails: short", (
        f"A run of two theses: the real swing, then a short-horizon copy whose evidence adds {OPINION}, an opinion. "
        f"The short fails P2, so the run scores 0.0 and the explanation names the failing horizon: 'fails: short'. "
        f"P2 is binary per run, not a share of theses; got {shown(got)}"
    )


def test_one_broken_thesis_before_a_good_one_scores_zero():
    got = grade(with_opinion(swing()), short())
    assert isinstance(got, Score) and got.value == 0.0 and got.explanation == "fails: swing", (
        f"A run of two theses: the swing with {OPINION} (an opinion) added to its evidence, then the real thesis as "
        f"a short-horizon copy, which passes. One thesis failing fails the run, whichever place it holds: expected "
        f"Score(value=0.0, explanation='fails: swing'); got {shown(got)}"
    )


def test_every_failing_horizon_is_named_in_order():
    got = grade(with_opinion(swing()), with_opinion(short()))
    assert isinstance(got, Score) and got.value == 0.0 and got.explanation == "fails: swing, short", (
        f"Both theses of the run (swing, then short) cite the opinion {OPINION}. The explanation names every failing "
        f"horizon in the order the reply gave them: expected 'fails: swing, short'; got {shown(got)}"
    )


def test_a_broken_third_thesis_fails_the_run():
    got = grade(swing(horizon="day", hold_sessions=0), short(), with_opinion(swing()))
    assert isinstance(got, Score) and got.value == 0.0 and got.explanation == "fails: swing", (
        f"A run of three theses, one per horizon the item asks for: day and short copies of the real thesis, which "
        f"pass, then the swing with {OPINION} (an opinion) added to its evidence. The third fails P2 as surely as a "
        f"first would: expected Score(value=0.0, explanation='fails: swing'); got {shown(got)}"
    )


def test_an_item_that_does_not_build_is_not_graded_here():
    got = grade(swing(), "not a thesis")
    assert isinstance(got, Score) and got.value == 1.0 and got.explanation is None, (
        f"A run holding the real swing thesis and the string 'not a thesis'. That item never builds into a Thesis, "
        f"so P2 has nothing to check in it (theses_valid counts it); the one thesis passes and the run scores "
        f"Score(value=1.0, explanation=None); got {shown(got)}"
    )


NOTHING_TO_GRADE = (
    ("the real reply with parse_status 'invalid_json'", (swing(),), "invalid_json", "did not parse"),
    ("a parsed run whose items are the swing with hold_sessions 3 (a swing needs 5-20) and the string 'not a thesis'",
     (swing(hold_sessions=3), "not a thesis"), "ok", "no item builds"),
)


@pytest.mark.parametrize(("described", "items", "status", "why"), NOTHING_TO_GRADE, ids=("no-parse", "none-builds"))
def test_a_run_with_nothing_to_grade_cannot_be_graded(described, items, status, why):
    try:
        got = grade(*items, parse_status=status)
    except CannotGrade as exc:
        assert why in str(exc), f"{described}: CannotGrade says {exc!s}; expected the reason {why!r}"
        return
    pytest.fail(
        f"{described}: there is no thesis to check ({why}), so the grader raises CannotGrade and the run is left out "
        f"of the rate. A 0 would count it as a run whose theses failed P2; got {shown(got)}"
    )
