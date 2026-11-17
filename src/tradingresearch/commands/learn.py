"""`tr learn`: the playbook (SPIKE §8.1) and the pre-registered champion/challenger rule changes (§8.2-8.3).
No model call; only `--decide` writes, and only a final decision."""

from __future__ import annotations

from gigai_core.stats import MIN_CLUSTERS, ClusterBootstrap

from .. import adopt, journal, playbook, report
from ..records import RuleChange
from .common import session_arg

EMPTY = adopt.SessionPairs((), (), (), (), (), waiting=None)


def ci_text(boot: ClusterBootstrap | None, sessions: int) -> str:
    if boot is None:
        return f"insufficient ({sessions} sessions < {MIN_CLUSTERS})"
    return (f"{boot.difference:+.2f}, 95% CI [{boot.ci.lower:+.2f}, {boot.ci.upper:+.2f}] (cluster bootstrap over "
            f"{boot.clusters} sessions, {report.RESAMPLES} resamples, seed {report.SEED})")


def head(change: RuleChange) -> str:
    p = change.prereg
    return (f"{change.change_id} [{change.decided}] {journal.prereg_horizon(p)}: {change.description} (diff "
            f"{change.diff_ref}; registered {p.registered_at:%Y-%m-%d %H:%M %Z}, active from "
            f"{adopt.activation(p.registered_at)})")


def pair_lines(pairs: adopt.SessionPairs, d: adopt.Decision) -> list[str]:
    waiting = f"; waiting on session {pairs.waiting} (a thesis is not graded, expired or cancelled yet)" \
        if pairs.waiting else ""
    if pairs.excluded:
        waiting += (f"; left out {len(pairs.excluded)}, the challenger never answered: "
                    f"{', '.join(map(str, pairs.excluded))}")
    guard_sessions = sum(a is not None and b is not None for a, b in zip(pairs.champion_p1, pairs.challenger_p1))
    return [f"  paired sessions so far: {d.n_pairs} of {adopt.N_PLANNED}{waiting}",
            f"  delta session r_net (challenger - champion) {ci_text(d.delta_ci, d.n_pairs)}",
            f"  P1 met-rate guard (challenger - champion) {ci_text(d.p1_guard_ci, guard_sessions)}"]


def status_lines(conn) -> list[str]:
    changes = journal.rule_changes(conn)
    lines = [f"rule changes (SPIKE §8.2-8.3): {len(changes)} registered" if changes else
             "rule changes (SPIKE §8.2-8.3): none registered yet; a change is pre-registered before its first "
             "challenger thesis", f"rule: {adopt.RULE}"]
    shown = EMPTY
    for change in changes:
        lines.append(head(change))
        if change.decided == "pending":
            shown = adopt.sessions_r(conn, change.change_id)
            d = adopt.decide_pairs(shown, adopt.day60_reached())
            lines += [*pair_lines(shown, d), f"  the rule today: {d.status} ({d.reason})"]
    return lines + adopt.mde_lines(shown)


def decide_lines(conn, change_id: str) -> list[str]:
    try:
        change = adopt.find(conn, change_id)
    except KeyError as e:
        raise SystemExit(str(e.args[0])) from None
    if change.decided != "pending":
        raise SystemExit(f"{change_id} is already {change.decided}: a decision is final")
    pairs = adopt.sessions_r(conn, change_id)
    d = adopt.decide_pairs(pairs, adopt.day60_reached())
    lines = [head(change), f"rule: {adopt.RULE}", *pair_lines(pairs, d)]
    if d.status == "pending":
        return [*lines, f"{change_id}: pending, {d.reason}; nothing written"]
    journal.decide_rule_change(conn, change_id, d.status)
    return [*lines, f"{change_id}: {d.status} ({d.reason}); written to the journal, final"]


def cmd_learn(args, cfg) -> None:
    conn = journal.connect(cfg.db_path)
    if args.decide:
        lines = decide_lines(conn, args.decide)
    elif args.status:
        lines = status_lines(conn)
    else:
        lines = playbook.render(playbook.compute(conn, session_arg(args.session), args.arm))
    print("\n".join(lines))


def register(sub) -> None:
    p = sub.add_parser("learn", help="playbook per horizon and setup; rule changes and their adoption (no model call)")
    p.add_argument("--session", help="playbook as of this session, YYYY-MM-DD (default: last completed)")
    p.add_argument("--arm", choices=report.ARMS, default="champion", help="playbook arm (default: champion)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="rule changes, pairs so far, decision rule, MDE")
    mode.add_argument("--decide", metavar="CHANGE_ID", help="apply the §8.3 rule; writes only a final decision")
    p.set_defaults(func=cmd_learn)
