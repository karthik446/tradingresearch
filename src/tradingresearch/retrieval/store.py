"""The `retrieval` arm knob (week 6, RETRIEVAL-SPIKE): what a retrieval arm retrieves for one ticker-day, and the
journal row that records it.

- `Knob`: an arm's `retrieval` table, `mode` (dense, bm25, hybrid or hybrid+rerank), `k`, the full `index` digest
  and the `query` template. `mode = "none"` is no knob: the arm, its prompt and its input hash stay those of an arm
  without the table (experiment.retrieval).
- `retrieve`: the query (the template filled with the item's `{ticker}` and `{session}`) against the pinned index
  through evaluate.search, so the look-ahead mask runs at the session's close before ranking: a chunk public after
  it never reaches the prompt.
- `Retrieved`: the ordered chunks. Their sha256 list, the mode, k and the index digest join analyze.input_hash;
  masking.augment renders them as the numbered RETRIEVED PASSAGES block.
- the `retrieval` table (journal.SCHEMA, append-only): one row per stored analysis of a retrieval arm, linked by
  `analysis_id` and `input_hash`, with the query, the template and the ordered `(chunk_id, chunk_sha256, score)`.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from . import evaluate, manifest, rerank

MODES = ("none", *evaluate.RETRIEVERS)
MAX_K = rerank.DEPTH  # the reranker reorders the hybrid top 20, and recall is measured to k = 20
DEFAULT_K = 5
DEFAULT_QUERY = "{ticker} quarterly results: revenue, earnings, guidance, outlook and risks"
PLACEHOLDERS = ("ticker", "session")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
COLUMNS = ("analysis_id", "input_hash", "ticker", "as_of", "mode", "k", "index_digest", "query", "query_template",
           "chunks", "masked_docs")


@dataclass(frozen=True)
class Knob:
    mode: str
    k: int
    index: str  # the full `sha256:<hex>` digest of a built index (`tr retrieval build`)
    query: str = DEFAULT_QUERY


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    sha256: str
    score: float
    text: str


@dataclass(frozen=True)
class Retrieved:
    ticker: str
    as_of: date
    mode: str
    k: int
    index_digest: str
    query: str
    query_template: str
    passages: tuple[Passage, ...]
    masked_docs: int

    def hashed(self) -> dict:
        """What joins the input hash: the knob and the ordered chunk digests (the chunk text is in the prompt)."""
        return {"mode": self.mode, "k": self.k, "index_digest": self.index_digest,
                "chunks": [p.sha256 for p in self.passages]}

    def values(self) -> dict[str, None]:
        """Each passage as a citable source id with no number, as a headline row is."""
        return {p.chunk_id: None for p in self.passages}


def query_for(template: str, ticker: str, session: date) -> str:
    return template.format(ticker=ticker, session=session.isoformat())


def check_template(template: str) -> str | None:
    """Why `template` cannot be filled, or None: only `{ticker}` and `{session}` are known."""
    try:
        query_for(template, "TICKER", date(2000, 1, 3))
    except (KeyError, IndexError, ValueError) as exc:
        return f"query template {template!r} cannot be filled ({type(exc).__name__}: {exc}); placeholders: " + \
            ", ".join(f"{{{name}}}" for name in PLACEHOLDERS)
    return None


def retrieve(index: manifest.Index, retriever: evaluate.Retriever, knob: Knob, ticker: str, session: date,
             now: datetime | None = None) -> Retrieved:
    """The top `knob.k` chunks of `ticker` available at the session's close (or `now`, if earlier), in rank order."""
    query = query_for(knob.query, ticker, session)
    hits, masked = evaluate.search(index, retriever, query, ticker, session, knob.k, now)
    passages = tuple(Passage(index.records[i].chunk_id, index.records[i].sha256, round(float(score), 6),
                             index.records[i].text) for i, score in hits)
    return Retrieved(ticker, session, knob.mode, knob.k, index.digest, query, knob.query, passages, masked)


def retrieve_all(knob: Knob, keys: dict[str, tuple[str, date]], root: Path,
                 now: datetime | None = None) -> dict[str, Retrieved]:
    """One Retrieved per dataset item id (`key -> (ticker, session)`) from the pinned index under `root`."""
    index = manifest.load(root, knob.index)
    retriever = evaluate.retrievers(index, [knob.mode], root)[knob.mode]
    return {key: retrieve(index, retriever, knob, ticker, session, now) for key, (ticker, session) in keys.items()}


def add(conn: sqlite3.Connection, retrieved: Retrieved, analysis_id: str, input_hash: str) -> None:
    """One row, committed at once; the chunk list keeps the order the model saw."""
    chunks = [[p.chunk_id, p.sha256, p.score] for p in retrieved.passages]
    values = (analysis_id, input_hash, retrieved.ticker, retrieved.as_of.isoformat(), retrieved.mode, retrieved.k,
              retrieved.index_digest, retrieved.query, retrieved.query_template, json.dumps(chunks),
              retrieved.masked_docs, datetime.now(UTC).isoformat())
    with conn:
        conn.execute(f"INSERT INTO retrieval ({', '.join(COLUMNS)}, created_at) "
                     f"VALUES ({', '.join('?' for _ in values)})", values)


def rows(conn: sqlite3.Connection, analysis_id: str | None = None) -> list[dict]:
    """Stored retrieval rows in insertion order, for one analysis or all; `chunks` back as a list of lists."""
    cursor = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM retrieval WHERE ? IS NULL OR analysis_id = ? "
                          "ORDER BY seq", (analysis_id, analysis_id))
    found = [dict(zip(COLUMNS, values)) for values in cursor]
    return [row | {"chunks": json.loads(row["chunks"])} for row in found]
