"""w1l2.4 back-fill: every note gets the taxonomy classes it shows, and the table's counts come from them.

Checks `evals/labels.csv` against `evals/taxonomy.md` in your repo, and the cascade tag against the recorded run.
"""

import csv
import json
import os
import re
from pathlib import Path

import tradingresearch
from tradingresearch.analyze import validate_claims
from tradingresearch.taxonomy import TAGS, class_counts

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
REPO = Path(tradingresearch.__file__).resolve().parents[2]
REQUIRED = ("window_name", "inference_wider", "opinion_cites", "label_in_value")  # read by w1l3.6 and w1l4.1
WINDOW = re.compile(r"\b\d+-day\b", re.IGNORECASE)


def taxonomy() -> dict[str, int]:
    """Class name -> the Analyses column of evals/taxonomy.md."""
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in (REPO / "evals" / "taxonomy.md").read_text().splitlines() if re.match(r"\|\s*\d+\s*\|", line)]
    return {row[1].split(":")[0].strip(): int(row[3]) for row in rows}


def labels() -> list[dict]:
    with (REPO / "evals" / "labels.csv").open(newline="") as fh:
        return list(csv.DictReader(fh))


def classes(row: dict) -> set[str]:
    return {c.strip() for c in (row["classes"] or "").split(";")} - {""}


def test_every_failing_analysis_has_classes():
    known = set(taxonomy())
    for row in labels():
        if row["first_failure"] == "-":
            continue
        assert classes(row) - TAGS, (
            f"{row['item']} has a failure ({row['first_failure']}) but no classes. Read its note and list the "
            f"taxonomy classes it shows, ';'-separated: {', '.join(sorted(known))}"
        )
        unknown = classes(row) - known - TAGS
        assert not unknown, f"{row['item']} uses {sorted(unknown)}, which are not rows of evals/taxonomy.md"


def test_cascade_marks_every_analysis_with_a_bad_derivation():
    items = {r["item"]: r for r in map(json.loads, (DATA / "observe.jsonl").open())}
    for row in labels():
        item = items[row["item"]]
        _, rejected = validate_claims(item["output_parsed"], item["values"], "an_lab")
        cascaded = [x.claim for x in rejected if x.reason == "bad_derivation"]
        if cascaded:
            assert "cascade" in classes(row), (
                f"{row['item']}: {', '.join(cascaded)} were rejected as bad_derivation (a parent failed), so tag the "
                "row cascade after its classes"
            )


def test_the_fixed_class_ids_label_the_analyses_that_show_them():
    rows = labels()
    unused = [name for name in REQUIRED if not any(name in classes(row) for row in rows)]
    assert not unused, (
        f"no row of labels.csv uses {', '.join(unused)}. Lab w1l2 fixes four class ids ({', '.join(REQUIRED)}): w1l3.6 "
        "counts the analyses labelled inference_wider and w1l4.1 writes rules for the others, so a renamed class "
        "breaks them. Keep these names in labels.csv and taxonomy.md."
    )
    items = {r["item"]: r for r in map(json.loads, (DATA / "observe.jsonl").open())}
    shown = {}  # item -> class -> claims the code rejects for that class
    for row in rows:
        item = items[row["item"]]
        texts = {c.get("id"): str(c.get("text") or "") for c in item["output_parsed"]["claims"]}
        rejected = validate_claims(item["output_parsed"], item["values"], "an_lab")[1]
        shown[row["item"]] = {
            "window_name": [x.claim for x in rejected
                            if x.reason == "number_in_text" and WINDOW.search(texts.get(x.claim, ""))],
            "label_in_value": [x.claim for x in rejected if x.reason == "empty_placeholder"],
        }
    fixed = {name: sum(bool(by[name]) for by in shown.values()) for name in ("window_name", "label_in_value")}
    for row in rows:
        for name, claims in shown[row["item"]].items():
            assert not claims or name in classes(row), (
                f"{row['item']}: the code rejects {', '.join(claims)} for a failure that is class {name}, but the "
                f"row's classes are {sorted(classes(row)) or 'empty'}. Add {name}."
            )
            assert claims or name not in classes(row), (
                f"{row['item']} is labelled {name}, but the code rejects none of its claims for that failure. The code "
                f"finds these two classes by itself, so the recording fixes their rows: window_name in "
                f"{fixed['window_name']} analyses, label_in_value in {fixed['label_in_value']}. Remove {name} from this "
                "row (and keep the table's count at the recording's)."
            )


def test_table_counts_come_from_the_labels():
    counted, table = class_counts(REPO / "evals" / "labels.csv"), taxonomy()
    wrong = {name: (n, counted.get(name, 0)) for name, n in table.items() if counted.get(name, 0) != n}
    assert not wrong, "; ".join(
        f"taxonomy.md says {name} is in {n} analyses, labels.csv has {got}" for name, (n, got) in wrong.items()
    ) + (". Fix whichever is wrong: the counts in the table must add up from labels.csv. For window_name and "
         "label_in_value the recording decides (the code finds them), so match the analyses the code rejects.")
