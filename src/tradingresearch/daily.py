"""`tr daily`: one session's evening, screen → analyze → thesis → reconcile → grade (REPO-PLAN §7 G4a, G8; SPIKE L22,
L581).

Each step is an existing function passed in `Steps`. Work already in the journal is skipped, so a rerun for the same
session makes no model call. Every step leaves a `daily_run` row; a failed ticker is a row, not a crash. With
`TeacherSteps` (`tr daily --teachers`), the bake-off's teachers then answer the session's drawn names (SPIKE §9.4)
under their own cap; nothing in that step can fail the evening.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from gigai_core.budget import BudgetExceeded

from . import analyze as an, grade as gr, journal, reconcile_run, sessions, teacher as tc, thesis as th, usage
from .hashing import new_id
from .records import Analysis
from .screen import ScreenResult

ANALYZE_USD = 0.02  # estimate per call: measured `tr analyze` runs cost $0.016-0.017 (`tr usage`, 2026-11-16)
THESIS_USD = 0.03  # measured `tr thesis` run: $0.0195
MISSED_WINDOW = 10  # trading days looked back for sessions with no daily_run row
DONE = "already done"
TEACHER = "teacher"  # a teacher row's reason starts "teacher <model>: " (daily_run.step allows only the five steps)
GRADE = "grade"  # the grade row is step "reconcile" with a reason starting "grade: ", for the same CHECK
TEACHER_MAX_USD = 0.40  # --teacher-max-usd default: the teacher step's cap per session, every run of it counted


@dataclass(frozen=True)
class Steps:
    """The evening's steps as plain functions: commands/daily.py passes the real ones, tests pass recorded results."""

    screen: Callable[[date], list[ScreenResult]]
    analyze: Callable[[str, date], an.Result]
    horizons: Callable[[Analysis, datetime], tuple[str, ...]]
    thesis: Callable[[Analysis, tuple[str, ...]], th.Result]
    reconcile: Callable[[date, bool], reconcile_run.Report]
    grade: Callable[[date, bool], gr.Report]


@dataclass(frozen=True)
class TeacherSteps:
    """The opt-in teacher calls. `max_usd` is what is left of --teacher-max-usd: gigai-core refuses a call whose
    worst case does not fit it before anything is sent."""

    analyze: Callable[[str, date, tc.Teacher, float], an.Result]
    thesis: Callable[[Analysis, tc.Teacher, float], th.Result]


@dataclass(frozen=True)
class Row:
    """What one step did for one ticker (None for the session-wide steps)."""

    step: str
    ticker: str | None
    status: str
    reason: str
    ids: tuple[str, ...] = ()
    cost_usd: float = 0.0


@dataclass
class Daily:
    """One `tr daily` run: its rows, the running cost against `max_usd`, and the dry-run estimate."""

    conn: sqlite3.Connection
    session: date
    max_usd: float
    runs_dir: Path
    dry_run: bool
    daily_id: str = field(default_factory=lambda: new_id("dy"))
    rows: list[Row] = field(default_factory=list)
    spent_usd: float = 0.0
    planned: list[tuple[str, str]] = field(default_factory=list)  # (step, ticker) a dry run would pay for
    stopped: bool = False
    screen_failed: bool = False

    def record(self, row: Row, session: date | None = None) -> None:
        """Print the row and, outside a dry run, store it at once (a crash keeps every row before it)."""
        day = session or self.session
        self.rows.append(row)
        print(line(row, day))
        if not self.dry_run:
            journal.add_daily_run(self.conn, {
                "daily_id": self.daily_id, "session": day.isoformat(), "step": row.step, "ticker": row.ticker,
                "status": row.status, "reason": row.reason, "ids": row.ids, "cost_usd": row.cost_usd,
            })

    def affordable(self, step: str, ticker: str, estimate: float) -> bool:
        """False, with a `stopped` row, once the next call's estimate would take the run past `max_usd`."""
        if self.stopped or self.spent_usd + estimate > self.max_usd:
            self.stopped = True
            self.record(Row(step, ticker, "stopped", f"budget: spent ${self.spent_usd:.4f} + ≈${estimate:.2f} would "
                                                     f"pass --max-usd ${self.max_usd:.2f}"))
            return False
        return True

    def call[T](self, step: Callable[[], T]) -> tuple[T | None, str | None, float]:
        """Run one paid step: (result or None, error or None, cost of the run files it saved, failed calls too)."""
        result, error, cost = self.measure(step)
        self.spent_usd += cost
        return result, None if error is None else reason(error), cost

    def measure[T](self, step: Callable[[], T]) -> tuple[T | None, Exception | SystemExit | None, float]:
        """Run one paid step without charging `max_usd`: (result or None, the exception or None, run-file cost)."""
        before = set(self.runs_dir.glob("run_*.jsonl"))
        result, error = None, None
        try:
            result = step()
        except sqlite3.Error:
            raise  # the journal failed: the whole run stops
        except (Exception, SystemExit) as exc:  # a model error or a parse failure fails this ticker only
            error = exc
        cost = round(sum(usage.run_cost(path).cost_usd for path in set(self.runs_dir.glob("run_*.jsonl")) - before), 6)
        return result, error, cost


