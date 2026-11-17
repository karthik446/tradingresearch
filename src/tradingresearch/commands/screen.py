"""`tr screen`: the code-only daily shortlist (SPIKE §4.2). No model call."""

from __future__ import annotations

from pathlib import Path

from .. import journal, screen, sessions
from .common import alpaca_client, edgar_client, session_arg


def cmd_screen(args, cfg) -> None:
    day = session_arg(args.session)
    path = Path(args.universe) if args.universe else cfg.data_dir / "universe.txt"
    if not path.exists():
        raise SystemExit(f"no universe file at {path}: copy universe.example.txt there or pass --universe FILE")
    universe = screen.read_universe(path)
    conn = journal.connect(cfg.db_path)
    results = screen.stored(conn, day)
    if results:
        note = f"stored run, {len(results)} rows (a re-run adds nothing)"
    else:
        with alpaca_client(cfg) as http:
            fetched = screen.fetch_missing(conn, http, [*universe, "SPY"], day, cfg.feed)
        since = journal.last_screened(conn, day) or sessions.previous(day)
        results = screen.run(conn, edgar_client(cfg), universe, day, since, cfg.feed)
        note = f"fetched bars for {len(fetched)}, 8-Ks accepted after the {since} close"
    print(f"screen {day}  universe {len(universe)}  regime {screen.regime(conn, day, cfg.feed)}  "
          f"code {screen.CODE_VERSION}  {note}")
    print("\n".join(screen.render(results, args.top)))


def register(sub) -> None:
    p = sub.add_parser("screen", help="code-only daily shortlist of the universe (no model call)")
    p.add_argument("--session")
    p.add_argument("--universe", help="one ticker per line (default: $TR_DATA_DIR/universe.txt)")
    p.add_argument("--top", type=int, default=10)
    p.set_defaults(func=cmd_screen)
