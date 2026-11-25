"""w5l4.1 the embargo floor. records.py names the floor a TrainingSplit's embargo cannot go under, and why:
SWING_ENTRY_SESSIONS = 2 (a swing thesis enters on one of the two sessions after it is written), MIN_EMBARGO = that
plus the longest hold in HOLD_RANGE (20 sessions), so 22, and EMBARGO_WHY = "entry window 2 + longest hold 20". The
record refuses every embargo under MIN_EMBARGO, negative ones included, with a ValueError saying `embargo_sessions must
be >= 22 (entry window 2 + longest hold 20)`, and accepts any embargo at or above it; the rule that a split is
registered before its cutoff session stays. The floor and its reason follow the longest hold in HOLD_RANGE, whichever
horizon has it: a copy of records.py whose swing hold runs to 45 sessions has MIN_EMBARGO 47, refusing 46 and taking
47, and one whose short hold runs to 60 has MIN_EMBARGO 62.

The dates are real NYSE sessions (tradingresearch.sessions); the cutoff 2026-12-29 is the chapter's example, its
window crossing Thanksgiving and Christmas.
"""

import ast
import sys
import types
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
from gigai_core.records import Prereg
from pydantic import ValidationError

from tradingresearch import records, sessions

HOLDS = [("swing", (5, 45), 47), ("short", (2, 60), 62)]  # (horizon, its hold in a copy of records.py, the floor)

NOW = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)  # after the 2026-10-30 close
CUTOFF = date(2026, 12, 29)
WHY = "entry window 2 + longest hold 20"
PREREG = Prereg(primary_metric="claims_valid", pass_rule="r", margin=0.15, n_planned=40, registered_at=NOW)


def split(embargo: int, registered_at: datetime = NOW, cutoff: date = CUTOFF) -> records.TrainingSplit:
    return records.TrainingSplit(split_id="sp_lab", cutoff_session=cutoff, embargo_sessions=embargo, prereg=PREREG,
                                 registered_at=registered_at)


def leak(embargo: int) -> str:
    """What a shorter embargo lets through, on the chapter's cutoff: the counterexample a FAIL message shows."""
    cal = sessions.xnys()
    last_train = sessions.previous(sessions.recent(embargo, sessions.previous(CUTOFF))[0])
    exit_day = cal.session_offset(cal.session_offset(pd.Timestamp(last_train), 2), 20).date()
    return (f"with an embargo of {embargo} before the cutoff {CUTOFF}, the last train/val session is {last_train}, and "
            f"a swing thesis written after it enters by the 2nd session and exits 20 sessions later, on {exit_day}")


def test_the_floor_is_the_swing_entry_window_plus_the_longest_hold():
    got = tuple(getattr(records, name, None) for name in ("SWING_ENTRY_SESSIONS", "MIN_EMBARGO", "EMBARGO_WHY"))
    assert got == (2, 22, WHY), (
        f"records (SWING_ENTRY_SESSIONS, MIN_EMBARGO, EMBARGO_WHY) are {got}; expected (2, 22, {WHY!r}): "
        f"{leak(21)}, the cutoff itself; {leak(22)}, the session before it")
    assert records.HOLD_RANGE["swing"] == (5, 20), "HOLD_RANGE is thesis rule 3, not this exercise's: leave it as it is"


@pytest.mark.parametrize("embargo", [22, 23, 40, 48, 252])
def test_the_record_accepts_an_embargo_at_or_above_the_floor(embargo):
    try:
        got = split(embargo)
    except ValidationError as exc:
        raise AssertionError(f"TrainingSplit(embargo_sessions={embargo}) was refused: "
                             f"{exc.errors()[0]['msg']}; {leak(22)}, before the cutoff; the floor is a lower bound, a "
                             "longer embargo is a stricter split and is never refused") from None
    assert got.embargo_sessions == embargo


