"""`tr report`: per-horizon scorecards of champion and challenger theses (SPIKE §7.5, §7.6). No model call."""

from __future__ import annotations

from .. import journal, sessions
from .. import report as scorecards


def cmd_report(args, cfg) -> None:
    conn = journal.connect(cfg.db_path)
    since = None if args.include_pre_live else sessions.FIRST_SESSION
    arms = [args.arm] if args.arm else scorecards.arms_shown(conn, since)
    horizons = [args.horizon] if args.horizon else list(scorecards.HORIZONS)
    excluded = scorecards.pre_live(conn, [args.arm] if args.arm else list(scorecards.ARMS), horizons) if since else None
    card_list = scorecards.cards(conn, arms, horizons, since)
    print("\n".join(scorecards.render(card_list, scorecards.run_costs(conn, since), since, excluded or ((), ()))))


def register(sub) -> None:
    p = sub.add_parser("report", help="per-horizon scorecards: win rate, r_net, shadow, power, P1 (no model call)")
    p.add_argument("--horizon", choices=scorecards.HORIZONS, help="one horizon (default: each, never pooled)")
    p.add_argument("--arm", choices=scorecards.ARMS,
                   help="one arm (default: champion, plus challenger once it has a thesis)")
    p.add_argument("--include-pre-live", action="store_true",
                   help=f"also count theses and runs before the live stream ({sessions.FIRST_SESSION}): dev runs")
    p.set_defaults(func=cmd_report)
