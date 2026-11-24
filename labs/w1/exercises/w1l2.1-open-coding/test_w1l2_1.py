"""w1l2.1 open coding: tally_notes in src/tradingresearch/taxonomy.py, then one note per analysis in evals/labels.csv.

The first tests call tally_notes on small CSVs written here; the rest check your evals/labels.csv against the
recorded observe run (run_c40caab0968e44a3).
"""

import csv
import json
import os
import re
from pathlib import Path

import tradingresearch
from tradingresearch.analyze import validate_claims
from tradingresearch.taxonomy import tally_notes

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
REPO = Path(tradingresearch.__file__).resolve().parents[2]
RUN = DATA / "observe.jsonl"
HEADER = ["analysis_id", "item", "first_failure", "note", "classes"]
KEYS = {"missed", "caught", "clean", "missing", "unknown"}


def pack() -> dict[str, dict]:
    return {row["item"]: row for row in map(json.loads, RUN.open())}


def rejected(item: str) -> list[str]:
    row = pack()[item]
    return [x.claim for x in validate_claims(row["output_parsed"], row["values"], "an_lab")[1]]


def notes(tmp_path: Path, *rows: tuple[str, str]) -> Path:
    """A labels.csv with one row per (item, first_failure), each with that item's real analysis_id."""
    path = tmp_path / "labels.csv"
    with path.open("w", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(HEADER)
        for item, first in rows:
            out.writerow([pack()[item]["analysis_id"], item, first, f"{first} is what a reader objects to here", ""])
    return path


def tally(tmp_path: Path, *rows: tuple[str, str]) -> dict[str, list[str]]:
    got = tally_notes(notes(tmp_path, *rows), RUN)
    assert got and KEYS <= set(got), (
        f"tally_notes returned {got!r} for a labels.csv with notes on {', '.join(i for i, _ in rows)}. It should "
        f"return the lists {', '.join(sorted(KEYS))}: e.g. a note 'AMZN:2026-11-13 c4' goes under missed (the code "
        "checks keep c4), and each of the 20 analyses without a note goes under missing."
    )
    return got


def test_a_clean_note_is_clean(tmp_path):
    got = tally(tmp_path, ("KO:2026-11-13", "-"))
    assert got["clean"] == ["KO:2026-11-13"] and not got["missed"] and not got["caught"], (
        f"a note on KO:2026-11-13 with first_failure '-' (nothing wrong) should be listed under clean and nowhere "
        f"else; got clean={got['clean']}, missed={got['missed']}, caught={got['caught']}"
    )


def test_caught_is_about_the_first_failure_itself(tmp_path):
    got = tally(tmp_path, ("HD:2026-11-13", "c4"), ("UNH:2026-11-13", "c2"))
    assert got["missed"] == ["HD:2026-11-13 c4"], (
        f"HD:2026-11-13 c4 should be under missed; got missed={got['missed']}, caught={got['caught']}. The code "
        f"checks reject other claims of that analysis ({', '.join(rejected('HD:2026-11-13'))}) but keep c4, the "
        "claim the note names."
    )
    assert got["caught"] == ["UNH:2026-11-13 c2"], (
        f"UNH:2026-11-13 c2 is a claim the code checks reject, so it belongs under caught; got caught={got['caught']}"
    )


def test_a_note_belongs_to_the_trace_with_its_analysis_id(tmp_path):
    path = notes(tmp_path, ("AMZN:2026-11-13", "c4"))
    text = path.read_text().replace(pack()["AMZN:2026-11-13"]["analysis_id"], "an_0000000000000000")
    path.write_text(text)
    got = tally_notes(path, RUN)
    assert got.get("unknown") == ["AMZN:2026-11-13"] and "AMZN:2026-11-13" in got.get("missing", []), (
        f"a row with item AMZN:2026-11-13 and analysis_id an_0000000000000000 (no trace of the run has that id) "
        f"should be listed under unknown, and AMZN:2026-11-13 should stay under missing; got "
        f"unknown={got.get('unknown')}, missed={got.get('missed')}. The same item can be analysed in many runs; "
        "only the id says which trace a note is about."
    )


def test_the_four_starting_notes(tmp_path):
    stub = Path(__file__).resolve().parent / "stub" / "evals" / "labels.csv"
    with stub.open(newline="") as fh:
        rows = [(r["item"], r["first_failure"]) for r in csv.DictReader(fh)]
    got = tally(tmp_path, *rows)
    noted = {item for item, _ in rows}
    want = {"missed": ["AMZN:2026-11-13 c4", "HD:2026-11-13 c4"], "caught": ["UNH:2026-11-13 c2"],
            "clean": ["KO:2026-11-13"], "missing": [i for i in pack() if i not in noted], "unknown": []}
    for key, value in want.items():
        assert got[key] == value, (
            f"for the 4 notes the stub starts with, {key} should be {value} (in the run's order); got {got[key]}"
        )


def test_the_lists_follow_the_runs_order(tmp_path):
    run = tmp_path / "reversed.jsonl"
    run.write_text("".join(reversed(RUN.read_text().splitlines(keepends=True))))
    items = list(reversed(pack()))
    got = tally_notes(notes(tmp_path, ("AMZN:2026-11-13", "c4"), ("HD:2026-11-13", "c4")), run)
    want = {"missed": ["HD:2026-11-13 c4", "AMZN:2026-11-13 c4"],
            "missing": [i for i in items if i not in ("AMZN:2026-11-13", "HD:2026-11-13")]}
    for key, value in want.items():
        assert got.get(key) == value, (
            f"on a run whose traces are in reverse order (first {items[0]}, last {items[-1]}), {key} should be "
            f"{value[:3]}... (the run's order); got {(got.get(key) or [])[:3]}... The lists follow the order of the "
            "traces in the run, whatever order their items sort in."
        )


def test_every_unknown_row_is_listed_in_the_files_order(tmp_path):
    path = tmp_path / "labels.csv"
    with path.open("w", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(HEADER)
        out.writerow(["an_00000000000000aa", "KO:2026-11-13", "c2", "a note on a trace of another run", ""])
        out.writerow(["an_00000000000000bb", "AMZN:2026-11-13", "c4", "another note on another run", ""])
    got = tally_notes(path, RUN).get("unknown")
    assert got == ["KO:2026-11-13", "AMZN:2026-11-13"], (
        f"two rows whose analysis_id is no trace of the run, KO:2026-11-13 then AMZN:2026-11-13, gave unknown={got}; "
        "expected both, in the order the file has them"
    )


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
        "Read each trace and write one note per analysis; `uv run python -m tradingresearch.taxonomy notes` lists "
        "the ones with no note yet."
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
        _, bad = validate_claims(row["output_parsed"], row["values"], "an_lab")
        reason = {x.claim: x.reason for x in bad}.get(first)
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
    got = tally_notes(REPO / "evals" / "labels.csv", RUN)
    assert got["missed"], (
        "every first_failure is a claim the code checks already reject (tally_notes lists none under missed). "
        "Write what a reader would object to: the author found 6 analyses whose first failure no check catches "
        "(week-1.md §3, done when)."
    )
