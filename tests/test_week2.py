"""Week 2 acceptance: the P2-P4 code checks on hand-built cases, their registry entries, and the draft P1 judge.

Specs: evals/specs/p2_evidence_valid.md, p3_invalidation_testable.md, p4_levels_coherent.md, p1_judge.md.
`checks` is imported inside each test, so before you write it every test here fails on its own and the rest of the
suite still runs. No model calls.
"""

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tradingresearch import evals
from tradingresearch.records import Claim, EntryRule, Level, Thesis

FIXTURES = Path(__file__).parent / "fixtures" / "week2"
RUBRIC = Path(__file__).resolve().parents[1] / "evals" / "rubrics" / "p1_thesis_quality.md"
RUBRIC_SECTIONS = ("Question", "Inputs", "Met", "Not met", "Unknown", "Hindsight", "Verdict format")
CODE_GRADERS = ("p2_evidence_valid", "p3_invalidation_testable", "p4_levels_coherent")
CREATED = datetime(2030, 1, 2, 22, 0, tzinfo=UTC)  # after a made-up session's close
WINDOW = (datetime(2030, 1, 3, 14, 30, tzinfo=UTC), datetime(2030, 1, 3, 21, 0, tzinfo=UTC))


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def cases(name: str) -> list:
    return [pytest.param(case, id=case["name"]) for case in load(name)["cases"]]


def checks():
    return importlib.import_module("tradingresearch.checks")


def thesis(fields: dict) -> Thesis:
    """A valid Thesis on made-up ticker FAKEA; the case sets direction, entry, stop, target and what it tests."""
    f = dict(fields)
    entry = EntryRule(kind=f.pop("entry_kind"), price=f.pop("entry_price"), window_start=WINDOW[0],
                      window_end=WINDOW[1])
    f.setdefault("invalidation_price", f["stop"])
    f["evidence"] = tuple(f.get("evidence", ("cl_f1",)))
    base = dict(
        thesis_id="th_week2", analysis_id="an_week2", ticker="FAKEA", horizon="short", setup_type="breakout_20d",
        prediction="Moves to the target within 3 sessions.", reason="Hand-built case.", hold_sessions=3,
        invalidation_text="Hand-built case.", regime="bull-normal", arm="champion", sample_trace_id="tr_week2",
        provider_route="none", terms_class="unknown", rules_version="rules-1", created_at=CREATED,
        input_hash="sha256:" + "0" * 64,
    )
    return Thesis(entry=entry, **(base | f))


def claim(fields: dict) -> Claim:
    base = dict(analysis_id="an_week2", source_ids=(), derived_from=(), steps=None)
    f = base | fields
    return Claim(**(f | {"source_ids": tuple(f["source_ids"]), "derived_from": tuple(f["derived_from"])}))


@pytest.mark.parametrize("case", cases("p2_evidence_valid"))
def test_p2_evidence_valid(case):
    data = load("p2_evidence_valid")
    claims = tuple(claim(c) for c in data["claims"])
    tolerance = {"tolerance": case["tolerance"]} if "tolerance" in case else {}
    assert checks().p2_evidence_valid(thesis(case["thesis"]), claims, data["values"], **tolerance) is case["expect"]


@pytest.mark.parametrize("case", cases("p3_invalidation_testable"))
def test_p3_invalidation_testable(case):
    assert checks().p3_invalidation_testable(thesis(case["thesis"]), case["reference_close"]) is case["expect"]


@pytest.mark.parametrize("case", cases("p4_levels_coherent"))
def test_p4_levels_coherent(case):
    data = load("p4_levels_coherent")
    close, atr = case.get("reference_close", data["reference_close"]), case.get("atr14", data["atr14"])
    levels = tuple(Level(price=lv["price"], kind=lv["kind"], strength=1.0, distance_atr=(close - lv["price"]) / atr)
                   for lv in case.get("levels", data["levels"]))
    assert checks().p4_levels_coherent(thesis(case["thesis"]), levels, atr, close) is case["expect"]


def test_each_fixture_has_four_passes_and_six_fails():
    for name in CODE_GRADERS:
        expects = [case["expect"] for case in load(name)["cases"]]
        assert expects.count(True) >= 4 and expects.count(False) >= 6, name


@pytest.mark.parametrize("grader_id", CODE_GRADERS)
def test_the_code_check_is_a_registered_binary_code_grader(grader_id, monkeypatch):
    cls = evals.GRADERS[grader_id]
    assert cls.id == grader_id and cls.kind == "code"
    assert isinstance(cls.version, str) and cls.version
    monkeypatch.setattr(evals, "GRADERS", dict(evals.GRADERS))  # a failed refusal must not leave a stand-in behind
    with pytest.raises(ValueError, match="already registered"):
        evals.grader(type("StandIn", (), {"id": grader_id}))


def test_a_duplicate_registration_still_raises(monkeypatch):
    monkeypatch.setattr(evals, "GRADERS", dict(evals.GRADERS))
    with pytest.raises(ValueError, match="already registered"):
        evals.grader(type("StandIn", (), {"id": "parsed"}))


def test_the_p1_rubric_has_every_section():
    lines = {line.strip() for line in RUBRIC.read_text().splitlines()}
    missing = [name for name in RUBRIC_SECTIONS if f"## {name}" not in lines]
    assert not missing, f"missing sections: {missing}"


def test_p1_judge_is_registered_as_an_unvalidated_model_grader():
    cls = evals.GRADERS["p1_judge"]
    assert cls.id == "p1_judge" and cls.kind == "model"
    assert isinstance(cls.version, str) and cls.version
    assert cls.validated is False
