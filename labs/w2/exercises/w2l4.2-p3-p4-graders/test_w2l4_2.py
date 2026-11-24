"""w2l4.2 P3 and P4 as graders: the same whole-run score as P2, each fed what its check reads from the snapshot.

The sample is the author's recorded reply (tests/fixtures/thesis/AAPL_2026-11-16.*): one swing thesis, limit 343.41,
stop 338.7, target 360.83, invalidation 338.7. Its snapshot: close 352.78, atr_14 8.0457, levels low_20 325.33,
pivot_low 325.81, hvn 333.35, pivot_low 338.7, hvn 343.40978, high_20 360.83. Each case says what it changed.
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
P3, P4 = "p3_invalidation_testable", "p4_levels_coherent"


def swing(**changes) -> dict:
    return {**REPLY["theses"][0], **changes}


def short(**changes) -> dict:
    """The thesis as a short-horizon one (3 sessions), so a sample can hold two theses."""
    return swing(horizon="short", hold_sessions=3, **changes)


def market_open(**changes) -> dict:
    """The swing entered at the next open, so its entry for P3 and P4 is the snapshot's close, 352.78."""
    return swing(entry_kind="market_open", entry_price=None, **changes)


def grade(grader_id: str, *items, parse_status: str = "ok") -> object:
    sample = SimpleNamespace(parse_status=parse_status, output_parsed={"theses": list(items), "no_trade": []},
                             recorded_at=datetime(2026, 11, 17, 3, 46, tzinfo=UTC), trace_id="t")
    try:
        return evals.GRADERS[grader_id]().grade(sample, EXPECTED)
    except CannotGrade:
        raise
    except Exception as exc:  # show a crash as a result, so the message can say which sample caused it
        return f"{type(exc).__name__}: {exc}"


def shown(got: object) -> str:
    if isinstance(got, Score):
        return f"Score(value={got.value!r}, explanation={got.explanation!r})"
    return repr(got)


def scores(got: object, value: float, explanation: str | None) -> bool:
    return isinstance(got, Score) and got.value == value and got.explanation == explanation


@pytest.mark.parametrize("grader_id", (P3, P4))
def test_p3_and_p4_are_registered_code_graders(grader_id):
    assert grader_id in evals.GRADERS, (
        f"No grader is registered under {grader_id!r}. An experiment config names its graders by id and "
        f"evals.graders() finds them in evals.GRADERS, which holds {', '.join(evals.GRADERS)}"
    )
    cls = evals.GRADERS[grader_id]
    assert cls.id == grader_id, f"evals.GRADERS[{grader_id!r}] is {cls.__name__}, whose id is {cls.id!r}"
    assert cls.kind == "code", (
        f"{cls.__name__}.kind is {cls.kind!r}. kind says what decides the score: {grader_id} is a rule in code, like "
        f"p2_evidence_valid, not a model's judgement"
    )
    version = getattr(cls, "version", None)
    assert isinstance(version, str) and version, (
        f"{cls.__name__}.version is {version!r} ({type(version).__name__}). Every grader in the registry carries "
        f"its version as a non-empty string (EvidenceValid has {evals.GRADERS['p2_evidence_valid'].version!r}): the "
        f"eval records store it beside each score"
    )


@pytest.mark.parametrize("grader_id", (P3, P4))
def test_a_second_class_with_the_same_id_is_refused(grader_id, monkeypatch):
    monkeypatch.setattr(evals, "GRADERS", dict(evals.GRADERS))  # a failed refusal must not leave a stand-in behind
    first = evals.GRADERS[grader_id]
    try:
        evals.grader(type("StandIn", (), {"id": grader_id}))
    except ValueError as exc:
        assert "already registered" in str(exc), f"grader() raised ValueError({exc!s}); expected 'already registered'"
        return
    pytest.fail(
        f"evals.grader() accepted a second class with the id {grader_id!r}, already held by {first.__name__}; the "
        f"registry now maps it to {evals.GRADERS[grader_id].__name__}. A duplicate id must raise ValueError "
        f"('already registered'), or one module's grader silently replaces another's, or is silently dropped"
    )


def test_p3_passes_the_real_reply_and_names_a_broken_short():
    got = grade(P3, swing())
    assert scores(got, 1.0, None), (
        f"The recorded AAPL reply: limit 343.41, stop 338.7, invalidation 338.7, on the stop, which P3 allows. The "
        f"run scores Score(value=1.0, explanation=None); got {shown(got)}"
    )
    got = grade(P3, swing(), short(invalidation_price=344.0))
    assert scores(got, 0.0, "fails: short"), (
        f"The real swing, then a short-horizon copy with invalidation 344.0, above its entry 343.41: a long is wrong "
        f"when price falls, so a level above the entry cannot say so. That short fails P3, the run scores 0.0 with "
        f"'fails: short'; got {shown(got)}"
    )


