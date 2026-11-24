"""Observe for the week-2 labs: run your process checks on the author's recorded theses ($0, no network).

    python labs/w2/tools/observe.py

Reads labs/w2/data/theses.json (TR_LAB_DATA overrides the folder) and prints one row per thesis, one column per
check: 1 passes, 0 fails, - the function is not in checks.py yet, ! it raised (the note under the table says what).
The chapter's six theses come first, with the totals the chapter's table reports; then later real theses (shorts,
a market_open entry) the chapter does not show; then synthetic copies, each breaking one rule, with the check that
should catch it and a count per check of the copies it still accepts. Once checks.py has p4_levels_coherent, a
block runs your P4 twice on the real theses: on the prices as stored, and on the same prices rounded to cents by
observe, naming the level that changes side when rounded. Once evals.py has built_theses (lab w2l4), a last block
scores the author's recorded AAPL reply (tests/fixtures/thesis) with each of your graders, the network blocked so
no grader can reach a model. Always exits 0: it shows what your code does, the exercise's check decides.
"""

from __future__ import annotations

import importlib
import json
import os
import socket
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from tradingresearch.records import Claim, Level, Thesis

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[1] / "data")
FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "thesis"  # the author's recorded AAPL reply
CHAPTER_TOTALS = {"P2": 6, "P3": 6, "P4": 2}  # week-2.md §2, the table of the six theses (P4 at cents)


def p2(checks: object, thesis: Thesis, analysis: dict) -> bool:
    claims = tuple(Claim.model_validate_json(json.dumps(claim)) for claim in analysis["claims"])
    return checks.p2_evidence_valid(thesis, claims, analysis["values"])


def p3(checks: object, thesis: Thesis, analysis: dict) -> bool:
    return checks.p3_invalidation_testable(thesis, analysis["reference_close"])


def levels_of(analysis: dict) -> tuple[Level, ...]:
    return tuple(Level.model_validate_json(json.dumps(level)) for level in analysis["levels"])


def p4(checks: object, thesis: Thesis, analysis: dict) -> bool:
    return checks.p4_levels_coherent(thesis, levels_of(analysis), analysis["atr14"], analysis["reference_close"])


# column, function name in checks.py, how to call it. P4 shows only once checks.py has it (lab w2l3).
CHECKS: list[tuple[str, str, Callable[[object, Thesis, dict], bool]]] = [
    ("P2", "p2_evidence_valid", p2),
    ("P3", "p3_invalidation_testable", p3),
    ("P4", "p4_levels_coherent", p4),
]
LATER = {"P4"}


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


def at_cents(thesis: Thesis, analysis: dict) -> tuple[Thesis, dict]:
    """The same thesis and analysis with every price rounded to cents; the ATR stays as stored."""
    entry = thesis.entry
    if entry.price is not None:
        entry = entry.model_copy(update={"price": round(entry.price, 2)})
    rounded = thesis.model_copy(update={"entry": entry, "stop": round(thesis.stop, 2),
                                        "target": round(thesis.target, 2)})
    levels = [{**level, "price": round(level["price"], 2)} for level in analysis["levels"]]
    return rounded, {**analysis, "levels": levels, "reference_close": round(analysis["reference_close"], 2)}


def side_changes(thesis: Thesis, analysis: dict) -> str:
    """The levels whose side of the entry (under, at, over) is not the same at cents as stored."""
    entry = thesis.entry.price if thesis.entry.price is not None else analysis["reference_close"]
    moved = []
    for level in analysis["levels"]:
        price = level["price"]
        stored = (price > entry) - (price < entry)
        cents = (round(price, 2) > round(entry, 2)) - (round(price, 2) < round(entry, 2))
        if stored != cents:
            where = "the entry" if cents == 0 else "across the entry"
            moved.append(f"{level['kind']} {round(price, 5)} is {where} {round(entry, 2)} at cents")
    return "; ".join(moved) or "none"


