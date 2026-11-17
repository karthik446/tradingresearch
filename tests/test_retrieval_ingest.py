"""SEC Archives ingest and the headline loader, offline: an httpx MockTransport serves the invented FAKEA files."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from tradingresearch.news import Headline
from tradingresearch.retrieval import ingest
from tradingresearch.retry import HttpError, Policy

FIX = Path(__file__).parent / "fixtures" / "retrieval"
UA = "tradingresearch-test test@example.com"
NOW = datetime(2026, 11, 17, 15, tzinfo=UTC)
CIK = 9999999


class Clock:
    """A fake monotonic clock; `sleep` moves it forward."""

    def __init__(self) -> None:
        self.t = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class Server:
    """Serves `tests/fixtures/retrieval/<last URL segment>`, else 404; records each request and its clock time."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.urls: list[str] = []
        self.times: list[float] = []
        self.agents: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        self.times.append(self.clock())
        self.agents.add(request.headers["User-Agent"])
        path = FIX / request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=path.read_bytes()) if path.is_file() else httpx.Response(404)


def fake_archives(cache: Path, clock: Clock | None = None) -> tuple[ingest.Archives, Server]:
    clock = clock or Clock()
    server = Server(clock)
    archives = ingest.Archives(UA, cache, policy=Policy(tries=1), http=httpx.Client(transport=httpx.MockTransport(server)),
                               clock=clock, sleep=clock.sleep)
    return archives, server


def write_headlines(data_dir: Path, ticker: str, rows: list[tuple[int, str, datetime]]) -> None:
    for article_id, text, created in rows:
        path = data_dir / "news" / ticker / f"{created.date()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = Headline(article_id=article_id, headline=text, url=f"https://example.com/{article_id}", source="fake",
                       created_at=created, symbols=(ticker,), retrieved_at=created, content_sha256="x")
        with path.open("a") as out:
            out.write(row.model_dump_json() + "\n")


def test_filings_are_earnings_8ks_with_their_ex991_and_10qs(tmp_path):
    archives, server = fake_archives(tmp_path)
    docs = ingest.filing_docs(archives, "FAKEA", 1, NOW)
    assert [(d.doc_id, d.kind) for d in docs] == [
        ("0009999999-26-000101/fakea-8k_20261029.htm", "8-K"),
        ("0009999999-26-000101/fakea-ex991.htm", "EX-99.1"),  # not the EX-99.2 listed before it
        ("0009999999-26-000102/fakea-20260930.htm", "10-Q"),
        ("0009999999-26-000103/fakea-8k_20261106.htm", "8-K"),  # its index page has no EX-99.1
    ]
    assert docs[0].available_at == datetime(2026, 10, 29, 20, 30, tzinfo=UTC)
    assert docs[1].url == "https://www.sec.gov/Archives/edgar/data/9999999/000999999926000101/fakea-ex991.htm"
    assert docs[1].raw_content_sha256 == ingest.raw_sha256((FIX / "fakea-ex991.htm").read_bytes())
    assert "Widget revenue grew 14%" in docs[1].content and docs[1].media == "html"
    assert not any("pressrelease" in url or "20260902" in url or "20251231" in url for url in server.urls)
    assert archives.requests == len(server.urls) == 8  # tickers, submissions, 3 + 1 + 2 Archives files
    assert server.agents == {UA}
    assert (tmp_path / "archives" / "9999999" / "0009999999-26-000101" / "fakea-ex991.htm").is_file()


def test_second_build_reads_everything_from_the_cache(tmp_path):
    first = ingest.filing_docs(fake_archives(tmp_path)[0], "FAKEA", 1, NOW)
    archives, server = fake_archives(tmp_path)
    assert ingest.filing_docs(archives, "FAKEA", 1, NOW) == first
    assert archives.requests == 0 and server.urls == []


def test_submissions_are_refetched_once_per_utc_day(tmp_path):
    ingest.filing_docs(fake_archives(tmp_path)[0], "FAKEA", 1, NOW)
    path = tmp_path / "submissions" / "CIK0009999999.json"
    yesterday = (NOW - timedelta(days=1)).timestamp()
    os.utime(path, (yesterday, yesterday))
    archives, server = fake_archives(tmp_path)
    ingest.filing_docs(archives, "FAKEA", 1, NOW)
    assert [url.rsplit("/", 1)[-1] for url in server.urls] == ["CIK0009999999.json"]