@pytest.mark.parametrize("embargo", [*range(21, -2, -1), -22])
def test_the_record_refuses_an_embargo_under_the_floor_and_says_why(embargo):
    try:
        split(embargo)
    except ValidationError as exc:
        msg = exc.errors()[0]["msg"]
    else:
        raise AssertionError(f"TrainingSplit(embargo_sessions={embargo}) was accepted; {leak(max(embargo, 1))}; the "
                             "floor is a lower bound: every integer under 22 is refused, whatever its sign")
    want = f"embargo_sessions must be >= 22 ({WHY})"
    assert msg.endswith(want), f"TrainingSplit(embargo_sessions={embargo}) was refused with {msg!r}; expected {want!r}"


@pytest.mark.parametrize("registered_at", [datetime(2026, 12, 29, 14, 0, tzinfo=UTC),
                                           datetime(2026, 12, 30, 1, 0, tzinfo=UTC)])
def test_a_split_is_still_registered_before_its_cutoff_session(registered_at):
    try:
        split(22, registered_at)
    except ValidationError as exc:
        msg = exc.errors()[0]["msg"]
    else:
        raise AssertionError(f"TrainingSplit(cutoff_session={CUTOFF}, registered_at={registered_at}) was accepted; "
                             "the record's rule that a split is registered before its cutoff session is "
                             "week-5-start's, and stays")
    assert msg.endswith("a split is registered before its cutoff session"), (
        f"TrainingSplit(cutoff_session={CUTOFF}, registered_at={registered_at}) was refused with {msg!r}; expected "
        f"'a split is registered before its cutoff session'")


def records_with(horizon: str, hold: tuple[int, int]) -> tuple[str, types.ModuleType]:
    """A throwaway copy of records.py whose HOLD_RANGE gives `horizon` the hold `hold`, however the dict is spelled;
    registered in sys.modules so pydantic resolves it. The caller deletes it."""
    tree = ast.parse(Path(records.__file__).read_text(), records.__file__)
    assignment = next((node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                       and any(isinstance(t, ast.Name) and t.id == "HOLD_RANGE"
                               for t in getattr(node, "targets", [getattr(node, "target", None)]))), None)
    assert assignment is not None, "records.py should assign HOLD_RANGE at module level: it is thesis rule 3, leave it"
    assignment.value = ast.copy_location(ast.parse(repr({**records.HOLD_RANGE, horizon: hold}), mode="eval").body,
                                         assignment.value)
    name = f"tradingresearch.records_with_a_{hold[1]}_session_{horizon}_hold"
    copy = types.ModuleType(name)
    copy.__package__ = "tradingresearch"
    sys.modules[name] = copy
    exec(compile(ast.fix_missing_locations(tree), records.__file__, "exec"), copy.__dict__)
    return name, copy


@pytest.mark.parametrize("horizon, hold, floor", HOLDS)
def test_the_floor_and_its_reason_follow_the_longest_hold_in_hold_range(horizon, hold, floor):
    name, copy = records_with(horizon, hold)
    spelled = f'HOLD_RANGE "{horizon}": {hold}'
    try:
        got = (copy.MIN_EMBARGO, copy.EMBARGO_WHY)
        want = (floor, f"entry window 2 + longest hold {hold[1]}")
        assert got == want, (
            f"a copy of records.py with {spelled} has (MIN_EMBARGO, EMBARGO_WHY) = {got}; expected {want}: the floor "
            "is the entry window plus the longest hold in HOLD_RANGE, whichever horizon has it, so it moves when "
            "thesis rule 3 does")
        made = {}
        for embargo in (floor - 1, floor):
            try:
                copy.TrainingSplit(split_id="sp_lab", cutoff_session=CUTOFF, embargo_sessions=embargo, prereg=PREREG,
                                   registered_at=NOW)
                made[embargo] = "accepted"
            except ValidationError:
                made[embargo] = "refused"
        assert made == {floor - 1: "refused", floor: "accepted"}, (
            f"with {spelled}, TrainingSplit embargo {floor - 1} was {made[floor - 1]} and {floor} {made[floor]}; "
            f"expected {floor - 1} refused and {floor} accepted: the record checks against MIN_EMBARGO, not a "
            "written-in 22")
    finally:
        del sys.modules[name]
