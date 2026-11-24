"""w2l1.3 P2 rule 3: a fact's sources are in the thesis-stage table; inferences skip rules 3 and 4.

Theses, claims and source tables are the author's, from the journal (labs/w2/data/theses.json). `values` is the
table the thesis prompt showed (the snapshot rows), so EDGAR rows are not in it. Synthetic rows say so in their label.
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


def names(label: str) -> dict[str, str]:
    data = json.loads((DATA / "theses.json").read_text())
    row = next(row for row in data["theses"] if row["label"] == label)
    return data["analyses"][row["analysis"]]["names"]


def p2(thesis: Thesis, claims: tuple[Claim, ...], values: dict[str, float | None]) -> object:
    try:
        return p2_evidence_valid(thesis, claims, values)
    except Exception as exc:  # show a crash as a result, so the message can say which thesis caused it
        return f"{type(exc).__name__}: {exc}"


def test_xom_swing_citing_an_edgar_fact_fails():
    thesis, claims, values = case("w2l1.3: XOM swing cites an EDGAR fact")
    eps = next(claim for claim in claims if claim.claim_id == "cl_6d08913f181543f2")
    got = p2(thesis, claims, values)
    assert got is False, (
        f"XOM swing lists cl_6d08913f181543f2 ({eps.text!r}, value {eps.value}) as evidence. It cites "
        f"{eps.source_ids[0]}, an EDGAR row: the thesis-stage table ({len(values)} sources, the ones the thesis "
        f"prompt showed) has no such id, so no reader of the thesis can trace that number; p2_evidence_valid "
        f"returned {got!r}"
    )


def test_a_fact_with_no_number_is_in_the_table_too():
    thesis, claims, values = case("AAPL swing")
    label = next(claim for claim in claims if claim.claim_id == "cl_dfd3b95f6afc4f93")
    got = p2(thesis, claims, values)
    assert got is True, (
        f"AAPL swing cites cl_dfd3b95f6afc4f93 ({label.text[:50]!r}...), whose source {label.source_ids[0]} is "
        f"regime_spy: a row of the table that holds a label, not a number ({values[label.source_ids[0]]!r}). The id "
        f"is in the table, so rule 3 holds; p2_evidence_valid returned {got!r}"
    )


def test_a_fact_with_no_number_still_needs_its_source_in_the_table():
    thesis, claims, values = case("AAPL swing")
    label = next(claim for claim in claims if claim.claim_id == "cl_dfd3b95f6afc4f93")
    trimmed = {source: value for source, value in values.items() if source not in label.source_ids}
    got = p2(thesis, claims, trimmed)
    assert got is False, (
        f"AAPL swing cites cl_dfd3b95f6afc4f93 ({label.text[:50]!r}...), a fact with no value. With its source "
        f"regime_spy taken out of the table, the fact cites an id the table does not have: rule 3 applies to every "
        f"fact, with or without a number; p2_evidence_valid returned {got!r}"
    )


def test_every_real_thesis_passes():
    for label in REAL:
        got = p2(*case(label))
        assert got is True, f"{label}: every evidence fact cites sources of the thesis-stage table; got {got!r}"


def test_one_missing_source_of_two_fails():
    thesis, claims, values = case("MSFT day, direction short")
    low = next(claim for claim in claims if claim.claim_id == "cl_d84905e6fe69421b")
    table = names("MSFT day, direction short")
    for gone in reversed(low.source_ids):
        trimmed = {source: value for source, value in values.items() if source != gone}
        got = p2(thesis, claims, trimmed)
        assert got is False, (
            f"MSFT day cites cl_d84905e6fe69421b ({low.text!r}), which cites {table[low.source_ids[0]]} and "
            f"{table[low.source_ids[1]]}. With {table[gone]} taken out of the table, one cited id is missing and the "
            f"fact fails rule 3, even though the other source is there; p2_evidence_valid returned {got!r}"
        )


def test_an_inference_is_not_held_to_rules_3_and_4():
    thesis, claims, values = case("JPM swing")
    inference = next(claim for claim in claims if claim.claim_id == "cl_fa73b53dc54f49e5")
    odd = inference.model_copy(update={"source_ids": ("src_not_in_the_table",), "value": 1.0})
    claims = tuple(odd if claim.claim_id == odd.claim_id else claim for claim in claims)
    got = p2(thesis, claims, values)
    assert got is True, (
        "JPM swing cites the inference cl_fa73b53dc54f49e5. Given here a source id that is not in the table and a "
        f"value 1.0, it must still pass: rules 3 and 4 judge facts; an inference's numbers were checked against its "
        f"parents at analyze time. p2_evidence_valid returned {got!r}"
    )
