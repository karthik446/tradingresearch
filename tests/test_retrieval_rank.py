"""BM25 against a hand-written reference, the masked top k, and reciprocal rank fusion."""

from __future__ import annotations

import math

import numpy as np

from tradingresearch.retrieval.bm25 import BM25, tokenize, top_k
from tradingresearch.retrieval.fuse import rrf


def test_tokenizer_keeps_numbers_and_inner_punctuation():
    text = "Revenue of $114.5 billion, up 12% vs. $2,617 in the U.S. S&P-500 (Q3)."
    assert tokenize(text) == ["revenue", "of", "114.5", "billion", "up", "12%", "vs", "2617", "in", "the", "u.s",
                              "s&p-500", "q3"]


def reference(docs: list[list[str]], query: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    avgdl = sum(map(len, docs)) / n
    out = []
    for doc in docs:
        score = 0.0
        for term in query:
            df = sum(term in d for d in docs)
            tf = doc.count(term)
            if df and tf:
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(doc) / avgdl))
        out.append(score)
    return out


def test_bm25_matches_the_formula():
    docs = [tokenize(t) for t in (
        "Net income rose to $701 million",
        "Net income net income net income fell",
        "Widget revenue grew 14% on Gizmo demand",
        "The board declared a dividend",
        "",
    )]
    for query in (["net", "income"], ["gizmo", "revenue", "missing"], ["701"], ["net", "net"]):
        assert np.allclose(BM25(docs).scores(query), reference(docs, query), rtol=1e-6)


def test_bm25_empty_corpus_and_empty_docs():
    assert BM25([]).scores(["x"]).shape == (0,)
    assert BM25([[], []]).scores(["x"]).tolist() == [0.0, 0.0]


def test_top_k_ranks_only_allowed_chunks_and_breaks_ties_by_position():
    scores = np.array([5.0, 2.0, 9.0, 2.0, 0.0, 2.0], np.float32)
    allowed = np.array([True, True, False, True, True, True])
    # 2 is the best but masked; the mask is applied before ranking, so k allowed results still come back
    assert top_k(scores, allowed, 3) == [(0, 5.0), (1, 2.0), (3, 2.0)]
    assert top_k(scores, allowed, 10) == [(0, 5.0), (1, 2.0), (3, 2.0), (5, 2.0)]  # a zero score is never returned
    assert top_k(scores, np.zeros(6, bool), 3) == []


def test_rrf_sums_reciprocal_ranks_and_breaks_ties_by_item():
    assert rrf([[3, 1, 2], [1, 3, 4]]) == [1, 3, 2, 4]  # 1 and 3 tie, 2 and 4 tie
    assert rrf([["b", "a"], ["a"]]) == ["a", "b"]
    assert rrf([["x", "y", "z"]]) == ["x", "y", "z"]
    assert rrf([[]]) == []
