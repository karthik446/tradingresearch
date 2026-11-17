"""Reconcile engine (SPIKE §6, §7.1) on synthetic bars: one test per rule row, each docstring names its row."""

import json
from datetime import UTC, date, datetime, time
from pathlib import Path

import pandas as pd
import pytest

from factories import event, thesis
from tradingresearch import reconcile
from tradingresearch.costs import Costs
from tradingresearch.records import RULES_VERSION, EntryRule, Event, Thesis
from tradingresearch.sessions import NY, xnys

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "reconcile" / "bars.json").read_text())
RULES = RULES_VERSION
MIRROR = 200.0  # a short case is its long case with every price p written as 200 - p
D1, D2, D3, D4 = date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19)
BOTH = pytest.mark.parametrize("d", [1, -1], ids=["long", "short"])


def ny(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), NY).astimezone(UTC)


def px(price: float, d: int) -> float:
    return price if d == 1 else MIRROR - price


class Minutes:
    """The `minute_bars_for` callable; records which sessions the engine asked for."""

    def __init__(self, frames: dict[date, pd.DataFrame]):
        self.frames, self.asked = frames, []

    def __call__(self, session: date) -> pd.DataFrame | None:
        self.asked.append(session)
        return self.frames.get(session)


def bars(case: str, d: int = 1, *, until: date | None = None, drop: tuple[date, ...] = ()):
    """The case's daily frame and minute source, mirrored for a short (high and low swap)."""
    spec = FIXTURES[case]

    def ohlc(*prices):
        o, h, low, c = (px(p, d) for p in prices)
        return {"o": o, "h": max(h, low), "l": min(h, low), "c": c}

    daily = pd.DataFrame([
        {"session": date.fromisoformat(r[0]), **ohlc(*r[1:5]), "corporate_action": r[5:] == ["corporate_action"]}
        for r in spec["daily"] if until is None or date.fromisoformat(r[0]) <= until
    ])
    frames = {}
    for day, rows in spec["minutes"].items():
        session = date.fromisoformat(day)
        if session not in drop:
            frames[session] = pd.DataFrame([{"t": ny(session, r[0]), **ohlc(*r[1:5])} for r in rows])
    return daily, Minutes(frames)


def subject(d: int = 1, *, horizon: str = "short", kind: str = "stop", entry: float = 101.0, hold: int | None = None,
            start: datetime | None = None, end: datetime | None = None, day: date = D1) -> Thesis:
    """Long levels stop 98 / target 106 / invalidation 99, mirrored for a short; windows per §6.2."""
    windows = {
        "day": (ny(day, "09:30"), ny(day, "11:30")),
        "short": (ny(day, "09:30"), ny(day, "16:00")),
        "swing": (ny(day, "09:30"), ny(xnys().next_session(pd.Timestamp(day)).date(), "16:00")),
    }
    start = start or windows[horizon][0]
    end = end or windows[horizon][1]
    return thesis(
        "an_test", horizon=horizon, direction="long" if d == 1 else "short",
        entry=EntryRule(kind=kind, price=None if kind == "market_open" else px(entry, d), window_start=start,
                        window_end=end),
        stop=px(98.0, d), target=px(106.0, d), invalidation_price=px(99.0, d),
        hold_sessions=hold if hold is not None else {"day": 0, "short": 3, "swing": 5}[horizon],
    )


def settle(case: str, th: Thesis, d: int = 1, *, recorded: tuple[Event, ...] = (), until: date | None = None,
           drop: tuple[date, ...] = ()) -> tuple[reconcile.Settlement, Minutes]:
    daily, minutes = bars(case, d, until=until, drop=drop)
    events = (event(th.thesis_id, "PROPOSED"), *recorded)
    return reconcile.settle(th, events, daily, minutes, xnys(), RULES), minutes


def steps(result: reconcile.Settlement) -> list[tuple]:
    return [(e.state, e.reason, e.at, e.price) for e in result.events]


# -- §6.3 fill rules (long and short) -----------------------------------------------------------------------------


@BOTH
def test_entry_market_open(d):
    """§6.3 row 'Entry market_open': the first bar of the window, at its open."""
    result, _ = settle("market_open", subject(d, kind="market_open"), d)
    assert steps(result) == [("OPEN", "entry_fill", ny(D1, "09:30"), px(100.5, d))]


