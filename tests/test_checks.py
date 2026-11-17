"""The P2-P4 graders on a thesis-run sample (the recorded real AAPL reply, plus hand-mutated copies) and P4 at cents
on levels copied from stored theses. No model call."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from gigai_core.graders.protocol import CannotGrade

from tradingresearch import checks, evals, thesis as th
from tradingresearch.records import Analysis, Level

FIXTURES = Path(__file__).parent / "fixtures" / "thesis"
ANALYSIS = Analysis.model_validate_json((FIXTURES / "AAPL_2026-11-16.analysis.json").read_text())
REPLY = json.loads((FIXTURES / "AAPL_2026-11-16.reply.json").read_text())
WRITTEN_AT = datetime(2026, 11, 17, 3, 46, tzinfo=UTC)  # when the real reply was written
EXPECTED = th.item_for(ANALYSIS, ("day", "short", "swing"), "champion").expected
OPINION = "cl_ba1ecc8934034a7d"
CODE_GRADERS = ("p2_evidence_valid", "p3_invalidation_testable", "p4_levels_coherent")


def grade(grader_id: str, *theses: dict, parse_status: str = "ok"):
    output = {"theses": list(theses), "no_trade": []}
    sample = SimpleNamespace(parse_status=parse_status, output_parsed=output, recorded_at=WRITTEN_AT, trace_id="t")
    return evals.GRADERS[grader_id]().grade(sample, EXPECTED)


def swing(**changes) -> dict:
    """The real reply's swing thesis (limit 343.41, stop 338.7, target 360.83) with some fields changed."""
    return {**REPLY["theses"][0], **changes}


def built(**changes):
    return th.build(swing(**changes), ANALYSIS, th.Written("champion", WRITTEN_AT, "t", "grade", "unknown", "grade"))


@pytest.mark.parametrize("grader_id", ("p2_evidence_valid", "p3_invalidation_testable"))
def test_the_real_reply_passes_p2_and_p3(grader_id):
    score = grade(grader_id, swing())
    assert score.value == 1.0 and score.explanation is None


def test_p4_reads_the_real_reply_at_cents():
    # hvn 343.40978 rounds to the entry 343.41 and is ignored; the nearest support is pivot_low 338.70, the stop's price
    assert grade("p4_levels_coherent", swing()).explanation == "fails: swing"
    assert grade("p4_levels_coherent", swing(stop=338.69)).value == 1.0


@pytest.mark.parametrize(("grader_id", "changes"), [
    ("p2_evidence_valid", {"evidence": [*REPLY["theses"][0]["evidence"], OPINION]}),  # an opinion is not evidence
    ("p3_invalidation_testable", {"invalidation_price": 344.0}),  # above the entry
    ("p4_levels_coherent", {"target": 366.0}),  # high_20 360.83 + 0.5 x atr_14 4.02 = 364.85
])
def test_one_broken_thesis_scores_zero_and_names_its_horizon(grader_id, changes):
    ok = swing(stop=338.69)  # a cent beyond pivot_low 338.70, so the swing passes P4 too
    score = grade(grader_id, ok, {**ok, "horizon": "short", "hold_sessions": 3, **changes})
    assert score.value == 0.0 and score.explanation == "fails: short"


def levels(*priced: tuple[str, float]) -> tuple[Level, ...]:
    return tuple(Level(price=price, kind=kind, strength=1.0, distance_atr=0.0) for kind, price in priced)


def test_p4_a_level_that_rounds_to_the_entry_is_ignored():
    # JPM swing th_813ac52eb68c4df3: raw, hvn 335.11379 is the "next level above" the entry 335.11 and the target fails
    jpm = levels(("pivot_low", 333.0), ("hvn", 335.1137897535185), ("pivot_high", 344.4))
    thesis = built(entry_price=335.11, stop=332.8, target=344.4, invalidation_price=333.0)
    assert checks.p4_levels_coherent(thesis, jpm, 7.3046, 336.0) is True


def test_p4_a_stop_that_rounds_onto_a_level_is_not_beyond_it():
    # XOM th_066251b3465b4405: raw, stop 160.11 sits 0.0001 below low_20 160.1101; at cents it is on the level
    xom = levels(("low_20", 160.1101), ("hvn", 163.37701705364728), ("hvn", 168.7483617560788))
    thesis = built(entry_price=163.38, stop=160.11, target=168.75, invalidation_price=160.11)
    assert checks.p4_levels_coherent(thesis, xom, 4.2971, 164.0) is False
    assert checks.p4_levels_coherent(built(entry_price=163.38, stop=160.1, target=168.75, invalidation_price=160.11),
                                     xom, 4.2971, 164.0) is True


@pytest.mark.parametrize("grader_id", CODE_GRADERS)
def test_no_parse_or_nothing_that_builds_cannot_be_graded(grader_id):
    with pytest.raises(CannotGrade, match="did not parse"):
        grade(grader_id, swing(), parse_status="invalid_json")
    with pytest.raises(CannotGrade, match="no item builds"):
        grade(grader_id, swing(hold_sessions=3), "not a thesis")


def test_the_draft_p1_judge_makes_no_call():
    with pytest.raises(CannotGrade, match="draft"):
        evals.GRADERS["p1_judge"]().grade(SimpleNamespace(parse_status="ok"), {})
