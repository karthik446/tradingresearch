"""Observe for the week-2 labs: run your process checks on the author's recorded theses ($0, no network).

    python labs/w2/tools/observe.py

Reads labs/w2/data/theses.json (TR_LAB_DATA overrides the folder) and prints one row per thesis, one column per
check: 1 passes, 0 fails, - the function is not in checks.py yet, ! it raised (the note under the table says what).
The chapter's six theses come first, with the totals the chapter's table reports; then later real theses (shorts,
a market_open entry) the chapter does not show; then synthetic copies, each breaking one rule, with the check that
should catch it. Always exits 0: it shows what your code does, the exercise's check decides.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from tradingresearch.records import Claim, Thesis

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[1] / "data")
CHAPTER_TOTALS = {"P2": 6, "P3": 6}  # week-2.md §2, the table of the six theses


def p2(checks: object, thesis: Thesis, analysis: dict) -> bool:
    claims = tuple(Claim.model_validate_json(json.dumps(claim)) for claim in analysis["claims"])
    return checks.p2_evidence_valid(thesis, claims, analysis["values"])


def p3(checks: object, thesis: Thesis, analysis: dict) -> bool:
    return checks.p3_invalidation_testable(thesis, analysis["reference_close"])


# column, function name in checks.py, how to call it
CHECKS: list[tuple[str, str, Callable[[object, Thesis, dict], bool]]] = [
    ("P2", "p2_evidence_valid", p2),
    ("P3", "p3_invalidation_testable", p3),
]


def load_checks() -> object | str:
    try:
        return importlib.import_module("tradingresearch.checks")
    except Exception as exc:  # a learner's half-written file: show it, keep going
        return f"{type(exc).__name__}: {exc}"


def cell(checks: object | str, name: str, call: Callable, thesis: Thesis, analysis: dict, notes: list[str],
         label: str) -> str:
    if isinstance(checks, str) or not hasattr(checks, name):
        return "-"
    try:
        result = call(checks, thesis, analysis)
    except Exception as exc:
        notes.append(f"{label}: {name} raised {type(exc).__name__}: {exc}")
        return "!"
    return "1" if result is True else "0"


def main() -> int:
    data = json.loads((DATA / "theses.json").read_text())
    checks = load_checks()
    notes: list[str] = []
    if isinstance(checks, str):
        notes.append(f"tradingresearch.checks did not import: {checks}")
    width = max(len(row["label"]) for row in data["theses"])
    head = "  ".join(column for column, _, _ in CHECKS)
    blocks = {"chapter": "The chapter's six theses (week-2.md §2)",
              "more": "Later real theses the chapter does not show",
              "synthetic": "Synthetic copies, each breaking one rule (should read 0 in the check named)"}
    rows: dict[str, list[tuple[dict, list[str]]]] = {group: [] for group in blocks}
    for row in data["theses"]:
        thesis = Thesis.model_validate_json(json.dumps(row["thesis"]))
        analysis = data["analyses"][row["analysis"]]
        rows[row["group"]].append(
            (row, [cell(checks, name, call, thesis, analysis, notes, row["label"]) for _, name, call in CHECKS]))
    for group, title in blocks.items():
        print(f"{title}\n  {'thesis':<{width}}  {head}")
        for row, cells in rows[group]:
            extra = f"   ({row['check']}: {row['why']})" if group == "synthetic" else ""
            print(f"  {row['label']:<{width}}  {'   '.join(cells)}{extra}")
        if group == "chapter":
            totals = []
            for index, (column, _, _) in enumerate(CHECKS):
                column_cells = [cells[index] for _, cells in rows[group]]
                count = len(column_cells)
                if all(c in "01" for c in column_cells):
                    totals.append(f"{column} {column_cells.count('1')}/{count} (chapter: {CHAPTER_TOTALS[column]}/{count})")
                else:
                    totals.append(f"{column} not counted: a cell reads - or !")
            print("  passing: " + ", ".join(totals))
        if group == "synthetic":
            caught = [(row, cells[[column for column, _, _ in CHECKS].index(row["check"])]) for row, cells in rows[group]]
            open_ = sum(1 for _, c in caught if c != "0")
            print(f"  synthetic rows the named check does not reject yet: {open_} of {len(caught)} (0 once every rule "
                  f"is in)")
        print()
    for note in notes:
        print("note: " + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
