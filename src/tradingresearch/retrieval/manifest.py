"""The index on disk and its identity (RETRIEVAL-SPIKE §2.5).

`index_digest = sha256(canonical JSON of the manifest)`. The manifest holds what decides the chunks, the BM25
scores and the look-ahead mask: chunker version, `max_tokens`, the token counter, BM25 `k1`/`b` and tokeniser rule,
the sorted `(doc_id, raw_content_sha256, ticker, kind, available_at)` of every document and the sorted
`(chunk_id, sha256(chunk text))` of every chunk. So one digest is one set of chunks with one mask: the same documents
in any order name the same index. An index of an older `SCHEMA` is refused on load (rebuild it).
Build time is not in it, so two builds of the same documents have the same digest. `as_of` is a query-time mask, not
part of the index, so one index serves every session.

A `tr retrieval build --dense` index adds three sections, so its digest names the vectors' recipe too (never the
vectors themselves, whose bytes vary with the CPU's float rounding): `dense` (package and version, model id, ONNX
source repo and revision, dtype, normalize, max sequence length, query prefix, the vector cache-key rule and the
spot-check rule, `dense.pins`), `rerank` (cross-encoder id, revision, depth, `rerank.pins`) and `hybrid` (RRF k). The
observed `vectors_sha256` sits beside the manifest in `vectors.json`, outside the digest. A BM25-only build has none
of the three.

Layout: `<data_dir>/retrieval/<hex digest>/manifest.json` (exactly the hashed manifest) and `chunks.jsonl`; dense
vectors are cached per chunk under `<data_dir>/retrieval/vectors/` (see `dense.py`), shared across indexes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import cached_property
from pathlib import Path

import numpy as np

from .. import hashing
from . import bm25 as lexical
from .chunk import CHUNKER_VERSION, COUNTER, chunk_document
from .ingest import Doc

SCHEMA = "retrieval-index-v2"  # v2: headline doc ids carry the ticker, docs entries carry what the mask reads


@dataclass(frozen=True)
class Record:
    """One line of `chunks.jsonl`: a chunk and the facts the look-ahead mask needs."""

    chunk_id: str
    doc_id: str
    ordinal: int
    ticker: str
    kind: str
    available_at: datetime
    sha256: str
    tokens: int
    text: str

    def row(self) -> dict:
        return {**asdict(self), "available_at": self.available_at.isoformat()}

    @classmethod
    def of(cls, row: dict) -> Record:
        return cls(**{**row, "available_at": datetime.fromisoformat(row["available_at"])})


def build(docs: list[Doc], max_tokens: int, dense: dict | None = None) -> tuple[dict, list[Record]]:
    """The manifest and chunk records of `docs` (deduplicated by doc id, first kept). `dense` holds the `dense`,
    `rerank` and `hybrid` sections of a dense index (`evaluate.dense_sections`); None for BM25 only."""
    unique = list({doc.doc_id: doc for doc in reversed(docs)}.values())[::-1]
    records = [Record(chunk.chunk_id, doc.doc_id, chunk.ordinal, doc.ticker, doc.kind, doc.available_at, chunk.sha256,
                      chunk.tokens, chunk.text)
               for doc in sorted(unique, key=lambda d: d.doc_id)
               for chunk in chunk_document(doc.doc_id, doc.content, doc.media, max_tokens)]
    manifest = {
        "schema": SCHEMA,
        "chunker": {"version": CHUNKER_VERSION, "max_tokens": max_tokens, "counter": COUNTER},
        "bm25": {"k1": lexical.K1, "b": lexical.B, "tokenizer": lexical.TOKENIZER_RULE},
        "docs": sorted([doc.doc_id, doc.raw_content_sha256, doc.ticker, doc.kind, doc.available_at.isoformat()]
                       for doc in unique),
        "chunks": sorted([record.chunk_id, record.sha256] for record in records),
    }
    return manifest | (dense or {}), records


def digest(manifest: dict) -> str:
    return hashing.digest(manifest)


def write(root: Path, manifest: dict, records: list[Record]) -> Path:
    """Write the index under `root/<hex digest>/`; an index with the same digest is already the same index."""
    folder = root / digest(manifest).removeprefix("sha256:")
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in (("chunks.jsonl", "".join(json.dumps(r.row(), sort_keys=True) + "\n" for r in records)),
                       ("manifest.json", json.dumps(manifest, indent=1, sort_keys=True) + "\n")):
        part = folder / f"{name}.part"
        part.write_text(text)
        part.replace(folder / name)
    return folder


@dataclass
class Index:
    digest: str
    manifest: dict
    records: list[Record]

    @cached_property
    def bm25(self) -> lexical.BM25:
        m = self.manifest["bm25"]
        return lexical.BM25([lexical.tokenize(r.text) for r in self.records], m["k1"], m["b"])

    @cached_property
    def docs(self) -> dict[str, tuple[str, datetime]]:
        """doc id -> (ticker, available_at) for every document with at least one chunk."""
        return {r.doc_id: (r.ticker, r.available_at) for r in self.records}

    def mask(self, ticker: str, cutoff: datetime) -> np.ndarray:
        """True for the ticker's chunks available at or before `cutoff`."""
        return np.array([r.ticker == ticker and r.available_at <= cutoff for r in self.records], dtype=bool)

    def masked_docs(self, ticker: str, cutoff: datetime) -> int:
        """The ticker's documents hidden from a query because they appeared after `cutoff`."""
        return sum(1 for t, at in self.docs.values() if t == ticker and at > cutoff)


def find(root: Path, ref: str | None = None) -> Path:
    """The index folder for a digest (with or without `sha256:`, or a unique prefix); None means the newest."""
    folders = [p.parent for p in root.glob("*/manifest.json")] if root.is_dir() else []
    if not folders:
        raise SystemExit(f"no retrieval index under {root}: run `tr retrieval build` first")
    if ref is None:
        return max(folders, key=lambda p: ((p / "manifest.json").stat().st_mtime_ns, p.name))
    matches = [p for p in folders if p.name.startswith(ref.removeprefix("sha256:"))]
    if len(matches) != 1:
        raise SystemExit(f"index {ref!r} matches {len(matches)} indexes under {root}")
    return matches[0]


def load(root: Path, ref: str | None = None) -> Index:
    folder = find(root, ref)
    manifest = json.loads((folder / "manifest.json").read_text())
    if digest(manifest) != f"sha256:{folder.name}":
        raise SystemExit(f"index {folder.name}: manifest does not match its digest")
    if manifest.get("schema") != SCHEMA:
        raise SystemExit(f"index {folder.name} was built as {manifest.get('schema')!r}, not {SCHEMA!r}: rebuild it with "
                         "`tr retrieval build` (and pin the new digest in any arm's `retrieval.index`)")
    with (folder / "chunks.jsonl").open() as lines:
        records = [Record.of(json.loads(line)) for line in lines]
    return Index(digest(manifest), manifest, records)
