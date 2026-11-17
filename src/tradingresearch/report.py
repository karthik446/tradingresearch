"""`tr report`: one scorecard per arm and horizon, never pooled across horizons (SPIKE §7.5 statistics, §7.6 power,
§7.2 the 2x2). Only champion and challenger theses are read; teacher theses never enter a scorecard. Reads the
journal only; no model call, no network."""

from __future__ import annotations

import sqlite3
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Literal

from gigai_core.score import ScoreRecord
from gigai_core.stats import MIN_CLUSTERS, ClusterBootstrap, mde_continuous, paired_cluster_bootstrap, wilson_interval

from . import journal, sessions
from .daily import TEACHER
from .records import Event, Grade

ARMS = ("champion", "challenger")
HORIZONS = ("day", "short", "swing")
RESAMPLES = 2000  # §7.5: the cluster bootstrap's resamples
SEED = 0  # fixed, so a rerun of the report prints the same intervals

P1 = Literal["met", "not_met", "unknown"]


@dataclass(frozen=True)
class Trade:
    """One graded thesis: everything the scorecard statistics read about it."""

    thesis_id: str
    session: date  # the entry (fill) session, New York date: the bootstrap's cluster
    r_net: float
    shadow_r_net: float | None
    mfe_r: float
    mae_r: float
    p1: P1 | None = None  # None: no P1 result stored for this trade


@dataclass(frozen=True)
class Card:
    """One (arm, horizon) scorecard's inputs, counted from the journal."""

    arm: str
    horizon: str
    states: dict[str, int]  # last state per thesis; GRADED is counted as CLOSED
    filled: int  # theses with an OPEN event, whatever happened after
    no_trades: int  # no_trade rows on main analyses for this horizon
    answered: int  # main-analysis decisions for this horizon: champion/challenger theses plus no-trades
    trades: tuple[Trade, ...]  # graded theses only


def arms_shown(conn: sqlite3.Connection) -> list[str]:
    """Champion always; challenger only once it has a thesis, so an unused arm prints no empty cards."""
    has = conn.execute("SELECT 1 FROM thesis WHERE arm = 'challenger' LIMIT 1").fetchone()
    return ["champion", "challenger"] if has else ["champion"]


def cards(conn: sqlite3.Connection, arms: list[str], horizons: list[str]) -> list[Card]:
    """One card per (arm, horizon), in that order."""
    return [card(conn, arm, horizon) for arm in arms for horizon in horizons]


def card(conn: sqlite3.Connection, arm: str, horizon: str) -> Card:
    """Count one arm's theses at one horizon by last state, and collect its graded trades."""
    if arm not in ARMS:
        raise ValueError(f"arm {arm!r} has no scorecard: only {', '.join(ARMS)}")
    states: Counter[str] = Counter()
    filled, trades = 0, []
    rows = conn.execute("SELECT thesis_id FROM thesis WHERE arm = ? AND horizon = ? ORDER BY rowid", (arm, horizon))
    for (thesis_id,) in rows.fetchall():
        events = journal.events_for(conn, thesis_id)
        last = events[-1].state if events else "PROPOSED"
        states["CLOSED" if last == "GRADED" else last] += 1
        opened = next((e for e in events if e.state == "OPEN"), None)
        filled += opened is not None
        grade = graded(conn, thesis_id)
        if grade is not None and opened is not None:
            trades.append(trade(conn, grade, opened))
    no_trades, answered = abstention(conn, horizon)
    return Card(arm, horizon, dict(states), filled, no_trades, answered, tuple(trades))


def graded(conn: sqlite3.Connection, thesis_id: str) -> Grade | None:
    """The thesis's Grade, if `tr grade` wrote one."""
    row = conn.execute("SELECT body FROM grade WHERE thesis_id = ?", (thesis_id,)).fetchone()
    return Grade.model_validate_json(row[0]) if row else None


def trade(conn: sqlite3.Connection, grade: Grade, opened: Event) -> Trade:
    """A graded thesis as a Trade: its outcome, its shadow's r_net and its P1 result."""
    shadow = journal.shadow_outcome(conn, grade.shadow_id)
    o = grade.outcome
    return Trade(grade.thesis_id, opened.at.astimezone(sessions.NY).date(), o.r_net,
                 shadow.r_net if shadow else None, o.mfe_r, o.mae_r, p1_result(conn, grade))


