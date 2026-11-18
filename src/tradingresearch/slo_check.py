"""SLOs of the after-close loop (PLAN-60 week 3): `tr daily` finished by 17:30 ET, zero missed sessions, data fresh,
and (COST-6) the session's first paid run within the cost budget.

Reads the journal only (no model, no network). Finish time comes from the `daily_run` rows, which are written as each
step ends, so traces are not needed; cost comes from the same rows' `cost_usd`, the run files' measured cost.
`--inject-delay-minutes` adds to the measured finish to exercise the breach path without waiting. Only live sessions
(from `sessions.FIRST_SESSION`) are checked and counted; an earlier session is checked only when named with
`--session`, labelled pre-live. Exit 0 = every SLO met (a `cost` with no data is neither met nor breached), 1 = a
breach. Run as `tr slo` or `python -m tradingresearch.slo_check`.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from . import journal, sessions
from .config import Settings, settings
from .daily import MISSED_WINDOW, TEACHER

DEADLINE = time(17, 30)  # New York: the run's results are in before the evening review
COST_BUDGET_USD = 0.60  # the cost SLO's target for a session's first paid run, teacher steps apart: COST-SPIKE §2.3
# (analyze $0.27 + thesis $0.36 per session at shortlist 10, measured means with headroom). A target, not a stop:
# `tr daily` stops at `--max-usd`, whose default 1.00 is a literal in commands/daily.py and has no named setting.


@dataclass(frozen=True)
class Slo:
    """One SLO's verdict: what was measured against what was promised. `ok` None: nothing to measure (no data)."""

    name: str
    ok: bool | None
    measured: str
    target: str


def latest_session(conn: sqlite3.Connection, since: date | None = sessions.FIRST_SESSION) -> date | None:
    """The latest session on or after `since` (None: any) that `tr daily` ran for (a `missed` row is not a run)."""
    found = conn.execute("SELECT max(session) FROM daily_run WHERE status != 'missed' AND (? IS NULL OR session >= ?)",
                         (since and since.isoformat(),) * 2).fetchone()[0]
    return date.fromisoformat(found) if found else None


def runs(conn: sqlite3.Connection, session: date) -> dict[str, list[tuple[str, str, datetime]]]:
    """The session's runs in order: daily_id -> [(step, reason, created_at)] of its non-missed rows."""
    out: dict[str, list[tuple[str, str, datetime]]] = {}
    rows = conn.execute("SELECT daily_id, step, reason, created_at FROM daily_run WHERE session = ? "
                        "AND status != 'missed' ORDER BY seq", (session.isoformat(),))
    for daily_id, step, reason, created_at in rows:
        out.setdefault(daily_id, []).append((step, reason, datetime.fromisoformat(created_at)))
    return out


def finished(conn: sqlite3.Connection, session: date, delay: timedelta = timedelta()) -> Slo:
    """The first run that reached reconcile: its last non-teacher row is the finish (the teacher arm is not traded,
    so it is not on the deadline)."""
    deadline = datetime.combine(session, DEADLINE, sessions.NY)
    target = f"by {DEADLINE:%H:%M} ET on {session}"
    complete = [(daily_id, rows) for daily_id, rows in runs(conn, session).items()
                if any(step == "reconcile" for step, _, _ in rows)]
    if not complete:
        return Slo("finished", False, f"no tr daily run for {session} reached reconcile", target)
    daily_id, rows = complete[0]
    end = max(at for _, reason, at in rows if not reason.startswith(f"{TEACHER} ")) + delay
    injected = f" (+{delay.total_seconds() / 60:g} min injected)" if delay else ""
    return Slo("finished", end <= deadline, f"{daily_id} finished {end.astimezone(sessions.NY):%Y-%m-%d %H:%M} ET"
               f"{injected}", target)


def missed(conn: sqlite3.Connection, session: date, window: int = MISSED_WINDOW,
           since: date | None = sessions.FIRST_SESSION) -> Slo:
    """Sessions in the last `window` up to `session` with a `missed` row or no run at all, counted from the first run
    and from `since` (earlier sessions predate the loop or the live stream; None: from the first run only)."""
    first = journal.first_daily_session(conn)
    if first is not None and since is not None:
        first = max(first, since)
    days = [d for d in sessions.recent(window, session) if first is not None and d >= first]
    ran = {date.fromisoformat(d) for (d,) in conn.execute("SELECT DISTINCT session FROM daily_run "
                                                          "WHERE status != 'missed'")}
    recorded = {date.fromisoformat(d) for (d,) in conn.execute("SELECT DISTINCT session FROM daily_run "
                                                               "WHERE status = 'missed'")}
    gone = [d for d in days if d in recorded or d not in ran]
    listed = f": {', '.join(map(str, gone))}" if gone else ""
    return Slo("missed", not gone, f"{len(gone)} of the last {len(days)} sessions since {first}{listed}",
               f"0 in the last {window} sessions")


def fresh(conn: sqlite3.Connection, session: date, feed: str) -> Slo:
    """The session was screened, and every screened ticker has that session's daily bars on the configured feed."""
    target = f"a screen result for {session} and {feed} daily bars for every screened ticker"
    screened = {t for (t,) in conn.execute("SELECT DISTINCT ticker FROM screen_result WHERE session = ?",
                                           (session.isoformat(),))}
    if not screened:
        return Slo("fresh", False, f"no screen result for {session}", target)
    barred = {t for (t,) in conn.execute("SELECT DISTINCT ticker FROM bars_daily WHERE session = ? AND feed = ?",
                                         (session.isoformat(), feed))}
    lacking = sorted(screened - barred)
    tail = f"; no bars for {', '.join(lacking)}" if lacking else ""
    return Slo("fresh", not lacking, f"{len(screened) - len(lacking)} of {len(screened)} screened tickers have "
               f"{session} bars{tail}", target)