@BOTH
def test_entry_stop(d):
    """§6.3 row 'Entry stop': high >= trigger fills at the trigger."""
    result, _ = settle("entry_stop", subject(d), d)
    assert steps(result) == [("OPEN", "entry_fill", ny(D1, "10:00"), px(101.0, d))]


@BOTH
def test_entry_stop_gap(d):
    """§6.3 row 'Entry stop': a gap through the trigger fills at the open."""
    result, _ = settle("entry_stop_gap", subject(d), d)
    assert steps(result) == [("OPEN", "gap_fill", ny(D1, "09:30"), px(101.5, d))]


@BOTH
def test_entry_limit(d):
    """§6.3 row 'Entry limit': low < limit (trades through) fills at the limit."""
    result, _ = settle("entry_limit", subject(d, kind="limit", entry=100.0), d)
    assert steps(result) == [("OPEN", "entry_fill", ny(D1, "10:30"), px(100.0, d))]


@BOTH
def test_entry_limit_touch_is_no_fill(d):
    """§6.3 row 'Entry limit': a touch (low == limit) is no fill; the window ends unfilled."""
    result, minutes = settle("entry_limit_touch", subject(d, kind="limit", entry=100.0), d)
    assert steps(result) == [("EXPIRED", "window_missed", ny(D1, "16:00"), None)]
    assert minutes.asked == []  # the daily bar shows no trade through, so no 1-minute fetch


@BOTH
def test_entry_limit_gap(d):
    """§6.3 row 'Entry limit': min(limit, open), so a gap through the limit fills at the open."""
    result, _ = settle("entry_limit_gap", subject(d, kind="limit", entry=100.0), d)
    assert steps(result) == [("OPEN", "gap_fill", ny(D1, "09:30"), px(99.5, d))]


@BOTH
def test_exit_stop(d):
    """§6.3 row 'Stop': low <= stop exits at the stop."""
    result, _ = settle("exit_stop", subject(d), d)
    assert steps(result)[1] == ("CLOSED", "stop", ny(D2, "09:30"), px(98.0, d))


@BOTH
def test_exit_stop_gap(d):
    """§6.3 row 'Stop': a gap through the stop fills at the open."""
    result, _ = settle("exit_stop_gap", subject(d), d)
    assert steps(result)[1] == ("CLOSED", "stop", ny(D2, "09:30"), px(97.0, d))


@BOTH
def test_exit_target(d):
    """§6.3 row 'Target': high > target exits at the target."""
    result, _ = settle("exit_target", subject(d), d)
    assert steps(result)[1] == ("CLOSED", "target", ny(D2, "09:30"), px(106.0, d))


@BOTH
def test_exit_target_touch_is_no_exit(d):
    """§6.3 row 'Target': a touch (high == target) does not exit; the trade stays OPEN."""
    result, _ = settle("exit_target_touch", subject(d), d)
    assert [s[0] for s in steps(result)] == ["OPEN"]
    assert result.outcome is None


@BOTH
def test_exit_target_gap(d):
    """§6.3 row 'Target': max(target, open), so a gap through the target fills at the open."""
    result, _ = settle("exit_target_gap", subject(d), d)
    assert steps(result)[1] == ("CLOSED", "target", ny(D2, "09:30"), px(107.0, d))


@BOTH
def test_entry_stop_touch_fills(d):
    """§6.3 row 'Entry stop': high >= trigger is inclusive, so a touch (high == 101) fills at the trigger."""
    result, _ = settle("entry_stop_touch", subject(d), d)
    assert steps(result) == [("OPEN", "entry_fill", ny(D1, "11:00"), px(101.0, d))]


@BOTH
def test_exit_stop_touch_exits(d):
    """§6.3 row 'Stop': low <= stop is inclusive, so a touch (low == 98) exits at the stop."""
    result, _ = settle("exit_stop_touch", subject(d), d)
    assert steps(result)[1] == ("CLOSED", "stop", ny(D2, "09:30"), px(98.0, d))


# -- §6.2 time exits and invalidation -----------------------------------------------------------------------------


