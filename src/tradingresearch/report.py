"""`tr report`: one scorecard per arm and horizon, never pooled across horizons (SPIKE §7.5 statistics, §7.6 power,
§7.2 the 2x2). Only champion and challenger theses are read; teacher theses never enter a scorecard. Only the live
stream counts by default: theses whose analysis session, and `tr daily` runs whose session, is on or after
`sessions.FIRST_SESSION`; the earlier ones are counted and named, never dropped silently. Reads the journal only; no
model call, no network."""

from __future__ import annotations

import json
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


def arms_shown(conn: sqlite3.Connection, since: date | None = sessions.FIRST_SESSION) -> list[str]:
    """Champion always; challenger only once it has a thesis, so an unused arm prints no empty cards."""
    has = conn.execute("SELECT 1 FROM thesis t JOIN analysis a USING (analysis_id) WHERE t.arm = 'challenger' "
                       "AND (? IS NULL OR a.session >= ?) LIMIT 1", (since and since.isoformat(),) * 2).fetchone()
    return ["champion", "challenger"] if has else ["champion"]


def cards(conn: sqlite3.Connection, arms: list[str], horizons: list[str],
          since: date | None = sessions.FIRST_SESSION) -> list[Card]:
    """One card per (arm, horizon), in that order, over theses analysed on or after `since` (None: every session)."""
    return [card(conn, arm, horizon, since) for arm in arms for horizon in horizons]


def card(conn: sqlite3.Connection, arm: str, horizon: str, since: date | None = sessions.FIRST_SESSION) -> Card:
    """Count one arm's theses at one horizon by last state, and collect its graded trades."""
    if arm not in ARMS:
        raise ValueError(f"arm {arm!r} has no scorecard: only {', '.join(ARMS)}")
    states: Counter[str] = Counter()
    filled, trades = 0, []
    rows = conn.execute("SELECT t.thesis_id FROM thesis t JOIN analysis a USING (analysis_id) WHERE t.arm = ? "
                        "AND t.horizon = ? AND (? IS NULL OR a.session >= ?) ORDER BY t.rowid",
                        (arm, horizon, *(since and since.isoformat(),) * 2))
    for (thesis_id,) in rows.fetchall():
        events = journal.events_for(conn, thesis_id)
        last = events[-1].state if events else "PROPOSED"
        states["CLOSED" if last == "GRADED" else last] += 1
        opened = next((e for e in events if e.state == "OPEN"), None)
        filled += opened is not None
        grade = graded(conn, thesis_id)
        if grade is not None and opened is not None:
            trades.append(trade(conn, grade, opened))
    no_trades, answered = abstention(conn, horizon, since)
    return Card(arm, horizon, dict(states), filled, no_trades, answered, tuple(trades))


def pre_live(conn: sqlite3.Connection, arms: list[str], horizons: list[str],
             since: date = sessions.FIRST_SESSION) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(thesis ids, daily ids) a `since` report leaves out: the shown arms' and horizons' theses analysed earlier, and
    the `tr daily` runs of earlier sessions."""
    marks = ", ".join("?" * len(arms)), ", ".join("?" * len(horizons))
    theses = conn.execute(f"SELECT t.thesis_id FROM thesis t JOIN analysis a USING (analysis_id) WHERE t.arm IN "
                          f"({marks[0]}) AND t.horizon IN ({marks[1]}) AND a.session < ? ORDER BY t.rowid",
                          (*arms, *horizons, since.isoformat())).fetchall()
    runs = conn.execute("SELECT daily_id FROM daily_run WHERE session < ? GROUP BY daily_id ORDER BY min(seq)",
                        (since.isoformat(),)).fetchall()
    return tuple(t for (t,) in theses), tuple(d for (d,) in runs)


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
    """The trade's P1 verdict: the latest stored judge verdict, else the Grade's process score (pass = 1.0; an
    `unknown:` explanation is unknown, rubric p1_thesis_quality)."""
    verdict = journal.judge_verdict(conn, grade.thesis_id)
    if verdict is not None:
        if journal.abstained(verdict):
            return "unknown"
        return "met" if verdict["verdict"] == "pass" else "not_met"
    if grade.process_score_id is None:
        return None
    row = conn.execute("SELECT body FROM score WHERE score_id = ?", (grade.process_score_id,)).fetchone()
    if row is None:
        return None
    score = ScoreRecord.model_validate_json(row[0])
    if (score.explanation or "").startswith("unknown:"):
        return "unknown"
    return "met" if score.value == 1.0 else "not_met"


def abstention(conn: sqlite3.Connection, horizon: str, since: date | None = sessions.FIRST_SESSION) -> tuple[int, int]:
    """(no-trades, decisions) for one horizon on main analyses. A no_trade row carries no arm, so this rate belongs
    to the main analyses, not to one thesis arm."""
    on = (since and since.isoformat(),) * 2
    no_trades = conn.execute("SELECT count(*) FROM no_trade n JOIN analysis a USING (analysis_id) "
                             "WHERE a.arm = 'main' AND n.horizon = ? AND (? IS NULL OR a.session >= ?)",
                             (horizon, *on)).fetchone()[0]
    theses = conn.execute("SELECT count(*) FROM thesis t JOIN analysis a USING (analysis_id) WHERE t.horizon = ? "
                          "AND t.arm IN ('champion', 'challenger') AND (? IS NULL OR a.session >= ?)",
                          (horizon, *on)).fetchone()[0]
    return no_trades, no_trades + theses


def run_costs(conn: sqlite3.Connection, since: date | None = sessions.FIRST_SESSION) -> dict[str, tuple[float, float]]:
    """Per `tr daily` run of a session on or after `since`: (total cost, teacher part) from its stored daily_run rows,
    which carry the run files' measured cost."""
    costs: dict[str, tuple[float, float]] = {}
    for row in journal.daily_runs(conn):
        if since is not None and row["session"] < since.isoformat():
            continue
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