def test_archives_requests_are_at_most_five_per_second(tmp_path):
    clock = Clock()
    archives, server = fake_archives(tmp_path, clock)
    ingest.filing_docs(archives, "FAKEA", 1, NOW)
    gaps = [b - a for a, b in zip(server.times, server.times[1:])]
    assert len(gaps) == 7 and min(gaps) >= 0.2 - 1e-9
    assert clock.sleeps and all(s <= 0.2 + 1e-9 for s in clock.sleeps)


def test_quarters_window_and_forms():
    since = ingest.since_for(1, NOW)
    row = {"form": "8-K", "items": "2.02, 9.01", "acceptanceDateTime": "2026-10-29T20:30:00.000Z"}
    assert ingest.wanted(row, since)
    assert not ingest.wanted({**row, "items": "5.02"}, since)
    assert not ingest.wanted({**row, "items": "12.02"}, since)
    assert not ingest.wanted({**row, "form": "8-K/A"}, since)
    assert not ingest.wanted({**row, "form": "10-K", "items": ""}, since)
    assert ingest.wanted({**row, "form": "10-Q", "items": ""}, since)
    assert not ingest.wanted({**row, "form": "10-Q", "acceptanceDateTime": "2025-08-01T12:00:00.000Z"}, since)


def test_exhibit_comes_from_the_type_column():
    index = (FIX / "0009999999-26-000101-index.html").read_text()
    assert ingest.exhibit_name(index) == "fakea-ex991.htm"
    assert ingest.exhibit_name(index, "EX-99.2") == "fakea-pressrelease.htm"
    assert ingest.exhibit_name(index, "8-K") == "fakea-8k_20261029.htm"  # the /ix?doc= viewer link is unwrapped
    assert ingest.exhibit_name((FIX / "0009999999-26-000103-index.html").read_text()) is None


def test_archive_file_name_cannot_leave_the_cache(tmp_path):
    archives, server = fake_archives(tmp_path)
    archives.text(CIK, "0009999999-26-000101", "../../fakea-ex991.htm")
    assert server.urls == ["https://www.sec.gov/Archives/edgar/data/9999999/000999999926000101/fakea-ex991.htm"]
    assert (tmp_path / "archives" / "9999999" / "0009999999-26-000101" / "fakea-ex991.htm").is_file()
    with pytest.raises(ValueError):
        archives.text(CIK, "0009999999-26-000101", "..")


def test_missing_file_raises_http_error(tmp_path):
    archives, _ = fake_archives(tmp_path)
    with pytest.raises(HttpError):
        archives.text(CIK, "0009999999-26-000101", "absent.htm")
    assert not (tmp_path / "archives" / "9999999" / "0009999999-26-000101" / "absent.htm").exists()


def test_headlines_come_from_the_news_store_deduplicated(tmp_path):
    since = ingest.since_for(1, NOW)
    write_headlines(tmp_path, "FAKEA", [
        (1, "FakeA ships record Gizmos", datetime(2026, 11, 3, 14, tzinfo=UTC)),
        (2, "FakeA old news", since - timedelta(hours=1)),
        (3, "FakeA recalls Gizmo line", datetime(2026, 11, 6, 12, tzinfo=UTC)),
    ])
    write_headlines(tmp_path, "FAKEA", [(1, "FakeA ships record Gizmos", datetime(2026, 11, 3, 14, tzinfo=UTC))])
    docs = ingest.headline_docs(tmp_path, "FAKEA", since)
    assert [(d.doc_id, d.kind, d.media, d.content) for d in docs] == [
        ("headline/FAKEA/1", "headline", "text", "FakeA ships record Gizmos"),
        ("headline/FAKEA/3", "headline", "text", "FakeA recalls Gizmo line"),
    ]
    assert docs[1].available_at == datetime(2026, 11, 6, 12, tzinfo=UTC)
    assert ingest.headline_docs(tmp_path, "NONE", since) == []
