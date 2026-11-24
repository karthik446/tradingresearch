"""w1l1.3 placeholders: {value} is the only placeholder, and only when value is set.

Claims are the author's, from the recorded observe run (run_c40caab0968e44a3); the bad_placeholder case edits the
text of one of them, because the run has none.
"""

import json
import os
from pathlib import Path

from tradingresearch.analyze import validate_claims

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")


def rows() -> list[dict]:
    return [json.loads(line) for line in (DATA / "observe.jsonl").open()]


def reasons(raw: dict, values: dict) -> dict[str, tuple[str, str]]:
    _, rejected = validate_claims(raw, values, "an_lab")
    return {r.claim: (r.reason, r.detail) for r in rejected}


def ko() -> dict:
    return next(row for row in rows() if row["item"] == "KO:2026-11-12")


def test_ko_2026_11_12_c9_puts_a_label_in_value():
    got = reasons(ko()["output_parsed"], ko()["values"])
    assert "c9" in got, (
        "KO 2026-11-12 c9 'The SPY market regime is labeled {value} on this date, which is bull-high.' has {value} "
        "but value is null (the regime is a label, not a number), yet it was kept."
    )
    assert got["c9"] == ("empty_placeholder", "text has {value} but value is null"), (
        f"c9 should be ('empty_placeholder', 'text has {{value}} but value is null'); got {got['c9']}"
    )


def test_value_is_the_only_placeholder():
    c9 = next(c for c in ko()["output_parsed"]["claims"] if c["id"] == "c9")
    edited = {**c9, "text": "The SPY market regime is labeled {label} on this date."}
    got = reasons({"claims": [edited]}, ko()["values"])
    assert got.get("c9") == ("bad_placeholder", "{label}"), (
        f"'labeled {{label}}' uses a placeholder the renderer never fills: expected ('bad_placeholder', '{{label}}') "
        f"(the other placeholders, sorted, joined by ', '); got {got.get('c9')}"
    )


def test_any_braces_other_than_value_are_a_placeholder():
    for text, bad in (("The close is {value} {the unit}.", "{the unit}"), ("The close is {value} {}.", "{}")):
        claim = {"id": "c1", "tag": "fact", "text": text, "value": 1.0, "unit": "usd",
                 "source_ids": ["src_close"], "derived_from": [], "steps": None}
        got = reasons({"claims": [claim]}, {"src_close": 1.0})
        assert got.get("c1") == ("bad_placeholder", bad), (
            f"a fact {text!r} gave {got.get('c1')} (None: kept); expected "
            f"('bad_placeholder', {bad!r}). The renderer fills only {{value}}: braces holding anything else (spaces, "
            "or nothing at all) reach the reader as they are, so they count as a placeholder too."
        )


def test_the_recorded_run_has_4_empty_placeholders():
    found = sum(reason == "empty_placeholder" for row in rows()
                for reason, _ in reasons(row["output_parsed"], row["values"]).values())
    assert found == 4, f"the recorded observe run has 4 labels put in {{value}} (class label_in_value); you reject {found}"


def test_zero_is_a_value():
    for zero in (0, 0.0):
        claim = {"id": "c1", "tag": "fact", "text": "The change today is {value} percent.", "value": zero,
                 "unit": "pct", "source_ids": ["src_flat"], "derived_from": [], "steps": None}
        got = reasons({"claims": [claim]}, {"src_flat": 0.0})
        assert "c1" not in got, (
            f"a fact 'The change today is {{value}} percent.' with value {zero!r}, citing a source that holds 0.0, was "
            f"rejected as {got['c1']}. 0 is a number the table holds; only a missing value (null) leaves {{value}} empty."
        )


def test_several_bad_placeholders_are_sorted():
    text = "The {zeta} close is {value} above the {alpha} line."
    claim = {"id": "c1", "tag": "fact", "text": text, "value": 1.0, "unit": "usd", "source_ids": ["src_close"],
             "derived_from": [], "steps": None}
    got = reasons({"claims": [claim]}, {"src_close": 1.0}).get("c1")
    assert got == ("bad_placeholder", "{alpha}, {zeta}"), (
        f"a fact {text!r} gave {got}; expected ('bad_placeholder', '{{alpha}}, {{zeta}}'). With more than one bad "
        "placeholder the detail lists them sorted, whatever order the text has them in."
    )


def test_a_bad_placeholder_is_reported_before_an_empty_value():
    text = "The close is {value} and {foo}."
    claim = {"id": "c1", "tag": "fact", "text": text, "value": None, "unit": None, "source_ids": ["src_close"],
             "derived_from": [], "steps": None}
    got = reasons({"claims": [claim]}, {"src_close": 1.0}).get("c1")
    assert got == ("bad_placeholder", "{foo}"), (
        f"a fact {text!r} with value null gave {got}; expected ('bad_placeholder', '{{foo}}'). Both rules are broken; "
        "check_one reports the first one in the order the TODO lists them: a placeholder other than {value} first, "
        "then {value} with no value."
    )
