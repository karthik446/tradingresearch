"""BM25 keyword scoring in plain numpy (RETRIEVAL-SPIKE §2.2; https://en.wikipedia.org/wiki/Okapi_BM25).

score(d, q) = Σ_{t in q} idf(t) · tf·(k1+1) / (tf + k1·(1 − b + b·|d|/avgdl)), with
idf(t) = ln(1 + (N − df + 0.5)/(df + 0.5)), which is never negative.
Postings, not a docs × vocabulary matrix, so memory grows with the text, not with N × V.
"""

from __future__ import annotations

import re
from collections import Counter

import numpy as np

K1 = 1.5
B = 0.75
TOKENIZER_RULE = "bm25-tok-v1"
_TOKEN = re.compile(r"[a-z][a-z0-9&.\-]*[a-z0-9]|[a-z]|\d[\d,]*(?:\.\d+)?%?")


def tokenize(text: str) -> list[str]:
    """Lowercased words that keep inner `.`, `-`, `&` (u.s, s&p); numbers without `$` or thousands commas."""
    return [token.replace(",", "") for token in _TOKEN.findall(text.lower())]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = K1, b: float = B) -> None:
        self.n = len(docs)
        lengths = np.array([len(d) for d in docs], dtype=np.float64)
        mean = lengths.mean() if self.n and lengths.mean() > 0 else 1.0
        norm = k1 * (1 - b + b * lengths / mean)
        postings: dict[str, tuple[list[int], list[float]]] = {}
        for i, doc in enumerate(docs):
            for term, tf in Counter(doc).items():
                ids, ws = postings.setdefault(term, ([], []))
                ids.append(i)
                ws.append(tf * (k1 + 1) / (tf + norm[i]))
        self.postings = {t: (np.array(ids, np.int32),
                             np.log1p((self.n - len(ids) + 0.5) / (len(ids) + 0.5)) * np.array(ws, np.float32))
                         for t, (ids, ws) in postings.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(self.n, np.float32)
        for t in query:
            if t in self.postings:
                ids, ws = self.postings[t]
                out[ids] += ws
        return out


def top_k(scores: np.ndarray, allowed: np.ndarray, k: int) -> list[tuple[int, float]]:
    """The k best allowed positions with a positive score, best first; ties go to the lower position.

    The mask is applied before ranking, so k allowed results come back whenever k allowed chunks match.
    A chunk sharing no term with the query (score 0) is never returned.
    """
    candidates = np.flatnonzero(allowed & (scores > 0))
    order = np.lexsort((candidates, -scores[candidates]))[:k]
    return [(int(candidates[i]), float(scores[candidates[i]])) for i in order]