def test_time_exit_short():
    """§6.2 'Time exit' short: the close of the session hold_sessions (3) after the OPEN session."""
    result, _ = settle("time_exit_short", subject(hold=3))
    assert steps(result)[1] == ("CLOSED", "time_exit", ny(D4, "16:00"), 102.6)  # stamped at the close it is priced at
    assert result.outcome.sessions_held == 3


def test_time_exit_swing_over_holiday():
    """§6.2 'Time exit' swing: 5 sessions counted with XNYS skip Thanksgiving (11-26); exit on the 11-27 early close."""
    day = date(2026, 11, 19)
    result, _ = settle("time_exit_swing_holiday", subject(horizon="swing", hold=5, day=day))
    assert steps(result)[1] == ("CLOSED", "time_exit", ny(date(2026, 11, 27), "13:00"), 102.4)
    assert result.outcome.sessions_held == 5
    assert result.notes == ()  # the holiday has no bar and is not reported missing


def test_time_exit_day():
    """§6.2 'Time exit' day: the 15:54 bar's close; later bars are ignored."""
    result, _ = settle("time_exit_day", subject(horizon="day"))
    assert steps(result)[1] == ("CLOSED", "time_exit", ny(D1, "15:54"), 101.7)
    assert result.outcome.sessions_held == 0


def test_time_exit_day_early_close():
    """§6.1/§6.2: on an early close (13:00, 2026-11-27) the day exit moves to the 12:54 bar."""
    day = date(2026, 11, 27)
    result, _ = settle("time_exit_day_early_close", subject(horizon="day", day=day))
    assert steps(result)[1] == ("CLOSED", "time_exit", ny(day, "12:54"), 101.5)


def test_invalidation_day():
    """§6.2 'Invalidation' day: a 1-minute close beyond it exits at the next 1-minute bar's open."""
    result, _ = settle("invalidation_day", subject(horizon="day"))
    assert steps(result)[1] == ("CLOSED", "invalidated", ny(D1, "10:01"), 98.7)
    assert result.outcome.cost_bps == 8.0


def test_invalidation_short():
    """§6.2 'Invalidation' short/swing: a daily close beyond it exits at the next session's open, stop-exit cost."""
    result, _ = settle("invalidation_short", subject())
    assert steps(result)[1] == ("CLOSED", "invalidated", ny(D3, "09:30"), 98.5)
    assert result.outcome.cost_bps == 8.0


def test_invalidation_stop_takes_precedence():
    """§6.3 'Invalidation exit': the stop hit inside the signal bar wins."""
    result, _ = settle("invalidation_stop_first", subject())
    assert steps(result)[1] == ("CLOSED", "stop", ny(D2, "09:30"), 98.0)


def test_invalidation_time_exit_takes_precedence():
    """§6.3 'Invalidation exit': when the signal bar is the time-exit bar, the time exit applies."""
    result, _ = settle("invalidation_time_exit_first", subject(hold=2))
    assert steps(result)[1] == ("CLOSED", "time_exit", ny(D3, "16:00"), 98.7)
    assert result.outcome.cost_bps == 6.0


def test_invalidation_minute_stop_takes_precedence():
    """§6.3 'Invalidation exit' on the 1-minute path (day): the stop hit inside the signal bar wins."""
    result, _ = settle("minute_invalidation_stop_first", subject(horizon="day"))
    assert steps(result)[1] == ("CLOSED", "stop", ny(D1, "10:00"), 98.0)


def test_invalidation_minute_time_exit_takes_precedence():
    """§6.3 'Invalidation exit' on the 1-minute path (day): a signal on the 15:54 bar is the time exit."""
    result, _ = settle("minute_invalidation_time_exit_first", subject(horizon="day"))
    assert steps(result)[1] == ("CLOSED", "time_exit", ny(D1, "15:54"), 98.8)
    assert result.outcome.cost_bps == 6.0


def test_invalidation_signalled_by_entry_day_close():
    """§6.2 'Invalidation' short/swing: the entry day's own daily close can be the signal bar."""
    result, _ = settle("entry_day_invalidation", subject())
    assert steps(result)[1] == ("CLOSED", "invalidated", ny(D2, "09:30"), 98.6)


# -- §6.4 same-bar rules ------------------------------------------------------------------------------------------


