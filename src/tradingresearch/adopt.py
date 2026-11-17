"""Champion/challenger adoption (SPIKE §8.3): the per-session paired vectors of one rule change, read from the
journal, and the pre-registered decision rule (journal.RULE_*). Code decides, never a model; no network.

The unit is one analysis session on the change's horizon; each arm's value is its summed graded r_net that session
(0 without a trade) and its P1 met rate (None without a judged trade). Pairs are clustered by session.

A session whose challenger did not answer (rules.unanswered: `tr daily` recorded it failed, stopped or skipped) is
no pair: the challenger's 0 there would be a missing answer, not a no-trade. While the challenger can still answer
(before the next entry window opens) the session is the waiting one and the pairs stop, as for an open trade; once it
cannot, the session is ignored for good (`SessionPairs.excluded`) and the date-ordered list goes on past it.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from gigai_core.stats import MIN_CLUSTERS, ClusterBootstrap, mde_continuous, paired_cluster_bootstrap

from . import journal, report, rules, sessions
from .records import RuleChange

N_PLANNED = journal.RULE_N
GUARD_MARGIN = journal.RULE_MARGIN
DAY_60 = date(2027, 1, 15)  # plan day 60: live-stream day 1 is 2026-11-17 (docs/runbook.md) + 59 days
TERMINAL = ("GRADED", "EXPIRED", "CANCELLED")  # nothing about the thesis changes after these
SIGMAS = (1.0, math.sqrt(2))  # §8.3's assumed per-session SD of the difference, before any is measured
RULE = (f"adopt iff, over the first {N_PLANNED} paired sessions, the 95% CI lower bound of mean(challenger - champion) "
        f"session r_net is > 0 and that of the P1 met-rate difference is >= -{GUARD_MARGIN:.2f}; otherwise rejected; "
        f"insufficient if {N_PLANNED} pairs are not reached by day 60 ({DAY_60})")

Status = Literal["pending", "adopted", "rejected", "insufficient"]


@dataclass(frozen=True)
class Decision:
    """The §8.3 verdict and the evidence it rests on; the intervals are None under MIN_CLUSTERS sessions."""

    status: Status
    delta_ci: ClusterBootstrap | None
    p1_guard_ci: ClusterBootstrap | None
    n_pairs: int
    reason: str


@dataclass(frozen=True)
class SessionPairs:
    """One change's paired sessions in order, and the first session still waiting for a thesis to finish."""

    sessions: tuple[date, ...]
    champion_r: tuple[float, ...]
    challenger_r: tuple[float, ...]
    champion_p1: tuple[float | None, ...]
    challenger_p1: tuple[float | None, ...]
    waiting: date | None  # pairs stop before it, so a late-closing swing trade cannot reorder the first 20
    excluded: tuple[date, ...] = ()  # sessions the challenger never answered, skipped (never paired)


def bootstrap(a: list[float], b: list[float], clusters: list[date]) -> ClusterBootstrap | None:
    """Mean of b - a clustered by session; None under MIN_CLUSTERS sessions (§7.5)."""
    if len(set(clusters)) < MIN_CLUSTERS:
        return None
    return paired_cluster_bootstrap(a, b, clusters, resamples=report.RESAMPLES, seed=report.SEED)


def decide(champion_session_r: list[float], challenger_session_r: list[float], champion_p1: list[float | None],
           challenger_p1: list[float | None], session_dates: list[date], *, n_planned: int = N_PLANNED,
           day60_reached: bool = False) -> Decision:
    """§8.3 on the first `n_planned` sessions by date. The P1 guard pairs only sessions with a P1 rate on both arms;
    with fewer than MIN_CLUSTERS of those the guard cannot pass, so the change cannot be adopted."""
    columns = (champion_session_r, challenger_session_r, champion_p1, challenger_p1, session_dates)
    if len({len(c) for c in columns}) != 1:
        raise ValueError("every vector needs one value per session")
    if len(set(session_dates)) != len(session_dates):
        raise ValueError("one pair per session: a session date repeats")
    order = sorted(range(len(session_dates)), key=session_dates.__getitem__)[:n_planned]
    delta = bootstrap([champion_session_r[i] for i in order], [challenger_session_r[i] for i in order],
                      [session_dates[i] for i in order])
    both = [i for i in order if champion_p1[i] is not None and challenger_p1[i] is not None]
    guard = bootstrap([champion_p1[i] for i in both], [challenger_p1[i] for i in both], [session_dates[i] for i in both])
    n = len(order)
    if n < n_planned:
        if day60_reached:
            return Decision("insufficient", delta, guard, n, f"day 60 reached with {n} of {n_planned} paired sessions")
        return Decision("pending", delta, guard, n, f"{n} of {n_planned} paired sessions so far")
    failed = []
    if delta is None or delta.ci.lower <= 0:
        failed.append(f"delta lower bound {delta.ci.lower:+.3f} R is not > 0" if delta else "delta not computable")
    if guard is None:
        failed.append(f"P1 guard not computable ({len(both)} sessions with P1 on both arms < {MIN_CLUSTERS})")
    elif guard.ci.lower < -GUARD_MARGIN:
        failed.append(f"P1 guard lower bound {guard.ci.lower:+.3f} is below -{GUARD_MARGIN:.2f}")
    if failed:
        return Decision("rejected", delta, guard, n, "; ".join(failed))
    return Decision("adopted", delta, guard, n, f"delta lower bound {delta.ci.lower:+.3f} R > 0 and P1 guard lower "
                                                f"bound {guard.ci.lower:+.3f} >= -{GUARD_MARGIN:.2f}")


