"""w1l2.1 open coding: one note per analysis of the observe run, naming the first failure.

Checks `evals/labels.csv` in your repo against the recorded observe run (run_c40caab0968e44a3).
"""

import csv
import json
import os
import re
from pathlib import Path

import tradingresearch
from tradingresearch.analyze import validate_claims

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
REPO = Path(tradingresearch.__file__).resolve().parents[2]
HEADER = ["analysis_id", "item", "first_failure", "note", "classes"]


def pack() -> dict[str, dict]:
    return {row["item"]: row for row in map(json.loads, (DATA / "observe.jsonl").open())}


def labels() -> list[dict]:
    path = REPO / "evals" / "labels.csv"
    assert path.exists(), f"{path} does not exist; start it with the header {','.join(HEADER)}"
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == HEADER, f"labels.csv header is {reader.fieldnames}; expected {HEADER}"
        return list(reader)


def test_one_row_per_analysis():
    rows, items = labels(), pack()
    missing = sorted(set(items) - {r["item"] for r in rows})
    assert not missing, (
        f"labels.csv has {len(rows)} rows; the observe run has {len(items)} analyses. Missing: {', '.join(missing)}. "
        "Read each trace (`jq -r .item labs/w1/data/observe.jsonl` lists them) and write one note per analysis."
    )
    extra = [r["item"] for r in rows if r["item"] not in items]
    assert not extra, f"rows for items that are not in the observe run: {extra}"
    assert len(rows) == len(items), f"{len(rows)} rows for {len(items)} analyses: one row each, no duplicates"
    bad_ids = [r["analysis_id"] for r in rows if not re.fullmatch(r"an_[0-9a-f]{16}", r["analysis_id"])]
    assert not bad_ids, f"analysis_id must be the trace's id, an_ and 16 hex digits; got {bad_ids}"


def test_analysis_id_is_that_items_trace():
    items = pack()
    wrong = [f"{r['item']} has {r['analysis_id']}" for r in labels()
             if r["item"] in items and r["analysis_id"] != items[r["item"]]["analysis_id"]]
    assert not wrong, (
        f"analysis_id is not the id of that item's trace: {'; '.join(wrong[:3])}{' ...' if len(wrong) > 3 else ''}. "
        "Each trace in the data pack carries its own analysis_id; a made-up id joins nothing later. List them with "
        "`jq -r '[.item, .analysis_id] | @tsv' labs/w1/data/observe.jsonl`."
    )


def test_first_failure_is_a_real_claim_and_not_a_cascade():
    items = pack()
    for r in labels():
        row = items[r["item"]]
        ids = {c["id"] for c in row["output_parsed"]["claims"]}
        first = r["first_failure"]
        assert first == "-" or first in ids, (
            f"{r['item']}: first_failure {first!r} is not a claim of that analysis (claims: {', '.join(sorted(ids))}); "
            "use a claim id, or - for a clean analysis"
        )
        _, rejected = validate_claims(row["output_parsed"], row["values"], "an_lab")
        reason = {x.claim: x.reason for x in rejected}.get(first)
        assert reason != "bad_derivation", (
            f"{r['item']}: first_failure {first} was rejected only as bad_derivation, which means a parent failed. "
            "Note the parent's failure instead (week-1.md §3, traps)."
        )


def test_notes_quote_claim_ids():
    items = pack()
    for r in labels():
        ids = {c["id"] for c in items[r["item"]]["output_parsed"]["claims"]}
        quoted = set(re.findall(r"\bc\d+\b", r["note"]))
        if r["first_failure"] != "-":
            assert quoted & ids, (
                f"{r['item']}: the note {r['note']!r} names no claim id of that analysis. Say which claim and what "
                "is wrong with it, in your own words."
            )
        assert len(r["note"]) >= 40, f"{r['item']}: note {r['note']!r} is too short to say what is wrong"


def test_some_note_finds_what_the_checks_missed():
    items = pack()
    missed = []
    for r in labels():
        row = items[r["item"]]
        _, rejected = validate_claims(row["output_parsed"], row["values"], "an_lab")
        if r["first_failure"] != "-" and r["first_failure"] not in {x.claim for x in rejected}:
            missed.append(r["item"])
    assert missed, (
        "every first_failure is a claim the code checks already reject. Write what a reader would object to: the "
        "author found 6 analyses whose first failure no check catches (week-1.md §3, done when)."
    )
