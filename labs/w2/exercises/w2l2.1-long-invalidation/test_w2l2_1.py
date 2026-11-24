"""w2l2.1 P3 for a long: the invalidation can be reached before the stop.

Theses and snapshot closes are the author's, from the journal (labs/w2/data/theses.json); every chapter thesis is
long with a limit entry. The synthetic row and the boundary cases move one price of a real thesis and say so.
"""

import json
import os
from pathlib import Path

from tradingresearch.checks import p3_invalidation_testable
from tradingresearch.records import Thesis

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
CHAPTER = ("AAPL swing", "HD swing", "JPM short", "JPM swing", "XOM short", "XOM swing")


def case(label: str) -> tuple[Thesis, float]:
    data = json.loads((DATA / "theses.json").read_text())
    row = next(row for row in data["theses"] if row["label"] == label)
    return Thesis.model_validate_json(json.dumps(row["thesis"])), data["analyses"][row["analysis"]]["reference_close"]


def p3(thesis: Thesis, reference_close: float) -> object:
    try:
        return p3_invalidation_testable(thesis, reference_close)
    except Exception as exc:  # show a crash as a result, so the message can say which thesis caused it
        return f"{type(exc).__name__}: {exc}"


def test_xom_swing_invalidation_above_the_entry_fails():
    thesis, close = case("w2l2.1: XOM swing invalidation above the entry")
    got = p3(thesis, close)
    assert got is False, (
        f"XOM swing is long from a limit entry at {thesis.entry.price}, stop {thesis.stop}, target {thesis.target}. "
        f"In this copy its invalidation is {thesis.invalidation_price}: above the entry, on the profit side, so "
        f"price touching it says nothing about the idea failing before the stop; p3_invalidation_testable returned "
        f"{got!r}"
    )


def test_the_six_chapter_theses_pass():
    for label in CHAPTER:
        thesis, close = case(label)
        got = p3(thesis, close)
        assert got is True, (
            f"{label}: long, entry {thesis.entry.price}, stop {thesis.stop}, invalidation {thesis.invalidation_price}"
            f"{' (equal to the stop: the stop is the invalidation)' if thesis.invalidation_price == thesis.stop else ''}"
            f"; p3_invalidation_testable returned {got!r}. The chapter's table has P3 = 1 on all six."
        )


def test_the_long_boundaries():
    thesis, close = case("AAPL swing")
    for invalidation, want, why in ((338.7, True, "equal to the stop"), (338.69, False, "a cent beyond the stop"),
                                    (343.41, False, "equal to the entry: it would trigger on the fill"),
                                    (343.40, True, "a cent below the entry"), (341.0, True, "between stop and entry"),
                                    (338.699, False, "a tenth of a cent beyond the stop (P3 compares prices as "
                                     "written; no rule here rounds them)"),
                                    (338.6995, False, "half a tenth of a cent beyond the stop")):
        got = p3(thesis.model_copy(update={"invalidation_price": invalidation}), close)
        assert got is want, (
            f"AAPL swing (long, entry {thesis.entry.price}, stop {thesis.stop}) with invalidation {invalidation}, "
            f"{why}, should {'pass' if want else 'fail'}; p3_invalidation_testable returned {got!r}"
        )


def test_a_limit_entry_ignores_the_close():
    thesis, close = case("AAPL swing")
    beyond = thesis.model_copy(update={"invalidation_price": 344.0})
    for other in (330.0, close, 400.0):
        got = p3(thesis, other)
        assert got is True, (
            f"AAPL swing has a limit entry at {thesis.entry.price}; with reference_close {other} (the snapshot's was "
            f"{close}) the answer must not change; p3_invalidation_testable returned {got!r}"
        )
        got = p3(beyond, other)
        assert got is False, (
            f"AAPL swing with invalidation 344.0, above its limit entry {thesis.entry.price}, fails whatever the "
            f"close; with reference_close {other} p3_invalidation_testable returned {got!r}"
        )