@dataclass
class TeacherSpend:
    """Teacher spend against --teacher-max-usd over every run for this session, so the catch-up counts the first."""

    max_usd: float
    session_usd: float
    run_usd: float = 0.0
    stopped: bool = False
    planned: list[tuple[str, str, str]] = field(default_factory=list)  # (step, name, model) a dry run would pay for

    @property
    def left(self) -> float:
        return round(self.max_usd - self.session_usd, 6)

    def add(self, cost: float) -> None:
        self.session_usd += cost
        self.run_usd += cost


def reason(error: BaseException) -> str:
    return str(error) or type(error).__name__


def line(row: Row, session: date) -> str:
    if row.status == "missed":
        return f"missed: {session}"
    ids = f"  {','.join(row.ids)}" if row.ids else ""
    cost = f"  ${row.cost_usd:.4f}" if row.cost_usd else ""
    return f"{row.step:<9} {row.ticker or '-':<6} {row.status:<7} {row.reason}{ids}{cost}"


def missed_sessions(conn: sqlite3.Connection, session: date, now: datetime) -> list[date]:
    """Completed sessions of the last 10 trading days with no daily_run row, other than `session`. Days before the
    first session `tr daily` ran for are not misses (the runner did not exist yet). Never backfilled."""
    first = journal.first_daily_session(conn)
    if first is None:
        return []
    ran = journal.daily_sessions(conn)
    window = sessions.recent(MISSED_WINDOW, sessions.last_completed(now))
    return [day for day in window if day >= first and day != session and day not in ran]


def shortlist(results: list[ScreenResult], top: int) -> list[str]:
    """The screen's top `top` by rank; unranked tickers (filtered or zero points) are never analyzed (SPIKE §4.2)."""
    return [r.ticker for r in sorted(results, key=lambda r: r.rank or 0) if r.rank is not None and r.rank <= top]


def run(conn: sqlite3.Connection, steps: Steps, session: date, *, top: int, max_usd: float, runs_dir: Path,
        now: datetime, dry_run: bool = False, no_model: bool = False, teachers: TeacherSteps | None = None,
        teacher_max_usd: float = TEACHER_MAX_USD) -> Daily:
    """The whole evening for `session`, then the teacher step when `teachers` is given. Only a failed screen ends it
    early (`screen_failed`)."""
    daily = Daily(conn, session, max_usd, runs_dir, dry_run)
    for day in missed_sessions(conn, session, now):
        daily.record(Row("session", None, "missed", "no tr daily row for this completed session"), day)
    try:
        results = steps.screen(session)
    except sqlite3.Error:
        raise
    except (Exception, SystemExit) as error:
        daily.record(Row("screen", None, "failed", reason(error)))
        daily.screen_failed = True
        return daily
    tickers = shortlist(results, top)
    daily.record(Row("screen", None, "ok", f"{len(results)} rows, shortlist {len(tickers)}", tuple(tickers)))
    opens = th.windows(session, "day")[0]
    gate = "--no-model" if no_model else None
    if opens <= now:  # `tr thesis` refuses now, so an analysis would be paid for and never used
        gate = f"late: the entry window after {session} opened at {opens:%Y-%m-%d %H:%M} UTC"
    analyze_all(daily, steps, tickers, gate)
    thesis_all(daily, steps, now, gate)
    reconcile(daily, steps)
    grade(daily, steps)
    print(summary(daily))
    if teachers is not None:
        teach(daily, teachers, results, teacher_max_usd, no_model)
    return daily


