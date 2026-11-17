"""Dense vectors (cache key, pins in the digest, spot check), hybrid RRF and the reranker on FAKEA, offline.

The logic runs with an injected fake embedder and reranker, so it is tested with or without the `retrieval` extra;
the tests that touch fastembed itself skip without it and never download.
"""

from __future__ import annotations

import hashlib
import sys

import numpy as np
import pytest
from test_retrieval_eval import AS_OF, FUTURE, docs_for
from test_retrieval_ingest import NOW

from tradingresearch.retrieval import bm25, dense, evaluate, fuse, manifest, rerank

DIM = 64


class FakeEmbedder:
    """Hashed bag of words: chunks sharing words point the same way. Counts the texts it embeds."""

    def __init__(self, revision: str = "r1") -> None:
        self.revision = revision
        self.embedded = 0

    def pins(self) -> dict:
        return {"model": "fake/bag-of-words", "revision": self.revision, "dim": DIM}

    def embed(self, texts: list[str]) -> np.ndarray:
        self.embedded += len(texts)
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in bm25.tokenize(text):
                out[row, int(hashlib.sha256(token.encode()).hexdigest(), 16) % DIM] += 1.0
        return dense.normalized(out + 1e-3)


class FakeReranker:
    """Scores a passage by its length, an order unrelated to the hybrid's."""

    def pins(self) -> dict:
        return dict(rerank.PINS)

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [float(len(t)) for t in texts]


def dense_index(tmp_path, embedder, max_tokens=30) -> manifest.Index:
    built, records = manifest.build(docs_for(tmp_path), max_tokens, evaluate.dense_sections(embedder))
    manifest.write(tmp_path / "retrieval", built, records)
    dense.embed_missing(records, embedder, tmp_path / "retrieval")
    return manifest.load(tmp_path / "retrieval")


def all_retrievers(index, tmp_path, embedder):
    return evaluate.retrievers(index, evaluate.RETRIEVERS, tmp_path / "retrieval", embedder, FakeReranker())


def test_vectors_are_cached_by_chunk_text_model_and_revision(tmp_path):
    docs, root = docs_for(tmp_path), tmp_path / "retrieval"
    _, records = manifest.build(docs, 30)
    first = FakeEmbedder("r1")
    assert dense.embed_missing(records, first, root) == len({r.sha256 for r in records}) == first.embedded
    assert dense.embed_missing(records, first, root) == 0  # cached
    record = records[0]
    assert dense.path_for(root, record, first) == root / "vectors" / "fake--bag-of-words@r1" / f"{record.sha256}.npy"
    second = FakeEmbedder("r2")  # another revision never reads the first one's vectors
    assert dense.embed_missing(records, second, root) == first.embedded
    _, rechunked = manifest.build(docs, 40)  # a changed chunk text is a new key; unchanged texts are reused
    fresh = {r.sha256 for r in rechunked} - {r.sha256 for r in records}
    assert 0 < dense.embed_missing(rechunked, first, root) == len(fresh)


def test_dense_pins_join_the_digest_and_the_vectors_do_not(tmp_path):
    docs = docs_for(tmp_path)
    plain, records = manifest.build(docs, 256)
    assert set(plain) == {"schema", "chunker", "bm25", "docs", "chunks"}  # a BM25 index is unchanged
    with_dense, _ = manifest.build(docs, 256, evaluate.dense_sections(FakeEmbedder()))
    assert set(with_dense) - set(plain) == {"dense", "rerank", "hybrid"}
    assert with_dense["hybrid"] == {"rrf_k": 60} and with_dense["rerank"]["revision"] == rerank.REVISION
    digests = {manifest.digest(plain), manifest.digest(with_dense),
               manifest.digest(manifest.build(docs, 256, evaluate.dense_sections(FakeEmbedder("r2")))[0]),
               manifest.digest(manifest.build(docs, 256, evaluate.dense_sections(
                   FakeEmbedder(), {**rerank.PINS, "revision": "0" * 40}))[0])}
    assert len(digests) == 4
    folder = manifest.write(tmp_path / "retrieval", with_dense, records)
    vectors = FakeEmbedder().embed([r.text for r in records])
    observed = dense.write_observed(folder, vectors)
    assert observed.startswith("sha256:") and observed not in (folder / "manifest.json").read_text()
    assert manifest.load(tmp_path / "retrieval").digest == manifest.digest(with_dense)


