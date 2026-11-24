"""w2l1.2 P2 rule 2: an opinion is not evidence, even beside facts.

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


def test_aapl_swing_leaning_on_its_opinion_fails():
    thesis, claims, values = case("w2l1.2: AAPL swing leans on an opinion")
    opinion = next(claim for claim in claims if claim.claim_id == "cl_ba1ecc8934034a7d")
    got = p2(thesis, claims, values)
    assert got is False, (
        f"AAPL swing lists cl_ba1ecc8934034a7d as evidence beside two facts and an inference. That claim is tagged "
        f"{opinion.tag} ({opinion.text[:60]!r}...) and derives from {len(opinion.derived_from)} claims: a view of "
        f"the setup, not evidence for it; p2_evidence_valid returned {got!r}. tr thesis only refuses evidence that "
        f"is all opinion; P2 is stricter."
    )


def test_inferences_are_still_evidence():
    for label in ("AAPL swing", "XOM swing"):
        thesis, claims, values = case(label)
        tags = {claim.claim_id: claim.tag for claim in claims}
        got = p2(thesis, claims, values)
        assert got is True, (
            f"{label} cites {', '.join(f'{cid} ({tags[cid]})' for cid in thesis.evidence)}; p2_evidence_valid "
            f"returned {got!r}. Rule 2 removes opinions only: an inference is evidence, its numbers were checked "
            f"against its parents at analyze time."
        )


def test_each_analysis_opinion_fails_its_thesis_in_any_position():
    for label in CHAPTER:
        thesis, claims, values = case(label)
        opinion = next(claim for claim in claims if claim.tag == "opinion")
        for evidence in ((opinion.claim_id,), (opinion.claim_id, *thesis.evidence), (*thesis.evidence, opinion.claim_id)):
            got = p2(thesis.model_copy(update={"evidence": evidence}), claims, values)
            assert got is False, (
                f"{label} with evidence {evidence}: {opinion.claim_id} is the analysis's opinion "
                f"({opinion.text[:50]!r}...); p2_evidence_valid returned {got!r}"
            )


def test_the_six_chapter_theses_still_pass():
    for label in CHAPTER:
        got = p2(*case(label))
        assert got is True, f"{label} cites only facts and inferences of its analysis; p2_evidence_valid returned {got!r}"