def analyze_all(daily: Daily, steps: Steps, tickers: list[str], gate: str | None) -> None:
    """Analyze each shortlisted ticker with no main analysis at the current prompt for this session."""
    done = {a.ticker: a.analysis_id for a in journal.analyses(daily.conn, daily.session, "main")
            if a.prompt_version == an.DEFAULT_PROMPT}
    for ticker in tickers:
        if ticker in done:
            daily.record(Row("analyze", ticker, "skipped", f"{DONE} ({done[ticker]})"))
        elif gate:
            daily.record(Row("analyze", ticker, "skipped", gate))
        elif daily.dry_run:
            daily.planned.append(("analyze", ticker))
            print(f"would analyze {ticker} (≈${ANALYZE_USD:.2f}), then thesis (≈${THESIS_USD:.2f})")
        elif daily.affordable("analyze", ticker, ANALYZE_USD):
            result, error, cost = daily.call(lambda: steps.analyze(ticker, daily.session))
            if result is None:
                daily.record(Row("analyze", ticker, "failed", error or "?", cost_usd=cost))
                continue
            a = result.analysis
            status = "ok" if a.claims else "failed"
            text = f"{len(a.claims)} claims, {len(result.rejected)} rejected"
            daily.record(Row("analyze", ticker, status, text, (a.analysis_id,), cost))


def thesis_all(daily: Daily, steps: Steps, now: datetime, gate: str | None) -> None:
    """A champion thesis call for the newest main analysis of each ticker this session that has no decision yet."""
    newest = {a.ticker: a for a in journal.analyses(daily.conn, daily.session, "main")}
    for ticker, a in newest.items():
        if journal.has_decision(daily.conn, a.analysis_id):
            daily.record(Row("thesis", ticker, "skipped", f"{DONE} ({a.analysis_id})"))
        elif not a.claims:
            daily.record(Row("thesis", ticker, "skipped", f"no valid claims in {a.analysis_id}"))
        elif gate:
            daily.record(Row("thesis", ticker, "skipped", gate))
        else:
            thesis_one(daily, steps, a, now)
    for _, ticker in [p for p in daily.planned if p[0] == "analyze"]:
        daily.planned.append(("thesis", ticker))


def thesis_one(daily: Daily, steps: Steps, a: Analysis, now: datetime) -> None:
    try:
        asked = steps.horizons(a, now)
    except SystemExit as refused:
        daily.record(Row("thesis", a.ticker, "skipped", str(refused)))
        return
    if not asked:
        daily.record(Row("thesis", a.ticker, "skipped", "every horizon has a live champion thesis"))
    elif daily.dry_run:
        daily.planned.append(("thesis", a.ticker))
        print(f"would thesis {a.ticker} {','.join(asked)} from {a.analysis_id} (≈${THESIS_USD:.2f})")
    elif daily.affordable("thesis", a.ticker, THESIS_USD):
        result, error, cost = daily.call(lambda: steps.thesis(a, asked))
        if result is None:
            daily.record(Row("thesis", a.ticker, "failed", error or "?", cost_usd=cost))
            return
        status, text = decision(result.checked)
        daily.record(Row("thesis", a.ticker, status, text, tuple(t.thesis_id for t in result.checked.theses), cost))


def decision(c: th.Checked) -> tuple[str, str]:
    """A thesis call's status and reason: ok once a thesis or a no-trade is stored."""
    text = f"accepted {len(c.theses)}, no_trade {len(c.no_trades)}, rejected {len(c.rejected)}"
    text += "".join(f"; {r.horizon} {r.reason}" for r in c.rejected)
    return ("ok" if c.theses or c.no_trades else "failed"), text


def reconcile(daily: Daily, steps: Steps) -> None:
    """Settle everything open; a dry run appends nothing. A failure is a row: the evening's theses are already in."""
    try:
        report = steps.reconcile(daily.session, daily.dry_run)
    except sqlite3.Error:
        raise
    except (Exception, SystemExit) as error:
        daily.record(Row("reconcile", None, "failed", reason(error)))
        return
    lines = reconcile_run.render(report)
    for text in lines[:-1]:
        print(f"  {text}")
    events = tuple(e.event_id for s in report.settled for e in s.events) if not report.dry_run else ()
    daily.record(Row("reconcile", None, "ok", lines[-1], events))


