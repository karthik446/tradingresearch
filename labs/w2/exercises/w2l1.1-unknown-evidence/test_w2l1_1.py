"""w2l1.1 P2 rule 1: every evidence id names a claim of the thesis's own analysis.

Theses, claims and source tables are the author's, from the journal (labs/w2/data/theses.json). The synthetic row
is a copy of a real thesis with one evidence id added; it says so in its label.
"""

import json
import os
from pathlib import Path

from tradingresearch.checks import p2_evidence_valid
from tradingresearch.records import Claim, Thesis

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
CHAPTER = ("AAPL swing", "HD swing", "JPM short", "JPM swing", "XOM short", "XOM swing")


def case(label: str) -> tuple[Thesis, tuple[Claim, ...], dict[str, float | None]]:
    data = json.loads((DATA / "theses.json").read_text())
    row = next(row for row in data["theses"] if row["label"] == label)
    analysis = data["analyses"][row["analysis"]]
    claims = tuple(Claim.model_validate_json(json.dumps(claim)) for claim in analysis["claims"])
    return Thesis.model_validate_json(json.dumps(row["thesis"])), claims, analysis["values"]


def p2(thesis: Thesis, claims: tuple[Claim, ...], values: dict[str, float | None]) -> object:
    try:
        return p2_evidence_valid(thesis, claims, values)
    except Exception as exc:  # show a crash as a result, so the message can say which thesis caused it
        return f"{type(exc).__name__}: {exc}"


def test_jpm_swing_citing_a_claim_of_the_xom_analysis_fails():
    thesis, claims, values = case("w2l1.1: JPM swing cites an XOM claim")
    got = p2(thesis, claims, values)
    assert got is False, (
        f"JPM swing lists evidence cl_6318fbb2dd184267, an id from the XOM analysis: none of the {len(claims)} claims "
        f"of JPM's analysis has it, so the thesis cites evidence that does not exist; p2_evidence_valid returned "
        f"{got!r}. Its other three ids are real JPM claims: one id that names no claim is enough to fail."
    )


def test_the_six_chapter_theses_pass():
    for label in CHAPTER:
        thesis, claims, values = case(label)
        got = p2(thesis, claims, values)
        assert got is True, (
            f"{label} cites {len(thesis.evidence)} ids, all claims of its own analysis ({len(claims)} claims); "
            f"p2_evidence_valid returned {got!r}. The thesis need not cite every claim, only cite real ones."
        )


def test_an_unknown_id_fails_wherever_it_sits():
    thesis, claims, values = case("AAPL swing")
    real = thesis.evidence
    for evidence in (("cl_0000000000000000", *real), (real[0], "cl_0000000000000000", *real[1:]),
                     (*real, "cl_0000000000000000")):
        got = p2(thesis.model_copy(update={"evidence": evidence}), claims, values)
        assert got is False, (
            f"AAPL swing with evidence {evidence}: cl_0000000000000000 names no claim of the analysis, wherever it "
            f"sits in the list; p2_evidence_valid returned {got!r}"
        )


def test_an_analysis_with_no_claims_supports_nothing():
    thesis, _, values = case("HD swing")
    got = p2(thesis, (), values)
    assert got is False, f"HD swing checked against an analysis with no claims: none of its ids exist; got {got!r}"


def test_where_a_claim_sits_in_the_analysis_does_not_matter():
    for label in CHAPTER:
        thesis, claims, values = case(label)
        for how, order in (("in reverse order", claims[::-1]), ("rotated by one", claims[1:] + claims[:1])):
            got = p2(thesis, order, values)
            assert got is True, (
                f"{label} with the {len(claims)} claims of its analysis {how}, so {order[0].claim_id} comes first "
                f"and {order[-1].claim_id} last: the same claims, and the thesis still cites "
                f"{', '.join(thesis.evidence)}, all of them real; p2_evidence_valid returned {got!r}. A claim exists "
                f"wherever it sits in the analysis, first, middle or last."
            )


def test_a_fact_of_another_analysis_fails_on_every_chapter_thesis():
    cases = [(label, *case(label)) for label in CHAPTER]
    for i, (label, thesis, claims, values) in enumerate(cases):
        own = {claim.claim_id for claim in claims}
        other_label, other = next((other_label, claim) for other_label, _, other_claims, _ in cases[i + 1:] + cases[:i]
                                  for claim in other_claims if claim.claim_id not in own and claim.tag == "fact")
        got = p2(thesis.model_copy(update={"evidence": (*thesis.evidence, other.claim_id)}), claims, values)
        assert got is False, (
            f"{label} with {other.claim_id} added to its evidence: that id is a fact of {other_label}'s analysis "
            f"({other.text[:40]!r}...), and none of the {len(claims)} claims of {label}'s analysis has it, so the "
            f"thesis cites evidence that does not exist; p2_evidence_valid returned {got!r}. Any id from outside the "
            f"thesis's own analysis is unknown, not only the ones the tests above show."
        )


def test_a_source_id_is_not_a_claim_id():
    thesis, claims, values = case("AAPL swing")
    source = next(iter(values))
    citing = next(claim for claim in claims if source in claim.source_ids)
    got = p2(thesis.model_copy(update={"evidence": (*thesis.evidence, source)}), claims, values)
    assert got is False, (
        f"AAPL swing with {source} added to its evidence: that is a row of the analysis's source table (it holds "
        f"{values[source]}; the claim {citing.claim_id}, {citing.text!r}, cites it), not a claim. None of the "
        f"{len(claims)} claims has the id {source}, so as evidence it names nothing; p2_evidence_valid returned {got!r}"
    )


def test_a_repeated_id_is_still_a_real_claim():
    thesis, claims, values = case("AAPL swing")
    evidence = (*thesis.evidence, thesis.evidence[0])
    got = p2(thesis.model_copy(update={"evidence": evidence}), claims, values)
    assert got is True, (
        f"AAPL swing lists {evidence[0]} twice (evidence {evidence}): {len(evidence)} ids, every one of them a claim "
        f"of its {len(claims)}-claim analysis, so it cites nothing that does not exist; p2_evidence_valid returned "
        f"{got!r}. Listing a real claim twice is untidy, not unknown evidence."
    )