def cost(conn: sqlite3.Connection, session: date, budget: float = COST_BUDGET_USD) -> Slo:
    """The session's first `tr daily` run that paid for a step: its recorded cost (the `daily_run` rows' `cost_usd`,
    failed calls too) against the budget. A later rerun or catch-up does not change the reading. Teacher steps are paid
    under --teacher-max-usd, not --max-usd, so they are shown but not counted. No paid row at all is no data."""
    target = f"at most ${budget:.2f} for the session's first paid run, teacher steps apart"
    rows = conn.execute("SELECT daily_id, reason, cost_usd FROM daily_run WHERE session = ? AND status != 'missed' "
                        "ORDER BY seq", (session.isoformat(),)).fetchall()
    paid = next((daily_id for daily_id, _, usd in rows if usd > 0), None)
    if paid is None:
        ran = len({daily_id for daily_id, _, _ in rows})
        what = f"{ran} tr daily run(s) for {session}, none with a paid step" if ran else f"no tr daily run for {session}"
        return Slo("cost", None, f"no data: {what}", target)
    teacher = sum(usd for daily_id, reason, usd in rows if daily_id == paid and reason.startswith(f"{TEACHER} "))
    spent = sum(usd for daily_id, _, usd in rows if daily_id == paid) - teacher
    return Slo("cost", spent <= budget, f"{paid} spent ${spent:.6f} of ${budget:.2f} (teacher steps ${teacher:.6f} "
               "more)", target)


def check(conn: sqlite3.Connection, session: date, feed: str, delay: timedelta = timedelta(),
          window: int = MISSED_WINDOW, since: date | None = sessions.FIRST_SESSION,
          budget: float = COST_BUDGET_USD) -> list[Slo]:
    """Every SLO for one session."""
    return [finished(conn, session, delay), missed(conn, session, window, since), fresh(conn, session, feed),
            cost(conn, session, budget)]


def overdue(now: datetime) -> list[date]:
    """Live sessions whose 17:30 ET deadline has passed by `now`."""
    today = now.astimezone(sessions.NY).date()
    if today < sessions.FIRST_SESSION:
        return []
    return [d for d in sessions.between(sessions.FIRST_SESSION, today)
            if datetime.combine(d, DEADLINE, sessions.NY) <= now]


def no_live_run(conn: sqlite3.Connection, now: datetime, window: int = MISSED_WINDOW) -> tuple[list[str], int]:
    """The journal has no run for a live session: fine until a live session's deadline passes, then each such session
    is missed."""
    latest = latest_session(conn, since=None)
    before = f"; the latest tr daily run ({latest}) predates it and is not checked" if latest else ""
    due = overdue(now)
    if not due:
        return [f"slo: no live session yet: the live stream starts {sessions.FIRST_SESSION}{before}"], 0
    gone = due[-window:]
    slo = Slo("missed", False, f"{len(gone)} of the last {len(gone)} sessions since {sessions.FIRST_SESSION}: "
              f"{', '.join(map(str, gone))}", f"0 in the last {window} sessions")
    return [*render(gone[-1], [slo])[:1], f"slo: no tr daily run for any live session{before}"], 1


def render(session: date, slos: list[Slo]) -> list[str]:
    """One line per SLO (verdict, measured, target), then the total over the SLOs that had data."""
    verdict = {True: "ok", False: "BREACH", None: "n/a"}
    lines = [f"{verdict[s.ok]:<6} {s.name:<8} {s.measured}  (target: {s.target})" for s in slos]
    decided = [s for s in slos if s.ok is not None]
    none = [s.name for s in slos if s.ok is None]
    tail = f"; no data: {', '.join(none)}" if none else ""
    return [*lines, f"slo {session}: {sum(s.ok for s in decided)}/{len(decided)} met{tail}"]


def add_arguments(p: argparse.ArgumentParser) -> None:
    """Shared by `tr slo` and `python -m tradingresearch.slo_check`."""
    p.add_argument("--session", help="an NYSE session (default: the latest one tr daily ran for)")
    p.add_argument("--inject-delay-minutes", type=float, default=0.0,
                   help="add this many minutes to the measured finish, to exercise the breach path")
    p.add_argument("--window", type=int, default=MISSED_WINDOW,
                   help=f"sessions looked back for misses (default {MISSED_WINDOW})")
    p.add_argument("--budget-usd", type=float, default=COST_BUDGET_USD,
                   help=f"the cost target for the session's first paid run (default {COST_BUDGET_USD:.2f})")


def run(args: argparse.Namespace, cfg: Settings, now: datetime | None = None) -> int:
    """Print the SLO lines; 0 when every SLO is met, 1 on any breach."""
    conn = journal.connect(cfg.db_path)
    session = date.fromisoformat(args.session) if args.session else latest_session(conn)
    if session is None:
        lines, code = no_live_run(conn, now or datetime.now(UTC), args.window)
        print("\n".join(lines))
        return code
    if not sessions.is_session(session):
        raise SystemExit(f"{session} is not an NYSE session")
    live = session >= sessions.FIRST_SESSION
    if not live:
        print(f"pre-live: {session} predates the live stream (from {sessions.FIRST_SESSION}); a dev run, checked "
              "because --session named it")
    slos = check(conn, session, cfg.feed, timedelta(minutes=args.inject_delay_minutes), args.window,
                 sessions.FIRST_SESSION if live else None, args.budget_usd)
    print("\n".join(render(session, slos)))
    return 1 if any(s.ok is False for s in slos) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slo_check", description=__doc__.splitlines()[0])
    add_arguments(parser)
    return run(parser.parse_args(argv), settings())


if __name__ == "__main__":
    raise SystemExit(main())
