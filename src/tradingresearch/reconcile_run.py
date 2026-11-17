"""`tr reconcile` around the pure engine (SPIKE §6 intro, §6.1, §6.8): raw SIP bars in, `reconcile.settle` for every
PROPOSED or OPEN thesis, its events (and a teacher thesis's TeacherOutcome) appended to the journal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

import httpx
import pandas as pd

from . import alpaca, journal, reconcile, sessions
from .analyze import plain
from .hashing import digest
from .records import RULES_VERSION, Analysis, Event, OutcomeGrade, SourceRef, TeacherOutcome, Thesis

ADJUSTMENT = "raw"  # §6.1: prices as traded, so stop and target compare with the levels the thesis wrote
PRICES = ["session", "o", "h", "l", "c"]  # what settle reads from a daily bar, and what its SourceRef hashes
CORPORATE_ACTIONS_URL = f"{alpaca.DATA_HOST}/v1/corporate-actions"
TERMINAL = ("CLOSED", "CANCELLED", "EXPIRED")


class BarSource(Protocol):
    """Raw bars for reconcile: Alpaca live, the synthetic fixtures in tests."""

    feed: str

    def daily(self, ticker: str, start: date, end: date) -> pd.DataFrame: ...

    def corporate_action_days(self, ticker: str, start: date, end: date) -> set[date]: ...

    def minutes(self, ticker: str, session: date) -> pd.DataFrame | None: ...


class AlpacaBars:
    """Raw SIP daily bars, split and spin-off ex-dates from Alpaca's corporate-actions endpoint, cached raw minutes."""

    def __init__(self, http: httpx.Client, cache_dir: Path, feed: str) -> None:
        self.http, self.cache_dir, self.feed = http, cache_dir, feed

    def daily(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        frame = alpaca.daily_bars(self.http, [ticker], start, end, feed=self.feed, adjustment=ADJUSTMENT)
        return frame.drop(columns="ticker").reset_index(drop=True)

    def corporate_action_days(self, ticker: str, start: date, end: date) -> set[date]:
        """Ex-dates where raw prices jump for `ticker`: its splits, and spin-offs it is the source of (§6.1)."""
        params = {"symbols": ticker, "types": "forward_split,reverse_split,spin_off", "start": start.isoformat(),
                  "end": end.isoformat(), "limit": "1000"}
        days: set[date] = set()
        while True:
            page = alpaca.get_json(self.http, CORPORATE_ACTIONS_URL, params)
            found = page.get("corporate_actions") or {}
            splits = [*found.get("forward_splits", ()), *found.get("reverse_splits", ())]
            days |= {date.fromisoformat(a["ex_date"]) for a in splits if a.get("symbol") == ticker}
            days |= {date.fromisoformat(a["ex_date"]) for a in found.get("spin_offs", ())
                     if a.get("source_symbol") == ticker}
            token = page.get("next_page_token")
            if not token:
                return days
            params["page_token"] = token

    def minutes(self, ticker: str, session: date) -> pd.DataFrame:
        return alpaca.minute_bars(self.http, self.cache_dir, ticker, session, feed=self.feed, adjustment=ADJUSTMENT)


@dataclass(frozen=True)
class Settled:
    """One subject after a run: its state before, the events appended (or that a dry run would append), notes."""

    thesis: Thesis
    before: str
    events: tuple[Event, ...]
    teacher_outcome: TeacherOutcome | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Report:
    session: date
    settled: tuple[Settled, ...]
    shadows: tuple[str, ...]
    dry_run: bool


def run(conn, bars: BarSource, session: date, *, dry_run: bool = False, now: datetime | None = None) -> Report:
    """Settle every PROPOSED or OPEN thesis up to `session` (a completed session); shadows are listed, not settled."""
    now = now or datetime.now(UTC)
    settled = tuple(settle_one(conn, bars, t, state, session, now, dry_run) for t, state in journal.open_theses(conn))
    return Report(session, settled, tuple(journal.open_shadow_ids(conn)), dry_run)


def settle_one(conn, bars: BarSource, t: Thesis, state: str, session: date, now: datetime, dry_run: bool) -> Settled:
    """Bars from the first event to `session`, one `settle` call, then the stamped events in one transaction."""
    if t.rules_version != RULES_VERSION:
        return Settled(t, state, (), None, (f"skipped: written under {t.rules_version}, this engine is {RULES_VERSION}",))
    window_day = t.entry.window_start.astimezone(sessions.NY).date()
    if session < window_day:
        return Settled(t, state, (), None, (f"waiting: the entry window opens on {window_day}",))
    recorded = journal.events_for(conn, t.thesis_id)
    first = min((recorded[0].at if recorded else t.created_at).astimezone(sessions.NY).date(), window_day)
    daily = bars.daily(t.ticker, first, session)
    if daily.empty:
        return Settled(t, state, (), None, (f"no {bars.feed} daily bars for {first}..{session}",))
    prices = daily[PRICES].reset_index(drop=True)
    source = alpaca.bars_source(prices, ticker=t.ticker, feed=bars.feed, adjustment=ADJUSTMENT)
    flagged = sorted(bars.corporate_action_days(t.ticker, first, session))
    frame = prices.assign(corporate_action=prices["session"].isin(flagged))
    result = reconcile.settle(t, recorded, frame, lambda day: bars.minutes(t.ticker, day), sessions.xnys(),
                              RULES_VERSION)
    events = tuple(e.model_copy(update={"recorded_at": now, "bars_source_id": source.source_id})
                   for e in result.events)
    outcome = None
    if t.arm == "teacher" and events and events[-1].state in TERMINAL:
        from .grade import code_checks  # local import: grade imports this module

        checks = code_checks(t, journal.get(conn, Analysis, t.analysis_id))
        outcome = teacher_outcome(t, events[-1], result.outcome, checks)
    if events and not dry_run:
        journal.add_settlement(conn, list(events), [source], outcome)
    notes = (*revision_notes(conn, recorded, prices, t.ticker, bars.feed), *result.notes)
    return Settled(t, state, events, outcome, notes)


def teacher_outcome(t: Thesis, last: Event, outcome: OutcomeGrade | None, checks: dict[str, bool]) -> TeacherOutcome:
    """The one row a teacher thesis gets when it ends (SPIKE §1.1): no grade, no judge, no shadow; `checks` are its
    P2-P4 (`grade.code_checks`). The id comes from the thesis, so a second write is a duplicate-id error."""
    return TeacherOutcome(
        teacher_outcome_id="to_" + digest({"thesis": t.thesis_id}).removeprefix("sha256:")[:16],
        thesis_id=t.thesis_id, final_state=last.state, outcome=outcome if last.state == "CLOSED" else None,
        code_checks=checks, outcome_score_id=None, rules_version=RULES_VERSION, settled_at=last.at,
    )


def revision_notes(conn, recorded: tuple[Event, ...], prices: pd.DataFrame, ticker: str, feed: str) -> list[str]:
    """§6 intro: re-fetched bars over the range a recorded event cites must hash to the cited SourceRef; if not, a
    `data_revision` note (run output only) and the events stay as they are."""
    notes = []
    last_session = prices["session"].iloc[-1]
    for source_id in dict.fromkeys(e.bars_source_id for e in recorded if e.bars_source_id):
        cited = journal.get(conn, SourceRef, source_id)
        query = parse_qs(urlsplit(cited.uri).query)
        start, end = (date.fromisoformat(query[key][0]) for key in ("start", "end"))
        if end > last_session:
            continue  # an earlier --session than the events: nothing to compare
        again = prices[(prices["session"] >= start) & (prices["session"] <= end)]
        if again.empty or alpaca.bars_source(again, ticker=ticker, feed=feed,
                                             adjustment=ADJUSTMENT).content_sha256 != cited.content_sha256:
            notes.append(f"data_revision: re-fetched {ticker} bars {start}..{end} differ from {source_id}, which "
                         "recorded events cite; the events are kept as they are")
    return notes


def render(report: Report) -> list[str]:
    """One line per subject (`ticker horizon state→state reason price`), its notes, then the totals."""
    if not report.settled and not report.shadows:
        return ["nothing to settle"]
    lines = []
    for s in report.settled:
        t, tail = s.thesis, f"  ({s.thesis.thesis_id}, {s.thesis.arm})"
        if s.events:
            last = s.events[-1]
            states = "→".join([s.before, *(e.state for e in s.events)])
            lines.append(f"{t.ticker} {t.horizon} {states} {last.reason} "
                         f"{'-' if last.price is None else plain(last.price)}{tail}")
        else:
            lines.append(f"{t.ticker} {t.horizon} {s.before} unchanged{tail}")
        if s.teacher_outcome:
            o = s.teacher_outcome
            r = f" r_net {o.outcome.r_net:.3f}" if o.outcome else ""
            lines.append(f"  teacher_outcome {o.final_state}{r}")
        lines.extend(f"  note: {note}" for note in s.notes)
    if report.shadows:
        lines.append(f"skipped {len(report.shadows)} shadow(s): shadows are settled by tr grade")
    changed = [s for s in report.settled if s.events]
    outcomes = sum(1 for s in report.settled if s.teacher_outcome)
    written = "dry run: nothing written" if report.dry_run else "appended"
    lines.append(f"reconcile {report.session}: {len(report.settled)} subjects, {len(changed)} changed, "
                 f"{sum(len(s.events) for s in changed)} events, {outcomes} teacher outcomes ({written})")
    return lines