def test_spot_check_names_a_chunk_whose_cached_vector_drifted(tmp_path):
    embedder = FakeEmbedder()
    index = dense_index(tmp_path, embedder)
    root = tmp_path / "retrieval"
    assert dense.matrix(index, embedder, root).shape == (len(index.records), DIM)
    victim = index.records[dense.sample(len(index.records))[3]]
    path = dense.path_for(root, victim, embedder)
    drifted = np.load(path)
    drifted[0] += 0.05
    np.save(path, dense.normalized(drifted[None])[0])
    with pytest.raises(SystemExit, match=f"chunk {victim.chunk_id} differs"):
        dense.matrix(index, embedder, root)


def test_matrix_refuses_a_bm25_index_other_pins_and_missing_vectors(tmp_path):
    embedder = FakeEmbedder()
    index = dense_index(tmp_path, embedder)
    root = tmp_path / "retrieval"
    with pytest.raises(SystemExit, match="other pins"):
        dense.matrix(index, FakeEmbedder("r2"), root)
    dense.path_for(root, index.records[-1], embedder).unlink()
    with pytest.raises(SystemExit, match=f"no cached vector for chunk {index.records[-1].chunk_id}"):
        dense.matrix(index, embedder, root)
    plain = manifest.Index("sha256:x", manifest.build(docs_for(tmp_path), 256)[0], index.records)
    with pytest.raises(SystemExit, match="has no dense vectors"):
        dense.matrix(plain, embedder, root)


def test_every_retriever_ranks_only_allowed_chunks(tmp_path):
    embedder = FakeEmbedder()
    index = dense_index(tmp_path, embedder)
    end = evaluate.cutoff(AS_OF, NOW)
    for name, retriever in all_retrievers(index, tmp_path, embedder).items():
        for k in (1, 5, 20):
            hits, masked = evaluate.search(index, retriever, "Gizmo recall", "FAKEA", AS_OF, k, NOW)
            records = [index.records[i] for i, _ in hits]
            assert masked == 2 and (len(records) == k or name == "bm25" and 0 < len(records) < k), name  # BM25: matches only
            assert all(r.ticker == "FAKEA" and r.available_at <= end and r.doc_id != FUTURE for r in records), name


def test_hybrid_is_rrf_of_the_full_bm25_and_dense_rankings(tmp_path):
    embedder = FakeEmbedder()
    index = dense_index(tmp_path, embedder)
    found = all_retrievers(index, tmp_path, embedder)
    allowed = index.mask("FAKEA", evaluate.cutoff(AS_OF, NOW))
    depth = int(allowed.sum())
    text = "net income and cash"
    lists = [[i for i, _ in found[name](text, allowed, depth)] for name in ("bm25", "dense")]
    assert len(lists[1]) == depth > len(lists[0]) > 0  # dense ranks every allowed chunk, BM25 only matching ones
    hybrid = found["hybrid"](text, allowed, 10)
    assert [i for i, _ in hybrid] == fuse.rrf(lists)[:10]
    top = hybrid[0][0]
    assert hybrid[0][1] == pytest.approx(sum(1 / (60 + ranked.index(top) + 1) for ranked in lists if top in ranked))


def test_rerank_reorders_the_hybrid_top_20_and_drops_nothing(tmp_path):
    embedder = FakeEmbedder()
    index = dense_index(tmp_path, embedder)
    found = all_retrievers(index, tmp_path, embedder)
    allowed = index.mask("FAKEA", evaluate.cutoff(AS_OF, NOW))
    assert allowed.sum() > 20
    text = "Gizmo revenue guidance"
    hybrid, reranked = found["hybrid"](text, allowed, 20), found["hybrid+rerank"](text, allowed, 20)
    assert {i for i, _ in reranked} == {i for i, _ in hybrid}  # hybrid+rerank@20 == hybrid@20
    assert [i for i, _ in reranked] != [i for i, _ in hybrid]
    lengths = [len(index.records[i].text) for i, _ in reranked]
    assert lengths == sorted(lengths, reverse=True)
    assert found["hybrid+rerank"](text, allowed, 5) == reranked[:5]
    with pytest.raises(SystemExit, match="top 20"):
        found["hybrid+rerank"](text, allowed, 21)


