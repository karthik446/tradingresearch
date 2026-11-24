"""w1l2.2 class_counts: analyses per failure class, the count the taxonomy table reports.

fixtures/labels.csv is the author's evals/labels.csv at week-1-end, classes filled.
"""

from pathlib import Path

from tradingresearch.taxonomy import class_counts

AUTHOR = Path(__file__).resolve().parent / "fixtures" / "labels.csv"
EXPECTED = {"judgement_in_fact": 19, "window_name": 15, "inference_wider": 15, "opinion_cites": 5,
            "label_in_value": 4, "number_outside_value": 3, "other": 3}


def write(tmp_path: Path, *classes: str) -> Path:
    path = tmp_path / "labels.csv"
    rows = [f"an_{i:016x},T:2026-11-1{i},c1,note,{c}" for i, c in enumerate(classes)]
    path.write_text("\n".join(["analysis_id,item,first_failure,note,classes", *rows]) + "\n")
    return path


def test_the_authors_labels():
    got = class_counts(AUTHOR)
    assert got, f"class_counts returned {{}} for the author's labels.csv; expected 7 classes, e.g. judgement_in_fact: 19"
    assert "cascade" not in got, (
        f"cascade counted {got['cascade']} times: it is a tag on 12 rows (one failure took later claims down), "
        "not a failure class. Skip TAGS."
    )
    assert got == EXPECTED, f"analyses per class should be {EXPECTED}; got {got}"


def test_a_class_listed_twice_in_a_row_counts_once(tmp_path):
    got = class_counts(write(tmp_path, "window_name; window_name ;judgement_in_fact"))
    assert got == {"window_name": 1, "judgement_in_fact": 1}, (
        f"one row listing ' window_name ' twice is one analysis: strip spaces, count a class once per row, skip "
        f"blanks; got {got}"
    )


def test_a_clean_row_adds_nothing(tmp_path):
    got = class_counts(write(tmp_path, "", "cascade"))
    assert got == {}, f"an empty classes column and a row tagged only cascade add no class; got {got}"
