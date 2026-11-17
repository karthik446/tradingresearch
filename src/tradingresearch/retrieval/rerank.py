"""Cross-encoder reranking of the hybrid top `DEPTH` (RETRIEVAL-SPIKE §2.5).

A cross-encoder reads the query and one passage together and outputs a relevance score, which is slower than
comparing precomputed vectors but more accurate, so it only reorders a short first-stage list (Nogueira & Cho,
Passage Re-ranking with BERT, https://arxiv.org/abs/1901.04085; the sentence-transformers notes,
https://www.sbert.net/examples/applications/cross-encoder/README.html).

Model: `Xenova/ms-marco-MiniLM-L-6-v2` (ONNX of `cross-encoder/ms-marco-MiniLM-L-6-v2`) at a pinned revision, run by
fastembed's `TextCrossEncoder` from `<data_dir>/retrieval/models/`, downloaded only by `tr retrieval build --dense`.
Reranking reorders the first `DEPTH` hits and drops none, so `hybrid+rerank@DEPTH == hybrid@DEPTH` as sets. Tests
inject a fake reranker; the CLI and the arm config always build `FastReranker`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from .dense import TOKENIZER_FILES, fetch, require_fastembed

MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
REVISION = "a09144355adeed5f58c8ed011d209bf8ee5a1fec"
MODEL_FILE = "onnx/model.onnx"
DEPTH = 20
PINS = {"model": MODEL, "revision": REVISION, "model_file": MODEL_FILE, "depth": DEPTH}


class Reranker(Protocol):
    def pins(self) -> dict: ...  # the manifest's `rerank` section

    def score(self, query: str, texts: list[str]) -> list[float]: ...  # one relevance score per text, higher better


def fetch_files(models: Path, download: bool) -> str:
    return fetch(MODEL, REVISION, (MODEL_FILE, *TOKENIZER_FILES), models, download)


class FastReranker:
    """ms-marco-MiniLM-L-6-v2 through fastembed, from the pinned local snapshot."""

    def __init__(self, models: Path, download: bool = False) -> None:
        require_fastembed()
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self._model = TextCrossEncoder(MODEL, cache_dir=str(models), specific_model_path=fetch_files(models, download))

    def pins(self) -> dict:
        return dict(PINS)

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, texts)]


def retriever(first, texts: list[str], reranker: Reranker, depth: int = DEPTH):
    """An `evaluate.Retriever` that reorders `first`'s top `depth` by the cross-encoder; ties keep `first`'s order."""
    def retrieve(text: str, allowed: np.ndarray, k: int) -> list[tuple[int, float]]:
        if k > depth:
            raise SystemExit(f"the reranker reorders the top {depth}; k={k} is deeper")
        hits = first(text, allowed, depth)
        scores = reranker.score(text, [texts[i] for i, _ in hits]) if hits else []
        order = sorted(range(len(hits)), key=lambda j: (-scores[j], j))
        return [(hits[j][0], scores[j]) for j in order[:k]]
    return retrieve
