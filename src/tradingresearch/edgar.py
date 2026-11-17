"""SEC EDGAR XBRL company facts and filing lists: public, keyless, 10 requests/s, User-Agent required."""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .hashing import digest
from .records import SourceRef

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
LICENCE = "SEC EDGAR: US government public data"


class Edgar:
    """A polite client: one declared User-Agent, at most `per_second` requests, everything cached on disk."""

    def __init__(self, user_agent: str, cache_dir: Path, per_second: float = 8.0) -> None:
        if "@" not in user_agent:
            raise ValueError("SEC asks for a User-Agent with a contact email, e.g. 'tradingresearch you@example.com'")
        self._http = httpx.Client(headers={"User-Agent": user_agent}, timeout=30.0)
        self._cache = cache_dir
        self._gap = 1.0 / per_second
        self._last = 0.0
        self._lock = threading.Lock()

    def _get(self, url: str, path: Path) -> dict:
        if path.exists():
            return json.loads(path.read_bytes())
        with self._lock:  # keep under SEC's 10 requests/s even with threads
            wait = self._last + self._gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            response = self._http.get(url)
            self._last = time.monotonic()
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return response.json()

    def cik(self, ticker: str) -> int:
        table = self._get(TICKERS_URL, self._cache / "company_tickers.json")
        wanted = ticker.upper().replace(".", "-")  # SEC writes BRK-B where Alpaca writes BRK.B
        for row in table.values():
            if row["ticker"] == wanted:
                return int(row["cik_str"])
        raise KeyError(f"no CIK for {ticker}")

    def company_facts(self, ticker: str) -> dict:
        cik = self.cik(ticker)
        return self._get(FACTS_URL.format(cik=cik), self._cache / "companyfacts" / f"CIK{cik:010d}.json")

    def recent_8k(self, ticker: str, since: datetime, until: datetime | None = None) -> list[dict]:
        """8-Ks accepted after `since` and up to `until` (aware datetimes), oldest first (SPIKE §4.2 trigger).

        acceptanceDateTime is UTC (AAPL's 16:30 New York earnings 8-Ks read 21:30Z in winter, 20:30Z in summer).
        The filing date is not used: an 8-K accepted after 16:00 keeps that day's date. The submissions list grows
        every day, so its cache is refetched once per UTC day; `until` keeps a past session from seeing later filings.
        """
        cik = self.cik(ticker)
        path = self._cache / "submissions" / f"CIK{cik:010d}.json"
        if path.exists() and datetime.fromtimestamp(path.stat().st_mtime, UTC).date() < datetime.now(UTC).date():
            path.unlink()
        recent = self._get(SUBMISSIONS_URL.format(cik=cik), path)["filings"]["recent"]
        rows = [dict(zip(recent, values)) for values in zip(*recent.values())]

        def wanted(row: dict) -> bool:
            accepted = datetime.fromisoformat(row["acceptanceDateTime"])
            return row["form"] == "8-K" and since < accepted and (until is None or accepted <= until)

        return sorted(filter(wanted, rows), key=lambda r: r["acceptanceDateTime"])


def fact_for_frame(facts: dict, concept: str, frame: str, unit: str = "USD", taxonomy: str = "us-gaap") -> dict:
    """The one fact SEC assigned to a calendar `frame`: CY2025 (a year), CY2025Q3 (a quarter), CY2025Q3I (an instant).

    Never select by `fy`: it is the fiscal year of the FILING, so a 10-K's comparison columns from earlier years
    carry the newer filing's `fy`.
    """
    for row in facts["facts"][taxonomy][concept]["units"][unit]:
        if row.get("frame") == frame:
            return row
    raise KeyError(f"{concept}: no fact for frame {frame}")


def latest_frames(facts: dict, concept: str, kind: str, count: int, unit: str = "USD", taxonomy: str = "us-gaap") -> list[dict]:
    """The `count` most recent framed facts of one kind: 'year' (CY2025), 'quarter' (CY2025Q3) or 'instant' (…I)."""
    def matches(frame: str) -> bool:
        if kind == "year":
            return len(frame) == 6
        if kind == "quarter":
            return len(frame) == 8
        return frame.endswith("I")

    rows = [r for r in facts["facts"][taxonomy][concept]["units"][unit] if matches(r.get("frame", "x"))]
    return sorted(rows, key=lambda r: r["end"])[-count:]


def fact_source(ticker: str, cik: int, concept: str, row: dict) -> SourceRef:
    """One XBRL fact as a SourceRef. The uri names the accession number, so a reader can open the filing."""
    content = digest({"ticker": ticker, "concept": concept, **{k: row[k] for k in ("val", "end", "accn", "form", "frame")}})
    return SourceRef(
        source_id="src_" + content.removeprefix("sha256:")[:16], kind="edgar_fact",
        uri=f"{FACTS_URL.format(cik=cik)}#{concept}/{row['frame']}/accn={row['accn']}",
        retrieved_at=datetime.now(UTC), content_sha256=content, feed=None, licence_note=LICENCE,
    )