def scope_lines(since: date | None, excluded: tuple[tuple[str, ...], tuple[str, ...]]) -> list[str]:
    """The header, and on the live stream the one line counting and naming what it leaves out."""
    scope = (f"live stream from {since}" if since else
             f"every session, pre-live included (the live stream starts {sessions.FIRST_SESSION})")
    lines = [f"report: {scope}; champion and challenger theses only (teacher theses never enter a scorecard); "
             "one scorecard per horizon, never pooled"]
    if since is None:
        return lines
    theses, runs = excluded
    named = f": {', '.join(theses)}" if theses else ""
    return [*lines, f"pre-live, excluded (before {since}): {len(theses)} theses{named}; {len(runs)} tr daily runs "
            "(--include-pre-live shows them)"]


def render(card_list: list[Card], costs: dict[str, tuple[float, float]], since: date | None = sessions.FIRST_SESSION,
           excluded: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())) -> list[str]:
    """The scope lines, one block per card, then the cost line."""
    lines = scope_lines(since, excluded)
    for c in card_list:
        lines.extend(render_card(c))
    lines.append(cost_line(costs))
    return lines


# -- export: the aggregate scorecards as one JSON file a reader can publish (SPIKE §11, "Public") -------------------

EXPORT_SCHEMA = 1
STATES = ("CLOSED", "EXPIRED", "CANCELLED", "OPEN", "PROPOSED")  # the counts a card prints, GRADED inside CLOSED


def _rate(k: int, n: int) -> dict:
    """`k` of `n` and the proportion; null when nothing is counted, as the report's `n/a (0 of 0)`."""
    return {"k": k, "n": n, "p": k / n if n else None}


def _wilson(k: int, n: int) -> dict:
    """`k` of `n` (n >= 1) with its 95% Wilson interval."""
    w = wilson_interval(k, n)
    return {"k": k, "n": n, "p": w.proportion, "ci95": [w.ci.lower, w.ci.upper]}


def _boot(value: float, boot: ClusterBootstrap | None, trades: list[Trade] | tuple[Trade, ...]) -> dict:
    """A mean and its cluster-bootstrap interval; ci95 is null under MIN_CLUSTERS entry sessions (`insufficient`)."""
    return {"value": value, "clusters": cluster_count(trades),
            "ci95": None if boot is None else [boot.ci.lower, boot.ci.upper]}


def _p1(trades: tuple[Trade, ...]) -> dict | None:
    """P1 met over the met-or-not-met trades, the unknowns left out, and the 2x2; null with no judged trade."""
    judged = [t for t in trades if t.p1 is not None]
    if not judged:
        return None
    decided = [t for t in judged if t.p1 != "unknown"]
    met = _wilson(sum(t.p1 == "met" for t in decided), len(decided)) if decided else {**_rate(0, 0), "ci95": None}
    return {**met, "unknown": len(judged) - len(decided), "two_by_two": two_by_two(trades)}


def _stats(trades: tuple[Trade, ...]) -> dict:
    """The numbers `stats_lines` prints over a card's graded trades (at least one)."""
    n, pairs = len(trades), paired(trades)
    shadow = None
    if pairs:
        diff = statistics.fmean(t.r_net - t.shadow_r_net for t in pairs)
        shadow = {**_boot(diff, real_vs_shadow(trades), pairs), "pairs": len(pairs)}
    mde = None
    if n >= 2:
        sd = statistics.stdev(t.r_net for t in trades)
        m = mde_continuous(n, sd)
        mde = {"mde_r": m.mde, "sigma_r": sd, "alpha": m.alpha, "power": m.power}
    return {"win_rate": _wilson(sum(t.r_net > 0 for t in trades), n),
            "mean_r_net": _boot(statistics.fmean(t.r_net for t in trades), mean_r(trades), trades),
            "real_minus_shadow": shadow,
            "median_mfe_r": statistics.median(t.mfe_r for t in trades),
            "median_mae_r": statistics.median(t.mae_r for t in trades),
            "mde": mde, "p1": _p1(trades)}


def card_export(c: Card) -> dict:
    """One graded card as numbers: its counts, rates and statistics, never a thesis id, ticker or text."""
    s = Counter(c.states)
    return {"arm": c.arm, "horizon": c.horizon, "n": len(c.trades), "theses": sum(s.values()),
            "states": {state.lower(): s[state] for state in STATES},
            "fill_rate": _rate(c.filled, c.filled + s["EXPIRED"]), "abstention": _rate(c.no_trades, c.answered),
            **_stats(c.trades)}


def export(card_list: list[Card], since: date | None) -> dict:
    """The aggregate scorecards: one entry per (arm, horizon) card with a graded trade, in report order; `stream_from`
    is null when pre-live sessions are included."""
    return {"schema": EXPORT_SCHEMA, "stream_from": since and since.isoformat(),
            "arms": [card_export(c) for c in card_list if c.trades]}


def export_text(card_list: list[Card], since: date | None) -> str:
    """Sorted keys, 2-space indent, trailing newline: a rerun on the same data is byte-identical."""
    return json.dumps(export(card_list, since), indent=2, sort_keys=True, allow_nan=False) + "\n"
