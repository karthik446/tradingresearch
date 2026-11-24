"""w1l3.6 register: experiment configs name graders by id, and the spec's acceptance check must hold on real data.

Spec acceptance (evals/specs/inferences_grounded.md): on the observe run, the analyses the grader flags are the ones
your evals/labels.csv labels inference_wider.
"""

import csv
import json
import os
from pathlib import Path
from types import SimpleNamespace

import tradingresearch
from tradingresearch.evals import graders

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
REPO = Path(tradingresearch.__file__).resolve().parents[2]


def grader():
    try:
        (found,) = graders(["inferences_grounded"])
    except SystemExit as exc:
        raise AssertionError(
            f"graders(['inferences_grounded']) exited: {exc}. A config's `graders = [...]` list goes through this "
            "registry, so a grader that is not in GRADERS cannot be used in any experiment."
        ) from None
    return found


def flagged() -> dict[str, str]:
    g, out = grader(), {}
    for row in map(json.loads, (DATA / "observe.jsonl").open()):
        sample = SimpleNamespace(parse_status=row["parse_status"], output_parsed=row["output_parsed"])
        score = g.grade(sample, {"values": row["values"], "names": row["names"]})
        if score.value == 0:
            out[row["item"]] = score.explanation
    return out


def test_registered():
    assert grader().id == "inferences_grounded"


def test_amzn_2026_11_13_explanation():
    got = flagged().get("AMZN:2026-11-13")
    assert got == "c4: sma_20, sma_50", f"AMZN:2026-11-13 on the recorded run: {got!r}, expected 'c4: sma_20, sma_50'"


def test_flags_match_your_inference_wider_labels():
    with (REPO / "evals" / "labels.csv").open(newline="") as fh:
        labelled = {r["item"] for r in csv.DictReader(fh) if "inference_wider" in (r["classes"] or "").split(";")}
    got = set(flagged())
    assert got == labelled, (
        f"grader flags {len(got)} analyses, labels.csv has {len(labelled)} inference_wider. Only flagged: "
        f"{sorted(got - labelled)}; only labelled: {sorted(labelled - got)}. Read each one: either the grader is wrong "
        "(fix it) or your label is (fix labels.csv). The spec is done when they agree."
    )


def test_every_grader_is_registered_in_the_order_asked():
    ids = ["parsed", "claims_valid", "all_claims_valid", "inferences_grounded"]
    for names in (ids, ids[::-1]):
        try:
            got = [g.id for g in graders(names)]
        except SystemExit as exc:
            raise AssertionError(
                f"graders({names}) exited: {exc}. The three graders registered before still have to be found: "
                "experiment configs name them."
            ) from None
        assert got == names, (
            f"graders({names}) returned graders {got}: one grader per name, in the order the config lists them"
        )


def test_a_name_listed_twice_gives_two_graders():
    got = [g.id for g in graders(["parsed", "parsed"])]
    assert got == ["parsed", "parsed"], (
        f"graders(['parsed', 'parsed']) returned graders {got}: one grader per name the config lists, a repeat "
        "included. graders() returns what the config asked for; whether a config should list a grader twice is the "
        "config's call, which a pre-flight can flag, not something to fix silently here."
    )


def test_the_grader_is_an_entry_of_GRADERS():
    from tradingresearch.evals import GRADERS, InferencesGrounded

    got = GRADERS.get("inferences_grounded")
    held = "has no entry for that id" if got is None else f"holds {got!r} under that id"
    assert got is InferencesGrounded, (
        f"graders() finds inferences_grounded, but the registry itself {held}. graders() is not the registry's only "
        "reader: labs/w1/tools/regrade.py reads it directly, so a grader that only graders() knows about is not in what "
        "regrade.py reads. Which object do all of them share?"
    )
