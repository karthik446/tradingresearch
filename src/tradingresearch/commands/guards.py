"""`tr guards`: read the audit log (GUARDS-SPIKE §3.3), the last guard decisions and their counts (no model call)."""

from __future__ import annotations

from collections import Counter

from .. import guards
from .usage import show

HEADER = ("at", "stage", "decision", "rule", "ticker", "horizon", "run", "subject", "detail")


def row(r: guards.AuditRecord) -> tuple[str, ...]:
    """One decision as table cells; ids and the rule's own detail only, never fetched text."""
    return (r.at.strftime("%Y-%m-%d %H:%M:%S"), r.stage, r.decision, f"{r.rule}@{r.rule_version}", r.ticker or "-",
            r.horizon or "-", r.run_id or "-", r.subject.id, r.detail)


def cmd_guards(args, cfg) -> None:
    every, bad = guards.read_audit(cfg.data_dir)
    kept = [r for r in every if (not args.rule or r.rule == args.rule) and (not args.run or r.run_id == args.run)]
    skipped = f"; {bad} malformed line(s) skipped" if bad else ""
    print(f"audit log {cfg.data_dir / guards.AUDIT_FILE}: {len(kept)} of {len(every)} decision(s) match "
          f"(rule {args.rule or 'any'}, run {args.run or 'any'}){skipped}")
    show([HEADER, *[row(r) for r in kept[-args.last:] if args.last > 0]], len(HEADER))
    counts = Counter((r.stage, r.rule, r.decision) for r in kept)
    if counts:
        print("counts by stage, rule, decision:")
        show([(stage, rule, decision, str(n)) for (stage, rule, decision), n in sorted(counts.items())], 3)


def register(sub) -> None:
    p = sub.add_parser("guards", help="the audit log: the last guard decisions and counts by rule (no model call)",
                       description="read <data_dir>/audit.jsonl (GUARDS-SPIKE §3.3): the last guard decisions, then "
                                   "counts by stage, rule and decision; an empty or missing log prints the header")
    p.add_argument("--rule", metavar="ID", help="only this rule's decisions (e.g. stop_floor, one_live)")
    p.add_argument("--run", metavar="RUN_ID", help="only this run's decisions")
    p.add_argument("--last", type=int, default=20, metavar="N", help="show the last N decisions (default 20)")
    p.set_defaults(func=cmd_guards)
