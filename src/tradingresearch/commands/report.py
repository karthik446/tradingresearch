"""`tr report`: per-horizon scorecards of champion and challenger theses (SPIKE §7.5, §7.6). No model call."""

from __future__ import annotations

from .. import journal
from .. import report as scorecards


def cmd_report(args, cfg) -> None:
    conn = journal.connect(cfg.db_path)
    arms = [args.arm] if args.arm else scorecards.arms_shown(conn)
    horizons = [args.horizon] if args.horizon else list(scorecards.HORIZONS)
    print("\n".join(scorecards.render(scorecards.cards(conn, arms, horizons), scorecards.run_costs(conn))))


def register(sub) -> None:
    p = sub.add_parser("report", help="per-horizon scorecards: win rate, r_net, shadow, power, P1 (no model call)")
    p.add_argument("--horizon", choices=scorecards.HORIZONS, help="one horizon (default: each, never pooled)")
    p.add_argument("--arm", choices=scorecards.ARMS,
                   help="one arm (default: champion, plus challenger once it has a thesis)")
    p.set_defaults(func=cmd_report)
