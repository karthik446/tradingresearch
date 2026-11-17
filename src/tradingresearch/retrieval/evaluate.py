"""Labelled retrieval queries, the look-ahead mask and recall@k (RETRIEVAL-SPIKE §3.1-3.3).

- **Record** (`evals/retrieval_query.schema.md`): id, ticker, as_of, kind, text, 1-3 gold `{doc, quote}`, optional
  answer and notes. A gold is a quote from a document, resolved at eval time to every chunk of that document whose
  text contains it (whitespace-insensitive), so labels survive a chunker change.
- **Mask.** A chunk can be retrieved for `(ticker, as_of)` only if it belongs to that ticker and its document was
  available at or before the session cutoff that `news.headlines_for` uses (the session close, or now if earlier).
  The mask is given to the retriever, which ranks only allowed chunks: post-filtering a top k returns fewer than k.
- **Recall.** `recall_any@k`: 1 if any chunk of any gold quote is in the top k. `recall_frac@k`: the share of gold
  quotes with a chunk in the top k. Both are macro means over queries, at k in 1, 5, 10, 20.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np

from .. import news, sessions
from .bm25 import tokenize, top_k
from .manifest import Index

KINDS = ("lookup", "numeric", "event")
KS = (1, 5, 10, 20)
REQUIRED = ("id", "ticker", "as_of", "kind", "text", "gold")
OPTIONAL = ("answer", "notes")
MAX_GOLDS = 3

# (query text, allowed chunks, k) -> [(chunk position, score)], best first, only allowed positions.
Retriever = Callable[[str, np.ndarray, int], list[tuple[int, float]]]


@dataclass(frozen=True)
class Gold:
    doc: str
    quote: str


@dataclass(frozen=True)
class Query:
    id: str
    ticker: str
    as_of: date
    kind: str
    text: str
    gold: tuple[Gold, ...]


def cutoff(as_of: date, now: datetime | None = None) -> datetime:
    """The last instant a document may appear and still be visible to a run for session `as_of`."""
    return news.window(as_of, 1, now)[1]


def bm25_retriever(index: Index) -> Retriever:
    return lambda text, allowed, k: top_k(index.bm25.scores(tokenize(text)), allowed, k)


def search(index: Index, retriever: Retriever, text: str, ticker: str, as_of: date, k: int,
           now: datetime | None = None) -> tuple[list[tuple[int, float]], int]:
    """The top k allowed chunks for the query, and the number of the ticker's documents masked as future."""
    end = cutoff(as_of, now)
    return retriever(text, index.mask(ticker, end), k), index.masked_docs(ticker, end)


def _squash(text: str) -> str:
    return " ".join(text.split())


def resolve(index: Index, gold: Gold) -> set[int]:
    """Positions of the gold document's chunks that contain the quote."""
    quote = _squash(gold.quote)
    return {i for i, r in enumerate(index.records) if r.doc_id == gold.doc and quote in _squash(r.text)}


def parse(row: dict) -> Query:
    missing = [name for name in REQUIRED if name not in row]
    unknown = sorted(set(row) - set(REQUIRED) - set(OPTIONAL))
    if missing or unknown:
        raise ValueError(f"missing fields {missing}" if missing else f"unknown fields {unknown}")
    golds = row["gold"]
    if not isinstance(golds, list) or not 1 <= len(golds) <= MAX_GOLDS:
        raise ValueError(f"gold must hold 1-{MAX_GOLDS} quotes")
    if any(not isinstance(g, dict) or set(g) != {"doc", "quote"} for g in golds):
        raise ValueError('each gold is {"doc": ..., "quote": ...}')
    return Query(str(row["id"]), str(row["ticker"]), date.fromisoformat(row["as_of"]), row["kind"], str(row["text"]),
                 tuple(Gold(g["doc"], g["quote"]) for g in golds))


def validate(rows: list[dict], index: Index, now: datetime | None = None) -> tuple[list[Query], list[str]]:
    """Parsed queries and one message per problem; any problem means the file is not usable."""
    queries, problems, seen = [], [], set()
    for n, row in enumerate(rows, start=1):
        where = f"line {n} ({row.get('id', '?')})"
        try:
            query = parse(row)
        except (ValueError, TypeError) as error:
            problems.append(f"{where}: {error}")
            continue
        if query.id in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(query.id)
        if query.kind not in KINDS:
            problems.append(f"{where}: kind must be one of {', '.join(KINDS)}")
        if not sessions.is_session(query.as_of):
            problems.append(f"{where}: {query.as_of} is not an NYSE session")
            continue
        end = cutoff(query.as_of, now)
        for gold in query.gold:
            if gold.doc not in index.docs:
                problems.append(f"{where}: gold doc {gold.doc} is not in index")
                continue
            ticker, available = index.docs[gold.doc]
            if ticker != query.ticker:
                problems.append(f"{where}: gold doc {gold.doc} belongs to {ticker}")
            elif available > end:
                problems.append(f"{where}: gold doc {gold.doc} appeared {available.isoformat()}, after the cutoff")
            elif not resolve(index, gold):
                problems.append(f"{where}: quote {gold.quote[:60]!r} is in no chunk of {gold.doc}")
        queries.append(query)
    return queries, problems


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@dataclass(frozen=True)
class Score:
    """One query under one retriever: hits per k and the masked-doc count."""

    query: Query
    retriever: str
    any_hit: dict[int, int]  # k -> 0/1
    frac: dict[int, float]  # k -> share of gold quotes found
    masked_docs: int


def score(index: Index, query: Query, name: str, retriever: Retriever, now: datetime | None = None) -> Score:
    hits, masked = search(index, retriever, query.text, query.ticker, query.as_of, max(KS), now)
    ranked = [i for i, _ in hits]
    golds = [resolve(index, gold) for gold in query.gold]
    found = {k: [bool(g & set(ranked[:k])) for g in golds] for k in KS}
    return Score(query, name, {k: int(any(f)) for k, f in found.items()},
                 {k: sum(f) / len(f) for k, f in found.items()}, masked)


def evaluate(index: Index, queries: list[Query], retrievers: dict[str, Retriever],
             now: datetime | None = None) -> list[Score]:
    return [score(index, query, name, retriever, now) for name, retriever in retrievers.items() for query in queries]


def table(scores: list[Score]) -> list[str]:
    """Recall rows per retriever, for all queries and for each kind; counts next to rates."""
    header = "retriever | kind | n | " + " | ".join(f"any@{k}" for k in KS) + " | " + " | ".join(f"frac@{k}" for k in KS)
    out = [header]
    for name in dict.fromkeys(s.retriever for s in scores):
        mine = [s for s in scores if s.retriever == name]
        for kind in ("all", *KINDS):
            group = [s for s in mine if kind == "all" or s.query.kind == kind]
            if not group:
                continue
            n = len(group)
            anys = [f"{sum(s.any_hit[k] for s in group) / n:.2f} ({sum(s.any_hit[k] for s in group)}/{n})" for k in KS]
            fracs = [f"{sum(s.frac[k] for s in group) / n:.2f}" for k in KS]
            out.append(" | ".join([name, kind, str(n), *anys, *fracs]))
    return out
