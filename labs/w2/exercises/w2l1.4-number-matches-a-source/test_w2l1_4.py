"""w2l1.4 P2 rule 4: a fact's value matches one of its cited sources within a relative tolerance.

Theses, claims and source tables are the author's, from the journal (labs/w2/data/theses.json); the synthetic row
says so in its label. The boundary cases change one fact's value on a real thesis (the spec's worked example uses
100.0 and 100.4; they are used here too).
"""

import json
import os
from pathlib import Path

from tradingresearch.checks import p2_evidence_valid
from tradingresearch.records import Claim, Thesis

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
REAL = ("AAPL swing", "HD swing", "JPM short", "JPM swing", "XOM short", "XOM swing", "JPM swing, direction short",
        "MSFT day, direction short", "UNH swing, direction short", "HD day, market_open entry")


def case(label: str) -> tuple[Thesis, tuple[Claim, ...], dict[str, float | None]]:
    data = json.loads((DATA / "theses.json").read_text())
    row = next(row for row in data["theses"] if row["label"] == label)
    analysis = data["analyses"][row["analysis"]]
    claims = tuple(Claim.model_validate_json(json.dumps(claim)) for claim in analysis["claims"])
    return Thesis.model_validate_json(json.dumps(row["thesis"])), claims, analysis["values"]


def p2(thesis: Thesis, claims: tuple[Claim, ...], values: dict[str, float | None], **kw: float) -> object:
    try:
        return p2_evidence_valid(thesis, claims, values, **kw)
    except Exception as exc:  # show a crash as a result, so the message can say which thesis caused it
        return f"{type(exc).__name__}: {exc}"


def hd_close(value: float, sources: dict[str, float | None], **kw: float) -> object:
    """HD swing with its close fact cl_16f17802b00c4312 saying `value` and its cited sources holding `sources`."""
    thesis, claims, values = case("HD swing")
    fact = next(claim for claim in claims if claim.claim_id == "cl_16f17802b00c4312")
    fact = fact.model_copy(update={"value": value, "source_ids": tuple(sources)})
    claims = tuple(fact if claim.claim_id == fact.claim_id else claim for claim in claims)
    return p2(thesis, claims, values | sources, **kw)


def test_hd_swing_close_fact_two_percent_off_fails():
    thesis, claims, values = case("w2l1.4: HD swing's close fact is 2% off")
    fact = next(claim for claim in claims if claim.claim_id == "cl_16f17802b00c4312")
    source = values[fact.source_ids[0]]
    got = p2(thesis, claims, values)
    assert got is False, (
        f"HD swing cites cl_16f17802b00c4312 ({fact.text!r}). In this copy of its analysis the fact says "
        f"{fact.value}; its one source, close, holds {source}: {abs(fact.value - source) / source:.1%} away, past "
        f"the 0.5% tolerance, so the number is not the one code computed; p2_evidence_valid returned {got!r}"
    )


def test_every_real_thesis_passes():
    for label in REAL:
        got = p2(*case(label))
        assert got is True, (
            f"{label}: every evidence fact matches a cited source within 0.5% (MSFT day's low_20 fact matches its "
            f"second source; UNH swing's and JPM swing's facts are negative numbers); p2_evidence_valid returned {got!r}"
        )


def test_the_tolerance_is_relative_and_inclusive():
    for value, source, want in ((100.4, 100.0, True), (100.6, 100.0, False), (99.5, 100.0, True), (100.0, 99.5, True),
                                (-100.4, -100.0, True), (-100.6, -100.0, False)):
        got = hd_close(value, {"src_close_lab": source})
        assert got is want, (
            f"HD swing's close fact says {value}, its source holds {source}: the gap {abs(value - source):.2f} "
            f"against 0.5% of the larger magnitude, {0.005 * max(abs(value), abs(source)):.4f}, so it should "
            f"{'pass (at or inside the tolerance)' if want else 'fail'}; p2_evidence_valid returned {got!r}"
        )


def test_the_tolerance_argument_is_used():
    got = hd_close(100.4, {"src_close_lab": 100.0}, tolerance=0.001)
    assert got is False, (
        "HD swing's close fact says 100.4, its source holds 100.0, and p2_evidence_valid is called with "
        f"tolerance=0.001: 0.4 > 0.1004, so it fails at this tolerance (it passes at the default 0.005); got {got!r}"
    )


def test_a_zero_is_a_number():
    for value, source, want in ((0.0, 1.0, False), (1.0, 0.0, False), (0.0, 0.0, True)):
        got = hd_close(value, {"src_zero_lab": source})
        assert got is want, (
            f"a fact saying {value} citing a source that holds {source} should {'pass' if want else 'fail'} "
            f"(0.0 is a value, not a missing one; AAPL's nr7 row holds 0.0); p2_evidence_valid returned {got!r}"
        )


def test_a_source_holding_none_matches_nothing():
    got = hd_close(1.0, {"src_label_lab": None})
    assert got is False, (
        "a fact saying 1.0 whose only cited source holds None (a label row, like regime_spy) has no number to match, "
        f"so it fails rule 4; p2_evidence_valid returned {got!r}"
    )
    got = hd_close(1.0, {"src_label_lab": None, "src_one_lab": 1.0})
    assert got is True, (
        "a fact saying 1.0 citing a label row (None) and a row holding 1.0 matches the second; p2_evidence_valid "
        f"returned {got!r}"
    )


def test_a_fact_with_no_number_still_needs_its_source_in_the_table():
    thesis, claims, values = case("AAPL swing")
    label = next(claim for claim in claims if claim.claim_id == "cl_dfd3b95f6afc4f93")
    trimmed = {source: value for source, value in values.items() if source not in label.source_ids}
    got = p2(thesis, claims, trimmed)
    assert got is False, (
        f"AAPL swing cites cl_dfd3b95f6afc4f93 ({label.text[:50]!r}...), a fact with no value, and its source "
        f"regime_spy is taken out of the table. Rule 4 has nothing to match, but rule 3 still fails the fact: a fact "
        f"without a value passes rule 4 only after rule 3; p2_evidence_valid returned {got!r}"
    )


def test_a_negative_edge_a_none_and_the_first_of_two_sources():
    cases = (
        (-99.5, {"src_close_lab": -100.0}, True, "the gap 0.50 is exactly 0.5% of the larger magnitude, 100.0 (a "
         "minus sign does not make the allowance smaller, and a gap at the edge counts)"),
        (-100.0, {"src_close_lab": -99.5}, True, "the gap 0.50 is exactly 0.5% of the larger magnitude, 100.0, "
         "whichever side holds it"),
        (0.0, {"src_label_lab": None}, False, "None is no number (not a zero), it matches nothing, not even 0.0"),
        (1.0, {"src_one_lab": 1.0, "src_five_lab": 5.0}, True, "the first source matches exactly, and one match "
         "among the cited sources is enough, whatever the others hold"),
    )
    for value, sources, want, why in cases:
        got = hd_close(value, sources)
        held = ", ".join(f"{source} holding {number}" for source, number in sources.items())
        assert got is want, (
            f"HD swing's close fact says {value} and cites {held}: {why}, so it should "
            f"{'pass' if want else 'fail'}; p2_evidence_valid returned {got!r}"
        )
