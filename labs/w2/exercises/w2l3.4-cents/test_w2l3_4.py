"""w2l3.4 The cents amendment: P4 compares prices at cents, because levels are stored unrounded and the model quotes
cents.

The data is the author's, from the journal (labs/w2/data/theses.json): analyze stores levels as computed floats
(hvn 343.40978), and the thesis model, shown them rounded, quotes 343.41. On raw floats P4 passes 4 of the
chapter's six theses; at cents it passes 2. Each boundary case changes one field of a real thesis and says which.
"""

import json
import os
from pathlib import Path

from tradingresearch.checks import p4_levels_coherent
from tradingresearch.records import Level, Thesis

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")


def case(label: str) -> tuple[Thesis, tuple[Level, ...], float, float]:
    data = json.loads((DATA / "theses.json").read_text())
    row = next(row for row in data["theses"] if row["label"] == label)
    analysis = data["analyses"][row["analysis"]]
    levels = tuple(Level.model_validate_json(json.dumps(level)) for level in analysis["levels"])
    return Thesis.model_validate_json(json.dumps(row["thesis"])), levels, analysis["atr14"], analysis["reference_close"]


def p4(thesis: Thesis, levels: tuple[Level, ...], atr14: float, close: float) -> object:
    try:
        return p4_levels_coherent(thesis, levels, atr14, close)
    except Exception as exc:  # show a crash as a result, so the message can say which thesis caused it
        return f"{type(exc).__name__}: {exc}"


def market_open(thesis: Thesis) -> Thesis:
    return thesis.model_copy(update={"entry": thesis.entry.model_copy(update={"kind": "market_open", "price": None})})


def test_aapl_swing_at_cents_fails():
    thesis, levels, atr, close = case("AAPL swing")
    got = p4(thesis, levels, atr, close)
    assert got is False, (
        f"AAPL swing is long from a limit entry at {thesis.entry.price}, stop {thesis.stop}. Its level hvn 343.40978 "
        f"is 343.41 at cents: the entry itself, not a level under it. The nearest level under the entry is then "
        f"pivot_low 338.7, and the stop sits exactly on it; p4_levels_coherent returned {got!r}"
    )


CHAPTER = (
    ("AAPL swing", False, "hvn 343.40978 is the entry at cents; the stop 338.7 sits on pivot_low 338.7"),
    ("HD swing", False, "the stop 332.56 is inside hvn 319.08, with or without cents"),
    ("JPM short", True, "stop and target clear their levels, with or without cents"),
    ("JPM swing", True, "hvn 335.11379 is the entry 335.11 at cents, so the target 344.4 is measured from "
                        "pivot_high 344.4"),
    ("XOM short", False, "hvn 163.37702 is the entry 163.38 at cents; the stop 160.11 then sits on low_20 160.1101"),
    ("XOM swing", False, "hvn 163.37702 is the entry 163.38 at cents; the stop 160.11 then sits on low_20 160.1101"),
)


def test_the_chapter_six_at_cents():
    for label, want, why in CHAPTER:
        thesis, levels, atr, close = case(label)
        got = p4(thesis, levels, atr, close)
        assert got is want, (
            f"{label} (long, entry {thesis.entry.price}, stop {thesis.stop}, target {thesis.target}) should "
            f"{'pass' if want else 'fail'} at cents: {why}. The chapter's P4 is 2 of 6; p4_levels_coherent returned "
            f"{got!r}"
        )


def test_every_price_is_compared_at_cents():
    rows = (
        ("stop", 338.699, False, "338.70 at cents, on pivot_low 338.7"),
        ("stop", 338.68, True, "two cents under pivot_low 338.7"),
        ("target", 364.853, True, "364.85 at cents, inside high_20 360.83 + 0.5·ATR (364.8528)"),
    )
    thesis, levels, atr, close = case("AAPL swing")
    for field, value, want, why in rows:
        moved = thesis.model_copy(update={field: value} if field == "stop" else {"stop": 338.69, field: value})
        got = p4(moved, levels, atr, close)
        assert got is want, (
            f"AAPL swing (long, entry {thesis.entry.price}, stop {moved.stop}, target {moved.target}) with its {field} "
            f"at {value}, {why}, should {'pass' if want else 'fail'}; p4_levels_coherent returned {got!r}"
        )


