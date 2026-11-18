"""`tr guards`: read the audit log (GUARDS-SPIKE §3.3), the last guard decisions and their counts; `tr guards scan`:
search a directory for key-shaped strings, read only (redact.py). No model call."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .. import guards, redact
from .usage import show

HEADER = ("at", "stage", "decision", "rule", "ticker", "horizon", "run", "subject", "detail")
SCAN_HEADER = ("file", "line", "pattern", "hits")


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


def cmd_scan(args, cfg) -> None:
    """Every file under the directory against redact's patterns and the configured keys' exact values: the file,
    line and pattern name of each hit, never the text; any hit exits 1. A missing directory is refused, never 0 hits."""
    root = Path(args.dir) if args.dir else cfg.data_dir
    if not root.is_dir():
        raise SystemExit(f"guards scan: {root} is not a directory")
    redact.configure(cfg)
    files, hits = redact.scan(root)
    print(f"key scan {root}: {files} file(s), {sum(n for *_, n in hits)} hit(s) (patterns "
          f"{', '.join(redact.PATTERNS)}, and the configured keys by exact value)")
    if hits:
        show([SCAN_HEADER, *[(str(path.relative_to(root)), str(line), name, str(n))
                             for path, line, name, n in hits]], 3)
        raise SystemExit(1)


def register(sub) -> None:
    p = sub.add_parser("guards", help="the audit log: the last guard decisions and counts by rule (no model call)",
                       description="read <data_dir>/audit.jsonl (GUARDS-SPIKE §3.3): the last guard decisions, then "
                                   "counts by stage, rule and decision; an empty or missing log prints the header")
    p.add_argument("--rule", metavar="ID", help="only this rule's decisions (e.g. stop_floor, one_live)")
    p.add_argument("--run", metavar="RUN_ID", help="only this run's decisions")
    p.add_argument("--last", type=int, default=20, metavar="N", help="show the last N decisions (default 20)")
    p.set_defaults(func=cmd_guards)
    scan = p.add_subparsers(title="subcommands", metavar="{scan}").add_parser(
        "scan", help="search a directory for keys and tokens, read only (exit 1 on a hit)",
        description="search every file under a directory for key-shaped strings (redact.PATTERNS) and the configured "
                    "keys' exact values; prints file, line and pattern name, never the text; exit 1 on any hit")
    scan.add_argument("--dir", metavar="DIR", help="the directory to search (default: the data dir)")
    scan.set_defaults(func=cmd_scan)
