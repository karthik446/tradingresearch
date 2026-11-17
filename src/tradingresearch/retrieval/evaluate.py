"""Labelled retrieval queries, the look-ahead mask and recall@k (RETRIEVAL-SPIKE §3.1-3.3).

- **Record** (`evals/retrieval_query.schema.md`): id, ticker, as_of, kind, text, 1-3 gold `{doc, quote}`, optional
  answer and notes. A gold is a quote from a document, resolved at eval time to every chunk of that document whose
  text contains it (whitespace-insensitive), so labels survive a chunker change.
- **Mask.** A chunk can be retrieved for `(ticker, as_of)` only if it belongs to that ticker and its document was
  available at or before the session cutoff that `news.headlines_for` uses (the session close, or now if earlier).
  The mask is given to the retriever, which ranks only allowed chunks: post-filtering a top k returns fewer than k.
- **Recall.** `recall_any@k`: 1 if any chunk of any gold quote is in the top k. `recall_frac@k`: the share of gold
  quotes with a chunk in the top k. Both are macro means over queries, at k in 1, 5, 10, 20.
- **Retrievers.** `bm25`; `dense` (cosine over the cached bge vectors, `dense.py`); `hybrid`, reciprocal rank fusion
  (k = 60, `fuse.py`) of the full BM25 and dense rankings of the allowed chunks; `hybrid+rerank`, the hybrid top 20
  reordered by the cross-encoder (`rerank.py`), so its top 20 is the hybrid's top 20 as a set.
- **Citation hook.** A retrieval arm hands its graders `expected["passages"]` (chunk id -> text, in rank order).
  `CITATION_GRADER` names the grader slot that will check a claim's quote against the passage it cites; it is not
  written yet, and `citation_grader()` says so instead of failing as a generic unknown grader.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np

from .. import news, sessions
from . import dense, fuse, rerank
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


RETRIEVERS = ("bm25", "dense", "hybrid", "hybrid+rerank")
CITATION_GRADER = "citation_accuracy"


def dense_sections(embedder: dense.Embedder, reranker_pins: dict = rerank.PINS) -> dict:
    """The manifest sections a dense index adds: the vectors' recipe, the reranker and the fusion constant."""
    return {"dense": embedder.pins(), "rerank": reranker_pins, "hybrid": {"rrf_k": fuse.RRF_K}}


def hybrid_retriever(lexical: Retriever, semantic: Retriever, rrf_k: int = fuse.RRF_K) -> Retriever:
    """RRF over each retriever's full ranking of the allowed chunks; the score is the fused score."""
    def retrieve(text: str, allowed: np.ndarray, k: int) -> list[tuple[int, float]]:
        depth = int(allowed.sum())
        lists = [[i for i, _ in r(text, allowed, depth)] for r in (lexical, semantic)]
        ranks = [{item: rank for rank, item in enumerate(ranked, start=1)} for ranked in lists]
        return [(i, sum(1.0 / (rrf_k + r[i]) for r in ranks if i in r)) for i in fuse.rrf(lists, rrf_k)[:k]]
    return retrieve


def retrievers(index: Index, names: Iterable[str], root: Path, embedder: dense.Embedder | None = None,
               reranker: rerank.Reranker | None = None) -> dict[str, Retriever]:
    """The named retrievers over `index`. Dense ones load the cached vectors under `root` (spot-checked) and, unless
    a test injects them, the pinned local models; a model differing from the index's pins is refused."""
    names = list(names)
    unknown = sorted(set(names) - set(RETRIEVERS))
    if unknown:
        raise SystemExit(f"unknown retriever(s) {', '.join(unknown)}; choose from {', '.join(RETRIEVERS)}")
    out: dict[str, Retriever] = {"bm25": bm25_retriever(index)}
    if set(names) - {"bm25"}:
        embedder = embedder or dense.FastEmbedder(dense.models_dir(root))
        out["dense"] = dense.retriever(dense.matrix(index, embedder, root), embedder)
        out["hybrid"] = hybrid_retriever(out["bm25"], out["dense"], index.manifest["hybrid"]["rrf_k"])
    if "hybrid+rerank" in names:
        reranker = reranker or rerank.FastReranker(dense.models_dir(root))
        if index.manifest["rerank"] != reranker.pins():
            raise SystemExit(f"index {index.digest} pins another reranker than this install's; rebuild it with "
                             "`tr retrieval build --dense`")
        out["hybrid+rerank"] = rerank.retriever(out["hybrid"], [r.text for r in index.records], reranker,
                                                index.manifest["rerank"]["depth"])
    return {name: out[name] for name in names}


def citation_grader() -> type:
    """The registered `citation_accuracy` grader class, or a clear error while nobody has written it."""
    from .. import evals
    if CITATION_GRADER not in evals.GRADERS:
        raise SystemExit(f"no grader named {CITATION_GRADER!r} is registered: write it in evals.py with "
                         f"@grader({CITATION_GRADER!r}); it gets the cited passages as expected['passages']")
    return evals.GRADERS[CITATION_GRADER]


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
