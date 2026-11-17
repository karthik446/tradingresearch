"""`tr grade`: shadows and grades for closed champion and challenger theses (SPIKE §7.1, §7.4). No model call."""

from __future__ import annotations

from datetime import UTC, datetime

from .. import grade, journal, reconcile_run
from .common import alpaca_client
from .reconcile import completed_session


def cmd_grade(args, cfg) -> None:
    day = completed_session(args.session, datetime.now(UTC))
    conn = journal.connect(cfg.db_path)
    if all(state == "PROPOSED" for _, state in journal.ungraded_theses(conn)):  # nothing filled: no bars to read
        report = grade.run(conn, None, day, dry_run=args.dry_run)
    else:
        with alpaca_client(cfg) as http:
            bars = reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed)
            report = grade.run(conn, bars, day, dry_run=args.dry_run)
    print("\n".join(grade.render(report)))


def register(sub) -> None:
    p = sub.add_parser("grade", help="shadow baselines and grades for closed theses (no model call)")
    p.add_argument("--session", help="a completed session (default: the latest, after 16:15 ET)")
    p.add_argument("--dry-run", action="store_true", help="print what would be created or graded; write nothing")
    p.set_defaults(func=cmd_grade)