def cents_block(checks: object, data: dict, notes: list[str]) -> None:
    rows = [row for row in data["theses"] if row["group"] in ("chapter", "more")]
    width = max(len(row["label"]) for row in rows)
    print("P4 at cents: your P4 on the prices as stored, then on the same prices rounded to cents by observe "
          "(the ATR is not rounded)")
    print(f"  {'thesis':<{width}}  stored  cents  level that changes side at cents")
    counts = {"stored": [], "cents": []}
    differ = 0
    for row in rows:
        thesis = Thesis.model_validate_json(json.dumps(row["thesis"]))
        analysis = data["analyses"][row["analysis"]]
        stored = cell(checks, "p4_levels_coherent", p4, thesis, analysis, notes, row["label"])
        cents = cell(checks, "p4_levels_coherent", p4, *at_cents(thesis, analysis), notes,
                     row["label"] + " (at cents)")
        if row["group"] == "chapter":
            counts["stored"].append(stored)
            counts["cents"].append(cents)
        differ += stored != cents
        print(f"  {row['label']:<{width}}  {stored:<6}  {cents:<5}  {side_changes(thesis, analysis)}")
    totals = [f"{name} {cells.count('1')}/{len(cells)}" if all(c in "01" for c in cells) else f"{name} not counted"
              for name, cells in counts.items()]
    print(f"  chapter six passing: {', '.join(totals)} (chapter: {CHAPTER_TOTALS['P4']}/6, at cents)")
    print(f"  rows where stored and cents differ: {differ} of {len(rows)} (0 once your P4 compares at cents)")
    print()


GRADED = ("p2_evidence_valid", "p3_invalidation_testable", "p4_levels_coherent", "p1_judge")
OPINION = "cl_ba1ecc8934034a7d"  # a claim of the AAPL analysis tagged opinion


def no_network(*args: object, **kwargs: object) -> None:
    raise OSError("observe blocks the network: no grader here may call a model")


def scored(evals: object, grader_id: str, items: list, expected: dict) -> str:
    from gigai_core.graders.protocol import CannotGrade  # noqa: PLC0415  only once evals imports

    sample = SimpleNamespace(parse_status="ok", output_parsed={"theses": items, "no_trade": []},
                             recorded_at=datetime(2026, 11, 17, 3, 46, tzinfo=UTC), trace_id="observe")
    try:
        score = evals.GRADERS[grader_id]().grade(sample, expected)
    except CannotGrade as exc:
        return f"cannot grade ({exc})"
    except Exception as exc:  # a learner's half-written grader: show it, keep going
        return f"! {type(exc).__name__}: {exc}"
    value, explanation = getattr(score, "value", score), getattr(score, "explanation", None)
    return f"{value}" + (f" ({explanation})" if explanation else "")


def graders_block(evals: object) -> None:
    from tradingresearch import thesis as th  # noqa: PLC0415
    from tradingresearch.records import Analysis  # noqa: PLC0415

    analysis = Analysis.model_validate_json((FIXTURES / "AAPL_2026-11-16.analysis.json").read_text())
    reply = json.loads((FIXTURES / "AAPL_2026-11-16.reply.json").read_text())["theses"][0]
    expected = th.item_for(analysis, ("day", "short", "swing"), "champion").expected
    broken = {**reply, "horizon": "short", "hold_sessions": 3, "invalidation_price": 344.0,
              "evidence": [*reply["evidence"], OPINION]}
    samples = (("reply", [reply]), ("reply + broken short", [reply, broken]))
    print("Graders on the author's recorded AAPL reply (tests/fixtures/thesis), scored as an eval run scores it; "
          "observe blocks the network")
    print(f"  reply: one swing thesis, limit 343.41, stop 338.7, target 360.83. reply + broken short: the same, then "
          f"a short-horizon copy that adds the opinion {OPINION} to its evidence and an invalidation of 344.0, "
          f"above the entry")
    width = max(len(grader_id) for grader_id in GRADED)
    saved = socket.socket.connect, socket.create_connection
    socket.socket.connect, socket.create_connection = no_network, no_network
    try:
        for grader_id in GRADED:
            cls = evals.GRADERS.get(grader_id)
            if cls is None:
                print(f"  {grader_id:<{width}}  not registered yet")
                continue
            about = f"kind {getattr(cls, 'kind', None)!r}, version {getattr(cls, 'version', None)!r}"
            if hasattr(cls, "validated"):
                about += f", validated {cls.validated!r}"
            results = "; ".join(f"{name}: {scored(evals, grader_id, items, expected)}" for name, items in samples)
            print(f"  {grader_id:<{width}}  ({about})  {results}")
    finally:
        socket.socket.connect, socket.create_connection = saved
    print()


