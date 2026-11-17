"""`tr daily`: the whole evening for one completed session, screen → analyze → thesis → reconcile → grade (REPO-PLAN
§7 G4a, G8).
Paid unless --dry-run or --no-model; --max-usd stops it before the next model call. --teachers then runs the
bake-off's pinned teachers on the session's drawn names under --teacher-max-usd (SPIKE §9.4)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from functools import cache
from types import SimpleNamespace

from .. import analyze as an, daily, grade, journal, openrouter, reconcile_run, screen, teacher as tc, thesis as th
from ..config import require
from .common import alpaca_client, edgar_client
from .reconcile import completed_session
from .screen import cmd_screen
from .thesis import analysis_for, horizons_to_ask

CALL_USD = 0.25  # each call's own cap, the `tr analyze` and `tr thesis` default (core refuses a worst case above it)


def real_steps(conn, cfg, http, provider, top: int) -> daily.Steps:
    """The existing commands' functions; analyze and thesis write arm main and champion (the challenger is week 4)."""
    edgar = edgar_client(cfg)

    @cache
    def prices() -> dict:
        return openrouter.prices(sorted({an.DEFAULT_MODEL, th.DEFAULT_MODEL}))

    def screen_step(day):
        cmd_screen(SimpleNamespace(session=day.isoformat(), universe=None, top=top), cfg)
        return screen.stored(conn, day)

    def analyze_step(ticker, day):
        ctx = an.gather(conn, http, edgar, ticker, day, cfg.data_dir, cfg.feed)
        return an.analyze(conn, ctx, provider, model=an.DEFAULT_MODEL, max_usd=CALL_USD, prices=prices(),
                          data_dir=cfg.data_dir)

    def thesis_step(a, asked):
        return th.thesis(conn, a, provider, asked=asked, arm="champion", model=th.DEFAULT_MODEL, max_usd=CALL_USD,
                         prices=prices(), data_dir=cfg.data_dir)

    def reconcile_step(day, dry_run):
        bars = reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed)
        return reconcile_run.run(conn, bars, day, dry_run=dry_run)

    def grade_step(day, dry_run):
        bars = reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed)
        return grade.run(conn, bars, day, dry_run=dry_run)

    return daily.Steps(screen_step, analyze_step, lambda a, now: horizons_to_ask(conn, a, "champion", now),
                       thesis_step, reconcile_step, grade_step)


def teacher_steps(conn, cfg, http, provider) -> daily.TeacherSteps:
    """`tr analyze` and `tr thesis` with `--arm teacher --teacher MODEL`, one gather per name for all teachers."""
    edgar = edgar_client(cfg)

    @cache
    def prices() -> dict:
        return openrouter.prices(sorted(tc.TEACHERS))

    @cache
    def context(ticker, day) -> an.Context:
        return an.gather(conn, http, edgar, ticker, day, cfg.data_dir, cfg.feed)

    def analyze_step(ticker, day, t, max_usd):
        return an.analyze(conn, context(ticker, day), provider.routed(t.routing), model=t.model,
                          max_usd=min(CALL_USD, max_usd), prices=prices(), data_dir=cfg.data_dir, arm="teacher",
                          terms_class=t.terms_class)

    def thesis_step(a, t, max_usd):
        a = analysis_for(conn, SimpleNamespace(ticker=a.ticker, analysis=a.analysis_id, arm="teacher", teacher=t.model))
        asked = horizons_to_ask(conn, a, "teacher", datetime.now(UTC))  # all horizons: the teacher arm is exempt
        return th.thesis(conn, a, provider.routed(t.routing), asked=asked, arm="teacher", model=t.model,
                         max_usd=min(CALL_USD, max_usd), prices=prices(), data_dir=cfg.data_dir, terms=t.terms_class)

    return daily.TeacherSteps(analyze_step, thesis_step)


def cmd_daily(args, cfg) -> None:
    now = datetime.now(UTC)
    day = completed_session(args.session, now)
    conn = journal.connect(cfg.db_path)
    paid = not (args.dry_run or args.no_model)
    provider = openrouter.OpenRouter(require(cfg.openrouter_key, "OPENROUTER_API_KEY")) if paid else None
    try:
        with alpaca_client(cfg) as http:
            teachers = teacher_steps(conn, cfg, http, provider) if args.teachers else None
            report = daily.run(conn, real_steps(conn, cfg, http, provider, args.top), day, top=args.top,
                               max_usd=args.max_usd, runs_dir=cfg.data_dir / "runs", now=now, dry_run=args.dry_run,
                               no_model=args.no_model, teachers=teachers, teacher_max_usd=args.teacher_max_usd)
    except sqlite3.Error as error:
        raise SystemExit(f"journal failed: {error}") from error
    finally:
        if provider is not None:
            provider.close()
    if report.screen_failed:
        raise SystemExit(1)


def register(sub) -> None:
    p = sub.add_parser("daily", help="the evening run for one session: screen, analyze, thesis, reconcile, grade "
                                     "(paid)")
    p.add_argument("--session", help="a completed session (default: the latest, after 16:15 ET)")
    p.add_argument("--top", type=int, default=10, help="analyze the screen's top N (default 10, SPIKE §4.2)")
    p.add_argument("--max-usd", type=float, default=1.00,
                   help="stop before the next model call that would take the run past this (default 1.00)")
    p.add_argument("--dry-run", action="store_true",
                   help="free steps only (reconcile and grade write nothing): print what would be analyzed and its "
                        "cost")
    p.add_argument("--no-model", action="store_true", help="run the free steps for real; skip analyze and thesis")
    p.add_argument("--teachers", action="store_true",
                   help="then run the 3 pinned teachers on the session's 4 drawn bake-off names (paid, SPIKE §9.4); "
                        "a teacher failure never changes the exit code")
    p.add_argument("--teacher-max-usd", type=float, default=daily.TEACHER_MAX_USD,
                   help="stop the teacher step before a call whose worst case would take this session's teacher "
                        "spend past this (default 0.40)")
    p.set_defaults(func=cmd_daily)