def test_a_market_open_entry_is_compared_at_cents():
    thesis, levels, atr, close = case("AAPL swing")
    opened = market_open(thesis)
    got = p4(opened, levels, atr, 343.4138)
    assert got is False, (
        f"AAPL swing made market_open (long, stop {thesis.stop}, target {thesis.target}) with reference_close "
        f"343.4138: the entry is 343.41 at cents, so hvn 343.40978 is not under it and the stop sits on pivot_low "
        f"338.7; p4_levels_coherent returned {got!r}"
    )


def test_the_allowance_stays_exact():
    thesis, levels, _, close = case("AAPL swing")
    moved = thesis.model_copy(update={"stop": 338.69, "target": 364.86})
    got = p4(moved, levels, 8.052, close)
    assert got is False, (
        f"AAPL swing (long, entry {thesis.entry.price}, stop 338.69, target 364.86) with ATR14 set to 8.052: half an "
        f"ATR is 4.026, so the target may reach 360.83 + 4.026 = 364.856 and 364.86 is past it. Only prices go to "
        f"cents; p4_levels_coherent returned {got!r}"
    )


def test_the_atr_is_not_rounded_either():
    thesis, levels, _, close = case("AAPL swing")
    moved = thesis.model_copy(update={"stop": 338.69, "target": 365.0})
    got = p4(moved, levels, 8.3399, close)
    assert got is False, (
        f"AAPL swing (long, entry {thesis.entry.price}, stop 338.69, target 365.0) with ATR14 set to 8.3399: half an "
        f"ATR is 4.16995, so the target may reach 360.83 + 4.16995 = 364.99995 and 365.0 is past it. The ATR is "
        f"not a price: it stays exact at every digit; p4_levels_coherent returned {got!r}"
    )


def test_a_short_stop_is_compared_at_cents():
    thesis, levels, atr, close = case("MSFT day, direction short")
    got = p4(thesis.model_copy(update={"stop": 496.514}), levels, atr, close)
    assert got is False, (
        f"MSFT day (short, entry {thesis.entry.price}, target {thesis.target}) with its stop moved to 496.514: that "
        f"is 496.51 at cents, on low_20 496.51, the nearest level over the entry, not beyond it. A short's stop goes "
        f"to cents like a long's; p4_levels_coherent returned {got!r}"
    )


def test_a_price_goes_to_its_nearest_cent():
    thesis, levels, atr, close = case("JPM swing")
    got = p4(thesis.model_copy(update={"stop": 332.9949}), levels, atr, close)
    assert got is True, (
        f"JPM swing (long, entry {thesis.entry.price}, target {thesis.target}) with its stop moved to 332.9949: the "
        f"nearest cent is 332.99, a cent under pivot_low 333.0, the nearest level under the entry at cents, so it "
        f"should pass. Each price is rounded once, to its own nearest cent; p4_levels_coherent returned {got!r}"
    )


def test_a_short_is_compared_at_cents_too():
    thesis, levels, atr, close = case("JPM swing, direction short")
    moved = thesis.model_copy(update={"target": 327.0})
    got = p4(moved, levels, atr, close)
    assert got is True, (
        f"JPM swing (short, entry {thesis.entry.price}, stop {thesis.stop}) with target 327.0: hvn 335.32647 is the "
        f"entry 335.33 at cents, so the next level under the entry is low_20 330.4 and the target is within half an "
        f"ATR ({atr / 2:.2f}) of it; p4_levels_coherent returned {got!r}"
    )


def test_a_limit_entry_is_compared_at_cents():
    thesis, levels, atr, close = case("AAPL swing")
    moved = thesis.model_copy(update={"entry": thesis.entry.model_copy(update={"price": 343.414})})
    got = p4(moved, levels, atr, close)
    assert got is False, (
        f"AAPL swing with its limit entry moved to 343.414 (long, stop {thesis.stop}, target {thesis.target}) should "
        f"fail: the entry is 343.41 at cents like every other price, so hvn 343.40978 is the entry, not a level "
        f"under it, and the stop sits on pivot_low 338.7. A limit entry is a quoted price too, not only the close of "
        f"a market_open entry; p4_levels_coherent returned {got!r}"
    )