def test_eval_scores_every_retriever_at_every_k(tmp_path):
    embedder = FakeEmbedder()
    index = dense_index(tmp_path, embedder)
    query = evaluate.Query("q1", "FAKEA", AS_OF, "numeric", "net income",
                           (evaluate.Gold("0009999999-26-000101/fakea-ex991.htm", "Net income | $701 | $633"),))
    scores = evaluate.evaluate(index, [query], all_retrievers(index, tmp_path, embedder), NOW)
    assert [s.retriever for s in scores] == list(evaluate.RETRIEVERS)
    by_name = {s.retriever: s for s in scores}
    assert by_name["hybrid+rerank"].any_hit[20] == by_name["hybrid"].any_hit[20]
    assert all(set(s.any_hit) == {1, 5, 10, 20} for s in scores)
    assert [line.split(" | ")[0] for line in evaluate.table(scores)[1:]] == [
        name for name in evaluate.RETRIEVERS for _ in ("all", "numeric")]


def test_unknown_retriever_and_a_reranker_with_other_pins_are_refused(tmp_path):
    embedder = FakeEmbedder()
    index = dense_index(tmp_path, embedder)
    with pytest.raises(SystemExit, match="unknown retriever"):
        evaluate.retrievers(index, ["splade"], tmp_path / "retrieval", embedder)

    class OtherReranker(FakeReranker):
        def pins(self) -> dict:
            return {**rerank.PINS, "revision": "0" * 40}

    with pytest.raises(SystemExit, match="another reranker"):
        evaluate.retrievers(index, ["hybrid+rerank"], tmp_path / "retrieval", embedder, OtherReranker())


def test_without_fastembed_dense_names_the_extra(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "fastembed", None)  # import fastembed now raises ImportError
    for build in (dense.FastEmbedder, rerank.FastReranker):
        with pytest.raises(SystemExit, match="uv sync --extra retrieval"):
            build(tmp_path)
    index = dense_index(tmp_path, FakeEmbedder())
    assert evaluate.retrievers(index, ["bm25"], tmp_path / "retrieval")  # BM25 alone never needs it
    with pytest.raises(SystemExit, match="uv sync --extra retrieval"):
        evaluate.retrievers(index, ["dense"], tmp_path / "retrieval")


def test_unregistered_citation_hook_is_a_clear_error(monkeypatch):
    from tradingresearch import evals

    assert evaluate.CITATION_GRADER not in evals.GRADERS
    with pytest.raises(SystemExit, match="no grader named 'citation_accuracy' is registered.*@grader"):
        evaluate.citation_grader()
    monkeypatch.setitem(evals.GRADERS, "citation_accuracy", FakeReranker)
    assert evaluate.citation_grader() is FakeReranker


def test_pins_are_models_fastembed_supports():
    pytest.importorskip("fastembed")
    from fastembed import TextEmbedding
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    [embedder] = [m for m in TextEmbedding._list_supported_models() if m.model == dense.MODEL]
    assert (embedder.sources.hf, embedder.model_file, embedder.dim) == (dense.SOURCE, dense.MODEL_FILE, dense.DIM)
    [reranker] = [m for m in TextCrossEncoder._list_supported_models() if m.model == rerank.MODEL]
    assert (reranker.sources.hf, reranker.model_file) == (rerank.MODEL, rerank.MODEL_FILE)


def test_models_load_only_from_the_local_snapshot_outside_build(tmp_path):
    pytest.importorskip("fastembed")
    with pytest.raises(SystemExit, match="not in .*tr retrieval build --dense"):
        dense.FastEmbedder(tmp_path / "models")  # empty cache, local files only: no download is attempted
    with pytest.raises(SystemExit, match="not in .*tr retrieval build --dense"):
        rerank.FastReranker(tmp_path / "models")
