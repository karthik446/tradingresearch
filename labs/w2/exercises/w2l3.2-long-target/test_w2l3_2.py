"""w2l3.2 P4 for a long: the target sits at or before the next level over the entry, plus 0.5·ATR.

Theses, levels and ATRs are the author's, from the journal (labs/w2/data/theses.json). The levels are stored as
analyze computed them, unrounded and not sorted. Each boundary case changes one field of a real thesis, or one
level, and says which. AAPL swing's stop moves to 338.69 here (a cent below pivot_low 338.70) so that only the
target decides; every case has the same verdict with or without w2l3.4's cents rule.
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


def aapl(target: float) -> tuple[Thesis, tuple[Level, ...], float, float]:
    thesis, levels, atr, close = case("AAPL swing")
    return thesis.model_copy(update={"stop": 338.69, "target": target}), levels, atr, close


def test_aapl_swing_target_past_the_allowance_fails():
    thesis, levels, atr, close = aapl(366.0)
    got = p4(thesis, levels, atr, close)
    assert got is False, (
        f"AAPL swing is long from a limit entry at {thesis.entry.price} (stop moved to 338.69). With target 366.0: "
        f"the next level over the entry is high_20 360.83 (levels: {listed(levels)}), ATR14 is {atr:.4f}, and the "
        f"target sits {366.0 - 360.83:.2f} past the level, more than half an ATR ({atr / 2:.2f}); "
        f"p4_levels_coherent returned {got!r}"
    )


def test_xom_swing_target_inside_the_allowance_passes():
    thesis, levels, atr, close = case("XOM swing")
    thesis = thesis.model_copy(update={"stop": 160.1})
    got = p4(thesis, levels, atr, close)
    assert got is True, (
        f"XOM swing (long, entry {thesis.entry.price}, stop moved to 160.1) has target {thesis.target}: "
        f"{thesis.target - 168.75:.2f} past hvn 168.75, the next level over the entry, and within half an ATR "
        f"({atr / 2:.2f}, ATR14 {atr:.4f}). A target may run a little past a level; p4_levels_coherent returned {got!r}"
    )


def test_the_allowance_boundary():
    for target, want, why in ((360.83, True, "on high_20"), (350.0, True, "before high_20"),
                              (364.85, True, "inside 360.83 + 4.0228"), (364.86, False, "a cent past 364.8528")):
        thesis, levels, atr, close = aapl(target)
        got = p4(thesis, levels, atr, close)
        assert got is want, (
            f"AAPL swing (long, entry {thesis.entry.price}, stop 338.69, ATR14 {atr:.4f}) with target {target}, "
            f"{why}, should {'pass' if want else 'fail'}; p4_levels_coherent returned {got!r}"
        )


def test_the_atr_scales_the_allowance():
    for target, atr, want in ((362.0, 2.0, False), (361.83, 2.0, True), (360.83, 0.0, True), (360.84, 0.0, False)):
        thesis, levels, _, close = aapl(target)
        got = p4(thesis, levels, atr, close)
        assert got is want, (
            f"AAPL swing (long, entry {thesis.entry.price}, stop 338.69, next level over the entry high_20 360.83) "
            f"with target {target} and ATR14 set to {atr} should {'pass' if want else 'fail'}; the allowance is half "
            f"of whatever ATR is passed in; p4_levels_coherent returned {got!r}"
        )


def test_the_next_level_is_the_lowest_over_the_entry():
    thesis, levels, atr, close = case("JPM short")
    for extra, target in (((), 350.0), ((level(341.0, "pivot_high"),), 346.0)):
        got = p4(thesis.model_copy(update={"target": target}), (*levels, *extra), atr, close)
        assert got is False, (
            f"JPM short (long, entry {thesis.entry.price}, ATR14 {atr:.4f}) with target {target}"
            f"{' and one extra level, pivot_high 341.0, at the end of the stored list' if extra else ''}: the next "
            f"level over the entry is the lowest of {listed((*levels, *extra))} above it, and the target is more than "
            f"half an ATR past it; p4_levels_coherent returned {got!r}"
        )


def test_a_level_at_the_entry_is_not_over_it():
    thesis, levels, atr, close = aapl(360.83)
    got = p4(thesis, (*levels, level(343.41)), atr, close)
    assert got is True, (
        f"AAPL swing (long, entry {thesis.entry.price}, stop 338.69, target 360.83) with one extra level at exactly "
        f"343.41, the entry. A level at the entry is neither under nor over it, so the next level over the entry is "
        f"still high_20 360.83 and the target sits on it; p4_levels_coherent returned {got!r}"
    )


def test_no_level_over_the_entry_leaves_the_target_free():
    thesis, levels, atr, close = case("JPM short")
    under = tuple(lv for lv in levels if lv.price < thesis.entry.price)
    thesis = thesis.model_copy(update={"target": 400.0})
    for kept, what in ((under, f"only the levels under the entry ({listed(under)})"), ((), "no levels at all")):
        got = p4(thesis, kept, atr, close)
        assert got is True, (
            f"JPM short (long, entry {thesis.entry.price}, stop {thesis.stop}) with target 400.0 and {what}: there is "
            f"no level for the target to stop at, so this half holds; p4_levels_coherent returned {got!r}"
        )


def test_the_allowance_is_not_rounded():
    thesis, levels, atr, close = aapl(364.852)
    got = p4(thesis, levels, atr, close)
    assert got is True, (
        f"AAPL swing (long, entry {thesis.entry.price}, stop 338.69, ATR14 {atr:.4f}) with target 364.852 should "
        f"pass: the limit is high_20 360.83 plus half an ATR, {360.83 + atr / 2:.4f} exactly, and 364.852 is inside "
        f"it (364.85 at cents is inside too). Rounding that limit to cents moves it to 364.85 and refuses a target "
        f"the rule allows; p4_levels_coherent returned {got!r}"
    )


def test_any_level_between_the_entry_and_the_close_counts():
    thesis, levels, atr, close = aapl(360.83)
    extra = level(350.0, "pivot_low")
    got = p4(thesis, (*levels, extra), atr, close)
    assert got is False, (
        f"AAPL swing (long, entry {thesis.entry.price}, stop 338.69, target 360.83, ATR14 {atr:.4f}) with one extra "
        f"level, pivot_low 350.0, over the entry and under reference_close {close} (levels: "
        f"{listed((*levels, extra))}), should fail. Levels are measured from the entry, where the trade starts, not "
        f"from the close, and a level's side is set by its price, not its kind: pivot_low 350.0 is the next level "
        f"over the entry, and the target runs {360.83 - 350.0:.2f} past it, more than half an ATR ({atr / 2:.2f}); "
        f"p4_levels_coherent returned {got!r}"
    )


def test_a_level_of_zero_strength_still_counts():
    thesis, levels, atr, close = aapl(360.83)
    extra = Level(price=350.0, kind="hvn", strength=0.0, distance_atr=0.0)
    got = p4(thesis, (*levels, extra), atr, close)
    assert got is False, (
        f"AAPL swing (long, entry {thesis.entry.price}, stop 338.69, target 360.83, ATR14 {atr:.4f}) with one extra "
        f"level, hvn 350.0 of strength 0.0, over the entry. Strength ranks levels for the prompt; P4 reads only "
        f"prices, so hvn 350.0 is the next level over the entry and the target runs {360.83 - 350.0:.2f} past it; "
        f"p4_levels_coherent returned {got!r}"
    )
