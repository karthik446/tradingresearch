"""Data commands: sessions, bars, facts, snapshot (SPIKE §4–§6)."""

from __future__ import annotations

import json

from .. import alpaca, analyze as an, journal, sessions
from ..edgar import latest_frames
from .common import alpaca_client, context_for, edgar_client, session_arg


def cmd_sessions(args, cfg) -> None:
    end = session_arg(args.session)
    for day in sessions.recent(args.count, end):
        o, c = sessions.open_close(day)
        print(day, o.strftime("%H:%MZ"), c.strftime("%H:%MZ"))


def cmd_bars(args, cfg) -> None:
    end = session_arg(args.session)
    start = sessions.recent(args.sessions, end)[0]
    conn = journal.connect(cfg.db_path)
    with alpaca_client(cfg) as http:
        frame = alpaca.daily_bars(http, args.tickers, start, end, feed=cfg.feed)
    for ticker in args.tickers:
        rows = frame[frame["ticker"] == ticker]
        alpaca.store_daily(conn, rows, feed=cfg.feed, adjustment="split")
        print(f"{ticker}: {len(rows)} daily bars {start}..{end} feed={cfg.feed}")
    print(frame.groupby("ticker").tail(2).to_string(index=False))


def cmd_facts(args, cfg) -> None:
    edgar = edgar_client(cfg)
    facts = edgar.company_facts(args.ticker)
    print(f"{args.ticker} cik={edgar.cik(args.ticker)} {facts['entityName']}")
    for row in latest_frames(facts, args.concept, args.kind, args.count, args.unit):
        print(f"{row['frame']:<10} {row['val']:>16,} {row['start'] if 'start' in row else '':>10} {row['end']} "
              f"fy={row['fy']} fp={row['fp']} {row['form']} filed={row['filed']}")


def cmd_snapshot(args, cfg) -> None:
    _, ctx = context_for(args, cfg)
    if args.prompt:
        print(an.render(ctx))
        print(f"\ncontext_tokens={an.context_tokens(an.system_prompt(an.DEFAULT_PROMPT), an.render(ctx))}")
        return
    print(json.dumps(ctx.snapshot.model_dump(mode="json"), indent=1))


def register(sub) -> None:
    p = sub.add_parser("sessions", help="NYSE sessions ending at a date")
    p.add_argument("--session")
    p.add_argument("--count", type=int, default=5)
    p.set_defaults(func=cmd_sessions)

    p = sub.add_parser("bars", help="fetch and store daily bars")
    p.add_argument("tickers", nargs="+")
    p.add_argument("--session")
    p.add_argument("--sessions", type=int, default=300)
    p.set_defaults(func=cmd_bars)

    p = sub.add_parser("facts", help="framed EDGAR facts for one concept")
    p.add_argument("ticker")
    p.add_argument("--concept", default="RevenueFromContractWithCustomerExcludingAssessedTax")
    p.add_argument("--kind", choices=["year", "quarter", "instant"], default="quarter")
    p.add_argument("--unit", default="USD")
    p.add_argument("--count", type=int, default=4)
    p.set_defaults(func=cmd_facts)

    p = sub.add_parser("snapshot", help="indicators, levels and regime for one ticker-day")
    p.add_argument("ticker")
    p.add_argument("--session")
    p.add_argument("--prompt", action="store_true", help="print the analyze prompt instead")
    p.set_defaults(func=cmd_snapshot)
