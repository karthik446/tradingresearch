"""Week-6 retrieval plumbing (REPO-PLAN §3 Week 6, RETRIEVAL-SPIKE §4.1): filing text, chunks, BM25, dense vectors,
RRF, a cross-encoder reranker, recall@k, and the rows a retrieval arm writes.

The pipeline: `ingest` fetches 8-K/10-Q text from SEC Archives and reads stored headlines, `extract` turns HTML into
lines, `chunk` packs whole sentences and table rows into chunks, `manifest` names the index by a digest, `bm25`,
`dense` (optional extra) and `fuse` rank, `rerank` reorders the hybrid top 20, and `evaluate` scores recall on
labelled queries with the look-ahead mask applied before ranking. `store` journals what a retrieval arm retrieved.
"""