def p1_result(conn: sqlite3.Connection, grade: Grade) -> P1 | None:
    """The trade's P1 verdict. Today's only source is the Grade's process score (pass = 1.0; an `unknown:` explanation
    is unknown, rubric p1_thesis_quality); G9b's judge store plugs in here."""
    if grade.process_score_id is None:
        return None
    row = conn.execute("SELECT body FROM score WHERE score_id = ?", (grade.process_score_id,)).fetchone()
    if row is None:
        return None
    score = ScoreRecord.model_validate_json(row[0])
    if (score.explanation or "").startswith("unknown:"):
        return "unknown"
    return "met" if score.value == 1.0 else "not_met"


def abstention(conn: sqlite3.Connection, horizon: str) -> tuple[int, int]:
    """(no-trades, decisions) for one horizon on main analyses. A no_trade row carries no arm, so this rate belongs
    to the main analyses, not to one thesis arm."""
    no_trades = conn.execute("SELECT count(*) FROM no_trade n JOIN analysis a USING (analysis_id) "
                             "WHERE a.arm = 'main' AND n.horizon = ?", (horizon,)).fetchone()[0]
    theses = conn.execute("SELECT count(*) FROM thesis WHERE horizon = ? AND arm IN ('champion', 'challenger')",
                          (horizon,)).fetchone()[0]
    return no_trades, no_trades + theses


