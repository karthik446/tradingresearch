"""Reciprocal rank fusion (RETRIEVAL-SPIKE §2.3; Cormack, Clarke & Büttcher, SIGIR 2009,
https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf).

score(d) = Σ_lists 1 / (k + rank_list(d)), ranks from 1, k = 60. Ties are broken by the item (the chunk id), so the
fused list is the same on every run. G13a ships it for G13b's hybrid retriever.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Sequence
from typing import TypeVar

RRF_K = 60
T = TypeVar("T", bound=Hashable)


def rrf(lists: Sequence[Sequence[T]], k: int = RRF_K) -> list[T]:
    """Items of all lists, best fused score first; equal scores in ascending item order."""
    scores: dict[T, float] = defaultdict(float)
    for ranked in lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item] += 1.0 / (k + rank)
    return sorted(scores, key=lambda item: (-scores[item], item))  # type: ignore[operator]