def test_same_bar_rule1_daily_walks_minutes():
    """§6.4 rule 1: stop and target in one daily bar → that session's 1-minute bars decide (target first here)."""
    result, minutes = settle("same_bar_daily", subject())
    assert steps(result)[1] == ("CLOSED", "target", ny(D2, "11:00"), 106.0)
    assert minutes.asked == [D1, D2]  # the entry day and the ambiguous day only


def test_same_bar_rule1_minutes_say_stop_first():
    """§6.4 rule 1: stop and target in one daily bar, and the 1-minute bars reach the stop first → stop."""
    result, _ = settle("same_bar_daily_stop_first", subject())
    assert steps(result)[1] == ("CLOSED", "stop", ny(D2, "10:00"), 98.0)


def test_same_bar_rule2_minute_is_stop():
    """§6.4 rule 2: stop and target in one 1-minute bar → stop."""
    result, _ = settle("same_bar_minute", subject(horizon="day"))
    assert steps(result)[1] == ("CLOSED", "stop", ny(D1, "10:00"), 98.0)


def test_same_bar_rule3_entry_then_stop():
    """§6.4 rule 3: entry and stop in one 1-minute bar → entry, then stop (worst case)."""
    result, _ = settle("same_bar_entry_stop", subject(horizon="day"))
    assert steps(result) == [
        ("OPEN", "entry_fill", ny(D1, "09:45"), 101.0), ("CLOSED", "stop", ny(D1, "09:45"), 98.0),
    ]
    assert result.outcome.r_gross == pytest.approx((98.0 - 101.0) / abs(101.0 - 98.0))  # = -1


def test_same_bar_rule4_entry_then_target_needs_later_bar():
    """§6.4 rule 4: entry and target in one 1-minute bar → entry only; the target fills on a later bar."""
    result, _ = settle("same_bar_entry_target", subject(horizon="day"))
    assert steps(result) == [
        ("OPEN", "entry_fill", ny(D1, "09:45"), 101.0), ("CLOSED", "target", ny(D1, "09:46"), 106.0),
    ]
    # MFE: the entry bar's high is capped at the target (rule 4 puts the target before the entry); exit at 106
    assert result.outcome.mfe_r == pytest.approx((106.0 - 101.0) / abs(101.0 - 98.0))


def test_same_bar_rule5_missing_minutes_is_stop():
    """§6.4 rule 5: no 1-minute bars for an ambiguous daily bar → stop, flagged data_missing."""
    result, _ = settle("same_bar_daily", subject(), drop=(D2,))
    assert steps(result)[1] == ("CLOSED", "data_missing", ny(D2, "09:30"), 98.0)
    assert result.outcome.cost_bps == 8.0
    assert any("2026-11-17" in note for note in result.notes)


# -- §6.5 before entry --------------------------------------------------------------------------------------------


def test_before_entry_stop_cancels():
    """§6.5: the stop reached before the entry triggers → CANCELLED pre_entry_stop."""
    result, minutes = settle("pre_entry_stop", subject())
    assert steps(result) == [("CANCELLED", "pre_entry_stop", ny(D1, "09:30"), None)]
    assert minutes.asked == []


@BOTH
@pytest.mark.parametrize(("case", "kind", "entry"), [
    ("pre_entry_gap_limit_at_stop", "limit", 100.0),
    ("pre_entry_gap_limit_below_stop", "limit", 100.0),
    ("pre_entry_gap_stop_entry", "stop", 101.0),
])
def test_before_entry_open_through_stop_cancels(d, case, kind, entry):
    """§6.5: a window bar that opens at or through the stop reached it before any fill → CANCELLED pre_entry_stop."""
    result, _ = settle(case, subject(d, kind=kind, entry=entry), d)
    assert steps(result) == [("CANCELLED", "pre_entry_stop", ny(D1, "09:30"), None)]
    assert result.outcome is None


def test_before_entry_minute_stop_cancels():
    """§6.5 on the 1-minute path (day): a 1-minute low at the stop before the entry → CANCELLED pre_entry_stop."""
    result, _ = settle("day_pre_entry_stop", subject(horizon="day"))
    assert steps(result) == [("CANCELLED", "pre_entry_stop", ny(D1, "09:45"), None)]


def test_before_entry_minute_invalidation_cancels():
    """§6.5 on the 1-minute path (day): a 1-minute close beyond invalidation before the entry → CANCELLED."""
    result, _ = settle("day_pre_entry_invalidated", subject(horizon="day"))
    assert steps(result) == [("CANCELLED", "invalidated", ny(D1, "09:45"), None)]


