"""Week-6 retrieval plumbing (REPO-PLAN §3 Week 6, RETRIEVAL-SPIKE §4.1): filing text, chunks, BM25, RRF, recall@k.

The pipeline: `ingest` fetches 8-K/10-Q text from SEC Archives and reads stored headlines, `extract` turns HTML into
lines, `chunk` packs whole sentences and table rows into chunks, `manifest` names the index by a digest, `bm25` and
`fuse` rank, and `evaluate` scores recall on labelled queries with the look-ahead mask applied before ranking.
Dense retrieval and the reranker come in G13b.
"""
