"""Helpers shared by the `tr` commands: session parsing, API clients, gathered context."""

from __future__ import annotations

from datetime import UTC, date, datetime

from .. import alpaca, analyze as an, journal, sessions
from ..config import require
from ..edgar import Edgar


def session_arg(text: str | None) -> date:
    day = date.fromisoformat(text) if text else sessions.last_completed(datetime.now(UTC))
    if not sessions.is_session(day):
        raise SystemExit(f"{day} is not an NYSE session")
    return day


def edgar_client(cfg) -> Edgar:
    return Edgar(require(cfg.sec_user_agent, "TR_SEC_USER_AGENT"), cfg.data_dir / "edgar")


def alpaca_client(cfg):
    return alpaca.client(require(cfg.alpaca_key_id, "APCA_API_KEY_ID"), require(cfg.alpaca_secret, "APCA_API_SECRET_KEY"))


def context_for(args, cfg):
    day = session_arg(args.session)
    conn = journal.connect(cfg.db_path)
    with alpaca_client(cfg) as http:
        ctx = an.gather(conn, http, edgar_client(cfg), args.ticker, day, cfg.data_dir, cfg.feed)
    return conn, ctx