def grade(daily: Daily, steps: Steps) -> None:
    """Shadows and grades after the settle (SPIKE §7); a failure is a row, as for reconcile."""
    try:
        report = steps.grade(daily.session, daily.dry_run)
    except sqlite3.Error:
        raise
    except (Exception, SystemExit) as error:
        daily.record(Row("reconcile", None, "failed", f"{GRADE}: {reason(error)}"))
        return
    lines = gr.render(report)
    for text in lines[:-1]:
        print(f"  {text}")
    daily.record(Row("reconcile", None, "ok", f"{GRADE}: {lines[-1]}", gr.written_ids(report)))


def summary(daily: Daily) -> str:
    if daily.dry_run:
        n_analyze = sum(step == "analyze" for step, _ in daily.planned)
        n_thesis = len(daily.planned) - n_analyze
        cost = n_analyze * ANALYZE_USD + n_thesis * THESIS_USD
        return (f"daily {daily.session} (dry run): would analyze {n_analyze}, thesis {n_thesis}, estimated ${cost:.2f} "
                f"(≈${ANALYZE_USD:.2f} per analyze, ${THESIS_USD:.2f} per thesis); nothing written to daily_run")
    paid = [r for r in daily.rows if r.step in ("analyze", "thesis")]
    count = {status: sum(r.status == status for r in paid) for status in ("ok", "failed", "skipped", "stopped")}
    calls = count["ok"] + count["failed"]
    if paid and all(r.status == "skipped" and r.reason.startswith(DONE) for r in paid):
        return f"daily {daily.session}: {DONE}, no model call"
    return (f"daily {daily.session}: {count['ok']} ok, {count['failed']} failed, {count['skipped']} skipped, "
            f"{count['stopped']} stopped; {calls} model steps, spent ${daily.spent_usd:.4f} of ${daily.max_usd:.2f}")


# ---------- teachers (`--teachers`, SPIKE §9.4) ----------

def teach(daily: Daily, steps: TeacherSteps, results: list[ScreenResult], max_usd: float, no_model: bool) -> None:
    """Each pinned teacher on each drawn name of the session, after the evening's steps. Never raises: the evening is
    done and the exit code is its own."""
    try:
        spend = TeacherSpend(max_usd, teacher_spent(daily.conn, daily.session))
        start = len(daily.rows)
        names = teach_all(daily, steps, results, spend, "--no-model" if no_model else None)
        print(teacher_summary(daily, spend, names, daily.rows[start:]))
    except (Exception, SystemExit) as error:  # a journal failure too: nothing here may fail the evening
        print(f"teachers {daily.session}: stopped: {reason(error)}")


def teach_all(daily: Daily, steps: TeacherSteps, results: list[ScreenResult], spend: TeacherSpend,
              gate: str | None) -> list[str]:
    """A teacher's first stored analysis of a name is never redone (the bake-off scores the first answer)."""
    from . import bakeoff  # local import: bakeoff imports this module
    names = tc.draw(daily.session, shortlist(results, bakeoff.SHORTLIST))
    first = {model: bakeoff.first_analyses(daily.conn, model) for model in tc.TEACHERS}
    for name in names:
        for t in tc.TEACHERS.values():
            a = first[t.model].get((daily.session, name))
            if a is None:
                a = teacher_analyze(daily, steps, spend, name, t, gate)
            else:
                daily.record(Row("analyze", name, "skipped", f"{label(t)}{DONE} ({a.analysis_id})"))
            if a is not None:
                teacher_thesis(daily, steps, spend, a, t, gate)
    return names


def teacher_analyze(daily: Daily, steps: TeacherSteps, spend: TeacherSpend, name: str, t: tc.Teacher,
                    gate: str | None) -> Analysis | None:
    """One teacher's analysis of one drawn name, or None when gated, planned, stopped or failed."""
    if gate:
        daily.record(Row("analyze", name, "skipped", label(t) + gate))
    elif daily.dry_run:
        spend.planned += [("analyze", name, t.model), ("thesis", name, t.model)]
        print(f"would analyze {name} with {TEACHER} {t.model}, then thesis")
    else:
        result, cost = teacher_call(daily, spend, "analyze", name, t,
                                    lambda left: steps.analyze(name, daily.session, t, left))
        if result is not None:
            a = result.analysis
            text = f"{label(t)}{len(a.claims)} claims, {len(result.rejected)} rejected"
            daily.record(Row("analyze", name, "ok" if a.claims else "failed", text, (a.analysis_id,), cost))
            return a
    return None


