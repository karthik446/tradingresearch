"""w1l2.3 taxonomy table: 5 to 8 failure classes, each with counts, what catches it and a real example.

Checks the table in `evals/taxonomy.md` in your repo; examples and the two classes the code checks already find
(window_name, label_in_value) are looked up in the recorded observe run.
"""

import json
import os
import re
from pathlib import Path

import tradingresearch
from tradingresearch.analyze import validate_claims

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
REPO = Path(tradingresearch.__file__).resolve().parents[2]
REASONS = {"number_in_text", "bad_placeholder", "empty_placeholder", "unknown_source", "number_in_opinion",
           "unsourced_number", "bad_derivation", "not_a_claim"}
REQUIRED = {  # class id -> the later exercise that reads it under this name
    "window_name": "w1l4.1 writes a rule for it",
    "inference_wider": "w1l3.6 compares the grader's flags with it",
    "opinion_cites": "w1l4.1 writes a rule for it",
    "label_in_value": "w1l4.1 writes a rule for it",
}
WINDOW = re.compile(r"\b\d+-day\b", re.IGNORECASE)


def pack() -> list[dict]:
    return [json.loads(line) for line in (DATA / "observe.jsonl").open()]


def found_by_code() -> dict[str, tuple[int, int]]:
    """(claims, analyses) of the two classes a code check finds: number_in_text naming a window, empty_placeholder."""
    hits: dict[str, list[str]] = {"window_name": [], "label_in_value": []}
    for row in pack():
        texts = {c.get("id"): str(c.get("text") or "") for c in row["output_parsed"]["claims"]}
        for x in validate_claims(row["output_parsed"], row["values"], "an_lab")[1]:
            if x.reason == "number_in_text" and WINDOW.search(texts.get(x.claim, "")):
                hits["window_name"].append(row["item"])
            elif x.reason == "empty_placeholder":
                hits["label_in_value"].append(row["item"])
    return {name: (len(items), len(set(items))) for name, items in hits.items()}


def table() -> list[list[str]]:
    path = REPO / "evals" / "taxonomy.md"
    assert path.exists(), f"{path} does not exist"
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in path.read_text().splitlines() if re.match(r"\|\s*\d+\s*\|", line)]
    return rows


def test_five_to_eight_classes():
    rows = table()
    assert 5 <= len(rows) <= 8, (
        f"taxonomy.md has {len(rows)} class rows; group your 20 notes into 5 to 8 classes (week-1.md §4). Fewer "
        "and the classes say nothing; more and they will not get evals."
    )
    for row in rows:
        assert len(row) == 6, f"row {row[0]} has {len(row)} cells; columns are # | Class | Claims | Analyses | " \
                              "Caught today by | Example"


def test_classes_are_failures_not_validator_reasons():
    names = []
    for row in table():
        name, _, definition = row[1].partition(":")
        assert re.fullmatch(r"[a-z_]+", name.strip()) and definition.strip(), (
            f"class cell {row[1]!r} should be `snake_name: definition`, so labels.csv can use the name"
        )
        names.append(name.strip())
    assert "bad_derivation" not in names and "cascade" not in names, (
        "bad_derivation / cascade is a consequence of a parent's failure, not a class (week-1.md §4): count the "
        "parent's class instead"
    )
    assert not set(names) <= REASONS, (
        f"every class ({', '.join(names)}) is a validator reason. Grouping by reasons hides the failures no check "
        "fires on, which are the ones you most need an eval for."
    )


def test_the_classes_later_exercises_read_are_named_as_given():
    names = {row[1].partition(":")[0].strip() for row in table()}
    missing = [f"{name} ({why})" for name, why in REQUIRED.items() if name not in names]
    assert not missing, (
        f"taxonomy.md has no row for {'; '.join(missing)}. Lab w1l2 fixes these four class ids so later exercises can "
        "find them: keep the name exactly, write your own definition and counts. Other classes are yours to name."
    )


def test_counts_and_caught_by():
    rows, total = table(), sum(len(row["output_parsed"]["claims"]) for row in pack())
    for row in rows:
        claims, analyses = int(row[2]), int(row[3])
        assert 1 <= analyses <= 20 and analyses <= claims <= total, (
            f"{row[1].split(':')[0]}: {claims} claims in {analyses} analyses; each counted analysis has at least one "
            f"failing claim, there are 20 analyses and {total} claims"
        )
    counted = sum(int(row[2]) for row in rows)
    assert counted <= total, (
        f"the Claims column adds up to {counted}, but the observe run has {total} claims. Count each failing claim in "
        "the one class that explains it."
    )
    assert any(row[4].lower().startswith("nothing") for row in rows), (
        "no class is 'Caught today by: nothing'. The point of the table is to find the largest class the code misses."
    )


def test_the_classes_code_finds_match_the_recording():
    rows = {row[1].partition(":")[0].strip(): (int(row[2]), int(row[3])) for row in table()}
    how = {"window_name": "rejected as number_in_text and naming a window such as '200-day'",
           "label_in_value": "rejected as empty_placeholder"}
    for name, (claims, analyses) in found_by_code().items():
        assert rows[name] == (claims, analyses), (
            f"{name}: the table says {rows[name][0]} claims in {rows[name][1]} analyses, but the observe run has "
            f"{claims} claims {how[name]}, in {analyses} analyses. These two counts come straight from the code "
            "checks: recount them on the traces."
        )


def test_examples_are_real_claims():
    items = {row["item"]: row for row in map(json.loads, (DATA / "observe.jsonl").open())}
    for row in table():
        found = re.search(r"\b([A-Z]+) (\d\d-\d\d) (c\d+)\b", row[5])
        assert found, f"{row[1].split(':')[0]}: example {row[5]!r} should start `TICKER MM-DD cN`, e.g. JPM 11-12 c2"
        ticker, day, claim = found.groups()
        item = items.get(f"{ticker}:2026-{day}")
        assert item, f"example {ticker} {day} is not an analysis of the observe run"
        ids = {c["id"] for c in item["output_parsed"]["claims"]}
        assert claim in ids, f"example {ticker} {day} {claim}: that analysis has no claim {claim}"
