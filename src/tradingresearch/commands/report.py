"""`tr report`: per-horizon scorecards of champion and challenger theses (SPIKE §7.5, §7.6); `--export PATH` also
writes the aggregates as one publishable JSON file (SPIKE §11). No model call."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import journal, sessions
from .. import report as scorecards


def cmd_report(args, cfg) -> None:
    if args.export is not None and args.export.exists() and not args.force:
        print(f"refused: {args.export} exists; --force overwrites it", file=sys.stderr)
        raise SystemExit(2)
    conn = journal.connect(cfg.db_path)
    since = None if args.include_pre_live else sessions.FIRST_SESSION
    arms = [args.arm] if args.arm else scorecards.arms_shown(conn, since)
    horizons = [args.horizon] if args.horizon else list(scorecards.HORIZONS)
    excluded = scorecards.pre_live(conn, [args.arm] if args.arm else list(scorecards.ARMS), horizons) if since else None
    card_list = scorecards.cards(conn, arms, horizons, since)
    print("\n".join(scorecards.render(card_list, scorecards.run_costs(conn, since), since, excluded or ((), ()))))
    if args.export is not None:
        args.export.write_text(scorecards.export_text(card_list, since))
        shown = sum(1 for c in card_list if c.trades)
        print(f"exported {shown} graded scorecards (aggregates only) to {args.export}" if shown else
              f'exported to {args.export}: no graded trades yet, "arms": []')


def register(sub) -> None:
    p = sub.add_parser("report", help="per-horizon scorecards: win rate, r_net, shadow, power, P1 (no model call)")
    p.add_argument("--horizon", choices=scorecards.HORIZONS, help="one horizon (default: each, never pooled)")
    p.add_argument("--arm", choices=scorecards.ARMS,
                   help="one arm (default: champion, plus challenger once it has a thesis)")
    p.add_argument("--include-pre-live", action="store_true",
                   help=f"also count theses and runs before the live stream ({sessions.FIRST_SESSION}): dev runs")
    p.add_argument("--export", type=Path, metavar="PATH",
                   help="also write the graded scorecards' aggregates as JSON (no ticker, id or text)")
    p.add_argument("--force", action="store_true", help="with --export: overwrite an existing PATH")
    p.set_defaults(func=cmd_report)
