"""`tr split`: register the held-out training split and show the sessions it derives (SPIKE §1.1, TRAINING-SPIKE
§7.2 row 4, §7.3). No model call; only `register` writes."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from .. import journal, split


def cmd_split_register(args, cfg) -> None:
    now = datetime.now(UTC)
    try:
        cutoff = date.fromisoformat(args.cutoff)
    except ValueError:
        raise SystemExit(f"--cutoff {args.cutoff!r} is not YYYY-MM-DD") from None
    conn = journal.connect(cfg.db_path)
    try:
        prereg = split.prereg_from(Path(args.prereg_json).read_text() if args.prereg_json else None, args.note, now)
        held = split.find(conn, split.split_id_for(cutoff, args.embargo, prereg))
        record = split.register(conn, cutoff, args.embargo, prereg, now)
    except split.Refused as refused:
        raise SystemExit(str(refused)) from None
    stored = "already registered, nothing written" if held else "stored"
    print(f"{stored}: {record.split_id} (cutoff {record.cutoff_session}, embargo {record.embargo_sessions})")


def cmd_split_show(args, cfg) -> None:
    conn = journal.connect(cfg.db_path)
    try:
        record = split.governing(conn, args.split_id)
    except split.Refused as refused:
        raise SystemExit(str(refused)) from None
    print("\n".join(split.render(record, split.derive(conn, record.split_id), len(split.splits(conn)))))


def register(sub) -> None:
    p = sub.add_parser("split", help="register the held-out training split; show its sessions (no model call)")
    actions = p.add_subparsers(dest="split_command", required=True)
    p = actions.add_parser("register", help="store a TrainingSplit before its cutoff session (append-only)")
    p.add_argument("--cutoff", required=True, help="first test session, YYYY-MM-DD (a future NYSE session)")
    p.add_argument("--embargo", type=int, required=True, help=f"sessions left out before the cutoff (>= "
                   f"{split.MIN_EMBARGO})")
    p.add_argument("--prereg-json", metavar="FILE", help="Prereg fields as JSON, without registered_at (default: the "
                   "TRAINING-SPIKE §7.3 gate)")
    p.add_argument("--note", help="the hypothesis the Prereg tests")
    p.set_defaults(func=cmd_split_register)
    p = actions.add_parser("show", help="the split's train/val, embargoed and test sessions with counts (read-only)")
    p.add_argument("split_id", nargs="?", help="default: the latest registered split")
    p.set_defaults(func=cmd_split_show)
