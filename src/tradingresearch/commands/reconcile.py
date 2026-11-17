"""`tr reconcile`: settle every PROPOSED or OPEN thesis from raw bars after the close (SPIKE §6). No model call."""

from __future__ import annotations

from datetime import UTC, date, datetime

from .. import journal, reconcile_run, sessions
from .common import alpaca_client, session_arg


def completed_session(text: str | None, now: datetime) -> date:
    """The session to settle: default the latest completed one; a session whose close + 15 min (16:15 ET on a full
    day) has not passed is refused, because its SIP bars are not final yet."""
    latest = sessions.last_completed(now)
    if text is None:
        return latest
    day = session_arg(text)
    if day > latest:
        raise SystemExit(f"{day} is not complete yet: reconcile runs 15 minutes after the close (16:15 ET on a full "
                         f"day); the latest completed session is {latest}")
    return day


def cmd_reconcile(args, cfg) -> None:
    day = completed_session(args.session, datetime.now(UTC))
    conn = journal.connect(cfg.db_path)
    if not journal.open_theses(conn) and not journal.open_shadow_ids(conn):
        print("nothing to settle")
        return
    with alpaca_client(cfg) as http:
        report = reconcile_run.run(conn, reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed), day,
                                   dry_run=args.dry_run)
    print("\n".join(reconcile_run.render(report)))


def register(sub) -> None:
    p = sub.add_parser("reconcile", help="settle PROPOSED and OPEN theses from raw bars (no model call)")
    p.add_argument("--session", help="a completed session (default: the latest, after 16:15 ET)")
    p.add_argument("--dry-run", action="store_true", help="print what would be appended; write nothing")
    p.set_defaults(func=cmd_reconcile)
