"""Index manifest, the look-ahead mask (applied before ranking), the label validator and recall@k on FAKEA."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pytest
from test_retrieval_ingest import NOW, fake_archives, write_headlines

from tradingresearch.retrieval import evaluate, ingest, manifest
from tradingresearch.retrieval.evaluate import Gold

AS_OF = date(2026, 11, 5)  # cutoff 2026-11-05 21:00Z; the recall 8-K (11-06 13:00Z) and headline 3 come after it
EX991 = "0009999999-26-000101/fakea-ex991.htm"
TENQ = "0009999999-26-000102/fakea-20260930.htm"
FUTURE = "0009999999-26-000103/fakea-8k_20261106.htm"
SCHEMA = Path(__file__).parents[1] / "evals" / "retrieval_query.schema.md"


def docs_for(data_dir: Path) -> list[ingest.Doc]:
    since = ingest.since_for(1, NOW)
    write_headlines(data_dir, "FAKEA", [(1, "FakeA ships record Gizmos", datetime(2026, 11, 3, 14, tzinfo=UTC)),
                                        (3, "FakeA recalls Gizmo line", datetime(2026, 11, 6, 12, tzinfo=UTC))])
    write_headlines(data_dir, "FAKEB", [(9, "FakeB Gizmo recall recall recall", datetime(2026, 11, 2, 14, tzinfo=UTC))])
    archives, _ = fake_archives(data_dir / "edgar")
    return [*ingest.filing_docs(archives, "FAKEA", 1, NOW), *ingest.headline_docs(data_dir, "FAKEA", since),
            *ingest.headline_docs(data_dir, "FAKEB", since)]


@pytest.fixture
def index(tmp_path) -> manifest.Index:
    built, records = manifest.build(docs_for(tmp_path), 256)
    manifest.write(tmp_path / "retrieval", built, records)
    return manifest.load(tmp_path / "retrieval")


def bm25_search(index, text, as_of, k, ticker="FAKEA"):
    hits, masked = evaluate.search(index, evaluate.bm25_retriever(index), text, ticker, as_of, k, NOW)
    return [index.records[i] for i, _ in hits], masked


def test_future_doc_never_appears_and_the_mask_runs_before_ranking(index):
    for k in (1, 5, 20):
        records, masked = bm25_search(index, "Gizmo recall", AS_OF, k)
        assert records, k  # k=1 still returns an allowed chunk: the top unmasked chunk is the future one
        assert {r.doc_id for r in records}.isdisjoint({FUTURE, "headline/3", "headline/9"})
        assert all(r.ticker == "FAKEA" and r.available_at <= datetime(2026, 11, 5, 21, tzinfo=UTC) for r in records)
        assert masked == 2
    [top], masked = bm25_search(index, "Gizmo recall", date(2026, 11, 6), 1)  # once it is public, it ranks first
    assert top.doc_id == FUTURE and masked == 0


def test_cutoff_is_the_session_close_or_now(index):
    assert evaluate.cutoff(AS_OF, NOW) == datetime(2026, 11, 5, 21, tzinfo=UTC)
    early = datetime(2026, 11, 5, 18, tzinfo=UTC)
    assert evaluate.cutoff(AS_OF, early) == early


def test_recall_with_several_golds_uses_any_and_fraction(tmp_path):
    built, records = manifest.build(docs_for(tmp_path), 30)  # small chunks, so there are enough to rank
    index = manifest.Index(manifest.digest(built), built, records)
    net = evaluate.resolve(index, Gold(EX991, "Net income | $701 | $633"))
    cash = evaluate.resolve(index, Gold(TENQ, "Cash and cash  equivalents | $2,980"))  # whitespace-insensitive
    assert net and cash
    allowed = np.flatnonzero(index.mask("FAKEA", evaluate.cutoff(AS_OF, NOW)))
    other = [int(i) for i in allowed if i not in net | cash]
    assert len(other) >= 10
    ranking = [*other[:4], min(net), *other[4:10], min(cash)]  # net at rank 5, cash at rank 12

    def fixed(text, mask, k):
        return [(i, 1.0) for i in ranking if mask[i]][:k]

    query = evaluate.Query("q1", "FAKEA", AS_OF, "numeric", "net income and cash",
                           (Gold(EX991, "Net income | $701 | $633"), Gold(TENQ, "Cash and cash equivalents | $2,980")))
    [score] = evaluate.evaluate(index, [query], {"fixed": fixed}, NOW)
    assert score.any_hit == {1: 0, 5: 1, 10: 1, 20: 1}
    assert score.frac == {1: 0.0, 5: 0.5, 10: 0.5, 20: 1.0}
    assert score.masked_docs == 2
    lines = evaluate.table([score])
    assert lines[1] == "fixed | all | 1 | 0.00 (0/1) | 1.00 (1/1) | 1.00 (1/1) | 1.00 (1/1) | 0.00 | 0.50 | 0.50 | 1.00"
    assert lines[2].startswith("fixed | numeric | 1 |") and len(lines) == 3


def row(**changes) -> dict:
    base = {"id": "q1", "ticker": "FAKEA", "as_of": "2026-11-05", "kind": "numeric", "text": "FakeA net income?",
            "gold": [{"doc": EX991, "quote": "Net income | $701 | $633"}]}
    return {**base, **changes}


def test_schema_examples_validate_against_the_fakea_index(index):
    rows = [json.loads(line) for line in SCHEMA.read_text().splitlines() if line.startswith('{"id"')]
    queries, problems = evaluate.validate(rows, index, NOW)
    assert len(rows) == 2 and problems == [] and len(queries) == 2
    scores = evaluate.evaluate(index, queries, {"bm25": evaluate.bm25_retriever(index)}, NOW)
    assert all(s.any_hit[20] == 1 for s in scores)


@pytest.mark.parametrize(("changes", "problem"), [
    ({"gold": [{"doc": EX991, "quote": "Net income | $999"}]}, "is in no chunk"),
    ({"gold": [{"doc": FUTURE, "quote": "voluntary recall"}]}, "after the cutoff"),
    ({"gold": [{"doc": "headline/9", "quote": "FakeB"}]}, "belongs to FAKEB"),
    ({"gold": [{"doc": "nope/x.htm", "quote": "x"}]}, "not in index"),
    ({"as_of": "2026-11-07"}, "not an NYSE session"),
    ({"kind": "opinion"}, "kind must be one of"),
    ({"gold": []}, "1-3 quotes"),
    ({"gold": [{"doc": EX991, "quote": "Net income"}] * 4}, "1-3 quotes"),
    ({"gold": [{"doc": EX991}]}, '{"doc"'),
    ({"extra": 1}, "unknown fields"),
])
def test_validator_rejects(index, changes, problem):
    _, problems = evaluate.validate([row(**changes)], index, NOW)
    assert len(problems) == 1 and problem in problems[0], problems


def test_validator_rejects_missing_fields_and_duplicate_ids(index):
    bad = row()
    del bad["text"]
    _, problems = evaluate.validate([row(), row(), bad], index, NOW)
    assert ["duplicate id" in p for p in problems] == [True, False] and "missing fields ['text']" in problems[1]


def test_two_builds_have_the_same_digest_and_no_dense_fields(tmp_path):
    first, records = manifest.build(docs_for(tmp_path / "a"), 256)
    second, _ = manifest.build(docs_for(tmp_path / "b")[::-1], 256)
    assert manifest.digest(first) == manifest.digest(second)
    assert manifest.digest(manifest.build(docs_for(tmp_path / "c"), 128)[0]) != manifest.digest(first)
    assert set(first) == {"schema", "chunker", "bm25", "docs", "chunks"}
    assert first["chunker"]["version"] == "chunk-v1" and first["bm25"] == {"k1": 1.5, "b": 0.75,
                                                                           "tokenizer": "bm25-tok-v1"}
    assert len(first["docs"]) == 7 and len(first["chunks"]) == len(records)
    folder = manifest.write(tmp_path / "retrieval", first, records)
    assert folder.name == manifest.digest(first).removeprefix("sha256:")
    assert json.loads((folder / "manifest.json").read_text()) == first
    for ref in (None, manifest.digest(first), folder.name, folder.name[:8]):
        loaded = manifest.load(tmp_path / "retrieval", ref)
        assert loaded.records == records and loaded.digest == manifest.digest(first)


def test_load_refuses_a_changed_manifest_and_an_unknown_ref(tmp_path):
    built, records = manifest.build(docs_for(tmp_path), 256)
    folder = manifest.write(tmp_path / "retrieval", built, records)
    with pytest.raises(SystemExit):
        manifest.load(tmp_path / "retrieval", "ffff")
    (folder / "manifest.json").write_text(json.dumps({**built, "schema": "edited"}))
    with pytest.raises(SystemExit, match="does not match"):
        manifest.load(tmp_path / "retrieval")
    with pytest.raises(SystemExit, match="tr retrieval build"):
        manifest.load(tmp_path / "empty")
