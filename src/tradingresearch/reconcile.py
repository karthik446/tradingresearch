"""Settle a thesis from bars: fills, exits, same-bar order, state machine and outcome grade (SPIKE §6, §7.1).

Pure: no journal, no network, no model. The engine replays the subject's whole path from `entry.window_start` on
every call, so the same bars always give the same events; the caller (G4c) appends the events it returns.

Bars: `daily_bars` has a `session` (date) column and o/h/l/c, raw prices, completed sessions only (its last session
is the data horizon). An optional boolean `corporate_action` column marks a split or spin-off ex-date (§6.1).
`minute_bars_for(session)` returns that session's 1-minute bars (`t` = bar start, UTC, and o/h/l/c) or None.

Shorts are settled as longs on negated prices: -price turns every short rule of §6.3 into the long rule.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import exchange_calendars as xcals
import pandas as pd
from gigai_core import CoreModel

from .costs import Costs, cost_r
from .hashing import digest
from .records import Event, EventReason, OutcomeGrade, State, Thesis
from .sessions import NY

MinuteBars = Callable[[date], pd.DataFrame | None]

DAY_EXIT_BAR = timedelta(minutes=6)  # the 15:54 bar starts 6 minutes before the (scheduled, maybe early) close
STOP_EXITS = {"stop", "invalidated", "data_missing"}  # charged the extra stop-exit slippage (§6.6)
NOT_ENGINE = {"written", "graded"}  # reasons written by `tr thesis` and `tr grade`, not by reconcile


class Settlement(CoreModel):
    events: tuple[Event, ...]
    outcome: OutcomeGrade | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Bar:
    """One bar in long space (prices multiplied by the direction sign); a daily bar starts at the session open."""

    t: datetime
    o: float
    h: float
    l: float  # noqa: E741
    c: float

    @classmethod
    def of(cls, t: datetime, o: float, h: float, l: float, c: float, d: int) -> Bar:  # noqa: E741
        return cls(t, d * o, d * h, d * l, d * c) if d == 1 else cls(t, d * o, d * l, d * h, d * c)


@dataclass(frozen=True)
class Transition:
    state: State
    reason: EventReason
    at: datetime
    price: float | None  # real (not long-space) price; None when nothing filled


def settle(
    subject: Thesis,
    events: tuple[Event, ...],
    daily_bars: pd.DataFrame,
    minute_bars_for: MinuteBars,
    calendar: xcals.ExchangeCalendar,
    rules_version: str,
    costs: Costs = Costs(),
) -> Settlement:
    """New events for `subject` (its recorded events are a prefix of the replay) and the grade once CLOSED."""
    path = _Path(subject, daily_bars, minute_bars_for, calendar)
    path.run()
    replay = [_event(subject.thesis_id, step, rules_version) for step in path.steps]
    recorded = [event for event in events if event.reason not in NOT_ENGINE]
    notes = list(path.notes)
    common = min(len(recorded), len(replay))
    if [_key(event) for event in recorded[:common]] != [_key(event) for event in replay[:common]]:
        notes.append(f"data_revision: bars no longer give the recorded events of {subject.thesis_id}; kept as is")
        return Settlement(events=(), outcome=None, notes=tuple(notes))
    outcome = path.outcome(costs) if len(replay) >= len(recorded) and path.state == "CLOSED" else None
    return Settlement(events=tuple(replay[common:]), outcome=outcome, notes=tuple(notes))


def _key(event: Event) -> tuple:
    return event.state, event.reason, event.at, event.price


def _event(subject_id: str, step: Transition, rules_version: str) -> Event:
    """Ids come from the content, so a replay rebuilds the same event; G4c stamps `recorded_at` and the bars source."""
    identity = {"subject": subject_id, "state": step.state, "reason": step.reason, "at": step.at.isoformat(),
                "price": step.price}
    return Event(
        event_id="ev_" + digest(identity).removeprefix("sha256:")[:16], subject_id=subject_id, state=step.state,
        at=step.at, recorded_at=step.at, price=step.price, reason=step.reason, bars_source_id=None,
        rules_version=rules_version,
    )


def _utc(value: object) -> datetime:
    stamp = pd.Timestamp(value)
    return (stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")).to_pydatetime()


class _Path:
    """The walk over sessions and bars for one subject; `steps` collects its transitions in order."""

    def __init__(self, subject: Thesis, daily: pd.DataFrame, minutes: MinuteBars, calendar: xcals.ExchangeCalendar):
        self.s = subject
        self.d = 1 if subject.direction == "long" else -1
        self.cal = calendar
        self.daily = {row["session"]: row for row in daily.to_dict("records")}
        self.minutes_for = minutes
        self.entry = None if subject.entry.price is None else self.d * subject.entry.price
        self.stop = self.d * subject.stop
        self.target = self.d * subject.target
        self.invalid = self.d * subject.invalidation_price
        self.state: State = "PROPOSED"
        self.steps: list[Transition] = []
        self.notes: list[str] = []
        self.seen_window_bar = False
        self.pending_invalidation = False
        self.fill = self.exit = self.lo = self.hi = 0.0
        self.exit_reason: EventReason = "stop"
        self.open_session = self.exit_session = self.close_session = date.min

    # -- driver ---------------------------------------------------------------------------------------------------

    def run(self) -> None:
        if not self.daily:
            self.notes.append("no daily bars yet")
            return
        start = self.s.entry.window_start.astimezone(NY).date()
        end = max(self.daily)
        if end < start:
            return
        for ts in self.cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end)):
            session = ts.date()
            opens, closes = (_utc(x) for x in (self.cal.session_open(ts), self.cal.session_close(ts)))
            if closes <= self.s.entry.window_start:
                continue
            row = self.daily.get(session)
            if row is None:
                self.notes.append(f"no daily bar for {session}; settling waits there")
                return
            flag = row.get("corporate_action")
            if flag is not None and pd.notna(flag) and flag:
                self._step("CANCELLED", "corporate_action", max(opens, self.s.entry.window_start), None)
                return
            bar = Bar.of(opens, row["o"], row["h"], row["l"], row["c"], self.d)
            if self.state == "PROPOSED":
                self._before_entry(session, bar, closes)
                if self.state == "PROPOSED" and self.s.entry.window_end <= closes:
                    self._step("EXPIRED", "window_missed", self.s.entry.window_end, None)
            elif self.state == "OPEN":
                self._daily_open(session, bar)
            if self.state not in ("PROPOSED", "OPEN"):
                return

    def _step(self, state: State, reason: EventReason, at: datetime, price: float | None) -> None:
        self.state = state
        self.steps.append(Transition(state, reason, at, None if price is None else self.d * price))

    # -- before entry (§6.3 entries, §6.5) ------------------------------------------------------------------------

    def _before_entry(self, session: date, daily: Bar, closes: datetime) -> None:
        """Daily bar first; 1-minute bars only when the entry could trigger, for day trades, or a partial session."""
        partial = daily.t < self.s.entry.window_start
        if self.s.horizon != "day" and not partial and not self._could_enter(daily):
            if daily.l <= self.stop:
                self._step("CANCELLED", "pre_entry_stop", daily.t, None)
            elif daily.c < self.invalid:
                self._step("CANCELLED", "invalidated", daily.t, None)
            return
        bars = self._minutes(session)
        if bars is None:
            self._step("CANCELLED", "data_missing", max(daily.t, self.s.entry.window_start), None)
            return
        self._walk_minutes(session, bars, closes)
        if self.s.horizon != "day" and self.state in ("PROPOSED", "OPEN") and daily.c < self.invalid:
            if self.state == "PROPOSED":
                self._step("CANCELLED", "invalidated", daily.t, None)
            else:
                self.pending_invalidation = True  # the entry day's close is the signal bar (§6.2)

    def _could_enter(self, bar: Bar) -> bool:
        kind = self.s.entry.kind
        if kind == "market_open":
            return not self.seen_window_bar
        return bar.h >= self.entry if kind == "stop" else bar.l < self.entry

    def _entry_fill(self, bar: Bar) -> tuple[float, EventReason] | None:
        """§6.3: market_open at the first window bar's open; stop at max(trigger, open); limit at min(limit, open)."""
        kind = self.s.entry.kind
        first, self.seen_window_bar = not self.seen_window_bar, True
        if kind == "market_open":
            return (bar.o, "entry_fill") if first else None
        if kind == "stop" and bar.h >= self.entry:
            return (bar.o, "gap_fill") if bar.o > self.entry else (self.entry, "entry_fill")
        if kind == "limit" and bar.l < self.entry:
            return (bar.o, "gap_fill") if bar.o < self.entry else (self.entry, "entry_fill")
        return None

    # -- the 1-minute walk (§6.2 day path, §6.4 rules 2-4) --------------------------------------------------------

    def _walk_minutes(self, session: date, bars: list[Bar], closes: datetime) -> None:
        day = self.s.horizon == "day"
        cutoff = closes - DAY_EXIT_BAR
        last = max((i for i, bar in enumerate(bars) if bar.t <= cutoff), default=-1) if day else -1
        for i, bar in enumerate(bars):
            if day and i > last:
                break
            if self.state == "PROPOSED":
                if bar.t >= self.s.entry.window_end:
                    return
                self._minute_before_entry(session, bar, day)
                if self.state == "OPEN" and day and i == last:
                    self._close("time_exit", bar.c, bar.t)
            elif self.state == "OPEN":
                self._minute_open(bar, time_exit=day and i == last, signal=day)
            else:
                return

    def _minute_before_entry(self, session: date, bar: Bar, day: bool) -> None:
        fill = self._entry_fill(bar)
        if fill is None:
            if bar.l <= self.stop:
                self._step("CANCELLED", "pre_entry_stop", bar.t, None)
            elif day and bar.c < self.invalid:
                self._step("CANCELLED", "invalidated", bar.t, None)
            return
        price, reason = fill
        self._open(session, bar.t, price, reason)
        kind = self.s.entry.kind
        if bar.l <= self.stop:  # rule 3: entry, then stop, worst case; rule 4: no target on the entry bar
            self._close("stop", min(self.stop, bar.o), bar.t, hi=bar.h if kind != "limit" else price)
            return
        self._extend(price if kind == "stop" else bar.l, price if kind == "limit" else bar.h)
        if day and bar.c < self.invalid:
            self.pending_invalidation = True

    def _minute_open(self, bar: Bar, *, time_exit: bool, signal: bool) -> None:
        """One 1-minute bar while OPEN: pending invalidation, then stop before target (rule 2), then the time exit."""
        if self.pending_invalidation:
            self._close("invalidated", bar.o, bar.t, lo=bar.o, hi=bar.o)
            return
        hit = self._stop_or_target(bar)
        if hit in ("stop", "both"):
            self._close("stop", min(self.stop, bar.o), bar.t, hi=bar.h)
        elif hit == "target":
            self._close("target", max(self.target, bar.o), bar.t, lo=bar.l)
        else:
            self._extend(bar.l, bar.h)
            if time_exit:
                self._close("time_exit", bar.c, bar.t)
            elif signal and bar.c < self.invalid:
                self.pending_invalidation = True

    # -- daily path while OPEN (short and swing; §6.2, §6.4 rules 1 and 5) ----------------------------------------

    def _daily_open(self, session: date, bar: Bar) -> None:
        if self.pending_invalidation:
            self._close("invalidated", bar.o, bar.t, lo=bar.o, hi=bar.o)
            return
        hit = self._stop_or_target(bar)
        if hit == "both":
            self._ambiguous_day(session, bar)
        elif hit == "stop":
            self._close("stop", min(self.stop, bar.o), bar.t, hi=bar.h)
        elif hit == "target":
            self._close("target", max(self.target, bar.o), bar.t, lo=bar.l)
        else:
            self._extend(bar.l, bar.h)
            if session == self.exit_session:
                self._close("time_exit", bar.c, bar.t)
            elif bar.c < self.invalid:
                self.pending_invalidation = True

    def _ambiguous_day(self, session: date, bar: Bar) -> None:
        """Rule 1: walk that session's minutes; rule 5: no minutes (or none that settle it) → stop, data_missing."""
        bars = self._minutes(session)
        for minute in bars or []:
            self._minute_open(minute, time_exit=False, signal=False)
            if self.state != "OPEN":
                return
        self.notes.append(f"{session}: stop and target in one daily bar and no 1-minute bars settle it; stop")
        self._close("data_missing", min(self.stop, bar.o), bar.t, hi=bar.h)

    def _stop_or_target(self, bar: Bar) -> str | None:
        """A gap through a level settles at the open; otherwise stop on low <= stop, target on high > target."""
        if bar.o <= self.stop:
            return "stop"
        if bar.o > self.target:
            return "target"
        stop, target = bar.l <= self.stop, bar.h > self.target
        return "both" if stop and target else "stop" if stop else "target" if target else None

    # -- bookkeeping ----------------------------------------------------------------------------------------------

    def _minutes(self, session: date) -> list[Bar] | None:
        frame = self.minutes_for(session)
        if frame is None or frame.empty:
            self.notes.append(f"{session}: no 1-minute bars")
            return None
        bars = [Bar.of(_utc(r["t"]), r["o"], r["h"], r["l"], r["c"], self.d) for r in frame.to_dict("records")]
        return sorted((bar for bar in bars if bar.t >= self.s.entry.window_start), key=lambda bar: bar.t)

    def _open(self, session: date, at: datetime, price: float, reason: EventReason) -> None:
        self._step("OPEN", reason, at, price)
        self.fill = self.lo = self.hi = price
        self.open_session = session
        offset = self.cal.session_offset(pd.Timestamp(session), self.s.hold_sessions)
        self.exit_session = offset.date()

    def _close(self, reason: EventReason, price: float, at: datetime, *, lo: float | None = None,
               hi: float | None = None) -> None:
        """Exit at `price`; the exit bar counts toward MFE/MAE only up to the exit (lo/hi clip the side after it)."""
        self._step("CLOSED", reason, at, price)
        self.exit, self.exit_reason = price, reason
        self.close_session = at.astimezone(NY).date()
        if reason == "stop" or reason == "data_missing":
            lo = price
        elif reason == "target":
            hi = price
        self._extend(price if lo is None else lo, price if hi is None else hi)

    def _extend(self, lo: float, hi: float) -> None:
        self.lo, self.hi = min(self.lo, lo), max(self.hi, hi)

    def outcome(self, costs: Costs) -> OutcomeGrade:
        """§7.1 in long space: d·(X − E) is X' − E' once prices are multiplied by d."""
        entry, stop, risk = self.d * self.fill, self.s.stop, abs(self.fill - self.stop)
        cost_bps = costs.round_trip_bps(stop_exit=self.exit_reason in STOP_EXITS)
        r_gross = (self.exit - self.fill) / risk
        charge = cost_r(cost_bps, entry, stop)
        held = int(self.cal.sessions_distance(pd.Timestamp(self.open_session), pd.Timestamp(self.close_session))) - 1
        return OutcomeGrade(
            subject_id=self.s.thesis_id, entry_price=entry, exit_price=self.d * self.exit, r_gross=r_gross,
            cost_bps=cost_bps, cost_r=charge, r_net=r_gross - charge, mfe_r=(self.hi - self.fill) / risk,
            mae_r=(self.lo - self.fill) / risk, exit_reason=self.exit_reason, sessions_held=held,
        )
