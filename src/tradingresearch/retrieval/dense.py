"""Dense retrieval (RETRIEVAL-SPIKE §2.5): bge-small-en-v1.5 vectors, cached per chunk on disk, spot-checked on load.

A dense retriever embeds the query and every chunk into one vector space and ranks chunks by cosine similarity
(Karpukhin et al., Dense Passage Retrieval, https://arxiv.org/abs/2004.04906). It finds paraphrases BM25 misses
("sales" for "revenue") and misses exact tokens BM25 finds (tickers, figures), hence the hybrid in `evaluate`.

- **Model.** `BAAI/bge-small-en-v1.5`, the ONNX export `Qdrant/bge-small-en-v1.5-onnx-Q` at a pinned revision, run by
  fastembed (the optional extra: `uv sync --extra retrieval`). 384-d float32, L2-normalised, so cosine = dot
  product. No query prefix (bge v1.5 does not need one; fastembed's `query_embed` adds none for it).
- **Download.** Only `tr retrieval build --dense` may download (into `<data_dir>/retrieval/models/`, a Hugging Face
  cache layout); every other path loads local files only and says to run the build when they are missing.
- **Cache.** One `.npy` per chunk at `vectors/<model id with / as -->@<revision>/<sha256 of the chunk text>.npy`:
  a chunk unchanged across rebuilds (or shared by two indexes) is embedded once, and another model or revision
  never reads it.
- **Spot check.** Loading the vectors re-embeds `VERIFY_SAMPLE` evenly spaced chunks and requires cosine >=
  `MIN_COSINE` with the cached vector; a lower one is an error naming the chunk (a changed runtime or a corrupt
  cache would otherwise rank silently differently). Every cached row must also have norm 1 ± `NORM_TOLERANCE` (a
  scaled vector ranks as a dot product), and the rows must hash to the `vectors_sha256` the build recorded in
  `vectors.json` when it is there (a changed vector outside the sample).

fastembed is imported inside functions only, so the base install never needs it. Tests inject a fake embedder into
these functions; the CLI and the arm config always build `FastEmbedder`.
"""

from __future__ import annotations

import hashlib
import json
from importlib import metadata
from pathlib import Path
from typing import Protocol

import numpy as np

from .manifest import Index, Record

PACKAGE = "fastembed==0.9.1"
MODEL = "BAAI/bge-small-en-v1.5"
SOURCE = "Qdrant/bge-small-en-v1.5-onnx-Q"
REVISION = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
MODEL_FILE = "model_optimized.onnx"
DIM = 384
MAX_LENGTH = 512  # fastembed truncates at the model's 512 WordPiece tokens; chunks are capped at 256 regex tokens
CACHE_KEY = "vectors/<model id, / as -->@<revision>/<sha256(chunk text)>.npy"
VERIFY_SAMPLE = 20
MIN_COSINE = 0.9999
NORM_TOLERANCE = 1e-3
BATCH = 64
INSTALL = "uv sync --extra retrieval"
TOKENIZER_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json")


class Embedder(Protocol):
    def pins(self) -> dict: ...  # the manifest's `dense` section; `model` and `revision` key the cache

    def embed(self, texts: list[str]) -> np.ndarray: ...  # (len(texts), dim) float32, L2-normalised


def require_fastembed():
    try:
        import fastembed
    except ImportError:
        raise SystemExit(f"dense retrieval and the reranker need the optional extra: {INSTALL}") from None
    return fastembed


def models_dir(root: Path) -> Path:
    return root / "models"


def fetch(repo: str, revision: str, files: tuple[str, ...], models: Path, download: bool) -> str:
    """The local folder of `repo` at `revision` holding `files`; downloaded only when `download` is set."""
    require_fastembed()
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError
    try:
        return snapshot_download(repo, revision=revision, cache_dir=models, allow_patterns=list(files),
                                 local_files_only=not download)
    except LocalEntryNotFoundError:
        raise SystemExit(f"{repo} at revision {revision[:12]} is not in {models}: download it once with "
                         "`tr retrieval build --dense`") from None


def normalized(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True).clip(min=1e-12)


class FastEmbedder:
    """bge-small-en-v1.5 through fastembed, from the pinned local snapshot."""

    def __init__(self, models: Path, download: bool = False) -> None:
        fastembed = require_fastembed()
        path = fetch(SOURCE, REVISION, (MODEL_FILE, *TOKENIZER_FILES), models, download)
        self._model = fastembed.TextEmbedding(MODEL, cache_dir=str(models), specific_model_path=path)

    def pins(self) -> dict:
        return {"package": PACKAGE, "onnxruntime": metadata.version("onnxruntime"), "model": MODEL, "source": SOURCE,
                "revision": REVISION, "model_file": MODEL_FILE, "dim": DIM, "dtype": "float32", "normalize": True,
                "max_length": MAX_LENGTH, "query_prefix": "", "cache_key": CACHE_KEY,
                "verify": {"sample": VERIFY_SAMPLE, "min_cosine": MIN_COSINE}}

    def embed(self, texts: list[str]) -> np.ndarray:
        return normalized(np.array(list(self._model.embed(texts, batch_size=BATCH)), dtype=np.float32))


def vector_path(root: Path, chunk_sha256: str, model: str, revision: str) -> Path:
    """The cache file of one chunk's vector under one model revision (`CACHE_KEY`)."""
    return root / "vectors" / f"{model.replace('/', '--')}@{revision}" / f"{chunk_sha256}.npy"


