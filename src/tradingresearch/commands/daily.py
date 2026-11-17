"""`tr daily`: the whole evening for one completed session, screen → analyze → thesis → reconcile (REPO-PLAN §7 G4a).
Paid unless --dry-run or --no-model; --max-usd stops it before the next model call."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from functools import cache
from types import SimpleNamespace

from .. import analyze as an, daily, journal, openrouter, reconcile_run, screen, thesis as th
from ..config import require
from .common import alpaca_client, edgar_client
from .reconcile import completed_session
from .screen import cmd_screen
from .thesis import horizons_to_ask

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

    return daily.Steps(screen_step, analyze_step, lambda a, now: horizons_to_ask(conn, a, "champion", now),
                       thesis_step, reconcile_step)


def cmd_daily(args, cfg) -> None:
    now = datetime.now(UTC)
    day = completed_session(args.session, now)
    conn = journal.connect(cfg.db_path)
    paid = not (args.dry_run or args.no_model)
    provider = openrouter.OpenRouter(require(cfg.openrouter_key, "OPENROUTER_API_KEY")) if paid else None
    try:
        with alpaca_client(cfg) as http:
            report = daily.run(conn, real_steps(conn, cfg, http, provider, args.top), day, top=args.top,
                               max_usd=args.max_usd, runs_dir=cfg.data_dir / "runs", now=now, dry_run=args.dry_run,
                               no_model=args.no_model)
    except sqlite3.Error as error:
        raise SystemExit(f"journal failed: {error}") from error
    finally:
        if provider is not None:
            provider.close()
    if report.screen_failed:
        raise SystemExit(1)


def register(sub) -> None:
    p = sub.add_parser("daily", help="the evening run for one session: screen, analyze, thesis, reconcile (paid)")
    p.add_argument("--session", help="a completed session (default: the latest, after 16:15 ET)")
    p.add_argument("--top", type=int, default=10, help="analyze the screen's top N (default 10, SPIKE §4.2)")
    p.add_argument("--max-usd", type=float, default=1.00,
                   help="stop before the next model call that would take the run past this (default 1.00)")
    p.add_argument("--dry-run", action="store_true",
                   help="free steps only (reconcile writes nothing): print what would be analyzed and its cost")
    p.add_argument("--no-model", action="store_true", help="run the free steps for real; skip analyze and thesis")
    p.set_defaults(func=cmd_daily)
