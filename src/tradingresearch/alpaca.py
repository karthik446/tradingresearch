"""Alpaca market data over plain REST: daily bars (journal), 1-minute bars (CSV cache) and news (SPIKE §3.1)."""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pandas as pd

from . import sessions
from .hashing import digest
from .records import SourceRef

DATA_HOST = "https://data.alpaca.markets"
DATA_URL = f"{DATA_HOST}/v2/stocks/bars"
NEWS_URL = f"{DATA_HOST}/v1beta1/news"
BAR_COLUMNS = ["o", "h", "l", "c", "v", "n", "vw"]
LICENCE = "Alpaca market data: personal use; do not redistribute raw bars"


def client(key_id: str, secret: str) -> httpx.Client:
    return httpx.Client(
        headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret},
        timeout=httpx.Timeout(30.0),
    )


def get_json(http: httpx.Client, url: str, params: dict[str, str], *, tries: int = 4) -> dict:
    """GET with a short backoff on 429 and 5xx. Any other error is raised with Alpaca's message."""
    for attempt in range(tries):
        response = http.get(url, params=params)
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(float(response.headers.get("Retry-After", 2**attempt)))
            continue
        if response.status_code != 200:
            raise RuntimeError(f"Alpaca {response.status_code}: {response.text[:200]}")
        return response.json()
    raise RuntimeError(f"Alpaca: gave up after {tries} tries ({response.status_code})")


def fetch_bars(
    http: httpx.Client, symbols: list[str], start: str, end: str, *, timeframe: str = "1Day",
    feed: str = "sip", adjustment: str = "split",
) -> pd.DataFrame:
    """All bars for `symbols` in [start, end], following next_page_token until it is null.

    The 10,000 `limit` counts data points across ALL symbols, and pages are sorted by symbol then time, so the
    first page may hold only the first symbol. Never stop after one page.
    """
    params = {
        "symbols": ",".join(symbols), "timeframe": timeframe, "start": start, "end": end,
        "feed": feed, "adjustment": adjustment, "limit": "10000", "sort": "asc",
    }
    rows: list[dict] = []
    while True:
        page = get_json(http, DATA_URL, params)
        for symbol, bars in (page.get("bars") or {}).items():
            rows.extend({"ticker": symbol, **bar} for bar in bars)
        token = page.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    frame = pd.DataFrame(rows, columns=["ticker", "t", *BAR_COLUMNS])
    frame["t"] = pd.to_datetime(frame["t"], utc=True)
    return frame


def news(
    http: httpx.Client, tickers: list[str], start: str, end: str, limit: int = 50, *, sort: str = "asc",
    max_articles: int = 5000,
) -> list[dict]:
    """News articles for `tickers` in [start, end], following next_page_token until it is null or the cap.

    `limit` is the page size (Alpaca's maximum is 50). Article bodies are never requested (SPIKE §3.2).
    """
    params = {
        "symbols": ",".join(tickers), "start": start, "end": end, "limit": str(limit), "sort": sort,
        "include_content": "false",
    }
    articles: list[dict] = []
    while len(articles) < max_articles:
        page = get_json(http, NEWS_URL, params)
        articles.extend(page.get("news") or [])
        token = page.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    return articles[:max_articles]


def daily_bars(
    http: httpx.Client, symbols: list[str], start: date, end: date, *, feed: str = "sip", adjustment: str = "split"
) -> pd.DataFrame:
    """Daily bars with a `session` column. A daily bar's `t` is midnight New York time, given in UTC."""
    frame = fetch_bars(http, symbols, start.isoformat(), end.isoformat(), feed=feed, adjustment=adjustment)
    frame["session"] = frame["t"].dt.tz_convert(sessions.NY).dt.date
    return frame.drop(columns="t")[["ticker", "session", *BAR_COLUMNS]]


def store_daily(conn: sqlite3.Connection, frame: pd.DataFrame, *, feed: str, adjustment: str) -> int:
    """Upsert into bars_daily. Bars are not append-only: a re-fetch may correct a bar (SPIKE §2.2)."""
    fetched_at = datetime.now(UTC).isoformat()
    rows = [
        (r.ticker, r.session.isoformat(), r.o, r.h, r.l, r.c, int(r.v), int(r.n), r.vw, feed, adjustment, fetched_at)
        for r in frame.itertuples()
    ]
    with conn:
        conn.executemany("INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def load_daily(conn: sqlite3.Connection, ticker: str, end: date, *, feed: str, adjustment: str = "split") -> pd.DataFrame:
    """Stored daily bars for one ticker up to and including `end`, oldest first."""
    return pd.read_sql_query(
        "SELECT session, o, h, l, c, v, n, vw FROM bars_daily "
        "WHERE ticker = ? AND feed = ? AND adjustment = ? AND session <= ? ORDER BY session",
        conn, params=(ticker, feed, adjustment, end.isoformat()), parse_dates=["session"],
    )


def bars_source(frame: pd.DataFrame, *, ticker: str, feed: str, adjustment: str) -> SourceRef:
    """A content-addressed SourceRef for the daily bars an IndicatorSnapshot was computed from."""
    content = digest({
        "ticker": ticker, "feed": feed, "adjustment": adjustment,
        "bars": frame.assign(session=frame["session"].astype(str)).to_dict(orient="records"),
    })
    first, last = frame["session"].iloc[0], frame["session"].iloc[-1]
    return SourceRef(
        source_id="src_" + content.removeprefix("sha256:")[:16], kind="bars_daily",
        uri=f"{DATA_URL}?symbols={ticker}&timeframe=1Day&start={first:%Y-%m-%d}&end={last:%Y-%m-%d}"
            f"&feed={feed}&adjustment={adjustment}",
        retrieved_at=datetime.now(UTC), content_sha256=content, feed=feed, licence_note=LICENCE,
    )


def minute_bars(http: httpx.Client, cache_dir: Path, ticker: str, session: date, *, feed: str = "sip") -> pd.DataFrame:
    """Regular-session 1-minute bars for one ticker-day, cached as CSV on first use."""
    path = cache_dir / feed / ticker / f"{session.isoformat()}.csv"
    if path.exists():
        return pd.read_csv(path, parse_dates=["t"])
    open_utc, close_utc = sessions.open_close(session)
    frame = fetch_bars(
        http, [ticker], open_utc.isoformat(), close_utc.isoformat(), timeframe="1Min", feed=feed, adjustment="split"
    )
    # The window is [open, close]; a bar stamped at the close itself belongs to the after-hours session.
    frame = frame[(frame["t"] >= open_utc) & (frame["t"] < close_utc)].drop(columns="ticker")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame


def prune_minute_cache(cache_dir: Path, keep_sessions: int = 60) -> int:
    """Delete cached 1-minute CSVs older than the last `keep_sessions` sessions. Returns the number deleted."""
    cutoff = sessions.recent(keep_sessions)[0]
    removed = 0
    for path in cache_dir.glob("*/*/*.csv"):
        if date.fromisoformat(path.stem) < cutoff:
            path.unlink()
            removed += 1
    return removed