def test_before_entry_invalidation_cancels():
    """§6.5: invalidation (a daily close beyond it, short horizon) before the entry → CANCELLED invalidated."""
    result, _ = settle("pre_entry_invalidated", subject())
    assert steps(result) == [("CANCELLED", "invalidated", ny(D1, "09:30"), None)]


def test_before_entry_window_missed_expires():
    """§6.5: the swing window (2 sessions) ends unfilled → EXPIRED window_missed; not before it ends."""
    th = subject(horizon="swing")
    early, _ = settle("window_missed", th, until=D1)
    assert early.events == ()
    result, _ = settle("window_missed", th)
    assert steps(result) == [("EXPIRED", "window_missed", ny(D2, "16:00"), None)]


def test_before_entry_nothing_after_window_end():
    """§6.5: a session opening at or after window_end expires the subject before any pre-entry check reads it."""
    end = ny(D2, "09:00")  # the window ends before the next open; that session would otherwise be pre_entry_stop
    result, minutes = settle("window_end_after_close", subject(end=end))
    assert steps(result) == [("EXPIRED", "window_missed", end, None)]
    assert minutes.asked == []


def test_before_entry_data_missing_cancels():
    """§6.8: PROPOSED → CANCELLED data_missing when the entry day's 1-minute bars are missing."""
    result, _ = settle("entry_stop", subject(), drop=(D1,))
    assert steps(result) == [("CANCELLED", "data_missing", ny(D1, "09:30"), None)]


# -- §6.1 calendar and bars ---------------------------------------------------------------------------------------


def test_corporate_action_cancels_proposed():
    """§6.1 'Corporate actions': a split ex-date in the window → CANCELLED corporate_action."""
    result, _ = settle("corporate_action_proposed", subject())
    assert steps(result) == [("CANCELLED", "corporate_action", ny(D1, "09:30"), None)]


def test_corporate_action_cancels_open():
    """§6.1/§6.8: a split inside the holding period → OPEN → CANCELLED corporate_action, no grade."""
    result, _ = settle("corporate_action_open", subject())
    assert steps(result)[1] == ("CANCELLED", "corporate_action", ny(D2, "09:30"), None)
    assert result.outcome is None


def test_no_look_ahead_minute():
    """§6.1 'No look-ahead': a 09:45 bar that would fill is before window_start 10:00 and is ignored."""
    result, _ = settle("no_look_ahead", subject(start=ny(D1, "10:00")))
    assert steps(result) == [("EXPIRED", "window_missed", ny(D1, "16:00"), None)]


def test_no_look_ahead_daily():
    """§6.1 'No look-ahead': a filling daily bar the session before the window is never read."""
    result, minutes = settle("no_look_ahead_daily", subject(day=D2))
    assert steps(result) == [("EXPIRED", "window_missed", ny(D2, "16:00"), None)]
    assert minutes.asked == []


# -- determinism and idempotence (§6 intro, §6.8) ----------------------------------------------------------------


def test_deterministic():
    """§6 intro: the same bars give the same events, ids included."""
    th = subject()
    first, _ = settle("exit_target", th)
    second, _ = settle("exit_target", th)
    assert first == second
    assert all(e.rules_version == RULES for e in first.events)


def test_refuses_other_rules_version():
    """§6 intro: events carry the rules that made them, so a caller cannot stamp other rules on rules-1 logic."""
    daily, minutes = bars("exit_target")
    with pytest.raises(ValueError, match="rules-2"):
        reconcile.settle(subject(), (), daily, minutes, xnys(), "rules-2")


def test_ids_do_not_depend_on_the_timezone_offset():
    """§6 intro determinism: the same window written with a New York offset gives the same event ids."""
    th = subject(kind="limit", entry=100.0)
    entry = th.entry.model_copy(update={"window_start": th.entry.window_start.astimezone(NY),
                                        "window_end": th.entry.window_end.astimezone(NY)})
    utc, _ = settle("entry_limit_touch", th)
    offset, _ = settle("entry_limit_touch", th.model_copy(update={"entry": entry}))
    assert [e.event_id for e in offset.events] == [e.event_id for e in utc.events]
    assert offset.events[0].at.utcoffset().total_seconds() == 0