def activation(registered_at: datetime) -> date:
    """The first session that opens after the Prereg was registered: no trade before it can be under the change."""
    day = registered_at.astimezone(sessions.NY).date()
    return next(d for d in sessions.between(day, day + timedelta(days=10)) if sessions.open_close(d)[0] > registered_at)


def find(conn: sqlite3.Connection, change_id: str) -> RuleChange:
    """The stored change, or KeyError."""
    change = next((c for c in journal.rule_changes(conn) if c.change_id == change_id), None)
    if change is None:
        raise KeyError(f"rule_change: no row with change_id = {change_id!r}")
    return change


def arm_session(conn: sqlite3.Connection, thesis_ids: list[str]) -> tuple[float, float | None] | None:
    """(summed r_net, P1 met rate) of one arm's theses in one session; None while any is not terminal."""
    r, met, judged = 0.0, 0, 0
    for thesis_id in thesis_ids:
        events = journal.events_for(conn, thesis_id)
        if not events or events[-1].state not in TERMINAL:
            return None
        grade = report.graded(conn, thesis_id) if events[-1].state == "GRADED" else None
        if grade is not None:
            r += grade.outcome.r_net
            p1 = report.p1_result(conn, grade)
            met, judged = met + (p1 == "met"), judged + (p1 in ("met", "not_met"))
    return r, (met / judged if judged else None)


def sessions_r(conn: sqlite3.Connection, change_id: str, now: datetime | None = None) -> SessionPairs:
    """The change's pairs: main-analysis sessions from its activation (to its decision, once decided) whose
    champion and challenger theses on its horizon are all terminal, stopping at the first session still waiting and
    skipping those the challenger can no longer answer (module docstring)."""
    change = find(conn, change_id)
    horizon = journal.prereg_horizon(change.prereg)
    decided_at = journal.rule_change_decided_at(conn, change_id)
    end = decided_at.astimezone(sessions.NY).date().isoformat() if decided_at else "9999-12-31"
    days = [row[0] for row in conn.execute(
        "SELECT DISTINCT session FROM analysis WHERE arm = 'main' AND session >= ? AND session <= ? ORDER BY session",
        (activation(change.prereg.registered_at).isoformat(), end))]
    now = now or datetime.now(UTC)
    columns: list[list] = [[], [], [], [], []]
    excluded: list[date] = []
    for day in map(date.fromisoformat, days):
        if rules.unanswered(conn, day, change_id):
            if rules.answerable(day, now):
                return SessionPairs(*map(tuple, columns), waiting=day, excluded=tuple(excluded))
            excluded.append(day)
            continue
        values = []
        for arm in report.ARMS:
            ids = [row[0] for row in conn.execute(
                "SELECT t.thesis_id FROM thesis t JOIN analysis a USING (analysis_id) "
                "WHERE a.arm = 'main' AND a.session = ? AND t.horizon = ? AND t.arm = ? ORDER BY t.rowid",
                (day.isoformat(), horizon, arm))]
            values.append(arm_session(conn, ids))
        if None in values:
            return SessionPairs(*map(tuple, columns), waiting=day, excluded=tuple(excluded))
        (champ_r, champ_p1), (chall_r, chall_p1) = values
        for column, value in zip(columns, (day, champ_r, chall_r, champ_p1, chall_p1)):
            column.append(value)
    return SessionPairs(*map(tuple, columns), waiting=None, excluded=tuple(excluded))


def decide_pairs(pairs: SessionPairs, day60: bool) -> Decision:
    """decide() on a change's journal pairs."""
    return decide(list(pairs.champion_r), list(pairs.challenger_r), list(pairs.champion_p1),
                  list(pairs.challenger_p1), list(pairs.sessions), day60_reached=day60)


def day60_reached(today: date | None = None) -> bool:
    """Whether plan day 60 has closed (default: as of the last completed session)."""
    return (today or sessions.last_completed()) >= DAY_60


def mde_lines(pairs: SessionPairs) -> list[str]:
    """§8.3 power: the smallest per-session delta 20 pairs can detect, at the assumed sigmas and, from 2 pairs on,
    at the measured one."""
    assumed = ", ".join(f"{mde_continuous(N_PLANNED, s).mde:.2f} R at sigma {s:.2f}" for s in SIGMAS)
    lines = [f"  detectable delta at n = {N_PLANNED}: 2.80159/sqrt(n) * sigma = {assumed} (sigma assumed, SPIKE §8.3)"]
    diffs = [b - a for a, b in zip(pairs.champion_r, pairs.challenger_r)]
    if len(diffs) >= 2:
        sd = statistics.stdev(diffs)
        lines.append(f"  measured sigma {sd:.2f} R over {len(diffs)} pairs: detectable delta at n = {N_PLANNED} is "
                     f"{mde_continuous(N_PLANNED, sd).mde:.2f} R")
    return lines
