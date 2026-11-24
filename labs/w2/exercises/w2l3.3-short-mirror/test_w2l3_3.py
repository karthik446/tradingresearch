"""w2l3.3 P4 for a short: the stop beyond the nearest level over the entry, the target at or after the next level
under it, minus 0.5·ATR.

None of the chapter's six theses is short, so these are later real shorts from the journal
(labs/w2/data/theses.json). Each boundary case changes one field of a real thesis, or one level, and says which.
Every case has the same verdict with or without w2l3.4's cents rule.
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


def listed(levels: tuple[Level, ...]) -> str:
    return ", ".join(f"{level.kind} {round(level.price, 5)}" for level in sorted(levels, key=lambda lv: lv.price))


def level(price: float, kind: str = "hvn") -> Level:
    return Level(price=price, kind=kind, strength=1.0, distance_atr=0.0)


def market_open(thesis: Thesis) -> Thesis:
    return thesis.model_copy(update={"entry": thesis.entry.model_copy(update={"kind": "market_open", "price": None})})


def test_unh_swing_short_stop_under_the_nearest_level_fails():
    thesis, levels, atr, close = case("UNH swing, direction short")
    got = p4(thesis, levels, atr, close)
    assert got is False, (
        f"UNH swing is short from a limit entry at {thesis.entry.price}, stop {thesis.stop}. Its levels: "
        f"{listed(levels)}. A short loses when price rises: the nearest level over the entry is hvn 376.09, and the "
        f"stop sits under it, between the entry and the level; p4_levels_coherent returned {got!r}"
    )


def test_msft_day_short_passes():
    thesis, levels, atr, close = case("MSFT day, direction short")
    got = p4(thesis, levels, atr, close)
    assert got is True, (
        f"MSFT day is short from a stop entry at {thesis.entry.price}: stop {thesis.stop} is above low_20 496.51, the "
        f"nearest level over the entry, and target {thesis.target} is above pivot_low 486.0, the next level under it "
        f"(levels: {listed(levels)}, ATR14 {atr:.4f}); p4_levels_coherent returned {got!r}"
    )


def test_the_short_stop_boundary():
    for label, target, stop, want in (("MSFT day, direction short", None, 496.51, False),
                                      ("MSFT day, direction short", None, 496.52, True),
                                      ("UNH swing, direction short", 340.0, 376.10, True),
                                      ("UNH swing, direction short", 340.0, 360.0, False)):
        thesis, levels, atr, close = case(label)
        moved = thesis.model_copy(update={"stop": stop, "target": target or thesis.target})
        got = p4(moved, levels, atr, close)
        assert got is want, (
            f"{label} (entry {thesis.entry.price}, target {moved.target}) with stop {stop} should "
            f"{'pass' if want else 'fail'}: the nearest level over the entry is the lowest of {listed(levels)} above "
            f"{thesis.entry.price}; p4_levels_coherent returned {got!r}"
        )


def test_the_short_target_boundary():
    thesis, levels, atr, close = case("MSFT day, direction short")
    for target, atr14, want in ((486.0, atr, True), (478.05, atr, True), (478.04, atr, False), (486.0, 0.0, True),
                                (485.99, 0.0, False), (485.0, 2.0, True), (484.99, 2.0, False)):
        got = p4(thesis.model_copy(update={"target": target}), levels, atr14, close)
        assert got is want, (
            f"MSFT day (short, entry {thesis.entry.price}, stop {thesis.stop}, next level under the entry pivot_low "
            f"486.0) with target {target} and ATR14 {atr14:.4f} should {'pass' if want else 'fail'}: a short's target "
            f"may run half an ATR past that level, and reaching that exactly passes; p4_levels_coherent returned "
            f"{got!r}"
        )


def test_a_level_at_the_entry_is_neither_side():
    thesis, levels, atr, close = case("UNH swing, direction short")
    moved = thesis.model_copy(update={"stop": 360.0, "target": 340.0})
    got = p4(moved, (*levels, level(thesis.entry.price)), atr, close)
    assert got is False, (
        f"UNH swing (short, entry {thesis.entry.price}, stop 360.0, target 340.0) with one extra level at exactly "
        f"{thesis.entry.price}, the entry. That level is neither over nor under the entry, so the nearest level over "
        f"it is still hvn 376.09 and the stop is under it; p4_levels_coherent returned {got!r}"
    )


def test_a_short_side_with_no_level_holds():
    thesis, levels, atr, close = case("MSFT day, direction short")
    under = tuple(lv for lv in levels if lv.price < thesis.entry.price)
    over = tuple(lv for lv in levels if lv.price > thesis.entry.price)
    for kept, field, value, what in ((under, "stop", 600.0, "only the levels under the entry"),
                                     (over, "target", 400.0, "only the levels over the entry"),
                                     ((), "stop", 600.0, "no levels at all")):
        got = p4(thesis.model_copy(update={field: value}), kept, atr, close)
        assert got is True, (
            f"MSFT day (short, entry {thesis.entry.price}) with its {field} at {value} and {what} "
            f"({listed(kept) or 'none'}): the side without a level holds; p4_levels_coherent returned {got!r}"
        )


def test_a_short_market_open_measures_from_the_close():
    thesis, levels, atr, close = case("MSFT day, direction short")
    opened = market_open(thesis)
    for other, want in ((close, False), (496.0, True)):
        got = p4(opened, levels, atr, other)
        assert got is want, (
            f"MSFT day made market_open (short, stop {thesis.stop}, target {thesis.target}) with reference_close "
            f"{other}: the entry is that close, so the nearest level over it is "
            f"{'hvn 531.76 and the stop is under it' if other == close else 'low_20 496.51 and the stop is over it'}"
            f"; p4_levels_coherent returned {got!r}"
        )


def test_the_long_rules_still_hold():
    for label, want in (("HD swing", False), ("JPM short", True), ("HD day, market_open entry", False)):
        thesis, levels, atr, close = case(label)
        got = p4(thesis, levels, atr, close)
        assert got is want, (
            f"{label} is long (entry {thesis.entry.price or close}, stop {thesis.stop}, target {thesis.target}) and "
            f"should still {'pass' if want else 'fail'} after the short side is written; p4_levels_coherent returned "
            f"{got!r}"
        )


def test_jpm_swing_short_target_past_the_next_level_fails():
    thesis, levels, atr, close = case("JPM swing, direction short")
    got = p4(thesis, levels, atr, close)
    assert got is False, (
        f"JPM swing is short from a limit entry at {thesis.entry.price}, stop {thesis.stop}, target {thesis.target} "
        f"(levels: {listed(levels)}, ATR14 {atr:.4f}). The page's table shows this row failing P4. The next level "
        f"under the entry is the highest one below it: hvn 335.32647 on raw floats, low_20 330.4 at cents (where "
        f"that hvn is the entry). Either way the target runs more than half an ATR ({atr / 2:.2f}) past it; "
        f"pivot_low 325.07, farther down, is not the next level; p4_levels_coherent returned {got!r}"
    )


def test_a_level_at_the_entry_is_not_under_a_short_either():
    thesis, levels, atr, close = case("MSFT day, direction short")
    extra = level(thesis.entry.price)
    got = p4(thesis, (*levels, extra), atr, close)
    assert got is True, (
        f"MSFT day (short, entry {thesis.entry.price}, stop {thesis.stop}, target {thesis.target}, ATR14 {atr:.4f}) "
        f"with one extra level at exactly {thesis.entry.price}, the entry. That level is not under the entry, so the "
        f"next level under it is still pivot_low 486.0 and the target is above it; measured from a level at the "
        f"entry instead, the target would run {thesis.entry.price - thesis.target:.2f} past it, more than half an "
        f"ATR. p4_levels_coherent returned {got!r}"
    )
