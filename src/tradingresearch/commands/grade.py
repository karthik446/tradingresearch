"""`tr grade`: shadows and grades for closed champion and challenger theses (SPIKE §7.1, §7.4), no model call; with
`--judge`, also the P1 judge on graded theses that have no verdict (ADR-003), one paid call each."""

from __future__ import annotations

from datetime import UTC, datetime

from .. import evals, grade, journal, openrouter, reconcile_run
from ..config import require
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
    if args.judge:
        print("\n".join(judge_lines(conn, args, cfg)))


def judge_lines(conn, args, cfg) -> list[str]:
    """`--judge`: the key, prices and bars are read only when a thesis waits and this is not a dry run."""
    cap = args.judge_max_usd
    if args.dry_run or not grade.to_judge(conn):
        judged = grade.judge(conn, None, None, prices={}, data_dir=cfg.data_dir, max_usd=cap, dry_run=args.dry_run)
        return grade.render_judged(judged, dry_run=args.dry_run, max_usd=cap)
    provider = openrouter.OpenRouter(require(cfg.openrouter_key, "OPENROUTER_API_KEY"))
    try:
        prices = openrouter.prices([evals.JUDGE_MODEL])
        with alpaca_client(cfg) as http:
            bars = reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed)
            judged = grade.judge(conn, bars, provider, prices=prices, data_dir=cfg.data_dir, max_usd=cap)
    finally:
        provider.close()
    return grade.render_judged(judged, dry_run=False, max_usd=cap)


def register(sub) -> None:
    p = sub.add_parser("grade", help="shadow baselines and grades for closed theses (a paid P1 judge with --judge)")
    p.add_argument("--session", help="a completed session (default: the latest, after 16:15 ET)")
    p.add_argument("--dry-run", action="store_true", help="print what would be created or graded; write nothing")
    p.add_argument("--judge", action="store_true",
                   help=f"also run the P1 judge ({evals.JUDGE_MODEL}, one paid call per graded thesis without a "
                        "verdict; off by default)")
    p.add_argument("--judge-max-usd", type=float, default=grade.JUDGE_MAX_USD,
                   help="dollar cap for the whole judge run (default: %(default)s)")
    p.set_defaults(func=cmd_grade)
