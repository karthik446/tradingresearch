"""`tr bakeoff`: the teacher bake-off's date-seeded draw and its report (SPIKE §9.4). No model call."""

from __future__ import annotations

from .. import bakeoff, daily, journal, screen, teacher
from .common import session_arg


def cmd_bakeoff_draw(args, cfg) -> None:
    day = session_arg(args.session)
    results = screen.stored(journal.connect(cfg.db_path), day)
    if not results:
        raise SystemExit(f"no stored screen for {day}: run `tr screen --session {day}` first")
    shortlist = daily.shortlist(results, bakeoff.SHORTLIST)
    print(f"bake-off draw {day}: {' '.join(teacher.draw(day, shortlist))}  "
          f"({teacher.BAKEOFF_NAMES} of a shortlist of {len(shortlist)}, seeded by sha256 of {day.isoformat()})")


def cmd_bakeoff_report(args, cfg) -> None:
    print(bakeoff.render(*bakeoff.report(journal.connect(cfg.db_path), cfg.data_dir)))


def register(sub) -> None:
    p = sub.add_parser("bakeoff", help="the teacher bake-off: date-seeded draw and report (no model call)")
    bake = p.add_subparsers(dest="bakeoff_command", required=True)
    p = bake.add_parser("draw", help="the session's 4 bake-off names from its stored shortlist")
    p.add_argument("--session", help="a completed session (default: the last one)")
    p.set_defaults(func=cmd_bakeoff_draw)
    p = bake.add_parser("report", help="per-teacher pick-rule inputs and eligibility; no automatic pick")
    p.set_defaults(func=cmd_bakeoff_report)
