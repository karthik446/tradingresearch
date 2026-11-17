"""Documents for the retrieval index: SEC Archives filing text and stored headlines (RETRIEVAL-SPIKE §1.2, §4.1).

Filings, per ticker, accepted in the last `quarters` × 91 days:
- an earnings 8-K (form 8-K with item 2.02): its primary document, plus the exhibit whose Type column on the
  `{accession}-index.html` page reads EX-99.1 (the press release). The type comes from that page only: `index.json`
  has no type, and file names mislead (a filer's EX-99.2 supplement can be named like a press release);
- a 10-Q: its primary document, whole (a section cutter is fragile, SPIKE §1.3).
10-Ks and other 8-Ks are left out (SPIKE §4.1). The CIK is the one SEC's ticker table gives today; a filer that
changed CIK (XOM, SPIKE §1.2) has its older history under the other CIK, which is not fetched.

Each document is available from EDGAR's `acceptanceDateTime` (a headline: its `created_at`). Text is cached under
`<data_dir>/edgar/archives/{cik}/{accession}/`, never refetched, and named by `raw_content_sha256`. SEC asks for a
declared User-Agent and at most 10 requests/s; Archives text is fetched at 5 requests/s.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

import httpx

from .. import news
from ..edgar import SUBMISSIONS_URL, Edgar
from ..retry import DEFAULT, HttpError, Policy
from .extract import decode, squash

ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{name}"
ARCHIVES_PER_SECOND = 5.0
DAYS_PER_QUARTER = 91
EARNINGS_ITEM = "2.02"
PRESS_RELEASE = "EX-99.1"


@dataclass(frozen=True)
class Doc:
    """One retrievable document. `media` is "html" (a filing) or "text" (a headline)."""

    doc_id: str  # "{accession}/{file name}" or "headline/{article_id}"
    ticker: str
    kind: str  # "8-K", "EX-99.1", "10-Q" or "headline"
    available_at: datetime
    content: str
    media: str
    raw_content_sha256: str
    url: str


def raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Archives(Edgar):
    """`Edgar`'s polite client (declared User-Agent, retry policy, disk cache) plus a cached Archives text GET.

    `http`, `clock` and `sleep` are injected so tests run offline and check the request gap with a fake clock.
    """

    def __init__(self, user_agent: str, cache_dir: Path, per_second: float = ARCHIVES_PER_SECOND,
                 policy: Policy = DEFAULT, http: httpx.Client | None = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        super().__init__(user_agent, cache_dir, per_second, policy)
        if http is not None:
            self._http.close()
            http.headers["User-Agent"] = user_agent
            self._http = http
        self._clock = clock
        self._sleep = sleep
        self.requests = 0

    def _fetch(self, url: str) -> httpx.Response:
        """One GET at most `per_second` per second, measured from the end of the previous reply."""
        with self._lock:
            wait = self._last + self._gap - self._clock()
            if wait > 0:
                self._sleep(wait)
            self.requests += 1
            try:
                response = self._http.get(url)
            finally:
                self._last = self._clock()
        if not response.is_success:
            raise HttpError.of("EDGAR", response)
        return response

    def submissions(self, cik: int, now: datetime) -> list[dict]:
        """The filer's recent filings as rows; the cached list is refetched once per UTC day (as `recent_8k`)."""
        path = self._cache / "submissions" / f"CIK{cik:010d}.json"
        if path.exists() and datetime.fromtimestamp(path.stat().st_mtime, UTC).date() < now.date():
            path.unlink()
        recent = self._get(SUBMISSIONS_URL.format(cik=cik), path)["filings"]["recent"]
        return [dict(zip(recent, values)) for values in zip(*recent.values())]

    def text(self, cik: int, accession: str, name: str) -> bytes:
        """One Archives file of a filing, from the cache when present."""
        name = PurePosixPath(name).name
        if name in ("", ".", ".."):
            raise ValueError(f"bad archive file name for {accession}")
        path = self._cache / "archives" / str(cik) / accession / name
        if path.exists():
            return path.read_bytes()
        url = ARCHIVES_URL.format(cik=cik, folder=accession.replace("-", ""), name=name)
        content = self._policy.call(lambda: self._fetch(url)).content
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        part.write_bytes(content)
        part.replace(path)
        return content


