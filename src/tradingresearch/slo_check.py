"""SLOs of the after-close loop (PLAN-60 week 3): `tr daily` finished by 17:30 ET, zero missed sessions, data fresh.

Reads the journal only (no model, no network). Finish time comes from the `daily_run` rows, which are written as each
step ends, so traces are not needed. `--inject-delay-minutes` adds to the measured finish to exercise the breach path
without waiting. Exit 0 = every SLO met, 1 = a breach. Run as `tr slo` or `python -m tradingresearch.slo_check`.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from . import journal, sessions
from .config import Settings, settings
from .daily import MISSED_WINDOW, TEACHER

DEADLINE = time(17, 30)  # New York: the run's results are in before the evening review


@dataclass(frozen=True)
class Slo:
    """One SLO's verdict: what was measured against what was promised."""

    name: str
    ok: bool
    measured: str
    target: str


def latest_session(conn: sqlite3.Connection) -> date | None:
    """The latest session `tr daily` ran for (a `missed` row is not a run)."""
    found = conn.execute("SELECT max(session) FROM daily_run WHERE status != 'missed'").fetchone()[0]
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


def missed(conn: sqlite3.Connection, session: date, window: int = MISSED_WINDOW) -> Slo:
    """Sessions in the last `window` up to `session` with a `missed` row or no run at all, counted from the first run
    (earlier sessions predate the loop)."""
    first = journal.first_daily_session(conn)
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


def check(conn: sqlite3.Connection, session: date, feed: str, delay: timedelta = timedelta(),
          window: int = MISSED_WINDOW) -> list[Slo]:
    """Every SLO for one session."""
    return [finished(conn, session, delay), missed(conn, session, window), fresh(conn, session, feed)]


def render(session: date, slos: list[Slo]) -> list[str]:
    """One line per SLO (verdict, measured, target), then the total."""
    lines = [f"{'ok' if s.ok else 'BREACH':<6} {s.name:<8} {s.measured}  (target: {s.target})" for s in slos]
    return [*lines, f"slo {session}: {sum(s.ok for s in slos)}/{len(slos)} met"]


def add_arguments(p: argparse.ArgumentParser) -> None:
    """Shared by `tr slo` and `python -m tradingresearch.slo_check`."""
    p.add_argument("--session", help="an NYSE session (default: the latest one tr daily ran for)")
    p.add_argument("--inject-delay-minutes", type=float, default=0.0,
                   help="add this many minutes to the measured finish, to exercise the breach path")
    p.add_argument("--window", type=int, default=MISSED_WINDOW,
                   help=f"sessions looked back for misses (default {MISSED_WINDOW})")


def run(args: argparse.Namespace, cfg: Settings) -> int:
    """Print the SLO lines; 0 when every SLO is met, 1 on any breach."""
    conn = journal.connect(cfg.db_path)
    session = date.fromisoformat(args.session) if args.session else latest_session(conn)
    if session is None:
        print("BREACH no tr daily run in the journal")
        return 1
    if not sessions.is_session(session):
        raise SystemExit(f"{session} is not an NYSE session")
    slos = check(conn, session, cfg.feed, timedelta(minutes=args.inject_delay_minutes), args.window)
    print("\n".join(render(session, slos)))
    return 0 if all(s.ok for s in slos) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slo_check", description=__doc__.splitlines()[0])
    add_arguments(parser)
    return run(parser.parse_args(argv), settings())


if __name__ == "__main__":
    raise SystemExit(main())