def run_costs(conn: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    """Per `tr daily` run: (total cost, teacher part) from its stored daily_run rows, which carry the run files'
    measured cost."""
    costs: dict[str, tuple[float, float]] = {}
    for row in journal.daily_runs(conn):
        total, teacher = costs.get(row["daily_id"], (0.0, 0.0))
        cost = row["cost_usd"] or 0.0
        is_teacher = row["reason"].startswith(f"{TEACHER} ")
        costs[row["daily_id"]] = (total + cost, teacher + (cost if is_teacher else 0.0))
    return costs


def cluster_count(trades: list[Trade] | tuple[Trade, ...]) -> int:
    """Distinct entry sessions: the bootstrap's clusters."""
    return len({t.session for t in trades})


def bootstrap(a: list[float], b: list[float], trades: list[Trade] | tuple[Trade, ...]) -> ClusterBootstrap | None:
    """Mean of b - a with a cluster bootstrap over entry sessions; None under MIN_CLUSTERS sessions, where §7.5 says
    an interval would be overconfident."""
    if cluster_count(trades) < MIN_CLUSTERS:
        return None
    return paired_cluster_bootstrap(a, b, [t.session for t in trades], resamples=RESAMPLES, seed=SEED)


def mean_r(trades: tuple[Trade, ...]) -> ClusterBootstrap | None:
    """Mean r_net and its interval (b - 0)."""
    return bootstrap([0.0] * len(trades), [t.r_net for t in trades], trades)


def paired(trades: tuple[Trade, ...]) -> list[Trade]:
    """Trades whose shadow has an outcome: the only ones a real-vs-shadow difference can use."""
    return [t for t in trades if t.shadow_r_net is not None]


def real_vs_shadow(trades: tuple[Trade, ...]) -> ClusterBootstrap | None:
    """Real minus shadow r_net, paired per trade, clustered by entry session."""
    pairs = paired(trades)
    return bootstrap([t.shadow_r_net for t in pairs], [t.r_net for t in pairs], pairs)


def two_by_two(trades: tuple[Trade, ...]) -> dict[str, int]:
    """§7.2: outcome (r_net > 0) against process (P1 met); unknown P1 is left out."""
    table = {"Earned": 0, "Lucky": 0, "Unlucky": 0, "Deserved": 0}
    for t in trades:
        if t.p1 in ("met", "not_met"):
            won, met = t.r_net > 0, t.p1 == "met"
            table[{(True, True): "Earned", (True, False): "Lucky",
                   (False, True): "Unlucky", (False, False): "Deserved"}[(won, met)]] += 1
    return table


def ratio(k: int, n: int) -> str:
    """`k/n = p%`, or n/a when nothing is counted (never a division by zero)."""
    return f"{k}/{n} = {k / n:.1%}" if n else "n/a (0 of 0)"


def interval(boot: ClusterBootstrap | None, trades: list[Trade] | tuple[Trade, ...]) -> str:
    """The interval text, or why there is none."""
    count = cluster_count(trades)
    if boot is None:
        return f"insufficient ({count} sessions < {MIN_CLUSTERS})"
    return (f"[{boot.ci.lower:+.2f}, {boot.ci.upper:+.2f}] (cluster bootstrap over {count} entry sessions, "
            f"{RESAMPLES} resamples, seed {SEED})")


def detectable(trades: tuple[Trade, ...]) -> str:
    """§7.6 power line: the smallest mean r_net effect this n can detect, from the measured sigma."""
    n = len(trades)
    if n < 2:
        return f"  with n = {n}, the detectable effect is not computable (sigma needs at least 2 closed trades)"
    sd = statistics.stdev(t.r_net for t in trades)
    m = mde_continuous(n, sd)
    return (f"  with n = {n}, only effects >= {m.mde:.2f} R are detectable "
            f"(sigma {sd:.2f} R from these trades, alpha {m.alpha}, power {m.power})")


def process_lines(trades: tuple[Trade, ...]) -> list[str]:
    """P1 met rate and the 2x2, only when P1 results exist."""
    judged = [t for t in trades if t.p1 is not None]
    if not judged:
        return ["  P1: no judged trades"]
    decided = [t for t in judged if t.p1 != "unknown"]
    unknown = len(judged) - len(decided)
    if not decided:
        return [f"  P1: {unknown} unknown, none met or not met"]
    met = sum(t.p1 == "met" for t in decided)
    w = wilson_interval(met, len(decided))
    table = two_by_two(trades)
    return [f"  P1 met {met}/{len(decided)} = {w.proportion:.1%}, 95% CI [{w.ci.lower:.1%}, {w.ci.upper:.1%}] "
            f"(Wilson); {unknown} unknown excluded",
            "               P1 met       P1 not met",
            f"  r_net > 0    Earned {table['Earned']:<5} Lucky {table['Lucky']}",
            f"  r_net <= 0   Unlucky {table['Unlucky']:<4} Deserved {table['Deserved']}"]


def stats_lines(trades: tuple[Trade, ...]) -> list[str]:
    """Win rate, mean r_net, real vs shadow, MFE/MAE, power and P1 over the graded trades."""
    n = len(trades)
    wins = sum(t.r_net > 0 for t in trades)
    w = wilson_interval(wins, n)
    lines = [f"  win rate {wins}/{n} = {w.proportion:.1%}, 95% CI [{w.ci.lower:.1%}, {w.ci.upper:.1%}] (Wilson)",
             f"  mean r_net {statistics.fmean(t.r_net for t in trades):+.2f} R, 95% CI {interval(mean_r(trades), trades)}"]
    pairs = paired(trades)
    if pairs:
        diff = statistics.fmean(t.r_net - t.shadow_r_net for t in pairs)
        lines.append(f"  real - shadow {diff:+.2f} R over {len(pairs)} pairs, 95% CI "
                     f"{interval(real_vs_shadow(trades), pairs)}")
    else:
        lines.append("  real - shadow: no shadow outcome yet")
    lines.append(f"  median MFE {statistics.median(t.mfe_r for t in trades):+.2f} R, "
                 f"median MAE {statistics.median(t.mae_r for t in trades):+.2f} R")
    return [*lines, detectable(trades), *process_lines(trades)]


def render_card(c: Card) -> list[str]:
    """One scorecard: counts always; statistics only over graded trades."""
    s = Counter(c.states)
    lines = [f"{c.arm} {c.horizon}: {sum(s.values())} theses: {s['CLOSED']} closed ({len(c.trades)} graded), "
             f"{s['EXPIRED']} expired, {s['CANCELLED']} cancelled, {s['OPEN']} open, {s['PROPOSED']} proposed",
             f"  fill rate {ratio(c.filled, c.filled + s['EXPIRED'])} (filled / (filled + expired)); abstention "
             f"{ratio(c.no_trades, c.answered)} (no-trades / main-analysis decisions for {c.horizon}, both arms)"]
    if c.trades:
        return lines + stats_lines(c.trades)
    if s["CLOSED"]:
        return [*lines, f"  no graded trades yet: {s['CLOSED']} closed, waiting for their shadows (tr grade)"]
    return [*lines, "  no closed trades yet"]


def cost_line(costs: dict[str, tuple[float, float]]) -> str:
    """Cost per `tr daily` run from the stored rows."""
    if not costs:
        return "cost per tr daily run: no run recorded"
    totals = [total for total, _ in costs.values()]
    teacher = sum(t for _, t in costs.values())
    return (f"cost per tr daily run: {len(costs)} runs, total ${sum(totals):.6f}, mean ${statistics.fmean(totals):.6f}, "
            f"max ${max(totals):.6f}; teacher steps ${teacher:.6f} of the total")


def render(card_list: list[Card], costs: dict[str, tuple[float, float]]) -> list[str]:
    """The header, one block per card, then the cost line."""
    lines = ["report: champion and challenger theses only (teacher theses never enter a scorecard); "
             "one scorecard per horizon, never pooled"]
    for c in card_list:
        lines.extend(render_card(c))
    lines.append(cost_line(costs))
    return lines
