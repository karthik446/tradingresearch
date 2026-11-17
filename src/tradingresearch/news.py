"""Alpaca News headlines: a local store and the look-ahead guard (SPIKE §3.1 news row, §3.2).

Only headline, url, source, time and symbols are kept. The article body is never stored (Alpaca terms, SPIKE §3.2).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import httpx
from gigai_core import CoreModel
from pydantic import AwareDatetime

from . import alpaca, sessions
from .hashing import digest
from .records import SourceRef

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class Headline(CoreModel):
    """One stored article. Headlines are untrusted input: third-party text that may try to steer a model."""

    article_id: int
    headline: str
    url: str
    source: str
    created_at: AwareDatetime
    symbols: tuple[str, ...]
    retrieved_at: AwareDatetime
    content_sha256: str


def normalise(article: dict, retrieved_at: datetime) -> Headline:
    """Pick the kept fields of an Alpaca article; the digest covers them all except retrieved_at."""
    fields = {
        "article_id": int(article["id"]), "headline": article["headline"].strip(), "url": article.get("url") or "",
        "source": article.get("source") or "", "symbols": tuple(article.get("symbols") or ()),
        "created_at": datetime.fromisoformat(article["created_at"]).astimezone(UTC),
    }
    content = digest({**fields, "created_at": fields["created_at"].isoformat()})
    return Headline(**fields, retrieved_at=retrieved_at, content_sha256=content)


def source_ref(headline: Headline) -> SourceRef:
    """The SourceRef a news claim cites; the id comes from the content digest, as for the other sources."""
    return SourceRef(
        source_id="src_" + headline.content_sha256.removeprefix("sha256:")[:16], kind="news", uri=headline.url,
        retrieved_at=headline.retrieved_at, content_sha256=headline.content_sha256, feed=None,
        licence_note=f"Alpaca News ({headline.source}): personal use; headline and url only, do not redistribute",
    )


def path_for(data_dir: Path, ticker: str, day: date) -> Path:
    return data_dir / "news" / ticker / f"{day.isoformat()}.jsonl"


def ny_day(moment: datetime) -> date:
    return moment.astimezone(sessions.NY).date()


def ny_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), sessions.NY).astimezone(UTC)


def load(path: Path) -> list[Headline]:
    if not path.exists():
        return []
    return [Headline.model_validate_json(line) for line in path.read_text().splitlines() if line]


def store(data_dir: Path, ticker: str, headlines: list[Headline]) -> int:
    """Append to the New York day's file, skipping article ids already there. Returns the number added."""
    added = 0
    for headline in headlines:
        path = path_for(data_dir, ticker, ny_day(headline.created_at))
        if headline.article_id in {row.article_id for row in load(path)}:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as file:
            file.write(headline.model_dump_json() + "\n")
        added += 1
    return added


def fetch(http: httpx.Client, data_dir: Path, ticker: str, start: date, end: date, now: datetime | None = None) -> int:
    """Fetch and store New York days start..end. Each day file's mtime records how far that day has been fetched."""
    now = now or datetime.now(UTC)
    until = min(ny_midnight(end + timedelta(days=1)), now)
    articles = alpaca.news(http, [ticker], ny_midnight(start).isoformat(), until.isoformat())
    retrieved_at = datetime.now(UTC)
    added = store(data_dir, ticker, [normalise(article, retrieved_at) for article in articles])
    day = start
    while day <= end and ny_midnight(day) < until:
        path = path_for(data_dir, ticker, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        through = ns(min(until, ny_midnight(day + timedelta(days=1))))
        os.utime(path, ns=(through, through))
        day += timedelta(days=1)
    return added


def ns(moment: datetime) -> int:
    """Nanoseconds since the epoch in integer arithmetic, so an mtime round-trips exactly."""
    return (moment - EPOCH) // timedelta(microseconds=1) * 1000


def window(session: date, days: int = 1, now: datetime | None = None) -> tuple[datetime, datetime]:
    """(close of the session `days` back, this session's close or `now` if earlier]: what an end-of-day run may see."""
    _, close = sessions.open_close(session)
    _, start = sessions.open_close(sessions.recent(days + 1, session)[0])
    return start, min(close, now or datetime.now(UTC))


def days_in(start: datetime, end: datetime) -> list[date]:
    first, last = ny_day(start), ny_day(end)
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def missing_days(data_dir: Path, ticker: str, session: date, days: int = 1, now: datetime | None = None) -> list[date]:
    """New York days in the window not yet fetched as far as the window needs (day end or cutoff)."""
    start, cutoff = window(session, days, now)
    missing = []
    for day in days_in(start, cutoff):
        path = path_for(data_dir, ticker, day)
        needed = ns(min(cutoff, ny_midnight(day + timedelta(days=1))))
        if not path.exists() or path.stat().st_mtime_ns < needed:
            missing.append(day)
    return missing


def headlines_for(
    data_dir: Path, ticker: str, session: date, *, days: int = 1, now: datetime | None = None
) -> list[Headline]:
    """Stored headlines published in the window, oldest first. Nothing after the session's close (look-ahead)."""
    start, cutoff = window(session, days, now)
    rows = [row for day in days_in(start, cutoff) for row in load(path_for(data_dir, ticker, day))]
    return sorted((row for row in rows if start < row.created_at <= cutoff), key=lambda r: (r.created_at, r.article_id))
