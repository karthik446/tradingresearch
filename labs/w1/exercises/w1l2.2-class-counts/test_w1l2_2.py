"""w1l2.2 class_counts: analyses per failure class, the count the taxonomy table reports.

fixtures/labels.csv is the author's evals/labels.csv at week-1-end, classes filled.
"""

import csv
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
        f"one row that lists ' window_name ' twice is one analysis: strip spaces, count a class once per row, skip "
        f"blanks; got {got}"
    )


def test_a_clean_row_adds_nothing(tmp_path):
    got = class_counts(write(tmp_path, "", "cascade"))
    assert got == {}, f"an empty classes column and a row tagged only cascade add no class; got {got}"


def test_any_class_a_row_lists_is_counted(tmp_path):
    got = class_counts(write(tmp_path, "sign_backwards", "sign_backwards; missing_unit",
                             "cascade; missing_unit; sign_backwards"))
    assert got == {"sign_backwards": 3, "missing_unit": 2}, (
        f"three rows listing sign_backwards (3 rows) and missing_unit (2 rows) gave {got}. class_counts counts "
        "whatever classes your rows name, not a fixed list of the author's."
    )


def test_class_names_are_case_sensitive(tmp_path):
    got = class_counts(write(tmp_path, "Window_Name; window_name"))
    assert got == {"Window_Name": 1, "window_name": 1}, (
        f"a row listing 'Window_Name; window_name' gave {got}; expected {{'Window_Name': 1, 'window_name': 1}}. "
        "Class names are counted as written: a miscased name is another class, which w1l2.4 then reports as no row "
        "of the table, instead of being merged silently."
    )


def test_a_hyphen_is_not_an_underscore(tmp_path):
    got = class_counts(write(tmp_path, "wrong-sign; wrong_sign"))
    assert got == {"wrong-sign": 1, "wrong_sign": 1}, (
        f"a row listing 'wrong-sign; wrong_sign' gave {got}; expected {{'wrong-sign': 1, 'wrong_sign': 1}}. Names "
        "are counted as written, punctuation included: a miswritten name shows up as its own class for you to fix "
        "in labels.csv, instead of being merged by a guess."
    )


def test_only_a_semicolon_separates_classes(tmp_path):
    path = tmp_path / "labels.csv"
    with path.open("w", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(["analysis_id", "item", "first_failure", "note", "classes"])
        out.writerow(["an_0000000000000000", "T:2026-11-10", "c1", "note", "window_name,judgement_in_fact"])
    got = class_counts(path)
    assert got == {"window_name,judgement_in_fact": 1}, (
        f"a row whose classes cell is 'window_name,judgement_in_fact' gave {got}; expected "
        "{'window_name,judgement_in_fact': 1}. Only ';' separates classes, so that cell names one (misspelt) class, "
        "which w1l2.4 then reports as no row of the table, instead of being split into two by a guess."
    )
