"""SEC EDGAR XBRL company facts: public, keyless, 10 requests/s, User-Agent required."""

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
        for row in table.values():
            if row["ticker"] == ticker.upper():
                return int(row["cik_str"])
        raise KeyError(f"no CIK for {ticker}")

    def company_facts(self, ticker: str) -> dict:
        cik = self.cik(ticker)
        return self._get(FACTS_URL.format(cik=cik), self._cache / "companyfacts" / f"CIK{cik:010d}.json")


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