def test_idempotent_feedback():
    """§6 intro: feeding back the engine's own events adds nothing and keeps the grade."""
    th = subject()
    first, _ = settle("exit_target", th)
    again, _ = settle("exit_target", th, recorded=first.events)
    assert again.events == ()
    assert again.outcome == first.outcome


def test_incremental_sessions():
    """§6.8: one session per run: OPEN on day 1, then only CLOSED on day 2, never a second OPEN."""
    th = subject()
    day1, _ = settle("exit_target", th, until=D1)
    assert [e.state for e in day1.events] == ["OPEN"]
    day2, _ = settle("exit_target", th, recorded=day1.events)
    assert [e.state for e in day2.events] == ["CLOSED"]


def test_data_revision_keeps_events():
    """§6 intro: bars that no longer match the recorded events → no new events, a data_revision note."""
    th = subject()
    first, _ = settle("exit_target", th, until=D1)
    revised = first.events[0].model_copy(update={"price": 101.5})
    result, _ = settle("exit_target", th, recorded=(revised,))
    assert result.events == ()
    assert result.notes[-1].startswith("data_revision")


# -- §7.1 outcome grade, hand-computed ----------------------------------------------------------------------------


def grade_by_hand(d, entry, stop, exit_, best, worst, bps):
    """§7.1 written out: r_gross = d·(X − E)/|E − S|; cost_r = bps·E/10,000/|E − S|; r_net = r_gross − cost_r."""
    risk = abs(entry - stop)
    r_gross = d * (exit_ - entry) / risk
    cost = bps * entry / 10_000 / risk
    return dict(r_gross=r_gross, cost_r=cost, r_net=r_gross - cost, mfe_r=d * (best - entry) / risk,
                mae_r=d * (worst - entry) / risk)


def check(outcome, expected, **fields):
    for name, value in expected.items():
        assert getattr(outcome, name) == pytest.approx(value), name
    for name, value in fields.items():
        assert getattr(outcome, name) == value, name


def test_grade_long_target():
    """§7.1 trade A: long 101 → target 106, stop 98, 6 bps; best 106 (exit), worst 100.9 (day-1 15:59 low)."""
    result, _ = settle("exit_target", subject())
    check(result.outcome, grade_by_hand(1, 101.0, 98.0, 106.0, 106.0, 100.9, 6.0),
          exit_reason="target", sessions_held=1, cost_bps=6.0, entry_price=101.0, exit_price=106.0)


def test_grade_short_stop_gap():
    """§7.1 trade B: short 99 → stop gapped at 103 (stop 102), 8 bps; best 98.7, worst 103 (the gap fill)."""
    result, _ = settle("exit_stop_gap", subject(-1), -1)
    check(result.outcome, grade_by_hand(-1, 99.0, 102.0, 103.0, MIRROR - 101.3, 103.0, 8.0),
          exit_reason="stop", sessions_held=1, cost_bps=8.0)


def test_grade_long_time_exit():
    """§7.1 trade C: long 101 → time exit 102.6 after 3 sessions, 6 bps; best 103, worst 100 (daily path)."""
    result, _ = settle("time_exit_short", subject(hold=3))
    check(result.outcome, grade_by_hand(1, 101.0, 98.0, 102.6, 103.0, 100.0, 6.0),
          exit_reason="time_exit", sessions_held=3)


def test_grade_short_invalidation():
    """§7.1 trade D: short 99 → invalidated at the next open 101.5 (invalidation 101, stop 102), 8 bps."""
    result, _ = settle("invalidation_short", subject(-1), -1)
    check(result.outcome, grade_by_hand(-1, 99.0, 102.0, MIRROR - 98.5, MIRROR - 101.3, MIRROR - 98.5, 8.0),
          exit_reason="invalidated", sessions_held=2, cost_bps=8.0)


def test_costs_defaults():
    """§6.6: 6.0 bps round trip, 8.0 on a stop or invalidation exit; commission is configurable."""
    assert Costs().round_trip_bps(stop_exit=False) == 6.0
    assert Costs().round_trip_bps(stop_exit=True) == 8.0
    assert Costs(commission_bps=1.0).round_trip_bps(stop_exit=False) == 8.0