def test_p3_measures_a_market_open_entry_from_the_snapshot_close():
    got = grade(P3, market_open(stop=338.69, invalidation_price=350.0))
    assert scores(got, 1.0, None), (
        f"The swing made market_open (entry = the snapshot's close, 352.78), stop 338.69, invalidation 350.0: 350.0 "
        f"lies between 352.78 and the stop, so P3 passes. P3 gets the close from analysis.snapshot.values; got "
        f"{shown(got)}"
    )
    got = grade(P3, market_open(stop=338.69, invalidation_price=353.0))
    assert scores(got, 0.0, "fails: swing"), (
        f"The swing made market_open (entry = the close, 352.78), stop 338.69, invalidation 353.0, above the entry: "
        f"P3 fails it, 'fails: swing'; got {shown(got)}"
    )


def test_p4_fails_the_real_reply_at_cents():
    got = grade(P4, swing())
    assert scores(got, 0.0, "fails: swing"), (
        f"The recorded AAPL reply: limit 343.41, stop 338.7. At cents hvn 343.40978 is the entry, so the nearest "
        f"level under it is pivot_low 338.7 and the stop sits on it: P4 fails, 'fails: swing'. P4 gets the "
        f"snapshot's levels, its atr_14 and its close, in that order; got {shown(got)}"
    )
    got = grade(P4, swing(stop=338.69))
    assert scores(got, 1.0, None), (
        f"The reply with its stop a cent below pivot_low 338.7 (338.69) and target 360.83 on high_20: P4 passes, "
        f"Score(value=1.0, explanation=None); got {shown(got)}"
    )


def test_p4_allows_half_the_atr_14_past_the_next_level():
    got = grade(P4, swing(stop=338.69, target=364.0))
    assert scores(got, 1.0, None), (
        f"The reply with stop 338.69 and target 364.0: 3.17 past high_20 360.83, inside half of the snapshot's "
        f"atr_14 (8.0457 / 2 = 4.02), so P4 passes; got {shown(got)}"
    )
    got = grade(P4, swing(stop=338.69), short(stop=338.69, target=366.0))
    assert scores(got, 0.0, "fails: short"), (
        f"The reply with stop 338.69, then a short-horizon copy with target 366.0, 5.17 past high_20 360.83, more "
        f"than half an ATR (4.02): the run scores 0.0, 'fails: short'; got {shown(got)}"
    )


def test_p4_measures_a_market_open_entry_from_the_snapshot_close():
    got = grade(P4, market_open(stop=338.69))
    assert scores(got, 1.0, None), (
        f"The swing made market_open (entry = the snapshot's close, 352.78) with stop 338.69, target 360.83: the "
        f"stop is under hvn 343.41, the nearest level below 352.78, and the target is on high_20 360.83, the nearest "
        f"above, so P4 passes. P4 gets the close from analysis.snapshot.values; got {shown(got)}"
    )
    got = grade(P4, market_open(stop=345.0, invalidation_price=346.0))
    assert scores(got, 0.0, "fails: swing"), (
        f"The swing made market_open (entry = the close, 352.78) with stop 345.0: the nearest level under 352.78 is "
        f"hvn 343.41, and the stop sits between it and the entry, so P4 fails, 'fails: swing'; got {shown(got)}"
    )


@pytest.mark.parametrize("grader_id", (P3, P4))
def test_a_run_with_nothing_to_grade_cannot_be_graded(grader_id):
    for described, items, status, why in (
            ("the real reply with parse_status 'invalid_json'", (swing(),), "invalid_json", "did not parse"),
            ("a run whose items are the swing with hold_sessions 3 (a swing needs 5-20) and 'not a thesis'",
             (swing(hold_sessions=3), "not a thesis"), "ok", "no item builds")):
        try:
            got = grade(grader_id, *items, parse_status=status)
        except CannotGrade as exc:
            assert why in str(exc), f"{grader_id}, {described}: CannotGrade says {exc!s}; expected {why!r}"
            continue
        pytest.fail(
            f"{grader_id}, {described}: there is no thesis to check ({why}), so the grader raises CannotGrade and "
            f"the run is left out of the rate; got {shown(got)}"
        )
