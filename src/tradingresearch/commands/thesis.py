"""`tr thesis` (paid call) and `tr open`: theses from a stored Analysis, and the subjects still live (SPIKE §6.8, P5)."""

from __future__ import annotations

from datetime import UTC, datetime

from .. import analyze as an, journal, openrouter, sessions, teacher as tc, thesis as th
from ..config import require
from ..records import Analysis, Thesis
from .common import session_arg

ARMS = ("champion", "challenger", "teacher")


def analysis_for(conn, args) -> Analysis:
    """The stored analysis to write from; never runs analyze. Validator 6: a teacher thesis needs a teacher analysis
    (from the same teacher model), champion and challenger theses a main one."""
    wanted = "teacher" if args.arm == "teacher" else "main"
    if args.analysis:
        a = journal.get(conn, Analysis, args.analysis)
        if a.ticker != args.ticker:
            raise SystemExit(f"{a.analysis_id} is {a.ticker}, not {args.ticker}")
    else:
        day = session_arg(args.session)
        a = journal.latest_analysis(conn, args.ticker, day, wanted)
        if a is None:
            raise SystemExit(f"no {wanted} analysis for {args.ticker} {day}: run `tr analyze {args.ticker}` first")
    if a.arm != wanted:
        raise SystemExit(f"a {args.arm} thesis needs a {wanted} analysis; {a.analysis_id} is {a.arm}")
    teacher = getattr(args, "teacher", None)
    if wanted == "teacher" and teacher and a.model != teacher:
        raise SystemExit(f"{a.analysis_id} was written by {a.model}, not {teacher}: pass --analysis <id> of a "
                         f"{teacher} analysis")
    return a


def horizons_to_ask(conn, a: Analysis, arm: str, now: datetime) -> tuple[str, ...]:
    """The horizons worth a model call: entry windows not started yet, and no live thesis for the one_live key."""
    if arm != "teacher":
        start, _ = th.windows(a.session, "day")
        if start <= now:
            raise SystemExit(f"entry windows after {a.session} already started at {start.isoformat()}")
    live = journal.live_horizons(conn, a.ticker, arm) if arm != "teacher" else set()  # teacher arm is exempt (§6.7)
    for horizon in sorted(live):
        print(f"skip {a.ticker} {horizon} {arm}: a PROPOSED or OPEN thesis exists (one live per ticker, horizon, arm)")
    return tuple(h for h in th.HORIZONS if h not in live)


def entry_text(t: Thesis) -> str:
    return "open" if t.entry.price is None else f"{t.entry.kind}@{an.plain(t.entry.price)}"


def thesis_line(t: Thesis) -> str:
    return (f"{t.thesis_id}  {t.ticker} {t.horizon:<5} {t.direction:<5} {t.setup_type:<17} entry {entry_text(t)}  "
            f"stop {an.plain(t.stop)}  target {an.plain(t.target)}  hold {t.hold_sessions}  "
            f"evidence {','.join(t.evidence)}")


def cmd_thesis(args, cfg) -> None:
    teacher = tc.from_args(args.arm, args.teacher, args.model, th.DEFAULT_MODEL)
    model = teacher.model if teacher else args.model
    conn = journal.connect(cfg.db_path)
    a = analysis_for(conn, args)
    asked = horizons_to_ask(conn, a, args.arm, datetime.now(UTC))
    if not asked:
        print(f"nothing to ask for {a.ticker}: every horizon has a live {args.arm} thesis (no model call)")
        return
    provider = openrouter.OpenRouter(require(cfg.openrouter_key, "OPENROUTER_API_KEY"),
                                     routing=teacher.routing if teacher else None)
    try:
        result = th.thesis(conn, a, provider, asked=asked, arm=args.arm, model=model, max_usd=args.max_usd,
                           prices=openrouter.prices([model]), data_dir=cfg.data_dir, prompt_version=args.prompt,
                           terms=teacher.terms_class if teacher else None)
    finally:
        provider.close()
    c = result.checked
    print(f"thesis {a.ticker} {a.session}  analysis {a.analysis_id}  arm={args.arm}  prompt={args.prompt}  "
          f"model={model}  asked {','.join(asked)}  spent=${result.spent_usd:.4f}")
    print(f"run={result.run_path}")
    for t in c.theses:
        print(f"  ACCEPTED {thesis_line(t)}")
    for n in c.no_trades:
        print(f"  NO_TRADE {n.horizon}: {n.reason}")
    for r in c.rejected:
        print(f"  REJECTED {r.horizon}: {r.reason}: {r.detail}")
    print(f"accepted {len(c.theses)}, no_trade {len(c.no_trades)}, rejected {len(c.rejected)}")


def cmd_open(args, cfg) -> None:
    rows = journal.open_theses(journal.connect(cfg.db_path), args.arm)
    print("thesis_id ticker horizon direction state entry stop target created")
    for t, state in rows:
        created = t.created_at.astimezone(sessions.NY).strftime("%Y-%m-%d %H:%M")
        print(f"{t.thesis_id} {t.ticker} {t.horizon} {t.direction} {state} {entry_text(t)} {an.plain(t.stop)} "
              f"{an.plain(t.target)} {created}")
    print(f"{len(rows)} open")


def register(sub) -> None:
    p = sub.add_parser("thesis", help="write 0-3 checked theses or no-trades from a stored Analysis (paid call)")
    p.add_argument("ticker")
    p.add_argument("--session")
    p.add_argument("--analysis", help="analysis id (default: the newest for the ticker-day and arm)")
    p.add_argument("--arm", choices=ARMS, default="champion")
    p.add_argument("--prompt", default=th.DEFAULT_PROMPT, help="prompt version: prompts/<version>.txt")
    p.add_argument("--model", default=th.DEFAULT_MODEL)
    p.add_argument("--teacher", choices=tuple(tc.TEACHERS), metavar="MODEL",
                   help="the teacher arm's model, pinned to its DeepInfra endpoint: " + ", ".join(tc.TEACHERS))
    p.add_argument("--max-usd", type=float, default=0.25)
    p.set_defaults(func=cmd_thesis)
    p = sub.add_parser("open", help="theses whose last event is PROPOSED or OPEN")
    p.add_argument("--arm", choices=ARMS, help="one arm only (default: every arm)")
    p.set_defaults(func=cmd_open)