class _IndexTables(HTMLParser):
    """Rows of every table on a filing index page: (cell text, first link) per cell."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[tuple[str, str]]]] = []
        self.cell: list[str] | None = None
        self.href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.tables[-1].append([])
        elif tag in ("td", "th") and self.tables and self.tables[-1]:
            self.cell, self.href = [], ""
        elif tag == "a" and self.cell is not None and not self.href:
            self.href = dict(attrs).get("href") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.cell is not None:
            self.tables[-1][-1].append((squash("".join(self.cell)), self.href))
            self.cell = None

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)


def exhibit_name(index_html: str, doc_type: str = PRESS_RELEASE) -> str | None:
    """The file name of the first document whose Type column equals `doc_type`, or None."""
    parser = _IndexTables()
    parser.feed(index_html)
    parser.close()
    for table in parser.tables:
        if not table:
            continue
        header = [text.lower() for text, _ in table[0]]
        if "type" not in header or "document" not in header:
            continue
        type_col, doc_col = header.index("type"), header.index("document")
        for row in table[1:]:
            if len(row) > max(type_col, doc_col) and row[type_col][0].upper() == doc_type:
                text, href = row[doc_col]
                target = href.split("doc=", 1)[-1] if href else text.split()[0]
                return PurePosixPath(target).name
    return None


def wanted(row: dict, since: datetime) -> bool:
    """A 10-Q, or an 8-K carrying item 2.02, accepted after `since`."""
    if datetime.fromisoformat(row["acceptanceDateTime"]) <= since:
        return False
    items = {item.strip() for item in (row.get("items") or "").split(",")}
    return row["form"] == "10-Q" or (row["form"] == "8-K" and EARNINGS_ITEM in items)


def since_for(quarters: int, now: datetime) -> datetime:
    return now - timedelta(days=DAYS_PER_QUARTER * quarters)


def filing_docs(archives: Archives, ticker: str, quarters: int, now: datetime) -> list[Doc]:
    """The ticker's earnings 8-Ks (primary + EX-99.1) and 10-Qs of the last `quarters`, oldest first."""
    cik = archives.cik(ticker)
    since = since_for(quarters, now)
    rows = sorted((row for row in archives.submissions(cik, now) if wanted(row, since)),
                  key=lambda row: (row["acceptanceDateTime"], row["accessionNumber"]))
    docs = []
    for row in rows:
        accession = row["accessionNumber"]
        available = datetime.fromisoformat(row["acceptanceDateTime"]).astimezone(UTC)
        files = [(row["form"], row["primaryDocument"])]
        if row["form"] == "8-K":
            index = decode(archives.text(cik, accession, f"{accession}-index.html"))
            exhibit = exhibit_name(index)
            if exhibit:
                files.append((PRESS_RELEASE, exhibit))
        for kind, name in files:
            raw = archives.text(cik, accession, name)
            url = ARCHIVES_URL.format(cik=cik, folder=accession.replace("-", ""), name=name)
            docs.append(Doc(f"{accession}/{name}", ticker, kind, available, decode(raw), "html", raw_sha256(raw), url))
    return docs


def headline_docs(data_dir: Path, ticker: str, since: datetime) -> list[Doc]:
    """Headlines already in the news store (`tr news` fetches them), created after `since`. Nothing is fetched."""
    folder = data_dir / "news" / ticker
    rows = [row for path in sorted(folder.glob("*.jsonl")) for row in news.load(path)] if folder.is_dir() else []
    seen: dict[int, Doc] = {}
    for row in sorted(rows, key=lambda r: (r.created_at, r.article_id)):
        if row.created_at > since and row.article_id not in seen:
            seen[row.article_id] = Doc(f"headline/{row.article_id}", ticker, "headline", row.created_at, row.headline,
                                       "text", raw_sha256(row.headline.encode()), row.url)
    return list(seen.values())