def teacher_thesis(daily: Daily, steps: TeacherSteps, spend: TeacherSpend, a: Analysis, t: tc.Teacher,
                   gate: str | None) -> None:
    """The thesis-step decision from the teacher's own first analysis, unless one is stored already."""
    from . import bakeoff  # local import: bakeoff imports this module
    if bakeoff.decided(daily.conn, a.analysis_id):
        daily.record(Row("thesis", a.ticker, "skipped", f"{label(t)}{DONE} ({a.analysis_id})"))
    elif not a.claims:
        daily.record(Row("thesis", a.ticker, "skipped", f"{label(t)}no valid claims in {a.analysis_id}"))
    elif gate:
        daily.record(Row("thesis", a.ticker, "skipped", label(t) + gate))
    elif daily.dry_run:
        spend.planned.append(("thesis", a.ticker, t.model))
        print(f"would thesis {a.ticker} with {TEACHER} {t.model} from {a.analysis_id}")
    else:
        result, cost = teacher_call(daily, spend, "thesis", a.ticker, t, lambda left: steps.thesis(a, t, left))
        if result is not None:
            status, text = decision(result.checked)
            ids = tuple(x.thesis_id for x in result.checked.theses)
            daily.record(Row("thesis", a.ticker, status, label(t) + text, ids, cost))


def teacher_call[T](daily: Daily, spend: TeacherSpend, step: str, name: str, t: tc.Teacher,
                    call: Callable[[float], T]) -> tuple[T | None, float]:
    """One paid teacher step under what is left of the cap. A refusal stops the step; any other error fails only
    this (name, teacher). Returns None once a row says why."""
    spent = f"${spend.session_usd:.4f} of --teacher-max-usd ${spend.max_usd:.2f} spent this session"
    if spend.stopped or spend.left <= 0:
        spend.stopped = True
        daily.record(Row(step, name, "stopped", f"{label(t)}budget: {spent}"))
        return None, 0.0
    left = spend.left
    result, error, cost = daily.measure(lambda: call(left))
    spend.add(cost)
    if isinstance(error, BudgetExceeded):
        spend.stopped = True
        daily.record(Row(step, name, "stopped", f"{label(t)}budget: {error}; {spent}", cost_usd=cost))
    elif error is not None:
        daily.record(Row(step, name, "failed", label(t) + reason(error), cost_usd=cost))
    return (None if error else result), cost


def label(t: tc.Teacher) -> str:
    return f"{TEACHER} {t.model}: "


def teacher_spent(conn: sqlite3.Connection, session: date) -> float:
    """Teacher spend already recorded for `session` by earlier runs (their `daily_run` rows)."""
    return sum(r["cost_usd"] for r in journal.daily_runs(conn, session) if r["reason"].startswith(f"{TEACHER} "))


def teacher_summary(daily: Daily, spend: TeacherSpend, names: list[str], rows: list[Row]) -> str:
    head = f"teachers {daily.session}"
    drawn = f"{len(names)} names ({' '.join(names) or 'none'}) x {len(tc.TEACHERS)} teachers"
    if daily.dry_run:
        n_analyze = sum(step == "analyze" for step, _, _ in spend.planned)
        return (f"{head} (dry run): {drawn}; would analyze {n_analyze}, thesis {len(spend.planned) - n_analyze}; "
                f"each call's worst case must fit what is left of --teacher-max-usd ${spend.max_usd:.2f} "
                f"(${spend.session_usd:.4f} spent this session); nothing written")
    count = {status: sum(r.status == status for r in rows) for status in ("ok", "failed", "skipped", "stopped")}
    if rows and all(r.status == "skipped" and DONE in r.reason for r in rows):
        return f"{head}: {drawn}; {DONE}, no model call"
    return (f"{head}: {drawn}; {count['ok']} ok, {count['failed']} failed, {count['skipped']} skipped, "
            f"{count['stopped']} stopped; {count['ok'] + count['failed']} model steps, spent ${spend.run_usd:.4f} "
            f"this run, ${spend.session_usd:.4f} of ${spend.max_usd:.2f} this session")
