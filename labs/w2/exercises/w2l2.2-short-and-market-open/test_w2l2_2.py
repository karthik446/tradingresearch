"""w2l2.2 P3 for a short, and for a market_open entry that has no price yet.

Theses and snapshot closes are the author's, from the journal (labs/w2/data/theses.json): none of the chapter's six
is short or market_open, so these are later real theses. Synthetic rows and boundary cases move one field of a real
thesis and say so.
"""

import json
import os
from pathlib import Path

from tradingresearch.checks import p3_invalidation_testable
from tradingresearch.records import Thesis

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
CHAPTER = ("AAPL swing", "HD swing", "JPM short", "JPM swing", "XOM short", "XOM swing")
SHORTS = ("JPM swing, direction short", "MSFT day, direction short", "UNH swing, direction short")


def case(label: str) -> tuple[Thesis, float]:
    data = json.loads((DATA / "theses.json").read_text())
    row = next(row for row in data["theses"] if row["label"] == label)
    return Thesis.model_validate_json(json.dumps(row["thesis"])), data["analyses"][row["analysis"]]["reference_close"]


def p3(thesis: Thesis, reference_close: float) -> object:
    try:
        return p3_invalidation_testable(thesis, reference_close)
    except Exception as exc:  # show a crash as a result, so the message can say which thesis caused it
        return f"{type(exc).__name__}: {exc}"


def market_open(thesis: Thesis) -> Thesis:
    return thesis.model_copy(update={"entry": thesis.entry.model_copy(update={"kind": "market_open", "price": None})})


def test_msft_day_short_invalidation_below_the_entry_fails():
    thesis, close = case("w2l2.2: MSFT day (direction short) invalidation below the entry")
    got = p3(thesis, close)
    assert got is False, (
        f"MSFT day is short from a stop entry at {thesis.entry.price}, stop {thesis.stop}, target {thesis.target}. "
        f"In this copy its invalidation is {thesis.invalidation_price}: below the entry, which for a short is the "
        f"profit side; p3_invalidation_testable returned {got!r}"
    )


def test_the_real_shorts_pass():
    for label in SHORTS:
        thesis, close = case(label)
        got = p3(thesis, close)
        assert got is True, (
            f"{label}: entry {thesis.entry.price}, stop {thesis.stop} above it, invalidation "
            f"{thesis.invalidation_price}{' (equal to the stop)' if thesis.invalidation_price == thesis.stop else ''}"
            f"; p3_invalidation_testable returned {got!r}. A short loses when price rises, so its invalidation sits "
            f"above the entry, up to the stop."
        )


def test_the_short_boundaries():
    thesis, close = case("MSFT day, direction short")
    for invalidation, want, why in ((500.6, True, "equal to the stop"), (500.61, False, "a cent beyond the stop"),
                                    (496.5, False, "equal to the entry: it would trigger on the fill"),
                                    (496.51, True, "a cent above the entry")):
        got = p3(thesis.model_copy(update={"invalidation_price": invalidation}), close)
        assert got is want, (
            f"MSFT day (short, entry {thesis.entry.price}, stop {thesis.stop}) with invalidation {invalidation}, "
            f"{why}, should {'pass' if want else 'fail'}; p3_invalidation_testable returned {got!r}"
        )


def test_hd_day_market_open_takes_the_close_as_its_entry():
    thesis, close = case("HD day, market_open entry")
    got = p3(thesis, close)
    assert got is True, (
        f"HD day is long with a market_open entry: entry.price is {thesis.entry.price}, because the price is the next "
        f"open. P3 uses the snapshot's last close, {close}, instead: stop {thesis.stop} <= invalidation "
        f"{thesis.invalidation_price} below {close}, so it passes; p3_invalidation_testable returned {got!r}"
    )
    bad, close = case("w2l2.2: HD day (market_open entry) invalidation above the close")
    got = p3(bad, close)
    assert got is False, (
        f"HD day (market_open) with invalidation {bad.invalidation_price}, above the close {close} that stands in "
        f"for its entry, should fail; p3_invalidation_testable returned {got!r}"
    )
    got = p3(thesis, 344.0)
    assert got is False, (
        f"HD day (market_open, stop {thesis.stop}, invalidation {thesis.invalidation_price}) with reference_close "
        f"344.0: the invalidation is now above the entry, so it fails; p3_invalidation_testable returned {got!r}"
    )


def test_a_short_market_open_takes_the_close_too():
    thesis, close = case("MSFT day, direction short")
    opened = market_open(thesis)
    for other, want in ((close, True), (500.7, False)):
        got = p3(opened, other)
        assert got is want, (
            f"MSFT day made market_open (short, stop {thesis.stop}, invalidation {thesis.invalidation_price}) with "
            f"reference_close {other} should {'pass' if want else 'fail'}; p3_invalidation_testable returned {got!r}"
        )


def test_limit_and_stop_entries_ignore_the_close():
    for label in (*SHORTS, *CHAPTER):
        thesis, close = case(label)
        for other in (close * 0.9, close * 1.1):
            got = p3(thesis, other)
            assert got is True, (
                f"{label} has a {thesis.entry.kind} entry at {thesis.entry.price}; with reference_close {other:.2f} "
                f"(the snapshot's was {close}) the answer must not change; p3_invalidation_testable returned {got!r}"
            )