def main() -> int:
    data = json.loads((DATA / "theses.json").read_text())
    checks = load_checks()
    notes: list[str] = []
    if isinstance(checks, str):
        notes.append(f"tradingresearch.checks did not import: {checks}")
    shown = [check for check in CHECKS
             if check[0] not in LATER or (not isinstance(checks, str) and hasattr(checks, check[1]))]
    width = max(len(row["label"]) for row in data["theses"])
    head = "  ".join(column for column, _, _ in shown)
    blocks = {"chapter": "The chapter's six theses (week-2.md §2)",
              "more": "Later real theses the chapter does not show",
              "synthetic": "Synthetic copies, each breaking one rule (should read 0 in the check named)"}
    rows: dict[str, list[tuple[dict, list[str]]]] = {group: [] for group in blocks}
    for row in data["theses"]:
        thesis = Thesis.model_validate_json(json.dumps(row["thesis"]))
        analysis = data["analyses"][row["analysis"]]
        rows[row["group"]].append(
            (row, [cell(checks, name, call, thesis, analysis, notes, row["label"]) for _, name, call in shown]))
    for group, title in blocks.items():
        print(f"{title}\n  {'thesis':<{width}}  {head}")
        for row, cells in rows[group]:
            extra = f"   ({row['check']}: {row['why']})" if group == "synthetic" else ""
            print(f"  {row['label']:<{width}}  {'   '.join(cells)}{extra}")
        if group == "chapter":
            totals = []
            for index, (column, _, _) in enumerate(shown):
                column_cells = [cells[index] for _, cells in rows[group]]
                count = len(column_cells)
                if all(c in "01" for c in column_cells):
                    totals.append(f"{column} {column_cells.count('1')}/{count} (chapter: {CHAPTER_TOTALS[column]}/{count})")
                else:
                    totals.append(f"{column} not counted: a cell reads - or !")
            print("  passing: " + ", ".join(totals))
        if group == "synthetic":
            columns = [column for column, _, _ in shown]
            caught = [(row, cells[columns.index(row["check"])]) for row, cells in rows[group]]
            for column in columns:
                mine = [c for row, c in caught if row["check"] == column]
                if mine:
                    still = sum(1 for c in mine if c != "0")
                    print(f"  {column}: synthetic rows still accepted: {still} of {len(mine)}")
            open_ = sum(1 for _, c in caught if c != "0")
            print(f"  synthetic rows the named check does not reject yet: {open_} of {len(caught)} (0 once every rule "
                  f"is in)")
        print()
    if any(column == "P4" for column, _, _ in shown):
        cents_block(checks, data, notes)
    try:
        evals = importlib.import_module("tradingresearch.evals")
    except Exception as exc:  # a learner's half-written file: show it, keep going
        notes.append(f"tradingresearch.evals did not import: {type(exc).__name__}: {exc}")
    else:
        if hasattr(evals, "built_theses"):  # lab w2l4's stub adds it
            graders_block(evals)
    for note in notes:
        print("note: " + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
