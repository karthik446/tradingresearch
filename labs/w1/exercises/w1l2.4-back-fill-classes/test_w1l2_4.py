"""w1l2.4 back-fill: backfill_todo in src/tradingresearch/taxonomy.py, then every note gets the taxonomy classes it
shows and the table's counts come from them.

The first tests call backfill_todo on small files written here; the rest check `evals/labels.csv` against
`evals/taxonomy.md` in your repo, and the cascade tag against the recorded run.
"""

import csv
import json
import os
import re
from pathlib import Path

import tradingresearch
from tradingresearch.analyze import validate_claims
from tradingresearch.taxonomy import TAGS, backfill_todo, class_counts

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
REPO = Path(tradingresearch.__file__).resolve().parents[2]
RUN = DATA / "observe.jsonl"
REQUIRED = ("window_name", "inference_wider", "opinion_cites", "label_in_value")  # read by w1l3.6 and w1l4.1
WINDOW = re.compile(r"\b\d+-day\b", re.IGNORECASE)
KEYS = {"unlabelled", "unknown", "code", "counts"}


def files(tmp_path: Path, rows: dict[str, str], table: dict[str, int], clean: tuple[str, ...] = ()) -> tuple[Path, Path]:
    """labels.csv with one row per item -> classes (first_failure c1, or - when classes is '-' or the item is in
    clean), and a table whose Claims column (count + 3) differs from its Analyses column (count)."""
    ids = {r["item"]: r["analysis_id"] for r in map(json.loads, RUN.open())}
    labels, md = tmp_path / "labels.csv", tmp_path / "taxonomy.md"
    with labels.open("w", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(["analysis_id", "item", "first_failure", "note", "classes"])
        for item, listed in rows.items():
            out.writerow([ids[item], item, "-" if listed == "-" or item in clean else "c1",
                          "c1 is a note long enough to keep", "" if listed == "-" else listed])
    md.write_text("| # | Class | Claims | Analyses | Caught today by | Example |\n|---|---|---|---|---|---|\n" + "".join(
        f"| {n} | {name}: a class | {count + 3} | {count} | nothing | JPM 11-12 c2 |\n"
        for n, (name, count) in enumerate(table.items(), 1)))
    return labels, md


def todo(tmp_path: Path, rows: dict[str, str], table: dict[str, int], clean: tuple[str, ...] = ()) -> dict[str, list[str]]:
    got = backfill_todo(*files(tmp_path, rows, table, clean), RUN)
    assert got and KEYS <= set(got), (
        f"backfill_todo returned {got!r} for labels {rows} and a table with {', '.join(table)}. It should return "
        f"the lists {', '.join(sorted(KEYS))}: e.g. a failing row with no classes (AAPL:2026-11-12 here) goes under "
        "unlabelled."
    )
    return got


def test_a_failing_row_without_classes_is_unlabelled(tmp_path):
    got = todo(tmp_path, {"AAPL:2026-11-12": "", "KO:2026-11-13": "-", "AMZN:2026-11-13": "cascade"},
               {"inference_wider": 1})
    assert got["unlabelled"] == ["AAPL:2026-11-12", "AMZN:2026-11-13"], (
        f"unlabelled should be AAPL:2026-11-12 (a failure, no classes) and AMZN:2026-11-13 (a failure, only the "
        f"cascade tag, which is no class); KO:2026-11-13 is clean. Got {got['unlabelled']}"
    )


def test_a_class_that_is_no_row_of_the_table_is_unknown(tmp_path):
    got = todo(tmp_path, {"AMZN:2026-11-13": "uncited_names;inference_wider;cascade"}, {"inference_wider": 1})
    assert got["unknown"] == ["AMZN:2026-11-13: uncited_names"], (
        "AMZN:2026-11-13 lists uncited_names, which is no row of the table (rows: inference_wider); cascade is a tag "
        f"and needs no row. unknown should be ['AMZN:2026-11-13: uncited_names']; got {got['unknown']}"
    )


def test_a_class_matches_a_row_only_as_written(tmp_path):
    got = todo(tmp_path, {"AMZN:2026-11-13": "Window_Name;inference_wider"}, {"window_name": 1, "inference_wider": 1})
    assert got["unknown"] == ["AMZN:2026-11-13: Window_Name"], (
        "AMZN:2026-11-13 lists Window_Name; the table's row is window_name. unknown should be "
        f"['AMZN:2026-11-13: Window_Name']; got {got['unknown']}. A class matches a row only as written, case "
        "included: class_counts counts Window_Name as a class of its own, so this list is where the typo shows."
    )


def test_rows_are_checked_against_what_the_code_finds(tmp_path):
    rows = {"AAPL:2026-11-12": "inference_wider", "AMZN:2026-11-13": "window_name;inference_wider",
            "NVDA:2026-11-12": "window_name;label_in_value;cascade"}
    got = todo(tmp_path, rows, {"window_name": 2, "label_in_value": 1, "inference_wider": 2})
    want = ["AAPL:2026-11-12: +cascade", "AAPL:2026-11-12: +window_name", "AMZN:2026-11-13: -window_name"]
    assert got["code"] == want, (
        f"code should be {want}; got {got['code']}. AAPL:2026-11-12 has claims rejected as bad_derivation and as a "
        "window name, and its row lists neither. AMZN:2026-11-13 lists window_name, but the code rejects no claim of "
        "it for that. NVDA:2026-11-12 is tagged cascade with no bad_derivation: a reader may see a cascade the code "
        "does not, so a cascade tag the code does not confirm is not reported."
    )


def test_counts_cover_every_row_of_the_table(tmp_path):
    got = todo(tmp_path, {"AAPL:2026-11-12": "window_name;other;cascade"},
               {"window_name": 1, "inference_wider": 15, "other": 1})
    assert got["counts"] == ["inference_wider: table 15, labels 0"], (
        "the table says inference_wider is in 15 analyses and no row lists it (its Claims column says 18), so counts "
        f"should be ['inference_wider: table 15, labels 0'] (window_name and other agree at 1); got {got['counts']}. "
        "counts compares the Analyses column with class_counts, which counts analyses."
    )


def test_a_row_marked_clean_is_still_checked(tmp_path):
    got = todo(tmp_path, {"KO:2026-11-13": "phantom;window_name"}, {"window_name": 1}, clean=("KO:2026-11-13",))
    want = {"unlabelled": [], "unknown": ["KO:2026-11-13: phantom"], "code": ["KO:2026-11-13: -window_name"]}
    assert {key: got[key] for key in want} == want, (
        f"KO:2026-11-13 is marked clean (first_failure -) but lists phantom, no row of the table, and window_name, "
        f"which the code does not find in it. backfill_todo gave {({key: got[key] for key in want})}; expected {want}. "
        "Only unlabelled depends on first_failure: a row that lists classes is checked against the table and the code "
        "whatever its first_failure says, or a wrong label hides behind a '-'."
    )


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
    items = {r["item"]: r for r in map(json.loads, RUN.open())}
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
    items = {r["item"]: r for r in map(json.loads, RUN.open())}
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