def path_for(root: Path, record: Record, embedder: Embedder) -> Path:
    pins = embedder.pins()
    return vector_path(root, record.sha256, pins["model"], pins["revision"])


def embed_missing(records: list[Record], embedder: Embedder, root: Path) -> int:
    """Embed and cache every chunk without a cached vector; the number embedded."""
    missing = list({r.sha256: r for r in records if not path_for(root, r, embedder).exists()}.values())
    for start in range(0, len(missing), BATCH):
        batch = missing[start:start + BATCH]
        for record, vector in zip(batch, embedder.embed([r.text for r in batch]), strict=True):
            path = path_for(root, record, embedder)
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_suffix(".part.npy")
            np.save(part, vector.astype(np.float32))
            part.replace(path)
    return len(missing)


def vectors_sha256(matrix: np.ndarray) -> str:
    """The observed digest of the vectors, row order = chunk order (recorded beside the manifest, never hashed in)."""
    return "sha256:" + hashlib.sha256(np.ascontiguousarray(matrix, dtype=np.float32).tobytes()).hexdigest()


def write_observed(folder: Path, matrix: np.ndarray) -> str:
    """Record the observed `vectors_sha256` in `<index folder>/vectors.json`; returns it."""
    observed = vectors_sha256(matrix)
    (folder / "vectors.json").write_text(json.dumps({"vectors_sha256": observed, "rows": len(matrix)}) + "\n")
    return observed


def sample(count: int, n: int = VERIFY_SAMPLE) -> list[int]:
    """`n` evenly spaced positions of `count`, first and last included: the same chunks on every run."""
    return sorted({int(i) for i in np.linspace(0, count - 1, min(n, count))}) if count else []


def verify(records: list[Record], matrix: np.ndarray, embedder: Embedder, root: Path, n: int = VERIFY_SAMPLE) -> float:
    """Re-embed `n` sampled chunks; the lowest cosine with the cached vectors. Below MIN_COSINE is an error."""
    picked = sample(len(records), n)
    if not picked:
        return 1.0
    fresh = embedder.embed([records[i].text for i in picked])
    cached = matrix[picked]
    cosines = np.sum(fresh * cached, axis=1) / np.linalg.norm(cached, axis=1).clip(min=1e-12)
    worst = int(np.argmin(cosines))
    if cosines[worst] < MIN_COSINE:
        record = records[picked[worst]]
        raise SystemExit(f"cached vector of chunk {record.chunk_id} differs from a fresh embedding (cosine "
                         f"{cosines[worst]:.6f} < {MIN_COSINE}): delete {path_for(root, record, embedder)} and "
                         "rebuild with `tr retrieval build --dense`")
    return float(cosines.min())


def matrix(index: Index, embedder: Embedder, root: Path, n: int = VERIFY_SAMPLE) -> np.ndarray:
    """The index's vectors in chunk order, after checking the embedder is the index's, every row's norm, the recorded
    `vectors_sha256` (when `vectors.json` is there) and spot-checking `n`."""
    pinned = index.manifest.get("dense")
    if pinned is None:
        raise SystemExit(f"index {index.digest} has no dense vectors: build one with `tr retrieval build --dense`")
    if pinned != embedder.pins():
        raise SystemExit(f"index {index.digest} was embedded with other pins than this install's; rebuild it with "
                         "`tr retrieval build --dense`")
    rows = []
    for record in index.records:
        path = path_for(root, record, embedder)
        if not path.exists():
            raise SystemExit(f"no cached vector for chunk {record.chunk_id}: run `tr retrieval build --dense`")
        rows.append(np.load(path))
    found = np.array(rows, dtype=np.float32).reshape(len(rows), -1)
    norms = np.linalg.norm(found, axis=1)
    if bad := np.flatnonzero(np.abs(norms - 1) > NORM_TOLERANCE).tolist():
        record = index.records[bad[0]]
        raise SystemExit(f"cached vector of chunk {record.chunk_id} has norm {norms[bad[0]]:.6f}, not 1 ± "
                         f"{NORM_TOLERANCE} ({len(bad)} such rows): delete {path_for(root, record, embedder)} and "
                         "rebuild with `tr retrieval build --dense`")
    observed = root / index.digest.removeprefix("sha256:") / "vectors.json"
    if observed.exists() and (recorded := json.loads(observed.read_text())["vectors_sha256"]) != vectors_sha256(found):
        first = path_for(root, index.records[0], embedder).parent
        raise SystemExit(f"index {index.digest}: the cached vectors hash to {vectors_sha256(found)}, not the "
                         f"{recorded} recorded at build (a cached vector changed): delete {first} and rebuild with "
                         "`tr retrieval build --dense`")
    verify(index.records, found, embedder, root, n)
    return found


def ranked(scores: np.ndarray, allowed: np.ndarray, k: int) -> list[tuple[int, float]]:
    """The k best allowed positions by score, ties to the lower position (every allowed chunk can rank)."""
    positions = np.flatnonzero(allowed)
    order = positions[np.lexsort((positions, -scores[positions]))][:k]
    return [(int(i), float(scores[i])) for i in order]


def retriever(vectors: np.ndarray, embedder: Embedder):
    """An `evaluate.Retriever` ranking by cosine between the query's vector and the chunks'."""
    def retrieve(text: str, allowed: np.ndarray, k: int) -> list[tuple[int, float]]:
        return ranked(vectors @ embedder.embed([text])[0], allowed, k)
    return retrieve
