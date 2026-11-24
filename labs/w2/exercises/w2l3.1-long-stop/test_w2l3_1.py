"""w2l3.1 P4 for a long: the stop sits beyond the nearest level under the entry.

Theses, levels and ATRs are the author's, from the journal (labs/w2/data/theses.json). The levels are stored as
analyze computed them, unrounded and not sorted. Each boundary case changes one field of a real thesis, or one
level, and says which. Every case here has the same verdict with or without w2l3.4's cents rule.
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


def test_hd_swing_stop_above_the_nearest_level_fails():
    thesis, levels, atr, close = case("HD swing")
    got = p4(thesis, levels, atr, close)
    assert got is False, (
        f"HD swing is long from a limit entry at {thesis.entry.price}, stop {thesis.stop}. Its levels: "
        f"{listed(levels)}. The nearest one under the entry is hvn 319.08, and the stop sits above it, between the "
        f"level and the entry, where ordinary noise can reach it; p4_levels_coherent returned {got!r}"
    )


def test_a_stop_below_the_nearest_level_passes():
    for label, stop in (("JPM short", None), ("JPM short", 335.10), ("AAPL swing", 338.69)):
        thesis, levels, atr, close = case(label)
        if stop is not None:
            thesis = thesis.model_copy(update={"stop": stop})
        got = p4(thesis, levels, atr, close)
        assert got is True, (
            f"{label} (long, entry {thesis.entry.price}){' with its stop moved to ' + str(stop) if stop else ''}: "
            f"stop {thesis.stop} sits below the nearest level under the entry (levels: {listed(levels)}), so the "
            f"stop half holds; p4_levels_coherent returned {got!r}"
        )


def test_a_stop_on_the_level_fails():
    thesis, levels, atr, close = case("JPM swing")
    for stop, why in ((333.0, "exactly on pivot_low 333.0"), (333.5, "half a dollar above pivot_low 333.0")):
        got = p4(thesis.model_copy(update={"stop": stop}), levels, atr, close)
        assert got is False, (
            f"JPM swing (long, entry {thesis.entry.price}) with stop {stop}, {why}, the nearest level under the entry "
            f"(levels: {listed(levels)}). A stop on the level is taken by a retest of it; p4_levels_coherent "
            f"returned {got!r}"
        )


def test_the_nearest_level_is_the_highest_under_the_entry():
    thesis, levels, atr, close = case("HD swing")
    for stop, want in ((315.0, True), (310.0, True), (319.08, False), (325.0, False)):
        got = p4(thesis.model_copy(update={"stop": stop}), levels, atr, close)
        assert got is want, (
            f"HD swing (long, entry {thesis.entry.price}) with stop {stop} should {'pass' if want else 'fail'}: the "
            f"nearest level under the entry is hvn 319.08, the highest of {listed(levels)} below it, whatever order the "
            f"levels are stored in; p4_levels_coherent returned {got!r}"
        )


def test_a_level_at_the_entry_is_not_under_it():
    thesis, levels, atr, close = case("JPM short")
    moved = thesis.model_copy(update={"stop": 335.5})
    got = p4(moved, (*levels, level(thesis.entry.price)), atr, close)
    assert got is False, (
        f"JPM short (long, entry {thesis.entry.price}) with stop 335.5, above hvn 335.11, and one extra level at "
        f"exactly {thesis.entry.price}, the entry. A level at the entry is neither under nor over it, so the nearest "
        f"level under the entry is still hvn 335.11 and the stop is inside it; p4_levels_coherent returned {got!r}"
    )


def test_two_levels_at_one_price():
    thesis, levels, atr, close = case("JPM short")
    over = tuple(lv for lv in levels if lv.price > thesis.entry.price)
    pair = (level(330.4, "low_20"), level(330.4, "pivot_low"))
    for stop, want in ((330.4, False), (330.39, True)):
        got = p4(thesis.model_copy(update={"stop": stop}), (*pair, *over), atr, close)
        assert got is want, (
            f"JPM short (long, entry {thesis.entry.price}) with only low_20 330.4 and pivot_low 330.4 under the entry "
            f"(the real pair, without hvn 335.11 and pivot_low 333.0): stop {stop} should "
            f"{'pass' if want else 'fail'}; p4_levels_coherent returned {got!r}"
        )


def test_no_level_under_the_entry_leaves_the_stop_free():
    thesis, levels, atr, close = case("JPM short")
    over = tuple(lv for lv in levels if lv.price > thesis.entry.price)
    for kept, what in ((over, f"only the levels over the entry ({listed(over)})"), ((), "no levels at all")):
        got = p4(thesis, kept, atr, close)
        assert got is True, (
            f"JPM short (long, entry {thesis.entry.price}, stop {thesis.stop}, target {thesis.target}) with {what}: "
            f"there is no level for the stop to sit beyond, so this half holds; p4_levels_coherent returned {got!r}"
        )
