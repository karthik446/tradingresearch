"""Error analysis on your notes (week 1, lab w1l2): evals/labels.csv and evals/taxonomy.md against a recorded run.

    uv run python -m tradingresearch.taxonomy notes        # w1l2.1: what your notes say about each analysis
    uv run python -m tradingresearch.taxonomy counts       # w1l2.2: analyses per class in labels.csv
    uv run python -m tradingresearch.taxonomy table        # w1l2.3: your table next to what the code checks find
    uv run python -m tradingresearch.taxonomy check        # w1l2.4: what is left to back-fill

The run is the recorded observe run (labs/w1/data/observe.jsonl; `--run` picks another). No model is called.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter
from pathlib import Path

from .analyze import validate_claims

REPO = Path(__file__).resolve().parents[2]
RUN = Path(os.environ.get("TR_LAB_DATA") or REPO / "labs" / "w1" / "data") / "observe.jsonl"
TAGS = {"cascade"}  # marks on a row, not failure classes: never counted
WINDOW = re.compile(r"\b\d+-day\b", re.IGNORECASE)  # an indicator named by its window: "200-day", "14-Day"
CODE_FINDS = ("window_name", "label_in_value", "cascade")  # the keys of code_classes


def load_run(path: Path) -> list[dict]:
    """The recorded traces, one dict per analysis: item, analysis_id, run_id, output_parsed, values, names, scores."""
    return [json.loads(line) for line in Path(path).open()]


def rejected(trace: dict) -> list[tuple[str, str]]:
    """(claim id, reason) for each claim the code checks reject in one trace, in reply order."""
    return [(x.claim, x.reason) for x in validate_claims(trace["output_parsed"], trace["values"], "an_lab")[1]]


def claim_texts(trace: dict) -> dict[str, str]:
    """Claim id -> text, for the claims of one trace."""
    claims = (trace["output_parsed"] or {}).get("claims") or []
    return {str(c.get("id")): str(c.get("text") or "") for c in claims if isinstance(c, dict)}


def table_rows(path: Path) -> list[dict]:
    """The class rows of a taxonomy table: `| # | Class | Claims | Analyses | Caught today by | Example |`.

    Each row is a dict: name (the class id before the ':'), claims and analyses (ints, None when the cell is not a
    number), caught, example.
    """
    rows = []
    for line in Path(path).read_text().splitlines():
        if re.match(r"\|\s*\d+\s*\|", line):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")] + [""] * 6
            rows.append({"name": cells[1].partition(":")[0].strip(), "claims": _int(cells[2]),
                         "analyses": _int(cells[3]), "caught": cells[4], "example": cells[5]})
    return rows


def _int(cell: str) -> int | None:
    return int(cell) if cell.isdigit() else None


def tally_notes(labels: Path, run: Path) -> dict[str, list[str]]:
    """What your notes say about each analysis of the run. A note belongs to the trace with its analysis_id.

    Returns five lists. The first four follow the run's order, `unknown` follows the file's:
      missed:  "ITEM cN" when first_failure is a claim the code checks keep (only a reader saw it)
      caught:  "ITEM cN" when first_failure is a claim the code checks reject
      clean:   "ITEM" when first_failure is "-"
      missing: "ITEM" for an analysis of the run that no row is about
      unknown: the item of each row whose analysis_id is no analysis of the run
    """
    # TODO(w1l2.1) read labels.csv and load_run(run); put each trace in one list, using the row with its analysis_id.
    return {}


def class_counts(path: Path) -> dict[str, int]:
    """Analyses per class: a row adds one to each class it lists, however often it lists it.

    Classes are ';'-separated in `classes`; names are stripped and case-sensitive. Blanks and TAGS are skipped.
    """
    # TODO(w1l2.2) read the CSV with csv.DictReader and count.
    return {}


def code_classes(run: Path) -> dict[str, dict[str, list[str]]]:
    """The classes the code checks find by themselves: class -> item -> claim ids, in the run's and the reply's order.

      window_name:    rejected as number_in_text, and the claim's text names a window (WINDOW)
      label_in_value: rejected as empty_placeholder
      cascade:        rejected as bad_derivation (a parent failed; a tag, not a class)
    Every name in CODE_FINDS is a key. An item with no such claim is not listed under it.
    """
    # TODO(w1l2.3) for each trace, file each rejected claim under the class its reason (and text) shows.
    return {}


def backfill_todo(labels: Path, taxonomy: Path, run: Path) -> dict[str, list[str]]:
    """What is left before labels.csv and taxonomy.md agree. Four sorted lists:

      unlabelled: "ITEM" for a row with a failure (first_failure is not "-") that lists no class (TAGS do not count)
      unknown:    "ITEM: name" for a class a row lists that is no row of the table (TAGS are not classes)
      code:       "ITEM: +name" when code_classes finds name in ITEM and the row does not list it;
                  "ITEM: -name" when the row lists window_name or label_in_value and the code finds none there
                  (cascade is checked one way only: a reader may see a cascade the code does not)
      counts:     "name: table N, labels M" for a table row whose Analyses is not class_counts(labels)[name] (0 if absent)
    """
    # TODO(w1l2.4) read both files and code_classes(run); check each row against the table and the code, then the
    #   table's Analyses against class_counts.
    return {}


# ---------- the command ----------

NOTE_LISTS = (("missed", "first failure missed by the code checks"), ("caught", "first failure caught by the code checks"),
              ("clean", "clean (first_failure -)"), ("missing", "no note yet"), ("unknown", "analysis_id not in the run"))
TODO_LISTS = (("unlabelled", "failing rows with no class"), ("unknown", "classes that are no row of the table"),
              ("code", "rows that disagree with the code checks"), ("counts", "table counts labels.csv does not give"))
EXAMPLE = re.compile(r"\b([A-Z]+) (\d\d-\d\d) (c\d+)\b")


def run_id(run: Path) -> str:
    traces = load_run(run)
    return traces[0]["run_id"] if traces else str(run)


def size(by_item: dict[str, list[str]]) -> tuple[int, int]:
    """(claims, analyses) of one code_classes entry."""
    return sum(map(len, by_item.values())), len(by_item)


def show_notes(labels: Path, run: Path) -> None:
    got, total = tally_notes(labels, run), len(load_run(run))
    if not got:
        print("tally_notes returned nothing: write it first (TODO(w1l2.1))")
        return
    print(f"{labels} against {run_id(run)}: notes for {total - len(got.get('missing', []))} of {total} analyses")
    for key, what in NOTE_LISTS:
        items = got.get(key, [])
        print(f"  {what:<40} {len(items):>2}  {', '.join(items)}".rstrip())


def show_counts(paths: list[Path]) -> None:
    for path in paths:
        with Path(path).open(newline="") as fh:
            rows = list(csv.DictReader(fh))
        filled = sum(bool((row.get("classes") or "").strip()) for row in rows)
        counts = class_counts(path)
        print(f"{path}: {len(counts)} classes; {filled} of {len(rows)} rows list classes")
        for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {n:>3}  {name}")


def example_says(cell: str, traces: dict[str, dict]) -> str:
    found = EXAMPLE.search(cell)
    if not found:
        return "example should start TICKER MM-DD cN"
    ticker, day, claim = found.groups()
    trace = next((t for item, t in traces.items() if item == f"{ticker}:{item.split(':')[-1][:4]}-{day}"), None)
    if trace is None:
        return f"{ticker} {day} is no analysis of the run"
    return f"{ticker} {day} {claim} found" if claim in claim_texts(trace) else f"{ticker} {day} has no claim {claim}"


def show_table(taxonomy: Path, run: Path) -> None:
    rows, found = table_rows(taxonomy), code_classes(run)
    traces = {t["item"]: t for t in load_run(run)}
    print(f"{taxonomy}: {len(rows)} class rows, against {run_id(run)}")
    print(f"  {'class':<22} {'claims':>6} {'analyses':>8}  {'code finds':<20} example")
    for row in rows:
        code = ""
        if row["name"] in found and row["name"] not in TAGS:
            claims, analyses = size(found[row["name"]])
            same = (row["claims"], row["analyses"]) == (claims, analyses)
            code = f"{claims} in {analyses}, {'same' if same else 'DIFFERENT'}"
        print(f"  {row['name']:<22} {row['claims']!s:>6} {row['analyses']!s:>8}  {code:<20} "
              f"{example_says(row['example'], traces)}")
    if not found:
        print("code_classes returned nothing: write it first (TODO(w1l2.3))")
        return
    for name in sorted(set(found) - TAGS - {row["name"] for row in rows}):
        print(f"  no row for {name}: the code finds %d claims in %d analyses" % size(found[name]))
    print("  not a class: cascade, %d claims in %d analyses rejected as bad_derivation" % size(found.get("cascade", {})))


def show_check(labels: Path, taxonomy: Path, run: Path) -> None:
    got = backfill_todo(labels, taxonomy, run)
    if not got:
        print("backfill_todo returned nothing: write it first (TODO(w1l2.4))")
        return
    print(f"{labels} and {taxonomy} against {run_id(run)}:")
    for key, what in TODO_LISTS:
        items = got.get(key, [])
        print(f"  {what} ({len(items)}){': ' + ', '.join(items) if items else ''}")
    if not any(got.values()):
        print("nothing left: every failing row has classes, they agree with the code checks and add up to the table")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, default=RUN, help="a recorded run, .jsonl (default: the observe run)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("notes").add_argument("labels", nargs="?", type=Path, default=Path("evals/labels.csv"))
    sub.add_parser("counts").add_argument("labels", nargs="*", type=Path, default=[Path("evals/labels.csv")])
    sub.add_parser("table").add_argument("taxonomy", nargs="?", type=Path, default=Path("evals/taxonomy.md"))
    check = sub.add_parser("check")
    check.add_argument("labels", nargs="?", type=Path, default=Path("evals/labels.csv"))
    check.add_argument("taxonomy", nargs="?", type=Path, default=Path("evals/taxonomy.md"))
    args = parser.parse_args()
    if args.command == "notes":
        show_notes(args.labels, args.run)
    elif args.command == "counts":
        show_counts(args.labels)
    elif args.command == "table":
        show_table(args.taxonomy, args.run)
    else:
        show_check(args.labels, args.taxonomy, args.run)


if __name__ == "__main__":
    main()
